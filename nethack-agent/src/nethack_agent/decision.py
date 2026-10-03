from __future__ import annotations

import json
import re
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
from nethack_agent.observation import ProjectedObservation
from nethack_agent.tasks import PROMPT_KEY_ACTION_NAMES
from nethack_agent.traversal import (
    DUNGEON_EXIT_LEVEL,
    GOAL_TYPES,
    ApproachOracleGoal,
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

PRAY_ACTION_NAME: Final = "Command.PRAY"
YES_COMMAND: Final = ord("y")
_PRAYER_CONFIRMATION: Final = "Are you sure you want to pray? [yn] (n) "
_FLOOR_CORPSE_CONFIRMATION: Final = re.compile(
    r"There is a ([a-z][a-z -]*) corpse here; eat it\? \[ynq\] \(n\) \Z"
)
EAT_ACTION_NAME: Final = "Command.EAT"
ESC_COMMAND: Final = 27
ALLOWED_CORPSES: Final = frozenset(
    {"lichen", "newt", "sewer rat", "giant rat", "gecko"}
)


def parse_floor_corpse_prompt(message: str) -> str | None:
    """Return only the exact corpse noun in NetHack's floor-eat question."""
    match = _FLOOR_CORPSE_CONFIRMATION.fullmatch(message)
    return None if match is None else match.group(1)


class Skill(Enum):
    STAIRCASE_NAVIGATION = "staircase_navigation"
    EXPLORE_LEVEL = "explore_level"
    CORPSE = "corpse"
    HUNGER = "hunger"
    PRAYER = "prayer"
    # Route to visible gold on NetHackGold-v0; deterministic, never offered to
    # the model.
    GOLD_NAVIGATION = "gold_navigation"


def model_selectable_skills(goal: Goal) -> tuple[Skill, ...]:
    """The skills the model may choose for `goal`.

    Staircase navigation serves only stair goals. Deterministic specialists
    such as hunger and gold navigation are never offered.
    """
    if isinstance(goal, ExploreLevelGoal):
        return (Skill.EXPLORE_LEVEL,)
    if isinstance(goal, ApproachOracleGoal):
        raise ValueError(f"{goal.kind.value} goals have no skills yet")
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
    # A displayed gold-piece stack gold navigation routes onto.
    GOLD = "gold"
    CORPSE = "corpse"


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


class CorpseOutcomeKind(Enum):
    FINISHED = "finished"
    INTERRUPTED = "interrupted"
    DECLINED = "declined"


@dataclass(frozen=True, slots=True)
class CorpseOutcome:
    kind: CorpseOutcomeKind
    turn: int
    hunger: int
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CorpseOutcomeKind):
            raise TypeError("corpse outcome kind must be a CorpseOutcomeKind")
        integer_value(self.turn, "corpse outcome turn", minimum=0)
        integer_value(self.hunger, "corpse outcome hunger", minimum=0)
        string_value(self.message, "corpse outcome message", maximum=4096)

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "turn": self.turn,
            "hunger": self.hunger,
            "message": self.message,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value, "corpse outcome", {"kind", "turn", "hunger", "message"}
        )
        return cls(
            kind=enum_value(payload["kind"], "corpse outcome kind", CorpseOutcomeKind),
            turn=integer_value(payload["turn"], "corpse outcome turn", minimum=0),
            hunger=integer_value(payload["hunger"], "corpse outcome hunger", minimum=0),
            message=string_value(
                payload["message"], "corpse outcome message", maximum=4096
            ),
        )


