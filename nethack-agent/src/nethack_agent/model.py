from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Final, Protocol, TypeVar

from nethack_agent.contracts import (
    ContractError,
    integer_value,
    number_value,
    string_value,
)
from nethack_agent.decision import (
    ACTION_DECISION_SCHEMA,
    MAX_CANDIDATE_REASON_LENGTH,
    MAX_FALLBACK_CANDIDATES,
    SKILL_DECISION_SCHEMA,
    ActionCandidate,
    ActionDecision,
    DecisionError,
    DecisionMetrics,
    Goal,
    ModelActionDecision,
    ModelSkillDecision,
    Skill,
    SkillDecision,
    StuckReason,
    parse_action_decision,
    parse_skill_decision,
)
from nethack_agent.environment import LegalAction
from nethack_agent.knowledge import KnowledgeBundle
from nethack_agent.observation import ProjectedObservation
from nethack_agent.ollama import (
    Generation,
    OllamaClient,
    OllamaContextLimitError,
    OllamaError,
)


@dataclass(frozen=True, slots=True)
class DecisionAttemptDiagnostic:
    error: str
    raw_response: str | None
    prompt_tokens: int
    output_tokens: int
    elapsed_ms: float
    returned_duration_ms: float | None

    def __post_init__(self) -> None:
        string_value(self.error, "decision attempt error", minimum=1, maximum=8192)
        if self.raw_response is not None:
            string_value(self.raw_response, "decision raw response", maximum=65536)
        integer_value(self.prompt_tokens, "decision prompt_tokens", minimum=0)
        integer_value(self.output_tokens, "decision output_tokens", minimum=0)
        if number_value(self.elapsed_ms, "decision elapsed_ms") < 0:
            raise ContractError("decision elapsed_ms must be nonnegative")
        if (
            self.returned_duration_ms is not None
            and number_value(self.returned_duration_ms, "decision returned_duration_ms")
            < 0
        ):
            raise ContractError("decision returned_duration_ms must be nonnegative")

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
            "metrics": self.metrics.to_json(),
        }


class HierarchicalDecisionModel(Protocol):
    def select_skill(
        self,
        observation: ProjectedObservation,
        available_goals: tuple[Goal, ...],
        available_skills: tuple[Skill, ...],
        stuck: StuckReason | None,
    ) -> ModelSkillDecision: ...

    def select_action(
        self,
        observation: ProjectedObservation,
        legal_actions: tuple[LegalAction, ...],
        goal: Goal,
        skill: Skill,
    ) -> ModelActionDecision: ...


class ScriptedDevelopmentModel:
    """Deterministic no-Ollama model for explicit development verification."""

    _metrics = DecisionMetrics(0, 0, 0.0, False)

    def select_skill(
        self,
        observation: ProjectedObservation,
        available_goals: tuple[Goal, ...],
        available_skills: tuple[Skill, ...],
        stuck: StuckReason | None,
    ) -> ModelSkillDecision:
        del observation
        goal = Goal.STAND_ON_DOWNSTAIRS
        skill = Skill.EXPLORE_LEVEL
        if goal not in available_goals or skill not in available_skills:
            raise DecisionFailure("development goal or skill is unavailable")
        rationale = (
            "Explore deterministically during development verification."
            if stuck is None
            else "Grant exploration another bounded search round."
        )
        decision = SkillDecision(goal, skill, rationale)
        return ModelSkillDecision(
            decision, self._metrics, json.dumps(decision.to_json(), sort_keys=True)
        )

    def select_action(
        self,
        observation: ProjectedObservation,
        legal_actions: tuple[LegalAction, ...],
        goal: Goal,
        skill: Skill,
    ) -> ModelActionDecision:
        del observation, goal, skill
        wait = next(
            (action for action in legal_actions if action.name == "MiscDirection.WAIT"),
            None,
        )
        if wait is None:
            raise DecisionFailure("development wait action is unavailable")
        rationale = "Wait for one deterministic development verification step."
        decision = ActionDecision(
            candidates=(ActionCandidate(wait.index, 1.0, "Development wait."),),
            action_index=wait.index,
            rationale=rationale,
        )
        return ModelActionDecision(
            decision, self._metrics, json.dumps(decision.to_json(), sort_keys=True)
        )


