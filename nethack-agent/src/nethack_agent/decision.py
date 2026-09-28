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
from nethack_agent.tasks import PROMPT_KEY_ACTION_NAMES
from nethack_agent.traversal import (
    DUNGEON_EXIT_LEVEL,
    GOAL_TYPES,
    ExploreLevelGoal,
    Goal,
    LevelKey,
    StairDirection,
    StairIdentity,
    TraverseStairsGoal,
    candidate_tier,
    goal_from_json,
)

# The actions that change dungeon level. The gate passes one only with a
# coordinator TraversalPermit (ADR 0004); the model is never offered them.
# `<` on the first level asks to leave the dungeon, and `>` descends rather
# than standing on `>`.
LEVEL_CHANGE_ACTIONS: Final[dict[str, StairDirection]] = {
    "MiscDirection.UP": StairDirection.UP,
    "MiscDirection.DOWN": StairDirection.DOWN,
}

EAT_ACTION_NAME: Final = "Command.EAT"
ESC_COMMAND: Final = 27


class Skill(Enum):
    STAIRCASE_NAVIGATION = "staircase_navigation"
    EXPLORE_LEVEL = "explore_level"
    HUNGER = "hunger"


def model_selectable_skills(goal: Goal) -> tuple[Skill, ...]:
    """The skills the model may choose for `goal`.

    Staircase navigation serves only stair goals. Deterministic specialists
    such as hunger are never offered.
    """
    if isinstance(goal, ExploreLevelGoal):
        return (Skill.EXPLORE_LEVEL,)
    return (Skill.STAIRCASE_NAVIGATION, Skill.EXPLORE_LEVEL)


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

    # A remembered `>` that staircase navigation routes to, stands on, or uses.
    DOWNSTAIRS = "downstairs"
    # A remembered `<` that staircase navigation routes to, stands on, or uses.
    UPSTAIRS = "upstairs"
    # The known cell next to never-observed space that exploration routes to.
    FRONTIER = "frontier"
    # The committed spot exploration walks to and searches from.
    SEARCH_SPOT = "search_spot"
    # A known-locked door exploration walks beside, kicks, and aims a kick at.
    LOCKED_DOOR = "locked_door"


STAIR_DESTINATIONS: Final = {
    StairDirection.DOWN: DestinationKind.DOWNSTAIRS,
    StairDirection.UP: DestinationKind.UPSTAIRS,
}


MAX_FALLBACK_CANDIDATES: Final = 3
MAX_CANDIDATE_REASON_LENGTH: Final = 100
MAX_DECISION_RATIONALE_LENGTH: Final = 200
# A shortest route never revisits a cell, so it fits within NetHack's 21x79 map.
MAX_INTENT_PATH_LENGTH: Final = 21 * 79


