from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Protocol

from nethack_agent.decision import (
    DECISION_SCHEMA,
    DecisionError,
    DecisionMetrics,
    ModelDecision,
    parse_action_decision,
)
from nethack_agent.environment import LegalAction
from nethack_agent.observation import ProjectedObservation
from nethack_agent.ollama import Generation, OllamaClient, OllamaError


@dataclass(frozen=True, slots=True)
class DecisionAttemptDiagnostic:
    error: str
    raw_response: str | None
    prompt_tokens: int
    output_tokens: int
    elapsed_ms: float
    returned_duration_ms: float | None

    @property
    def effective_latency_ms(self) -> float:
        return (
            self.returned_duration_ms
            if self.returned_duration_ms is not None
            else self.elapsed_ms
        )

    def to_json(self) -> dict[str, object]:
        return asdict(self)


class DecisionFailure(RuntimeError):
    """Both model decision attempts failed, with inspectable diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        attempts: tuple[DecisionAttemptDiagnostic, ...] = (),
        metrics: DecisionMetrics | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.metrics = metrics or DecisionMetrics(0, 0, 0.0, bool(attempts))

    def to_json(self) -> dict[str, object]:
        return {
            "message": str(self),
            "attempts": [attempt.to_json() for attempt in self.attempts],
            "metrics": asdict(self.metrics),
        }


class DecisionModel(Protocol):
    def decide(
        self,
        observation: ProjectedObservation,
        legal_actions: tuple[LegalAction, ...],
    ) -> ModelDecision: ...


class OllamaDecisionModel:
    def __init__(self, client: OllamaClient) -> None:
        self._client = client

    def decide(
        self,
        observation: ProjectedObservation,
        legal_actions: tuple[LegalAction, ...],
    ) -> ModelDecision:
        legal_indices = frozenset(action.index for action in legal_actions)
        prompt = _decision_prompt(observation, legal_actions)
        first: Generation | None = None
        first_started = time.perf_counter_ns()
        try:
            first = self._client.generate(
                prompt,
                format_schema=DECISION_SCHEMA,
                max_tokens=512,
            )
            decision = parse_action_decision(first.text, legal_indices)
        except (DecisionError, OllamaError) as first_error:
            first_elapsed = time.perf_counter_ns() - first_started
            first_diagnostic = _failure_diagnostic(first_error, first, first_elapsed)
            repair_prompt = _repair_prompt(prompt, first_error, first)
            second: Generation | None = None
            second_started = time.perf_counter_ns()
            try:
                second = self._client.generate(
                    repair_prompt,
                    format_schema=DECISION_SCHEMA,
                    max_tokens=512,
                )
                decision = parse_action_decision(second.text, legal_indices)
            except (DecisionError, OllamaError) as second_error:
                second_elapsed = time.perf_counter_ns() - second_started
                attempts = (
                    first_diagnostic,
                    _failure_diagnostic(second_error, second, second_elapsed),
                )
                raise DecisionFailure(
                    "decision failed after one repair: "
                    f"initial attempt: {first_error}; repair attempt: {second_error}",
                    attempts=attempts,
                    metrics=_failure_metrics(attempts),
                ) from second_error
            second_elapsed = time.perf_counter_ns() - second_started
            return ModelDecision(
                decision=decision,
                metrics=DecisionMetrics(
                    prompt_tokens=(
                        first_diagnostic.prompt_tokens + second.prompt_tokens
                    ),
                    output_tokens=(
                        first_diagnostic.output_tokens + second.output_tokens
                    ),
                    latency_ms=(
                        first_diagnostic.effective_latency_ms
                        + _effective_latency_ms(second, second_elapsed)
                    ),
                    repair_attempted=True,
                ),
                raw_response=second.text,
            )
        assert first is not None
        first_elapsed = time.perf_counter_ns() - first_started
        return ModelDecision(
            decision=decision,
            metrics=DecisionMetrics(
                prompt_tokens=first.prompt_tokens,
                output_tokens=first.output_tokens,
                latency_ms=_effective_latency_ms(first, first_elapsed),
                repair_attempted=False,
            ),
            raw_response=first.text,
        )


def _failure_diagnostic(
    error: Exception, generation: Generation | None, elapsed_ns: int
) -> DecisionAttemptDiagnostic:
    return DecisionAttemptDiagnostic(
        error=f"{type(error).__name__}: {error}",
        raw_response=generation.text if generation else None,
        prompt_tokens=generation.prompt_tokens if generation else 0,
        output_tokens=generation.output_tokens if generation else 0,
        elapsed_ms=elapsed_ns / 1_000_000,
        returned_duration_ms=(
            generation.total_duration_ns / 1_000_000
            if generation and generation.total_duration_ns > 0
            else None
        ),
    )


def _effective_latency_ms(generation: Generation, elapsed_ns: int) -> float:
    if generation.total_duration_ns > 0:
        return generation.total_duration_ns / 1_000_000
    return elapsed_ns / 1_000_000


def _failure_metrics(
    attempts: tuple[DecisionAttemptDiagnostic, ...],
) -> DecisionMetrics:
    return DecisionMetrics(
        prompt_tokens=sum(attempt.prompt_tokens for attempt in attempts),
        output_tokens=sum(attempt.output_tokens for attempt in attempts),
        latency_ms=sum(attempt.effective_latency_ms for attempt in attempts),
        repair_attempted=True,
    )


def _decision_prompt(
    observation: ProjectedObservation,
    legal_actions: tuple[LegalAction, ...],
) -> str:
    map_text = "\n".join(observation.map.rows)
    inventory = [
        {
            "letter": item.letter,
            "description": item.description,
            "object_class": item.object_class,
        }
        for item in observation.inventory
    ]
    actions = [
        {"action_index": action.index, "name": action.name} for action in legal_actions
    ]
    return f"""You control a lawful dwarven Valkyrie in NetHack.
Your current task is to stand on the downstairs tile (`>`). Do not descend.
Choose exactly one legal action.
Prefer safe exploration and avoid repeating actions that make no progress.
Return only one JSON object with exactly goal, candidates, action_index, and rationale.
Goal must contain 1-200 characters and rationale 1-500 characters after trimming.
Supply 1-5 candidate objects with exactly action_index, score, and reason. Candidate
reasons must contain 1-240 characters. Candidate action_index values must be unique,
legal JSON integer literals (never booleans or decimals); scores must be JSON numbers
from zero through one. The selected action_index must also be a legal JSON integer,
must occur in candidates, and must have the highest candidate score (ties are allowed).
Do not repeat any object key. Do not add fields. The rationale must be concise and
inspectable, not hidden chain-of-thought.

Step: {observation.step_index}
Message: {observation.message or "(none)"}
Prompt flags: {json.dumps(asdict(observation.prompt), separators=(",", ":"))}
Player: {json.dumps(asdict(observation.player), separators=(",", ":"))}
Inventory: {json.dumps(inventory, separators=(",", ":"))}
Legal actions: {json.dumps(actions, separators=(",", ":"))}

Visible map:
```text
{map_text}
```
"""


def _repair_prompt(prompt: str, error: Exception, first: object | None) -> str:
    previous = getattr(first, "text", "(request failed before a response)")
    return f"""{prompt}

Your previous response violated the decision contract.
Validation error: {error}
Previous response:
```text
{previous}
```
Return one corrected JSON object only.
Use a legal action index and include it among one to five unique candidates.
Give the selected action the highest score.
"""