@dataclass(frozen=True, slots=True)
class CorpseEvidence:
    name: str
    kill_turn: int
    age: int
    cell: MapCell
    outcome: CorpseOutcome | None = None

    def __post_init__(self) -> None:
        string_value(self.name, "corpse name", minimum=1, maximum=100)
        if re.fullmatch(r"[a-z][a-z -]*", self.name) is None:
            raise ContractError("corpse name must be a lowercase monster name")
        integer_value(self.kill_turn, "corpse kill_turn", minimum=0)
        integer_value(self.age, "corpse age", minimum=0)
        if not isinstance(self.cell, MapCell):
            raise TypeError("corpse cell must be a MapCell")
        if self.outcome is not None:
            if not isinstance(self.outcome, CorpseOutcome):
                raise TypeError("corpse outcome must be a CorpseOutcome or None")
            if self.outcome.turn < self.kill_turn:
                raise ContractError("corpse outcome predates the observed kill")
            classified = classify_corpse_outcome(self.name, self.outcome.message)
            if self.outcome.kind is CorpseOutcomeKind.DECLINED:
                if classified is not None:
                    raise ContractError(
                        "declined corpse outcome cannot describe a meal"
                    )
            elif self.outcome.kind is not classified:
                raise ContractError("corpse outcome does not match observed meal text")

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kill_turn": self.kill_turn,
            "age": self.age,
            "cell": self.cell.to_json(),
            "outcome": None if self.outcome is None else self.outcome.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value,
            "corpse evidence",
            {"name", "kill_turn", "age", "cell"},
            optional={"outcome"},
        )
        outcome = payload.get("outcome")
        return cls(
            name=string_value(payload["name"], "corpse name", minimum=1, maximum=100),
            kill_turn=integer_value(
                payload["kill_turn"], "corpse kill_turn", minimum=0
            ),
            age=integer_value(payload["age"], "corpse age", minimum=0),
            cell=MapCell.from_json(payload["cell"], "corpse cell"),
            outcome=None if outcome is None else CorpseOutcome.from_json(outcome),
        )


def classify_corpse_outcome(name: str, message: str) -> CorpseOutcomeKind | None:
    """Do not call an unfinished multi-turn meal an interruption."""
    if f"You finish eating the {name} corpse." in message:
        return CorpseOutcomeKind.FINISHED
    if "You stop eating" in message or "You are interrupted" in message:
        return CorpseOutcomeKind.INTERRUPTED
    return None


def is_corpse_decline(command: int, selection: ActionSelection) -> bool:
    """Only a prompt answer declines food; the same `n` command moves SE."""
    return (
        selection.skill is Skill.CORPSE
        and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        and command in (ord("n"), ESC_COMMAND)
    )


def observed_corpse_decline(
    command: int,
    selection: ActionSelection,
    observation: ProjectedObservation,
    *,
    terminated: bool,
    truncated: bool,
) -> CorpseOutcome | None:
    """The shared live decline outcome, never inferred from terminal stats."""
    if not is_corpse_decline(command, selection) or terminated or truncated:
        return None
    return CorpseOutcome(
        CorpseOutcomeKind.DECLINED,
        observation.player.turn,
        observation.player.hunger,
        observation.message,
    )


PRAYER_FIRST_SAFE_TURN: Final = 100
PRAYER_REPEAT_WAIT_TURNS: Final = 1229


class PrayerOutcomeKind(Enum):
    FIXED = "fixed"
    NOT_FIXED = "not_fixed"
    DISPLEASED_OR_PUNISHED = "displeased_or_punished"


def classify_prayer_outcome(hunger: int, message: str) -> PrayerOutcomeKind | None:
    """Classify a live prayer result, without treating hidden favor as evidence."""
    if (
        "displeased" in message
        or "Thou must relearn thy lessons!" in message
        or "You feel foolish!" in message
    ):
        return PrayerOutcomeKind.DISPLEASED_OR_PUNISHED
    if hunger < 3 or "Your stomach feels content." in message:
        return PrayerOutcomeKind.FIXED
    if "You finish your prayer." in message or "You feel that" in message:
        return PrayerOutcomeKind.NOT_FIXED
    return None


