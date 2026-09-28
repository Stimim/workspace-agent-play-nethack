"""Objective planning: the typed goal for every step (ADR 0004).

The planner is a pure function of the run's objective, the current leg, and
dungeon memory. It never reads NLE's private task state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from nethack_agent.navigation import DungeonMemory, LevelMemory
from nethack_agent.traversal import (
    BRANCH_STAIRS,
    DUNGEONS_OF_DOOM,
    BranchStairs,
    EnterDungeonLeg,
    Goal,
    LevelKey,
    Objective,
    ObjectiveLeg,
    ReachLevelLeg,
    StairConnection,
    StairDirection,
    StairIdentityKind,
    StairTarget,
    StandOnStairsGoal,
    StandOnStairsLeg,
    TraverseStairsGoal,
    candidate_tier,
)

# The Dungeons of Doom staircase branches, by the dungeon they lead into.
_BRANCHES: Final[dict[int, tuple[StairDirection, BranchStairs]]] = {
    branch.dungeon_number: (direction, branch)
    for direction, branch in BRANCH_STAIRS.items()
}


class ObjectivePlanningError(ValueError):
    """The planner cannot derive a goal for this objective and position."""


@dataclass(frozen=True, slots=True)
class PlannedGoal:
    goal: Goal
    # Grant the current level one more exploration round before it is searched
    # again for a branch staircase.
    rearm: bool = False


def main_stairs(direction: StairDirection) -> TraverseStairsGoal:
    return TraverseStairsGoal(StairTarget(direction, StairConnection.MAIN, None))


def branch_stairs(direction: StairDirection, dungeon_number: int) -> TraverseStairsGoal:
    return TraverseStairsGoal(
        StairTarget(direction, StairConnection.BRANCH, dungeon_number)
    )


class ObjectivePlanner:
    """Derive each step's goal from the objective's current leg and memory."""

    def __init__(self, objective: Objective) -> None:
        for leg in objective.legs:
            dungeon = (
                leg.level.dungeon_number
                if isinstance(leg, ReachLevelLeg)
                else leg.dungeon_number
                if isinstance(leg, EnterDungeonLeg)
                else DUNGEONS_OF_DOOM
            )
            if dungeon != DUNGEONS_OF_DOOM and dungeon not in _BRANCHES:
                raise ObjectivePlanningError(
                    f"dungeon {dungeon} has no known staircase branch from the "
                    "Dungeons of Doom"
                )
        self.objective = objective

    @property
    def legs(self) -> tuple[ObjectiveLeg, ...]:
        return self.objective.legs

    def advance(self, index: int, dungeon: DungeonMemory) -> int:
        """The first leg at or after `index` that is not yet complete."""
        while index < len(self.legs) and leg_complete(self.legs[index], dungeon):
            index += 1
        return index

    def plan(self, index: int, dungeon: DungeonMemory) -> PlannedGoal:
        """The goal for the current leg; the last leg's goal once all are met."""
        leg = self.legs[min(index, len(self.legs) - 1)]
        if isinstance(leg, StandOnStairsLeg):
            return PlannedGoal(StandOnStairsGoal(leg.target))
        here = _level(dungeon.current)
        target_dungeon = (
            leg.level.dungeon_number
            if isinstance(leg, ReachLevelLeg)
            else leg.dungeon_number
        )
        if here.dungeon_number != target_dungeon:
            if here.dungeon_number != DUNGEONS_OF_DOOM:
                return PlannedGoal(_leave_branch(dungeon, here))
            return _enter_branch(dungeon, here, target_dungeon)
        if isinstance(leg, ReachLevelLeg) and leg.level != here:
            return PlannedGoal(_toward(here, leg.level.dungeon_level))
        raise ObjectivePlanningError(
            "a completed level leg has no goal; the coordinator ends the run"
        )


