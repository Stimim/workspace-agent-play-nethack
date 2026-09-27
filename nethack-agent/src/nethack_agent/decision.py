from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Final, Self

from nethack_agent.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    number_value,
    object_value,
    optional_enum_value,
    string_value,
)

# Level changes are never part of the staircase task. `<` on dungeon level 1
# leaves the dungeon and ends the game; `>` descends instead of standing on `>`.
FORBIDDEN_ACTION_NAMES: Final = frozenset({"MiscDirection.UP", "MiscDirection.DOWN"})


class Goal(Enum):
    STAND_ON_DOWNSTAIRS = "stand_on_downstairs"


class Skill(Enum):
    STAIRCASE_NAVIGATION = "staircase_navigation"
    EXPLORE_LEVEL = "explore_level"


class SkillSelectionSource(Enum):
    """Who chose the skill that controlled a step."""

    # The deterministic switch: a routable visible `>` selects staircase
    # navigation, otherwise level exploration.
    ARBITER = "arbiter"
    # The latest model skill decision after exploration reported stuck.
    MODEL = "model"


class StuckReason(Enum):
    """Why deterministic exploration could not propose an action."""

    SEARCH_EXHAUSTED = "search_exhausted"
    MONSTER_BLOCKED = "monster_blocked"


class DestinationKind(Enum):
    """What the map cell a deterministic skill works toward is."""

    # A remembered `>` that staircase navigation routes to or stands on.
    DOWNSTAIRS = "downstairs"
    # The known cell next to never-observed space that exploration routes to.
    FRONTIER = "frontier"
    # The committed spot exploration walks to and searches from.
    SEARCH_SPOT = "search_spot"
    # A known-locked door exploration walks beside, kicks, and aims a kick at.
    LOCKED_DOOR = "locked_door"


MAX_FALLBACK_CANDIDATES: Final = 3
MAX_CANDIDATE_REASON_LENGTH: Final = 100
MAX_DECISION_RATIONALE_LENGTH: Final = 200

SKILL_DECISION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["goal", "skill", "rationale"],
    "properties": {
        "goal": {"type": "string", "enum": [goal.value for goal in Goal]},
        "skill": {"type": "string", "enum": [skill.value for skill in Skill]},
        "rationale": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_DECISION_RATIONALE_LENGTH,
        },
    },
}

ACTION_DECISION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates", "action_index", "rationale"],
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_FALLBACK_CANDIDATES,
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
                        "maxLength": MAX_CANDIDATE_REASON_LENGTH,
                    },
                },
            },
        },
        "action_index": {
            "type": "integer",
            "minimum": 0,
            "description": "A JSON integer literal; decimals are invalid.",
        },
        "rationale": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_DECISION_RATIONALE_LENGTH,
        },
    },
}


class DecisionError(ContractError):
    """A model response does not satisfy a decision contract."""


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


class ActionSelectionSource(Enum):
    DETERMINISTIC_SKILL = "deterministic_skill"
    DETERMINISTIC_PROMPT = "deterministic_prompt"
    MODEL_FALLBACK = "model_fallback"