@dataclass(frozen=True, slots=True)
class PrayerOutcome:
    turn: int
    hunger: int
    message: str
    kind: PrayerOutcomeKind

    def __post_init__(self) -> None:
        integer_value(self.turn, "prayer outcome turn", minimum=0)
        integer_value(self.hunger, "prayer outcome hunger", minimum=0)
        string_value(self.message, "prayer outcome message", maximum=4096)
        if not isinstance(self.kind, PrayerOutcomeKind):
            raise TypeError("prayer outcome kind must be a PrayerOutcomeKind")
        if self.kind is not classify_prayer_outcome(self.hunger, self.message):
            raise ContractError(
                "prayer outcome kind does not match observed hunger and message"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "turn": self.turn,
            "hunger": self.hunger,
            "message": self.message,
            "kind": self.kind.value,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value, "prayer outcome", {"turn", "hunger", "message", "kind"}
        )
        return cls(
            turn=integer_value(payload["turn"], "prayer outcome turn", minimum=0),
            hunger=integer_value(payload["hunger"], "prayer outcome hunger", minimum=0),
            message=string_value(
                payload["message"], "prayer outcome message", maximum=4096
            ),
            kind=enum_value(payload["kind"], "prayer outcome kind", PrayerOutcomeKind),
        )


@dataclass(frozen=True, slots=True)
class PrayerEvidence:
    reason_hunger: int
    prayer_turn: int
    safe_turn: int
    kill_count: int = 0
    outcome: PrayerOutcome | None = None

    def __post_init__(self) -> None:
        integer_value(self.reason_hunger, "prayer reason_hunger", minimum=0)
        integer_value(self.prayer_turn, "prayer prayer_turn", minimum=0)
        integer_value(self.safe_turn, "prayer safe_turn", minimum=0)
        integer_value(self.kill_count, "prayer kill_count", minimum=0)
        if self.outcome is not None and not isinstance(self.outcome, PrayerOutcome):
            raise TypeError("prayer outcome must be a PrayerOutcome or None")

    def to_json(self) -> dict[str, object]:
        return {
            "reason_hunger": self.reason_hunger,
            "prayer_turn": self.prayer_turn,
            "safe_turn": self.safe_turn,
            "kill_count": self.kill_count,
            "outcome": None if self.outcome is None else self.outcome.to_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value,
            "prayer evidence",
            {"reason_hunger", "prayer_turn", "safe_turn", "kill_count"},
            optional={"outcome"},
        )
        outcome = payload.get("outcome")
        return cls(
            reason_hunger=integer_value(
                payload["reason_hunger"], "prayer reason_hunger", minimum=0
            ),
            prayer_turn=integer_value(
                payload["prayer_turn"], "prayer prayer_turn", minimum=0
            ),
            safe_turn=integer_value(
                payload["safe_turn"], "prayer safe_turn", minimum=0
            ),
            kill_count=integer_value(
                payload["kill_count"], "prayer kill_count", minimum=0
            ),
            outcome=None if outcome is None else PrayerOutcome.from_json(outcome),
        )