def skill_decision_schema(
    goals: tuple[Goal, ...], skills: tuple[Skill, ...] = tuple(Skill)
) -> dict[str, object]:
    """The Ollama generation schema offering exactly these goals and skills."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["goal", "skill", "rationale"],
        "properties": {
            "goal": {"type": "string", "enum": [goal.token for goal in goals]},
            "skill": {"type": "string", "enum": [skill.value for skill in skills]},
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
    # The coordinator completed the last objective leg on a task without an
    # NLE success state; NLE neither terminated nor truncated the episode.
    OBJECTIVE_COMPLETE = "objective_complete"
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
        if not isinstance(self.goal, GOAL_TYPES):
            raise TypeError("goal must be a typed Goal")
        if not isinstance(self.skill, Skill):
            raise TypeError("skill must be a Skill")
        _decision_text(
            self.rationale, "skill rationale", maximum=MAX_DECISION_RATIONALE_LENGTH
        )

    def to_json(self) -> dict[str, object]:
        return {
            "goal": self.goal.to_json(),
            "skill": self.skill.value,
            "rationale": self.rationale,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "skill decision", {"goal", "skill", "rationale"})
        return cls(
            goal=goal_from_json(payload["goal"], "skill decision goal"),
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
    # What a stair destination was believed to connect to when chosen. None
    # for other kinds and for stair intents recorded before identities were.
    stair: StairIdentity | None = None
    # Whether level memory held two staircases of this direction when the
    # destination was chosen, the evidence that allows an unknown staircase
    # to be probed as a branch. None for other kinds and for stair intents
    # recorded before this evidence was.
    pair_known: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DestinationKind):
            raise TypeError("destination kind must be a DestinationKind")
        integer_value(self.x, "intent destination x", minimum=0)
        integer_value(self.y, "intent destination y", minimum=0)
        stair_kind = self.kind in STAIR_DESTINATIONS.values()
        if self.stair is not None:
            if not isinstance(self.stair, StairIdentity):
                raise TypeError("intent destination stair must be a StairIdentity")
            if not stair_kind:
                raise ContractError("only a stair destination has a stair identity")
        if self.pair_known is not None:
            boolean_value(self.pair_known, "intent destination pair_known")
            if not stair_kind:
                raise ContractError("only a stair destination records pair_known")

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {"kind": self.kind.value, "x": self.x, "y": self.y}
        if self.kind in STAIR_DESTINATIONS.values():
            result["stair"] = self.stair.to_json() if self.stair else None
            result["pair_known"] = self.pair_known
        return result

    @classmethod
    def from_json(cls, value: object) -> Self:
        # `stair` and `pair_known` are absent from stair intents recorded
        # before they were; absent and null both mean not recorded.
        payload = object_value(
            value,
            "intent destination",
            {"kind", "x", "y"},
            optional={"stair", "pair_known"},
        )
        stair = payload.get("stair")
        pair_known = payload.get("pair_known")
        return cls(
            kind=enum_value(
                payload["kind"], "intent destination kind", DestinationKind
            ),
            x=integer_value(payload["x"], "intent destination x", minimum=0),
            y=integer_value(payload["y"], "intent destination y", minimum=0),
            stair=(
                None
                if stair is None
                else StairIdentity.from_json(stair, "intent destination stair")
            ),
            pair_known=(
                None
                if pair_known is None
                else boolean_value(pair_known, "intent destination pair_known")
            ),
        )


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """The map targets a deterministic skill chose for one action.

    `destination` is the skill's route goal (or, for kicking, the locked
    door), usually not the adjacent cell the action steps into.
    `attack_target` is the displayed hostile monster the action attacks by
    moving into it. `path` is the breadth-first route the action follows:
    its cells after the hero's position, starting with the cell the action
    moves into and ending at the destination (for a locked door, at the cell
    orthogonally beside it where the hero kicks). It is None when the action
    does not step along a route (waiting, searching, kicking, and adjacent-
    hostile defense). All values come from the skill's own routing data.
    """

    destination: IntentDestination | None
    attack_target: MapCell | None
    path: tuple[MapCell, ...] | None
    # The level the cells belong to; the coordinator stamps it. None for
    # intents recorded before levels were.
    level: LevelKey | None = None

    def __post_init__(self) -> None:
        if self.destination is not None and not isinstance(
            self.destination, IntentDestination
        ):
            raise TypeError("intent destination must be an IntentDestination")
        if self.attack_target is not None and not isinstance(
            self.attack_target, MapCell
        ):
            raise TypeError("intent attack_target must be a MapCell")
        if self.level is not None and not isinstance(self.level, LevelKey):
            raise TypeError("intent level must be a LevelKey")
        if self.destination is None and self.attack_target is None:
            raise ContractError("intent requires a destination or an attack target")
        if self.path is not None:
            _validate_path(self.path, self.destination, self.attack_target)

    def cells(self) -> tuple[IntentDestination | MapCell, ...]:
        targets = (self.destination, self.attack_target)
        return (
            *(cell for cell in targets if cell is not None),
            *(self.path or ()),
        )

    def to_json(self) -> dict[str, object]:
        return {
            "destination": self.destination.to_json() if self.destination else None,
            "attack_target": (
                self.attack_target.to_json() if self.attack_target else None
            ),
            "path": (
                None if self.path is None else [cell.to_json() for cell in self.path]
            ),
            "level": self.level.to_json() if self.level else None,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        # `path` is absent from intents persisted before routes were recorded
        # and `level` from intents persisted before levels were; absent and
        # null both mean not recorded.
        payload = object_value(
            value,
            "intent",
            {"destination", "attack_target"},
            optional={"path", "level"},
        )
        destination = payload["destination"]
        attack_target = payload["attack_target"]
        path = payload.get("path")
        level = payload.get("level")
        if path is not None:
            path = array_value(path, "intent path")
            if len(path) > MAX_INTENT_PATH_LENGTH:
                raise ContractError(
                    f"intent path must have at most {MAX_INTENT_PATH_LENGTH} cells"
                )
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
            path=(
                None
                if path is None
                else tuple(MapCell.from_json(cell, "intent path cell") for cell in path)
            ),
            level=None if level is None else LevelKey.from_json(level, "intent level"),
        )


def _validate_path(
    path: object,
    destination: IntentDestination | None,
    attack_target: MapCell | None,
) -> None:
    if not isinstance(path, tuple) or not all(
        isinstance(cell, MapCell) for cell in path
    ):
        raise TypeError("intent path must be a tuple of MapCell values or None")
    if destination is None:
        raise ContractError("intent path requires a destination")
    if not 1 <= len(path) <= MAX_INTENT_PATH_LENGTH:
        raise ContractError(
            f"intent path must have 1 to {MAX_INTENT_PATH_LENGTH} cells"
        )
    if len({(cell.x, cell.y) for cell in path}) != len(path):
        raise ContractError("intent path must not revisit a cell")
    for before, after in zip(path, path[1:], strict=False):
        if max(abs(before.x - after.x), abs(before.y - after.y)) != 1:
            raise ContractError("intent path cells must be adjacent in order")
    last = path[-1]
    if destination.kind is DestinationKind.LOCKED_DOOR:
        # The hero kicks from beside the door, never diagonally.
        if abs(last.x - destination.x) + abs(last.y - destination.y) != 1:
            raise ContractError(
                "a locked-door intent path must end orthogonally beside the door"
            )
    elif (last.x, last.y) != (destination.x, destination.y):
        raise ContractError("intent path must end at the destination")
    if attack_target is not None and path[0] != attack_target:
        raise ContractError("intent path must start at the attack target")


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
    # The level this step's decision found exhausted: deterministic
    # exploration had nothing left to do there on the decided-on observation.
    # None when the step marked no exhaustion, and for steps recorded before
    # the marker existed (not recorded). The evaluator re-derives every marker.
    exhausted_level: LevelKey | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, ActionSelectionSource):
            raise TypeError("source must be an ActionSelectionSource")
        if not isinstance(self.goal, GOAL_TYPES):
            raise TypeError("goal must be a typed Goal")
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
        if self.exhausted_level is not None:
            if not isinstance(self.exhausted_level, LevelKey):
                raise TypeError("exhausted_level must be a LevelKey or None")
            if self.source is ActionSelectionSource.DETERMINISTIC_PROMPT:
                raise ContractError("a prompt answer cannot mark a level exhausted")
            if (
                self.intent is not None
                and self.intent.level is not None
                and self.intent.level != self.exhausted_level
            ):
                raise ContractError(
                    "an exhausted-level marker must name the intent's level"
                )

    def to_json(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "goal": self.goal.to_json(),
            "skill": self.skill.value,
            "skill_selection": self.skill_selection.value,
            "stuck_reason": self.stuck_reason.value if self.stuck_reason else None,
            "action_index": self.action_index,
            "rationale": self.rationale,
            "intent": self.intent.to_json() if self.intent else None,
            "exhausted_level": (
                self.exhausted_level.to_json() if self.exhausted_level else None
            ),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        # `intent` is absent from steps persisted before intents existed and
        # `exhausted_level` from steps persisted before exhaustion markers;
        # absent and null both mean not recorded.
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
            optional={"intent", "exhausted_level"},
        )
        intent = payload.get("intent")
        exhausted_level = payload.get("exhausted_level")
        return cls(
            source=enum_value(
                payload["source"], "action selection source", ActionSelectionSource
            ),
            goal=goal_from_json(payload["goal"], "action selection goal"),
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
            exhausted_level=(
                None
                if exhausted_level is None
                else LevelKey.from_json(exhausted_level, "selection exhausted_level")
            ),
        )


@dataclass(frozen=True, slots=True)
class TraversalPermit:
    """The coordinator's authorization for one level change from one staircase."""

    direction: StairDirection
    level: LevelKey
    cell: MapCell

    def __post_init__(self) -> None:
        if not isinstance(self.direction, StairDirection):
            raise TypeError("permit direction must be a StairDirection")
        if not isinstance(self.level, LevelKey):
            raise TypeError("permit level must be a LevelKey")
        if not isinstance(self.cell, MapCell):
            raise TypeError("permit cell must be a MapCell")