@dataclass(frozen=True, slots=True)
class SkillDecision:
    goal: Goal
    skill: Skill
    rationale: str

    def __post_init__(self) -> None:
        if not isinstance(self.goal, Goal):
            raise TypeError("goal must be a Goal")
        if not isinstance(self.skill, Skill):
            raise TypeError("skill must be a Skill")
        _decision_text(
            self.rationale, "skill rationale", maximum=MAX_DECISION_RATIONALE_LENGTH
        )

    def to_json(self) -> dict[str, object]:
        return {
            "goal": self.goal.value,
            "skill": self.skill.value,
            "rationale": self.rationale,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "skill decision", {"goal", "skill", "rationale"})
        return cls(
            goal=enum_value(payload["goal"], "skill decision goal", Goal),
            skill=enum_value(payload["skill"], "skill decision skill", Skill),
            rationale=_decision_text(
                payload["rationale"],
                "skill decision rationale",
                maximum=MAX_DECISION_RATIONALE_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    action_index: int
    score: float
    reason: str

    def __post_init__(self) -> None:
        integer_value(self.action_index, "candidate action_index", minimum=0)
        score = number_value(self.score, "candidate score")
        if not 0 <= score <= 1:
            raise DecisionError("candidate score must be between zero and one")
        _decision_text(
            self.reason, "candidate reason", maximum=MAX_CANDIDATE_REASON_LENGTH
        )

    def to_json(self) -> dict[str, object]:
        return {
            "action_index": self.action_index,
            "score": self.score,
            "reason": self.reason,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value, "action candidate", {"action_index", "score", "reason"}
        )
        return cls(
            action_index=integer_value(
                payload["action_index"], "candidate action_index", minimum=0
            ),
            score=number_value(payload["score"], "candidate score"),
            reason=_decision_text(
                payload["reason"],
                "candidate reason",
                maximum=MAX_CANDIDATE_REASON_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ActionDecision:
    candidates: tuple[ActionCandidate, ...]
    action_index: int
    rationale: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.candidates) <= MAX_FALLBACK_CANDIDATES:
            raise DecisionError(
                "candidates must contain between one and "
                f"{MAX_FALLBACK_CANDIDATES} items"
            )
        if not all(
            isinstance(candidate, ActionCandidate) for candidate in self.candidates
        ):
            raise TypeError("candidates must contain ActionCandidate values")
        action_index = integer_value(self.action_index, "action_index", minimum=0)
        _decision_text(
            self.rationale, "action rationale", maximum=MAX_DECISION_RATIONALE_LENGTH
        )
        candidate_indices = [candidate.action_index for candidate in self.candidates]
        if len(candidate_indices) != len(set(candidate_indices)):
            raise DecisionError("candidate action indices must be unique")
        if action_index not in candidate_indices:
            raise DecisionError("selected action_index must appear in candidates")
        selected = next(
            candidate.score
            for candidate in self.candidates
            if candidate.action_index == action_index
        )
        if selected < max(candidate.score for candidate in self.candidates):
            raise DecisionError(
                "selected action_index must have the highest candidate score"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "action_index": self.action_index,
            "rationale": self.rationale,
        }

    @classmethod
    def from_json(
        cls, value: object, legal_action_indices: frozenset[int] | None = None
    ) -> Self:
        payload = object_value(
            value, "action decision", {"candidates", "action_index", "rationale"}
        )
        candidates = tuple(
            ActionCandidate.from_json(candidate)
            for candidate in array_value(payload["candidates"], "candidates")
        )
        decision = cls(
            candidates=candidates,
            action_index=integer_value(
                payload["action_index"], "action_index", minimum=0
            ),
            rationale=_decision_text(
                payload["rationale"],
                "action rationale",
                maximum=MAX_DECISION_RATIONALE_LENGTH,
            ),
        )
        if legal_action_indices is not None:
            illegal = sorted(
                candidate.action_index
                for candidate in decision.candidates
                if candidate.action_index not in legal_action_indices
            )
            if illegal:
                raise DecisionError(f"candidate action_index {illegal[0]} is not legal")
            if decision.action_index not in legal_action_indices:
                raise DecisionError(
                    f"action_index {decision.action_index} is not legal"
                )
        return decision


@dataclass(frozen=True, slots=True)
class DecisionMetrics:
    prompt_tokens: int
    output_tokens: int
    latency_ms: float
    repair_attempted: bool

    def __post_init__(self) -> None:
        integer_value(self.prompt_tokens, "prompt_tokens", minimum=0)
        integer_value(self.output_tokens, "output_tokens", minimum=0)
        latency = number_value(self.latency_ms, "latency_ms")
        if latency < 0:
            raise ContractError("latency_ms must be nonnegative")
        boolean_value(self.repair_attempted, "repair_attempted")

    def to_json(self) -> dict[str, object]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "repair_attempted": self.repair_attempted,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value,
            "decision metrics",
            {"prompt_tokens", "output_tokens", "latency_ms", "repair_attempted"},
        )
        return cls(
            prompt_tokens=integer_value(
                payload["prompt_tokens"], "prompt_tokens", minimum=0
            ),
            output_tokens=integer_value(
                payload["output_tokens"], "output_tokens", minimum=0
            ),
            latency_ms=number_value(payload["latency_ms"], "latency_ms"),
            repair_attempted=boolean_value(
                payload["repair_attempted"], "repair_attempted"
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelSkillDecision:
    decision: SkillDecision
    metrics: DecisionMetrics
    raw_response: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision, SkillDecision):
            raise TypeError("decision must be a SkillDecision")
        if not isinstance(self.metrics, DecisionMetrics):
            raise TypeError("metrics must be DecisionMetrics")
        string_value(self.raw_response, "raw_response", maximum=65536)


@dataclass(frozen=True, slots=True)
class ModelActionDecision:
    decision: ActionDecision
    metrics: DecisionMetrics
    raw_response: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ActionDecision):
            raise TypeError("decision must be an ActionDecision")
        if not isinstance(self.metrics, DecisionMetrics):
            raise TypeError("metrics must be DecisionMetrics")
        string_value(self.raw_response, "raw_response", maximum=65536)


@dataclass(frozen=True, slots=True)
class MapCell:
    """Zero-based map coordinates, as in the projected observation."""

    x: int
    y: int

    def __post_init__(self) -> None:
        integer_value(self.x, "map cell x", minimum=0)
        integer_value(self.y, "map cell y", minimum=0)

    def to_json(self) -> dict[str, object]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_json(cls, value: object, name: str) -> Self:
        payload = object_value(value, name, {"x", "y"})
        return cls(
            x=integer_value(payload["x"], f"{name} x", minimum=0),
            y=integer_value(payload["y"], f"{name} y", minimum=0),
        )


@dataclass(frozen=True, slots=True)
class IntentDestination:
    kind: DestinationKind
    x: int
    y: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DestinationKind):
            raise TypeError("destination kind must be a DestinationKind")
        integer_value(self.x, "intent destination x", minimum=0)
        integer_value(self.y, "intent destination y", minimum=0)

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "x": self.x, "y": self.y}

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "intent destination", {"kind", "x", "y"})
        return cls(
            kind=enum_value(
                payload["kind"], "intent destination kind", DestinationKind
            ),
            x=integer_value(payload["x"], "intent destination x", minimum=0),
            y=integer_value(payload["y"], "intent destination y", minimum=0),
        )


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """The map targets a deterministic skill chose for one action.

    `destination` is the skill's route goal (or, for kicking, the locked
    door), usually not the adjacent cell the action steps into.
    `attack_target` is the displayed hostile monster the action attacks by
    moving into it. Both come from the skill's own routing data.
    """

    destination: IntentDestination | None
    attack_target: MapCell | None

    def __post_init__(self) -> None:
        if self.destination is not None and not isinstance(
            self.destination, IntentDestination
        ):
            raise TypeError("intent destination must be an IntentDestination")
        if self.attack_target is not None and not isinstance(
            self.attack_target, MapCell
        ):
            raise TypeError("intent attack_target must be a MapCell")
        if self.destination is None and self.attack_target is None:
            raise ContractError("intent requires a destination or an attack target")

    def cells(self) -> tuple[IntentDestination | MapCell, ...]:
        return tuple(
            cell for cell in (self.destination, self.attack_target) if cell is not None
        )

    def to_json(self) -> dict[str, object]:
        return {
            "destination": self.destination.to_json() if self.destination else None,
            "attack_target": (
                self.attack_target.to_json() if self.attack_target else None
            ),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "intent", {"destination", "attack_target"})
        destination = payload["destination"]
        attack_target = payload["attack_target"]
        return cls(
            destination=(
                None
                if destination is None
                else IntentDestination.from_json(destination)
            ),
            attack_target=(
                None
                if attack_target is None
                else MapCell.from_json(attack_target, "intent attack_target")
            ),
        )