@dataclass(frozen=True, slots=True)
class ActionIntent:
    """The route, attack target, or prayer evidence for one deterministic action.

    `destination` is the skill's route goal (or, for kicking, the locked
    door), usually not the adjacent cell the action steps into.
    `attack_target` is the displayed hostile monster the action attacks by
    moving into it. `path` is the breadth-first route the action follows:
    its cells after the hero's position, starting with the cell the action
    moves into and ending at the destination (for a locked door, at the cell
    orthogonally beside it where the hero kicks). It is None when the action
    does not step along a route (waiting, searching, kicking, and adjacent-
    hostile defense). `prayer` records the observed basis and, after an
    answered confirmation, the observed result. Map values come from the
    skill's own routing data.
    """

    destination: IntentDestination | None
    attack_target: MapCell | None
    path: tuple[MapCell, ...] | None
    # The level the cells belong to; the coordinator stamps it. None for
    # intents recorded before levels were.
    level: LevelKey | None = None
    prayer: PrayerEvidence | None = None
    corpse: CorpseEvidence | None = None

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
        if self.prayer is not None and not isinstance(self.prayer, PrayerEvidence):
            raise TypeError("intent prayer must be a PrayerEvidence or None")
        if self.corpse is not None and not isinstance(self.corpse, CorpseEvidence):
            raise TypeError("intent corpse must be a CorpseEvidence or None")
        if (
            self.destination is None
            and self.attack_target is None
            and self.prayer is None
            and self.corpse is None
        ):
            raise ContractError(
                "intent requires a destination, attack target, prayer, "
                "or corpse evidence"
            )
        if self.prayer is not None and self.corpse is not None:
            raise ContractError("intent cannot mix prayer and corpse evidence")
        if self.path is not None:
            _validate_path(self.path, self.destination, self.attack_target)

    def cells(self) -> tuple[IntentDestination | MapCell, ...]:
        targets = (self.destination, self.attack_target)
        return (
            *(cell for cell in targets if cell is not None),
            *(self.path or ()),
            *((self.corpse.cell,) if self.corpse is not None else ()),
        )

    def to_json(self) -> dict[str, object]:
        payload = {
            "destination": self.destination.to_json() if self.destination else None,
            "attack_target": (
                self.attack_target.to_json() if self.attack_target else None
            ),
            "path": (
                None if self.path is None else [cell.to_json() for cell in self.path]
            ),
            "level": self.level.to_json() if self.level else None,
        }
        if self.prayer is not None:
            payload["prayer"] = self.prayer.to_json()
        if self.corpse is not None:
            payload["corpse"] = self.corpse.to_json()
        return payload

    @classmethod
    def from_json(cls, value: object) -> Self:
        # `path` is absent from intents persisted before routes were recorded
        # and `level` from intents persisted before levels were; absent and
        # null both mean not recorded.
        payload = object_value(
            value,
            "intent",
            {"destination", "attack_target"},
            optional={"path", "level", "prayer", "corpse"},
        )
        destination = payload["destination"]
        attack_target = payload["attack_target"]
        path = payload.get("path")
        level = payload.get("level")
        prayer = payload.get("prayer")
        corpse = payload.get("corpse")
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
            prayer=None if prayer is None else PrayerEvidence.from_json(prayer),
            corpse=None if corpse is None else CorpseEvidence.from_json(corpse),
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
            if self.source is not ActionSelectionSource.DETERMINISTIC_SKILL and not (
                self.source is ActionSelectionSource.DETERMINISTIC_PROMPT
                and self.skill in (Skill.PRAYER, Skill.CORPSE)
                and self.intent.destination is None
                and self.intent.attack_target is None
                and self.intent.path is None
                and (
                    (self.skill is Skill.PRAYER and self.intent.prayer is not None)
                    or (self.skill is Skill.CORPSE and self.intent.corpse is not None)
                )
            ):
                raise ContractError(
                    "only deterministic skill or confirmation prompt selections "
                    "carry intent"
                )
        if (
            self.intent is not None
            and self.intent.corpse is not None
            and self.skill is not Skill.CORPSE
        ):
            raise ContractError("only the corpse skill carries corpse evidence")
        corpse_route = (
            self.intent is not None
            and self.intent.destination is not None
            and self.intent.destination.kind is DestinationKind.CORPSE
        )
        if corpse_route and self.skill is not Skill.CORPSE:
            raise ContractError("only the corpse skill has a corpse destination")
        if self.skill is Skill.CORPSE and (
            self.intent is None
            or self.intent.corpse is None
            or self.intent.attack_target is not None
            or (
                self.intent.destination is not None
                and self.intent.destination.kind is not DestinationKind.CORPSE
            )
            or (
                self.intent.destination is not None
                and (
                    self.intent.destination.x != self.intent.corpse.cell.x
                    or self.intent.destination.y != self.intent.corpse.cell.y
                )
            )
        ):
            raise ContractError("corpse skill needs matching corpse evidence and cell")
        gold_intent = (
            self.intent is not None
            and self.intent.destination is not None
            and self.intent.destination.kind is DestinationKind.GOLD
        )
        if gold_intent and self.skill is not Skill.GOLD_NAVIGATION:
            raise ContractError("only gold navigation has a gold destination")
        if self.skill is Skill.GOLD_NAVIGATION and (
            not gold_intent or self.skill_selection is not SkillSelectionSource.ARBITER
        ):
            raise ContractError(
                "gold navigation is an arbiter-selected skill with a gold destination"
            )
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

    item_letter: str | None = None
    corpse: CorpseEvidence | None = None

    def __post_init__(self) -> None:
        if (self.item_letter is None) == (self.corpse is None):
            raise ValueError("hunger permit requires exactly one ration or corpse")
        if self.corpse is not None:
            if not isinstance(self.corpse, CorpseEvidence):
                raise TypeError("hunger permit corpse must be a CorpseEvidence")
            return
        if (
            not isinstance(self.item_letter, str)
            or len(self.item_letter) != 1
            or not self.item_letter.isascii()
            or not self.item_letter.isalpha()
        ):
            raise ValueError("hunger permit item_letter must be one ASCII letter")