@dataclass(frozen=True, slots=True)
class HungerPermit:
    """Authorization for one evidence-backed EAT command."""

    item_letter: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.item_letter, str)
            or len(self.item_letter) != 1
            or not self.item_letter.isascii()
            or not self.item_letter.isalpha()
        ):
            raise ValueError("hunger permit item_letter must be one ASCII letter")


@dataclass(frozen=True, slots=True)
class PromptPermit:
    """Authorization for one command that answers or cancels an item prompt."""

    command: int

    def __post_init__(self) -> None:
        integer_value(self.command, "prompt permit command", minimum=0, maximum=255)


def survival_action_selection_error(
    action_name: str, selection: ActionSelection
) -> str | None:
    """Why a hunger-only action is invalid from its recorded selection fields."""
    if action_name == EAT_ACTION_NAME and (
        selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL
        or selection.skill is not Skill.HUNGER
        or selection.intent is not None
    ):
        return "only the deterministic hunger skill may select EAT"
    if action_name in PROMPT_KEY_ACTION_NAMES and (
        selection.source is not ActionSelectionSource.DETERMINISTIC_PROMPT
        or selection.skill is not Skill.HUNGER
        or selection.intent is not None
    ):
        return "prompt-key actions require the deterministic hunger prompt flow"
    return None