class OllamaDecisionModel:
    def __init__(self, client: OllamaClient, knowledge_bundle: KnowledgeBundle) -> None:
        self._client = client
        self._knowledge_bundle = knowledge_bundle

    def select_skill(
        self,
        observation: ProjectedObservation,
        available_goals: tuple[Goal, ...],
        available_skills: tuple[Skill, ...],
        stuck: StuckReason | None,
    ) -> ModelSkillDecision:
        goals = frozenset(available_goals)
        skills = frozenset(available_skills)
        decision, metrics, raw_response = self._request_decision(
            _skill_prompt(
                observation,
                available_goals,
                available_skills,
                stuck,
                self._knowledge_bundle.prompt_context,
            ),
            SKILL_DECISION_SCHEMA,
            lambda text: parse_skill_decision(text, goals, skills),
        )
        return ModelSkillDecision(decision, metrics, raw_response)

    def select_action(
        self,
        observation: ProjectedObservation,
        legal_actions: tuple[LegalAction, ...],
        goal: Goal,
        skill: Skill,
    ) -> ModelActionDecision:
        legal_indices = frozenset(action.index for action in legal_actions)
        decision, metrics, raw_response = self._request_decision(
            _action_prompt(
                observation,
                legal_actions,
                goal,
                skill,
                self._knowledge_bundle.prompt_context,
            ),
            ACTION_DECISION_SCHEMA,
            lambda text: parse_action_decision(text, legal_indices),
        )
        return ModelActionDecision(decision, metrics, raw_response)

    def _request_decision(
        self,
        prompt: str,
        schema: dict[str, object],
        parse: Callable[[str], DecisionT],
    ) -> tuple[DecisionT, DecisionMetrics, str]:
        first: Generation | None = None
        first_started = time.perf_counter_ns()
        try:
            first = self._client.generate(prompt, format_schema=schema, max_tokens=512)
            decision = parse(first.text)
        except (DecisionError, OllamaError) as first_error:
            first_elapsed = time.perf_counter_ns() - first_started
            first_diagnostic = _failure_diagnostic(first_error, first, first_elapsed)
            repair_prompt = _repair_prompt(prompt, first_error, first)
            second: Generation | None = None
            second_started = time.perf_counter_ns()
            try:
                second = self._client.generate(
                    repair_prompt, format_schema=schema, max_tokens=512
                )
                decision = parse(second.text)
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
            return (
                decision,
                DecisionMetrics(
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
                second.text,
            )
        assert first is not None
        first_elapsed = time.perf_counter_ns() - first_started
        return (
            decision,
            DecisionMetrics(
                prompt_tokens=first.prompt_tokens,
                output_tokens=first.output_tokens,
                latency_ms=_effective_latency_ms(first, first_elapsed),
                repair_attempted=False,
            ),
            first.text,
        )


DecisionT = TypeVar("DecisionT", SkillDecision, ActionDecision)


def _failure_diagnostic(
    error: Exception, generation: Generation | None, elapsed_ns: int
) -> DecisionAttemptDiagnostic:
    if generation is None and isinstance(error, OllamaContextLimitError):
        generation = error.generation
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


_SKILL_DESCRIPTIONS: Final = {
    Skill.STAIRCASE_NAVIGATION: (
        "route over known terrain to a remembered downstairs; it can act only "
        "while a downstairs is known and reachable"
    ),
    Skill.EXPLORE_LEVEL: (
        "walk to the nearest unexplored space, open doors, and search walls and "
        "dead ends for hidden passages within a bounded budget"
    ),
}
_STUCK_DESCRIPTIONS: Final = {
    StuckReason.SEARCH_EXHAUSTED: (
        "no unexplored space is reachable and this round's search budget is spent"
    ),
    StuckReason.MONSTER_BLOCKED: (
        "the only routes to unexplored space are blocked by a peaceful or "
        "unsafe-to-melee monster that has not moved"
    ),
}


def _skill_prompt(
    observation: ProjectedObservation,
    available_goals: tuple[Goal, ...],
    available_skills: tuple[Skill, ...],
    stuck: StuckReason | None,
    knowledge_context: str,
) -> str:
    skills = "\n".join(
        f"- {skill.value}: {_SKILL_DESCRIPTIONS[skill]}" for skill in available_skills
    )
    if stuck is None:
        situation = "The episode is starting."
        map_section = ""
    else:
        map_text = "\n".join(observation.map.rows)
        situation = (
            f"Deterministic exploration is stuck: {_STUCK_DESCRIPTIONS[stuck]}. "
            "staircase_navigation cannot act now: no downstairs is known and "
            "reachable. Choose explore_level to grant exploration one more bounded "
            "search round for hidden doors and corridors; that is normally right. "
            "Choose staircase_navigation only to pick each action yourself until "
            "exploration makes progress."
        )
        map_section = f"\nVisible map:\n```text\n{map_text}\n```\n"
    return f"""You control a lawful dwarven Valkyrie in NetHack.
Choose the current goal and skill. The task is to stand on the downstairs tile (`>`)
without descending. A deterministic arbiter runs staircase_navigation whenever a
downstairs is known and reachable and explore_level otherwise; you are consulted
at the start and when exploration is stuck. Return only one JSON object with
exactly goal, skill, and rationale. Use one of the supplied identifiers. Keep the
rationale to one short sentence; do not provide hidden chain-of-thought.

{knowledge_context}

Skills:
{skills}

Situation: {situation}
Step: {observation.step_index}
Message: {observation.message or "(none)"}
Available goals: {json.dumps([goal.value for goal in available_goals])}
Available skills: {json.dumps([skill.value for skill in available_skills])}
{map_section}"""


def _action_prompt(
    observation: ProjectedObservation,
    legal_actions: tuple[LegalAction, ...],
    goal: Goal,
    skill: Skill,
    knowledge_context: str,
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
The deterministic {skill.value} skill cannot select an unambiguous routine action.
Choose exactly one supplied fallback action for goal {goal.value}. Never change level.
Return only one JSON object with exactly candidates, action_index, and rationale.
Supply 1-{MAX_FALLBACK_CANDIDATES} candidate objects with exactly action_index,
score, and reason. Candidate indices must be unique legal JSON integers; scores must
be numbers from zero through one. The selected index must occur in candidates and
have the highest score. Keep each reason under {MAX_CANDIDATE_REASON_LENGTH}
characters and the rationale to one short sentence; do not provide hidden
chain-of-thought.

{knowledge_context}

Step: {observation.step_index}
Message: {observation.message or "(none)"}
Prompt flags: {json.dumps(asdict(observation.prompt), separators=(",", ":"))}
Player: {json.dumps(asdict(observation.player), separators=(",", ":"))}
Inventory: {json.dumps(inventory, separators=(",", ":"))}
Legal fallback actions: {json.dumps(actions, separators=(",", ":"))}

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
"""