@dataclass(frozen=True, slots=True)
class PrayerPermit:
    """One deterministic prayer command for the observed game turn."""

    turn: int

    def __post_init__(self) -> None:
        integer_value(self.turn, "prayer permit turn", minimum=0)


class PromptKind(Enum):
    ITEM = "item"
    PRAYER_CONFIRMATION = "prayer_confirmation"
    CORPSE_CONFIRMATION = "corpse_confirmation"


@dataclass(frozen=True, slots=True)
class PromptPermit:
    """Authorization for one command that answers or cancels an item prompt."""

    command: int
    kind: PromptKind = PromptKind.ITEM

    def __post_init__(self) -> None:
        integer_value(self.command, "prompt permit command", minimum=0, maximum=255)
        if not isinstance(self.kind, PromptKind):
            raise TypeError("prompt permit kind must be a PromptKind")


def survival_action_selection_error(
    action_name: str, selection: ActionSelection
) -> str | None:
    """Why a restricted action is invalid from its recorded selection fields."""
    if action_name == EAT_ACTION_NAME and (
        selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL
        or (
            (selection.skill is Skill.HUNGER and selection.intent is not None)
            or (
                selection.skill is Skill.CORPSE
                and (
                    selection.intent is None
                    or selection.intent.corpse is None
                    or selection.intent.corpse.outcome is not None
                    or selection.intent.destination is not None
                    or selection.intent.attack_target is not None
                    or selection.intent.path is not None
                )
            )
            or selection.skill not in (Skill.HUNGER, Skill.CORPSE)
        )
    ):
        return "only deterministic hunger or evidenced corpse skill may select EAT"
    if action_name == PRAY_ACTION_NAME and (
        selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL
        or selection.skill is not Skill.PRAYER
        or selection.intent is None
        or selection.intent.prayer is None
        or selection.intent.destination is not None
        or selection.intent.attack_target is not None
        or selection.intent.path is not None
        or selection.intent.prayer.outcome is not None
    ):
        return (
            "only the deterministic prayer skill with pending prayer evidence "
            "may select PRAY"
        )
    if action_name in PROMPT_KEY_ACTION_NAMES and (
        selection.source is not ActionSelectionSource.DETERMINISTIC_PROMPT
        or not (
            (selection.skill is Skill.HUNGER and selection.intent is None)
            or (
                selection.skill is Skill.CORPSE
                and action_name == "Command.ESC"
                and selection.intent is not None
                and selection.intent.corpse is not None
            )
        )
    ):
        return (
            "prompt-key actions require the deterministic hunger or corpse cancel flow"
        )
    if (
        action_name == "CompassDirection.NW"
        and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        and (
            selection.skill not in (Skill.PRAYER, Skill.HUNGER, Skill.CORPSE)
            or (selection.skill is Skill.HUNGER and selection.intent is not None)
            or (
                selection.skill is Skill.PRAYER
                and (
                    selection.intent is None
                    or selection.intent.prayer is None
                    or selection.intent.destination is not None
                    or selection.intent.attack_target is not None
                    or selection.intent.path is not None
                )
            )
            or (
                selection.skill is Skill.CORPSE
                and (
                    selection.intent is None
                    or selection.intent.corpse is None
                    or selection.intent.destination is not None
                    or selection.intent.attack_target is not None
                    or selection.intent.path is not None
                )
            )
        )
    ):
        return (
            "yes answers require a deterministic prayer, hunger, or corpse prompt skill"
        )
    return None