def hunger_action_error(
    action_name: str,
    selection: ActionSelection,
    *,
    hunger: int,
    prompt_active: bool,
    safe_ration_available: bool,
) -> str | None:
    """Why an EAT selection lacks the observation evidence needed for a permit."""
    error = survival_action_selection_error(action_name, selection)
    if error is not None or action_name != EAT_ACTION_NAME:
        return error
    if prompt_active:
        return "EAT cannot answer an active prompt"
    if hunger < 2:
        return "EAT requires Hungry or worse"
    if not safe_ration_available:
        return "EAT requires an explicitly known-safe inventory food ration"
    return None


def prompt_response_error(
    action_name: str,
    command: int,
    selection: ActionSelection,
    *,
    prompt_active: bool,
    item_selection: bool,
    offered_commands: frozenset[int],
) -> str | None:
    """Why an item-prompt answer lacks the active prompt evidence for a permit."""
    error = survival_action_selection_error(action_name, selection)
    if error is not None:
        return error
    if (
        selection.source is not ActionSelectionSource.DETERMINISTIC_PROMPT
        or selection.skill is not Skill.HUNGER
        or selection.intent is not None
    ):
        return "only the deterministic hunger prompt flow may answer item prompts"
    if not prompt_active or not item_selection:
        return (
            "an item prompt response requires a matching active item-selection prompt"
        )
    if command != ESC_COMMAND and command not in offered_commands:
        return "the item prompt did not offer that inventory letter"
    return None


def level_change_selection_error(
    direction: StairDirection, selection: ActionSelection
) -> str | None:
    """Why a selection may not change level, from its own recorded fields.

    A level change needs a traverse_stairs goal in its direction, chosen by
    deterministic staircase navigation, with an in-place intent on a staircase
    of that direction that records the staircase's identity and level.
    """
    goal = selection.goal
    if not isinstance(goal, TraverseStairsGoal) or goal.target.direction is not (
        direction
    ):
        return (
            f"changing level {direction.value} requires a traverse_stairs goal "
            "in that direction"
        )
    if (
        selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL
        or selection.skill is not Skill.STAIRCASE_NAVIGATION
    ):
        return "only deterministic staircase navigation may change level"
    intent = selection.intent
    destination = None if intent is None else intent.destination
    if (
        intent is None
        or destination is None
        or destination.kind is not STAIR_DESTINATIONS[direction]
        or destination.stair is None
        or intent.path is not None
        or intent.level is None
    ):
        return (
            "a level change requires an in-place intent on a staircase of its "
            "direction that records the staircase identity and level"
        )
    return None


def level_change_error(
    action_name: str,
    selection: ActionSelection,
    *,
    level_changes_allowed: bool,
    level: LevelKey,
    position: tuple[int, int],
    prompt_active: bool,
    pair_known: bool,
) -> str | None:
    """Why `action_name` may not change level here; None when it may.

    The coordinator applies it before issuing a TraversalPermit, and the
    evaluator audits every recorded step with it against the observation the
    step was decided on. Actions that do not change level always pass.
    """
    direction = LEVEL_CHANGE_ACTIONS.get(action_name)
    if direction is None:
        return None
    if not level_changes_allowed:
        return f"{action_name} is forbidden: this task never changes level"
    if direction is StairDirection.UP and level == DUNGEON_EXIT_LEVEL:
        return f"{action_name} is forbidden on {level}: it leaves the dungeon"
    error = level_change_selection_error(direction, selection)
    if error is not None:
        return error
    if prompt_active:
        return "a level change cannot answer an active prompt"
    intent = selection.intent
    assert intent is not None and intent.destination is not None
    destination = intent.destination
    if intent.level != level or (destination.x, destination.y) != position:
        return "the hero is not standing on the intent's staircase"
    goal = selection.goal
    assert isinstance(goal, TraverseStairsGoal) and destination.stair is not None
    if candidate_tier(goal.target, destination.stair, pair_known=pair_known) is None:
        return "the staircase's identity does not match the goal's target"
    return None


def parse_skill_decision(
    text: str,
    available_goals: tuple[Goal, ...],
    available_skills: frozenset[Skill],
) -> SkillDecision:
    """Parse a model skill decision that names one offered goal by its token."""
    payload = _load_model_json(text)
    offered = {goal.token: goal for goal in available_goals}
    try:
        fields = object_value(payload, "skill decision", {"goal", "skill", "rationale"})
        token = string_value(fields["goal"], "skill decision goal")
        goal = offered.get(token)
        if goal is None:
            raise DecisionError(f"goal {token!r} is not available")
        decision = SkillDecision(
            goal=goal,
            skill=enum_value(fields["skill"], "skill decision skill", Skill),
            rationale=_decision_text(
                fields["rationale"],
                "skill decision rationale",
                maximum=MAX_DECISION_RATIONALE_LENGTH,
            ),
        )
    except DecisionError:
        raise
    except ContractError as error:
        raise DecisionError(str(error)) from error
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
