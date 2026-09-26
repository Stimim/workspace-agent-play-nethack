from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Final

DECISION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["goal", "candidates", "action_index", "rationale"],
    "properties": {
        "goal": {"type": "string", "minLength": 1, "maxLength": 200},
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action_index", "score", "reason"],
                "properties": {
                    "action_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "A JSON integer literal; decimals are invalid.",
                    },
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                    },
                },
            },
        },
        "action_index": {
            "type": "integer",
            "minimum": 0,
            "description": "A JSON integer literal; decimals are invalid.",
        },
        "rationale": {"type": "string", "minLength": 1, "maxLength": 500},
    },
}


class DecisionError(ValueError):
    """A model response does not satisfy the action decision contract."""


class RunState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    TERMINAL = "terminal"
    STOPPED = "stopped"
    ERROR = "error"


class RunOutcome(Enum):
    TASK_SUCCESS = "task_success"
    DEATH = "death"
    TRUNCATED = "truncated"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    action_index: int
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class ActionDecision:
    goal: str
    candidates: tuple[ActionCandidate, ...]
    action_index: int
    rationale: str

    def to_json(self) -> dict[str, object]:
        return {
            "goal": self.goal,
            "candidates": [asdict(candidate) for candidate in self.candidates],
            "action_index": self.action_index,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class DecisionMetrics:
    prompt_tokens: int
    output_tokens: int
    latency_ms: float
    repair_attempted: bool


@dataclass(frozen=True, slots=True)
class ModelDecision:
    decision: ActionDecision
    metrics: DecisionMetrics
    raw_response: str


def parse_action_decision(
    text: str, legal_action_indices: frozenset[int]
) -> ActionDecision:
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except json.JSONDecodeError as error:
        raise DecisionError(f"response is not valid JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise DecisionError("response must be a JSON object")
    expected_keys = {"goal", "candidates", "action_index", "rationale"}
    if set(payload) != expected_keys:
        raise DecisionError("response fields do not exactly match the decision schema")

    goal = _bounded_text(payload["goal"], "goal", maximum=200)
    rationale = _bounded_text(payload["rationale"], "rationale", maximum=500)
    action_index = _integer(payload["action_index"], "action_index")
    if action_index not in legal_action_indices:
        raise DecisionError(f"action_index {action_index} is not legal")

    candidate_payloads = payload["candidates"]
    if (
        not isinstance(candidate_payloads, list)
        or not 1 <= len(candidate_payloads) <= 5
    ):
        raise DecisionError("candidates must contain between one and five items")
    candidates = tuple(
        _parse_candidate(candidate, legal_action_indices)
        for candidate in candidate_payloads
    )
    candidate_indices = [candidate.action_index for candidate in candidates]
    if len(candidate_indices) != len(set(candidate_indices)):
        raise DecisionError("candidate action indices must be unique")
    if action_index not in candidate_indices:
        raise DecisionError("selected action_index must appear in candidates")
    chosen_score = next(
        candidate.score
        for candidate in candidates
        if candidate.action_index == action_index
    )
    if chosen_score < max(candidate.score for candidate in candidates):
        raise DecisionError(
            "selected action_index must have the highest candidate score"
        )
    return ActionDecision(goal, candidates, action_index, rationale)


def _parse_candidate(
    payload: object, legal_action_indices: frozenset[int]
) -> ActionCandidate:
    if not isinstance(payload, dict):
        raise DecisionError("each candidate must be an object")
    if set(payload) != {"action_index", "score", "reason"}:
        raise DecisionError("candidate fields do not exactly match the schema")
    action_index = _integer(payload["action_index"], "candidate action_index")
    if action_index not in legal_action_indices:
        raise DecisionError(f"candidate action_index {action_index} is not legal")
    score_value = payload["score"]
    if isinstance(score_value, bool) or not isinstance(score_value, int | float):
        raise DecisionError("candidate score must be a number")
    score = float(score_value)
    if not 0 <= score <= 1:
        raise DecisionError("candidate score must be between zero and one")
    reason = _bounded_text(payload["reason"], "candidate reason", maximum=240)
    return ActionCandidate(action_index, score, reason)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DecisionError(f"response contains duplicate object key {key!r}")
        result[key] = value
    return result


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DecisionError(f"{name} must be an integer")
    return value


def _bounded_text(value: object, name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise DecisionError(f"{name} must be a string")
    text = value.strip()
    if not text or len(text) > maximum:
        raise DecisionError(f"{name} must contain between 1 and {maximum} characters")
    return text