def confirmation_prompt_kind(
    message: str,
    *,
    single_choice: bool,
    offered_item_commands: frozenset[int] | None = None,
) -> PromptKind | None:
    """Recognize observed confirmation text or an offered eat-item letter."""
    if not single_choice:
        return None
    if message == _PRAYER_CONFIRMATION:
        return PromptKind.PRAYER_CONFIRMATION
    if parse_floor_corpse_prompt(message) is not None:
        return PromptKind.CORPSE_CONFIRMATION
    if offered_item_commands is not None and YES_COMMAND in offered_item_commands:
        return PromptKind.ITEM
    return None


def prayer_action_error(
    action_name: str,
    selection: ActionSelection,
    *,
    permit: PrayerPermit | None,
    turn: int | None,
    hunger: int | None,
    prompt_active: bool,
    ration_available: bool,
    prior_prayers: int,
    on_altar: bool,
    last_prayer_turn: int | None = None,
) -> str | None:
    """The same prayer authorization predicate used at execution and audit."""
    if action_name != PRAY_ACTION_NAME:
        return None
    error = survival_action_selection_error(action_name, selection)
    if error is not None:
        return error
    evidence = selection.intent.prayer
    safe_turn = max(
        PRAYER_FIRST_SAFE_TURN,
        (last_prayer_turn + PRAYER_REPEAT_WAIT_TURNS)
        if last_prayer_turn is not None
        else PRAYER_FIRST_SAFE_TURN,
    )
    if (
        not isinstance(permit, PrayerPermit)
        or turn is None
        or hunger is None
        or permit.turn != turn
        or evidence.reason_hunger != hunger
        or evidence.prayer_turn != turn
        or evidence.safe_turn != safe_turn
        or (prior_prayers > 0) != (last_prayer_turn is not None)
    ):
        return "PRAY requires a matching deterministic prayer permit and evidence"
    if hunger < 3 or turn < safe_turn or prompt_active or ration_available or on_altar:
        return "PRAY requires Weak+ hunger, safe turn, and no prompt, ration, or altar"
    return None


def confirmation_answer_error(
    command: int,
    selection: ActionSelection,
    *,
    prompt_active: bool,
    prompt_kind: PromptKind | None,
    permit: PromptPermit | None,
) -> str | None:
    """Reject ambiguous `y` unless the recognized prompt and permit agree."""
    if command != YES_COMMAND:
        return None
    if selection.source is ActionSelectionSource.MODEL_FALLBACK:
        return "the model cannot choose the ambiguous yes/movement key"
    if (
        not prompt_active
        and selection.source is not ActionSelectionSource.DETERMINISTIC_PROMPT
    ):
        return None  # Ordinary deterministic northwest movement.
    if prompt_kind is None:
        return "yes requires an exact recognized confirmation prompt"
    skill = {
        PromptKind.PRAYER_CONFIRMATION: Skill.PRAYER,
        PromptKind.CORPSE_CONFIRMATION: Skill.CORPSE,
        PromptKind.ITEM: Skill.HUNGER,
    }[prompt_kind]
    if (
        selection.source is not ActionSelectionSource.DETERMINISTIC_PROMPT
        or selection.skill is not skill
        or (skill is Skill.HUNGER and selection.intent is not None)
        or (
            skill is Skill.PRAYER
            and (
                selection.intent is None
                or selection.intent.prayer is None
                or selection.intent.destination is not None
                or selection.intent.attack_target is not None
                or selection.intent.path is not None
            )
        )
        or (
            skill is Skill.CORPSE
            and (
                selection.intent is None
                or selection.intent.corpse is None
                or selection.intent.destination is not None
                or selection.intent.attack_target is not None
                or selection.intent.path is not None
            )
        )
    ):
        return "yes requires the matching deterministic prompt skill"
    if (
        permit is None
        or permit.command != YES_COMMAND
        or permit.kind is not prompt_kind
    ):
        return "yes requires a matching active confirmation prompt permit"
    return None