@dataclass(frozen=True, slots=True)
class ActionSelection:
    source: ActionSelectionSource
    goal: Goal
    skill: Skill
    skill_selection: SkillSelectionSource
    stuck_reason: StuckReason | None
    action_index: int
    rationale: str
    # None for prompt answers, model fallbacks, skill actions without a map
    # target, and steps recorded before intents existed (unknown).
    intent: ActionIntent | None

    def __post_init__(self) -> None:
        if not isinstance(self.source, ActionSelectionSource):
            raise TypeError("source must be an ActionSelectionSource")
        if not isinstance(self.goal, Goal):
            raise TypeError("goal must be a Goal")
        if not isinstance(self.skill, Skill):
            raise TypeError("skill must be a Skill")
        if not isinstance(self.skill_selection, SkillSelectionSource):
            raise TypeError("skill_selection must be a SkillSelectionSource")
        if self.stuck_reason is not None and not isinstance(
            self.stuck_reason, StuckReason
        ):
            raise TypeError("stuck_reason must be a StuckReason or None")
        integer_value(self.action_index, "selection action_index", minimum=0)
        string_value(
            self.rationale,
            "selection rationale",
            minimum=1,
            maximum=500,
            strip=True,
        )
        if self.intent is not None:
            if not isinstance(self.intent, ActionIntent):
                raise TypeError("intent must be an ActionIntent or None")
            if self.source is not ActionSelectionSource.DETERMINISTIC_SKILL:
                raise ContractError("only deterministic skill selections carry intent")
        if (
            self.skill_selection is SkillSelectionSource.MODEL
            and self.stuck_reason is None
        ):
            raise ContractError(
                "the model selects the step skill only after exploration is stuck"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "goal": self.goal.value,
            "skill": self.skill.value,
            "skill_selection": self.skill_selection.value,
            "stuck_reason": self.stuck_reason.value if self.stuck_reason else None,
            "action_index": self.action_index,
            "rationale": self.rationale,
            "intent": self.intent.to_json() if self.intent else None,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        # `intent` is absent from steps persisted before intents existed;
        # absent and null both mean no recorded intent.
        payload = object_value(
            value,
            "action selection",
            {
                "source",
                "goal",
                "skill",
                "skill_selection",
                "stuck_reason",
                "action_index",
                "rationale",
            },
            optional={"intent"},
        )
        intent = payload.get("intent")
        return cls(
            source=enum_value(
                payload["source"], "action selection source", ActionSelectionSource
            ),
            goal=enum_value(payload["goal"], "action selection goal", Goal),
            skill=enum_value(payload["skill"], "action selection skill", Skill),
            skill_selection=enum_value(
                payload["skill_selection"],
                "action selection skill_selection",
                SkillSelectionSource,
            ),
            stuck_reason=optional_enum_value(
                payload["stuck_reason"], "action selection stuck_reason", StuckReason
            ),
            action_index=integer_value(
                payload["action_index"], "selection action_index", minimum=0
            ),
            rationale=string_value(
                payload["rationale"],
                "selection rationale",
                minimum=1,
                maximum=500,
                strip=True,
            ),
            intent=None if intent is None else ActionIntent.from_json(intent),
        )


def parse_skill_decision(
    text: str,
    available_goals: frozenset[Goal],
    available_skills: frozenset[Skill],
) -> SkillDecision:
    payload = _load_model_json(text)
    try:
        decision = SkillDecision.from_json(payload)
    except ContractError as error:
        raise DecisionError(str(error)) from error
    if decision.goal not in available_goals:
        raise DecisionError(f"goal {decision.goal.value!r} is not available")
    if decision.skill not in available_skills:
        raise DecisionError(f"skill {decision.skill.value!r} is not available")
    return decision


def parse_action_decision(
    text: str, legal_action_indices: frozenset[int]
) -> ActionDecision:
    payload = _load_model_json(text)
    try:
        return ActionDecision.from_json(payload, legal_action_indices)
    except ContractError as error:
        raise DecisionError(str(error)) from error


def _load_model_json(text: str) -> dict[str, object]:
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise DecisionError(f"response is not valid JSON: {error.msg}") from error
    if not isinstance(payload, dict):
        raise DecisionError("response must be a JSON object")
    return payload


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DecisionError(f"response contains duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise DecisionError(f"response contains non-finite number {value}")


def _decision_text(value: object, name: str, *, maximum: int) -> str:
    try:
        return string_value(value, name, minimum=1, maximum=maximum, strip=True)
    except ContractError as error:
        raise DecisionError(str(error)) from error