def leg_complete(leg: ObjectiveLeg, dungeon: DungeonMemory) -> bool:
    """Whether the hero's current position satisfies `leg`."""
    memory = dungeon.current
    here = _level(memory)
    if isinstance(leg, ReachLevelLeg):
        return here == leg.level
    if isinstance(leg, EnterDungeonLeg):
        return here.dungeon_number == leg.dungeon_number
    position = memory.position
    direction = memory.stair_direction(position)
    return direction is leg.target.direction and (
        candidate_tier(
            leg.target,
            memory.identity(position),
            pair_known=memory.pair_known(direction),
        )
        is not None
    )


def _level(memory: LevelMemory) -> LevelKey:
    if memory.level is None:
        raise ValueError("level memory has observed no level")
    return memory.level


def _toward(here: LevelKey, dungeon_level: int) -> TraverseStairsGoal:
    """The main staircase one level closer to `dungeon_level`."""
    return main_stairs(
        StairDirection.DOWN if dungeon_level > here.dungeon_level else StairDirection.UP
    )


def _leave_branch(dungeon: DungeonMemory, here: LevelKey) -> TraverseStairsGoal:
    """Retrace the recorded branch link out of the current dungeon.

    The staircase the hero arrived by is linked and identified; main stairs
    lead to its level. Without such a record (never observed: branch dungeons
    are entered by staircase), the upward main staircase is probed.
    """
    exits = [
        (key, direction, identity.dungeon_number)
        for key, memory in dungeon.levels.items()
        if key.dungeon_number == here.dungeon_number
        for direction in StairDirection
        for stair in memory.stairs(direction)
        if (identity := memory.identity(stair)).kind is StairIdentityKind.BRANCH
        and identity.dungeon_number is not None
        and identity.dungeon_number != here.dungeon_number
    ]
    if not exits:
        return main_stairs(StairDirection.UP)
    key, direction, dungeon_number = min(
        exits, key=lambda exit: (abs(exit[0].dungeon_level - here.dungeon_level),)
    )
    assert dungeon_number is not None
    if key == here:
        return branch_stairs(direction, dungeon_number)
    return _toward(here, key.dungeon_level)


def _enter_branch(
    dungeon: DungeonMemory, here: LevelKey, dungeon_number: int
) -> PlannedGoal:
    """Find and take the Dungeons of Doom staircase into `dungeon_number`.

    Search order: a level whose branch staircase is identified; then any
    level of the branch range that is unvisited, still being explored, or
    shows two staircases of the branch direction; then, once, a re-armed
    search of each exhausted range level. Main staircases move between them.
    """
    direction, branch = _BRANCHES[dungeon_number]
    goal = branch_stairs(direction, dungeon_number)
    levels = {
        key.dungeon_level: memory
        for key, memory in dungeon.levels.items()
        if key.dungeon_number == DUNGEONS_OF_DOOM
    }
    identified = [
        level
        for level, memory in levels.items()
        if any(
            memory.identity(stair).kind is StairIdentityKind.BRANCH
            and memory.identity(stair).dungeon_number == dungeon_number
            for stair in memory.stairs(direction)
        )
    ]
    span = range(branch.first_level, branch.last_level + 1)
    open_levels = [
        level
        for level in span
        if level not in levels
        or not levels[level].exhausted
        or levels[level].pair_known(direction)
    ]
    rearmable = [
        level
        for level in span
        if level in levels
        and levels[level].exhausted
        and not levels[level].pair_known(direction)
        and not levels[level].branch_rearmed
    ]
    for candidates in (identified, open_levels):
        if here.dungeon_level in candidates:
            return PlannedGoal(goal)
        if candidates:
            return PlannedGoal(_toward(here, _nearest(candidates, here)))
    if here.dungeon_level in rearmable:
        return PlannedGoal(goal, rearm=True)
    if rearmable:
        return PlannedGoal(_toward(here, _nearest(rearmable, here)))
    # Every range level was searched twice without a branch staircase; keep
    # searching here and let stuck consultations decide.
    return PlannedGoal(goal)


def _nearest(levels: list[int], here: LevelKey) -> int:
    """The closest level; deeper wins a tie, since descent reveals new levels."""
    return min(levels, key=lambda level: (abs(level - here.dungeon_level), -level))