def hunger_action_error(
    action_name: str,
    selection: ActionSelection,
    *,
    hunger: int,
    prompt_active: bool,
    safe_ration_available: bool,
    corpse_evidence: CorpseEvidence | None = None,
    observed_corpse: CorpseEvidence | None = None,
    observation: ProjectedObservation | None = None,
) -> str | None:
    """Authorize ration EAT or an observed fresh corpse under the hero."""
    error = survival_action_selection_error(action_name, selection)
    if error is not None or action_name != EAT_ACTION_NAME:
        return error
    if prompt_active:
        return "EAT cannot answer an active prompt"
    if selection.skill is Skill.CORPSE:
        evidence = selection.intent.corpse
        if (
            corpse_evidence != evidence
            or evidence != observed_corpse
            or evidence is None
            or evidence.outcome is not None
            or evidence.age > 19
            or observation is None
            or evidence.name not in ALLOWED_CORPSES
            or observation.player.turn - evidence.kill_turn != evidence.age
            or observation.player.hunger != hunger
            or hunger < 1
            or (observation.player.x, observation.player.y)
            != (evidence.cell.x, evidence.cell.y)
            or observation.message != f"You see here a {evidence.name} corpse."
        ):
            return "EAT requires the observed fresh corpse under the hero"
        return None
    if hunger < 2:
        return "EAT requires Hungry or worse"
    if not safe_ration_available:
        return "EAT requires an explicitly known-safe inventory food ration"
    return None


def corpse_confirmation_matches(
    observation: ProjectedObservation, evidence: CorpseEvidence
) -> bool:
    """Match the live floor prompt to the fresh corpse identified before EAT."""
    age = observation.player.turn - evidence.kill_turn
    return (
        observation.prompt.single_character_choice
        and parse_floor_corpse_prompt(observation.message) == evidence.name
        and evidence.name in ALLOWED_CORPSES
        and 0 <= evidence.age <= age <= 19
        and observation.player.hunger >= 1
        and (observation.player.x, observation.player.y)
        == (evidence.cell.x, evidence.cell.y)
    )


def corpse_confirmation_error(
    command: int,
    selection: ActionSelection,
    *,
    prompt_active: bool,
    prompt_message: str,
    corpse_evidence: CorpseEvidence | None,
    observed_corpse: CorpseEvidence | None,
    observation: ProjectedObservation | None,
) -> str | None:
    """Authorize floor yes only for the matching pre-EAT kill and exact prompt."""
    if command != YES_COMMAND:
        return None
    intent = selection.intent
    if (
        selection.source is not ActionSelectionSource.DETERMINISTIC_PROMPT
        or selection.skill is not Skill.CORPSE
        or intent is None
        or intent.corpse is None
        or intent.destination is not None
        or intent.attack_target is not None
        or intent.path is not None
        or corpse_evidence is None
        or observed_corpse is None
        or corpse_evidence != observed_corpse
        or (
            intent.corpse.name != corpse_evidence.name
            or intent.corpse.kill_turn != corpse_evidence.kill_turn
            or intent.corpse.age != corpse_evidence.age
            or intent.corpse.cell != corpse_evidence.cell
        )
        or not prompt_active
        or parse_floor_corpse_prompt(prompt_message) != corpse_evidence.name
        or observation is None
        or not corpse_confirmation_matches(observation, corpse_evidence)
    ):
        return "yes requires a matching observed fresh floor corpse and exact prompt"
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
    if selection.source is not ActionSelectionSource.DETERMINISTIC_PROMPT or not (
        (selection.skill is Skill.HUNGER and selection.intent is None)
        or (
            selection.skill is Skill.CORPSE
            and command == ESC_COMMAND
            and selection.intent is not None
            and selection.intent.corpse is not None
            and selection.intent.destination is None
            and selection.intent.attack_target is None
            and selection.intent.path is None
        )
    ):
        return (
            "only the deterministic hunger or corpse cancel flow "
            "may answer item prompts"
        )
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
