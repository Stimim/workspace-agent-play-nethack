"""Typed traversal values: levels, stair targets and identities, goals, objectives.

These are pure value types with strict JSON construction (ADR 0003). They carry
no game logic beyond the reviewed NetHack 3.6.7 dungeon facts below, which come
from NLE's bundled ``nethackdir/dat/dungeon.def`` (ADR 0004).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Final, Self

from nethack_agent.contracts import (
    ContractError,
    array_value,
    enum_value,
    integer_value,
    object_value,
)

# NetHack 3.6.7 `global.h`: MAXDUNGEON 16 dungeons of at most MAXLEVEL 32 levels.
MAX_DUNGEON_NUMBER: Final = 15
MAX_DUNGEON_LEVEL: Final = 32
MAX_OBJECTIVE_LEGS: Final = 8

# `dungeon.def` order. The Mines number was observed in real traversals; the
# others follow the file order.
DUNGEONS_OF_DOOM: Final = 0
GNOMISH_MINES: Final = 2
SOKOBAN: Final = 4

# The only goal written before typed goals existed.
LEGACY_STAND_ON_DOWNSTAIRS: Final = "stand_on_downstairs"


@dataclass(frozen=True, slots=True, order=True)
class LevelKey:
    """One level: NLE blstats `dungeon_number` and `dungeon_level`.

    `depth` cannot identify a level: the first Gnomish Mines level and the
    third Dungeons of Doom level share depth 3.
    """

    dungeon_number: int
    dungeon_level: int

    def __post_init__(self) -> None:
        integer_value(
            self.dungeon_number,
            "level dungeon_number",
            minimum=0,
            maximum=MAX_DUNGEON_NUMBER,
        )
        integer_value(
            self.dungeon_level,
            "level dungeon_level",
            minimum=1,
            maximum=MAX_DUNGEON_LEVEL,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "dungeon_number": self.dungeon_number,
            "dungeon_level": self.dungeon_level,
        }

    @classmethod
    def from_json(cls, value: object, name: str = "level") -> Self:
        payload = object_value(value, name, {"dungeon_number", "dungeon_level"})
        return cls(
            dungeon_number=integer_value(
                payload["dungeon_number"],
                f"{name} dungeon_number",
                minimum=0,
                maximum=MAX_DUNGEON_NUMBER,
            ),
            dungeon_level=integer_value(
                payload["dungeon_level"],
                f"{name} dungeon_level",
                minimum=1,
                maximum=MAX_DUNGEON_LEVEL,
            ),
        )


# `<` on the first Dungeons of Doom level: `dungeon.def` places the one-way
# Elemental Planes branch there (`BRANCH ... @ (1, 0) no_down up`); without the
# Amulet, climbing it asks to leave the dungeon.
DUNGEON_EXIT_LEVEL: Final = LevelKey(DUNGEONS_OF_DOOM, 1)


class StairDirection(Enum):
    UP = "up"
    DOWN = "down"

    @property
    def opposite(self) -> StairDirection:
        return StairDirection.DOWN if self is StairDirection.UP else StairDirection.UP


@dataclass(frozen=True, slots=True)
class BranchStairs:
    """A Dungeons of Doom staircase branch from `dungeon.def`."""

    dungeon_number: int
    first_level: int
    last_level: int

    def contains(self, level: LevelKey) -> bool:
        return (
            level.dungeon_number == DUNGEONS_OF_DOOM
            and self.first_level <= level.dungeon_level <= self.last_level
        )


# `BRANCH "The Gnomish Mines" @ (2, 3)` puts a second `>` on DL2-4, and
# `CHAINBRANCH "Sokoban" "oracle" + (1, 0) up` a second `<` on the level below
# the Oracle (`LEVEL "oracle" @ (5, 5)`), DL6-10. Sokoban's number is unverified.
BRANCH_STAIRS: Final[dict[StairDirection, BranchStairs]] = {
    StairDirection.DOWN: BranchStairs(GNOMISH_MINES, 2, 4),
    StairDirection.UP: BranchStairs(SOKOBAN, 6, 10),
}
# Dungeons an objective may name: the Dungeons of Doom and the branches its
# staircases lead into.
REACHABLE_DUNGEONS: Final = frozenset(
    {DUNGEONS_OF_DOOM, *(branch.dungeon_number for branch in BRANCH_STAIRS.values())}
)


class StairConnection(Enum):
    """Which staircases of one direction a target accepts."""

    ANY = "any"
    # Connects adjacent levels of the current dungeon.
    MAIN = "main"
    # Connects to another dungeon, named by the target's dungeon_number.
    BRANCH = "branch"


@dataclass(frozen=True, slots=True)
class StairTarget:
    direction: StairDirection
    connection: StairConnection
    # Required for a branch target and absent otherwise.
    dungeon_number: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.direction, StairDirection):
            raise TypeError("stair target direction must be a StairDirection")
        if not isinstance(self.connection, StairConnection):
            raise TypeError("stair target connection must be a StairConnection")
        if self.connection is StairConnection.BRANCH:
            if self.dungeon_number is None:
                raise ContractError("a branch stair target requires a dungeon_number")
            integer_value(
                self.dungeon_number,
                "stair target dungeon_number",
                minimum=0,
                maximum=MAX_DUNGEON_NUMBER,
            )
        elif self.dungeon_number is not None:
            raise ContractError("only a branch stair target has a dungeon_number")

    @property
    def token(self) -> str:
        parts = [self.direction.value, self.connection.value]
        if self.dungeon_number is not None:
            parts.append(str(self.dungeon_number))
        return ":".join(parts)

    def to_json(self) -> dict[str, object]:
        return {
            "direction": self.direction.value,
            "connection": self.connection.value,
            "dungeon_number": self.dungeon_number,
        }

    @classmethod
    def from_json(cls, value: object, name: str = "stair target") -> Self:
        payload = object_value(
            value, name, {"direction", "connection", "dungeon_number"}
        )
        dungeon_number = payload["dungeon_number"]
        return cls(
            direction=enum_value(
                payload["direction"], f"{name} direction", StairDirection
            ),
            connection=enum_value(
                payload["connection"], f"{name} connection", StairConnection
            ),
            dungeon_number=(
                None
                if dungeon_number is None
                else integer_value(
                    dungeon_number,
                    f"{name} dungeon_number",
                    minimum=0,
                    maximum=MAX_DUNGEON_NUMBER,
                )
            ),
        )


class StairIdentityKind(Enum):
    """What a remembered staircase is known to connect to."""

    MAIN = "main"
    BRANCH = "branch"
    # `<` on (0, 1): leaves the dungeon; never a goal.
    EXIT = "exit"
    UNKNOWN = "unknown"


class IdentityEvidence(Enum):
    """How a stair identity was established."""

    # The hero used this staircase and observed the level it leads to.
    TRAVERSED = "traversed"
    # The hero arrived on this staircase by using its counterpart.
    ARRIVAL = "arrival"
    # The level has two staircases of this direction and the other is known.
    ELIMINATION = "elimination"
    # A `dungeon.def` fact, such as the dungeon exit.
    RULE = "rule"


@dataclass(frozen=True, slots=True)
class StairIdentity:
    kind: StairIdentityKind
    # The dungeon the staircase leads to: the own dungeon for main stairs, the
    # branch dungeon when known, otherwise None.
    dungeon_number: int | None
    evidence: IdentityEvidence | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StairIdentityKind):
            raise TypeError("stair identity kind must be a StairIdentityKind")
        if self.evidence is not None and not isinstance(
            self.evidence, IdentityEvidence
        ):
            raise TypeError("stair identity evidence must be an IdentityEvidence")
        if self.dungeon_number is not None:
            integer_value(
                self.dungeon_number,
                "stair identity dungeon_number",
                minimum=0,
                maximum=MAX_DUNGEON_NUMBER,
            )
        if self.kind is StairIdentityKind.UNKNOWN:
            if self.evidence is not None or self.dungeon_number is not None:
                raise ContractError(
                    "an unknown stair identity has no evidence or dungeon_number"
                )
            return
        if self.evidence is None:
            raise ContractError("an established stair identity requires evidence")
        if self.kind is StairIdentityKind.MAIN and self.dungeon_number is None:
            raise ContractError("a main stair identity requires its dungeon_number")
        if self.kind is StairIdentityKind.EXIT and (
            self.evidence is not IdentityEvidence.RULE
            or self.dungeon_number is not None
        ):
            raise ContractError("the dungeon exit is a rule without a dungeon_number")

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "dungeon_number": self.dungeon_number,
            "evidence": self.evidence.value if self.evidence else None,
        }

    @classmethod
    def from_json(cls, value: object, name: str = "stair identity") -> Self:
        payload = object_value(value, name, {"kind", "dungeon_number", "evidence"})
        dungeon_number = payload["dungeon_number"]
        evidence = payload["evidence"]
        return cls(
            kind=enum_value(payload["kind"], f"{name} kind", StairIdentityKind),
            dungeon_number=(
                None
                if dungeon_number is None
                else integer_value(
                    dungeon_number,
                    f"{name} dungeon_number",
                    minimum=0,
                    maximum=MAX_DUNGEON_NUMBER,
                )
            ),
            evidence=(
                None
                if evidence is None
                else enum_value(evidence, f"{name} evidence", IdentityEvidence)
            ),
        )


UNKNOWN_STAIR: Final = StairIdentity(StairIdentityKind.UNKNOWN, None, None)
DUNGEON_EXIT: Final = StairIdentity(StairIdentityKind.EXIT, None, IdentityEvidence.RULE)


def candidate_tier(
    target: StairTarget, identity: StairIdentity, *, pair_known: bool
) -> int | None:
    """Rank a staircase of the target's direction; None means incompatible.

    Tier 0 is an established match and tier 1 a probe whose identity is not
    established. `pair_known` says the level has two known staircases of this
    direction, which proves it is a branch level: only then may an unknown
    staircase be probed for a branch.
    """
    kind = identity.kind
    if kind is StairIdentityKind.EXIT:
        return None
    connection = target.connection
    if connection is StairConnection.ANY:
        return 0
    if connection is StairConnection.MAIN:
        if kind is StairIdentityKind.MAIN:
            return 0
        return 1 if kind is StairIdentityKind.UNKNOWN else None
    if kind is StairIdentityKind.BRANCH:
        if identity.dungeon_number == target.dungeon_number:
            return 0
        return 1 if identity.dungeon_number is None else None
    if kind is StairIdentityKind.UNKNOWN and pair_known:
        return 1
    return None


class GoalKind(Enum):
    # Stand on a matching staircase without using it.
    STAND_ON_STAIRS = "stand_on_stairs"
    # Reach a matching staircase and use it to change level.
    TRAVERSE_STAIRS = "traverse_stairs"
    # Explore one level until deterministic exploration is exhausted.
    EXPLORE_LEVEL = "explore_level"


@dataclass(frozen=True, slots=True)
class StandOnStairsGoal:
    target: StairTarget

    kind: ClassVar[GoalKind] = GoalKind.STAND_ON_STAIRS

    def __post_init__(self) -> None:
        if not isinstance(self.target, StairTarget):
            raise TypeError("goal target must be a StairTarget")

    @property
    def token(self) -> str:
        return f"{self.kind.value}:{self.target.token}"

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "target": self.target.to_json()}


@dataclass(frozen=True, slots=True)
class TraverseStairsGoal:
    target: StairTarget

    kind: ClassVar[GoalKind] = GoalKind.TRAVERSE_STAIRS

    def __post_init__(self) -> None:
        if not isinstance(self.target, StairTarget):
            raise TypeError("goal target must be a StairTarget")
        if self.target.connection is StairConnection.ANY:
            raise ContractError("a traversal goal must target main or branch stairs")

    @property
    def token(self) -> str:
        return f"{self.kind.value}:{self.target.token}"

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "target": self.target.to_json()}


@dataclass(frozen=True, slots=True)
class ExploreLevelGoal:
    """Explore this level until exploration finds nothing left to do.

    It names no staircase: exploration is not biased toward any stair.
    """

    level: LevelKey

    kind: ClassVar[GoalKind] = GoalKind.EXPLORE_LEVEL

    def __post_init__(self) -> None:
        if not isinstance(self.level, LevelKey):
            raise TypeError("goal level must be a LevelKey")

    @property
    def token(self) -> str:
        return (
            f"{self.kind.value}:{self.level.dungeon_number}:{self.level.dungeon_level}"
        )

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "level": self.level.to_json()}


type StairGoal = StandOnStairsGoal | TraverseStairsGoal
type Goal = StandOnStairsGoal | TraverseStairsGoal | ExploreLevelGoal
STAIR_GOAL_TYPES: Final = (StandOnStairsGoal, TraverseStairsGoal)
GOAL_TYPES: Final = (*STAIR_GOAL_TYPES, ExploreLevelGoal)

# Milestone 1's goal: stand on any `>` without descending.
STAND_ON_DOWNSTAIRS: Final = StandOnStairsGoal(
    StairTarget(StairDirection.DOWN, StairConnection.ANY, None)
)


def goal_from_json(value: object, name: str = "goal") -> Goal:
    """Parse a typed goal, reading the legacy milestone-1 string exactly."""
    if value == LEGACY_STAND_ON_DOWNSTAIRS:
        return STAND_ON_DOWNSTAIRS
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    kind = enum_value(value.get("kind"), f"{name} kind", GoalKind)
    if kind is GoalKind.EXPLORE_LEVEL:
        payload = object_value(value, name, {"kind", "level"})
        return ExploreLevelGoal(LevelKey.from_json(payload["level"], f"{name} level"))
    payload = object_value(value, name, {"kind", "target"})
    target = StairTarget.from_json(payload["target"], f"{name} target")
    if kind is GoalKind.STAND_ON_STAIRS:
        return StandOnStairsGoal(target)
    return TraverseStairsGoal(target)


class ObjectiveLegKind(Enum):
    STAND_ON_STAIRS = "stand_on_stairs"
    REACH_LEVEL = "reach_level"
    ENTER_DUNGEON = "enter_dungeon"
    EXPLORE_DUNGEON = "explore_dungeon"


@dataclass(frozen=True, slots=True)
class StandOnStairsLeg:
    """Complete while standing on a matching staircase on the current level."""

    target: StairTarget

    kind: ClassVar[ObjectiveLegKind] = ObjectiveLegKind.STAND_ON_STAIRS

    def __post_init__(self) -> None:
        if not isinstance(self.target, StairTarget):
            raise TypeError("objective leg target must be a StairTarget")

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "target": self.target.to_json()}


@dataclass(frozen=True, slots=True)
class ReachLevelLeg:
    """Complete when the hero is on this level."""

    level: LevelKey

    kind: ClassVar[ObjectiveLegKind] = ObjectiveLegKind.REACH_LEVEL

    def __post_init__(self) -> None:
        if not isinstance(self.level, LevelKey):
            raise TypeError("objective leg level must be a LevelKey")

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "level": self.level.to_json()}


@dataclass(frozen=True, slots=True)
class EnterDungeonLeg:
    """Complete when the hero is on any level of this dungeon."""

    dungeon_number: int

    kind: ClassVar[ObjectiveLegKind] = ObjectiveLegKind.ENTER_DUNGEON

    def __post_init__(self) -> None:
        integer_value(
            self.dungeon_number,
            "objective leg dungeon_number",
            minimum=0,
            maximum=MAX_DUNGEON_NUMBER,
        )

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "dungeon_number": self.dungeon_number}


@dataclass(frozen=True, slots=True)
class ExploreDungeonLeg:
    """Complete once every Dungeons of Doom level 1..max_level is exhausted.

    A level counts as exhausted after deterministic exploration once found
    nothing left to do on it; the coordinator records that step with an
    `exhausted_level` marker the evaluator re-derives.
    """

    max_level: int

    kind: ClassVar[ObjectiveLegKind] = ObjectiveLegKind.EXPLORE_DUNGEON

    def __post_init__(self) -> None:
        integer_value(
            self.max_level,
            "objective leg max_level",
            minimum=1,
            maximum=MAX_DUNGEON_LEVEL,
        )

    @property
    def levels(self) -> tuple[LevelKey, ...]:
        """The required levels, shallowest first."""
        return tuple(
            LevelKey(DUNGEONS_OF_DOOM, level) for level in range(1, self.max_level + 1)
        )

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind.value, "max_level": self.max_level}


type ObjectiveLeg = (
    StandOnStairsLeg | ReachLevelLeg | EnterDungeonLeg | ExploreDungeonLeg
)
OBJECTIVE_LEG_TYPES: Final = (
    StandOnStairsLeg,
    ReachLevelLeg,
    EnterDungeonLeg,
    ExploreDungeonLeg,
)


def objective_leg_from_json(value: object, name: str = "objective leg") -> ObjectiveLeg:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    kind = enum_value(value.get("kind"), f"{name} kind", ObjectiveLegKind)
    if kind is ObjectiveLegKind.STAND_ON_STAIRS:
        payload = object_value(value, name, {"kind", "target"})
        return StandOnStairsLeg(
            StairTarget.from_json(payload["target"], f"{name} target")
        )
    if kind is ObjectiveLegKind.REACH_LEVEL:
        payload = object_value(value, name, {"kind", "level"})
        return ReachLevelLeg(LevelKey.from_json(payload["level"], f"{name} level"))
    if kind is ObjectiveLegKind.EXPLORE_DUNGEON:
        payload = object_value(value, name, {"kind", "max_level"})
        return ExploreDungeonLeg(
            integer_value(
                payload["max_level"],
                f"{name} max_level",
                minimum=1,
                maximum=MAX_DUNGEON_LEVEL,
            )
        )
    payload = object_value(value, name, {"kind", "dungeon_number"})
    return EnterDungeonLeg(
        integer_value(
            payload["dungeon_number"],
            f"{name} dungeon_number",
            minimum=0,
            maximum=MAX_DUNGEON_NUMBER,
        )
    )


@dataclass(frozen=True, slots=True)
class Objective:
    """Legs completed in order; the run's objective is met after the last."""

    legs: tuple[ObjectiveLeg, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.legs, tuple) or not all(
            isinstance(leg, OBJECTIVE_LEG_TYPES) for leg in self.legs
        ):
            raise TypeError("objective legs must be a tuple of objective legs")
        if not 1 <= len(self.legs) <= MAX_OBJECTIVE_LEGS:
            raise ContractError(
                f"an objective must have 1 to {MAX_OBJECTIVE_LEGS} legs"
            )
        for leg in self.legs:
            dungeon = (
                leg.level.dungeon_number
                if isinstance(leg, ReachLevelLeg)
                else leg.dungeon_number
                if isinstance(leg, EnterDungeonLeg)
                else DUNGEONS_OF_DOOM
            )
            if dungeon not in REACHABLE_DUNGEONS:
                raise ContractError(
                    f"objective dungeon {dungeon} has no known staircase branch "
                    "from the Dungeons of Doom"
                )

    @property
    def changes_level(self) -> bool:
        """Whether any leg can require using a staircase."""
        return any(not isinstance(leg, StandOnStairsLeg) for leg in self.legs)

    def to_json(self) -> dict[str, object]:
        return {"legs": [leg.to_json() for leg in self.legs]}

    @classmethod
    def from_json(cls, value: object, name: str = "objective") -> Self:
        payload = object_value(value, name, {"legs"})
        legs = array_value(payload["legs"], f"{name} legs")
        if not 1 <= len(legs) <= MAX_OBJECTIVE_LEGS:
            raise ContractError(f"{name} must have 1 to {MAX_OBJECTIVE_LEGS} legs")
        return cls(
            tuple(
                objective_leg_from_json(leg, f"{name} leg {index}")
                for index, leg in enumerate(legs)
            )
        )


# The milestone-1 staircase task: stand on any `>`, never change level.
STAIRCASE_OBJECTIVE: Final = Objective((StandOnStairsLeg(STAND_ON_DOWNSTAIRS.target),))
