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
    ApproachOracleGoal,
    BranchStairs,
    EnterDungeonLeg,
    EnterMinetownTempleLeg,
    EnterTempleGoal,
    ExploreDungeonLeg,
    ExploreLevelGoal,
    FindOracleLeg,
    Goal,
    LevelKey,
    Objective,
    ObjectiveLeg,
    OccupyAltarGoal,
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
        # Construction validates the strict objective contracts.
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
        dungeon.current.target_conduct = any(
            isinstance(item, FindOracleLeg | EnterMinetownTempleLeg)
            for item in self.legs
        )
        dungeon.current.oracle_navigation = any(
            isinstance(item, FindOracleLeg) for item in self.legs
        )
        if isinstance(leg, StandOnStairsLeg):
            return PlannedGoal(StandOnStairsGoal(leg.target))
        here = _level(dungeon.current)
        if isinstance(leg, ExploreDungeonLeg):
            return PlannedGoal(_explore_dungeon(leg, dungeon, here))
        if isinstance(leg, EnterMinetownTempleLeg):
            if here.dungeon_number != 2:
                return (
                    PlannedGoal(_leave_branch(dungeon, here))
                    if here.dungeon_number != DUNGEONS_OF_DOOM
                    else _enter_branch(dungeon, here, 2)
                )
            memory = dungeon.current
            if memory.town_identified:
                goal_type = (
                    OccupyAltarGoal
                    if any("unaligned altar" in text for text in memory.altars.values())
                    else EnterTempleGoal
                )
                return PlannedGoal(goal_type(here))
            if here.dungeon_level < 3:
                return PlannedGoal(main_stairs(StairDirection.DOWN))
            if here.dungeon_level > 4:
                return PlannedGoal(main_stairs(StairDirection.UP))
            if here.dungeon_level == 3 and memory.explored:
                return PlannedGoal(main_stairs(StairDirection.DOWN))
            return PlannedGoal(EnterTempleGoal(here))
        if isinstance(leg, FindOracleLeg):
            if here.dungeon_number != DUNGEONS_OF_DOOM:
                return PlannedGoal(_leave_branch(dungeon, here))
            memory = dungeon.current
            if any(monster.name == "Oracle" for monster in memory.monsters.values()):
                return PlannedGoal(ApproachOracleGoal(here))
            if here.dungeon_level < 5:
                return PlannedGoal(main_stairs(StairDirection.DOWN))
            if here.dungeon_level > 9:
                return PlannedGoal(main_stairs(StairDirection.UP))
            if not memory.explored:
                return PlannedGoal(ApproachOracleGoal(here))
            if here.dungeon_level < 9:
                return PlannedGoal(main_stairs(StairDirection.DOWN))
            return PlannedGoal(main_stairs(StairDirection.UP))
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


def unexplored_level(leg: ExploreDungeonLeg, dungeon: DungeonMemory) -> LevelKey | None:
    """The shallowest required level exploration has not yet exhausted."""
    return next(
        (
            level
            for level in leg.levels
            if level not in dungeon.levels or not dungeon.levels[level].explored
        ),
        None,
    )


def _explore_dungeon(
    leg: ExploreDungeonLeg, dungeon: DungeonMemory, here: LevelKey
) -> Goal:
    """Explore the shallowest unexplored required level, moving by main stairs.

    A branch dungeon is left by its recorded link. A level skipped by a trap
    door or hole is revisited by climbing the main staircases.
    """
    if here.dungeon_number != DUNGEONS_OF_DOOM:
        return _leave_branch(dungeon, here)
    target = unexplored_level(leg, dungeon)
    if target is None:
        raise ObjectivePlanningError(
            "an explored dungeon leg has no goal; the coordinator ends the run"
        )
    if target == here:
        return ExploreLevelGoal(here)
    return _toward(here, target.dungeon_level)


def leg_complete(leg: ObjectiveLeg, dungeon: DungeonMemory) -> bool:
    """Whether the hero's current position satisfies `leg`."""
    memory = dungeon.current
    here = _level(memory)
    if isinstance(leg, ReachLevelLeg):
        return here == leg.level
    if isinstance(leg, EnterDungeonLeg):
        return here.dungeon_number == leg.dungeon_number
    if isinstance(leg, ExploreDungeonLeg):
        return unexplored_level(leg, dungeon) is None
    if isinstance(leg, EnterMinetownTempleLeg):
        from nethack_agent.targets import mines_candidate

        return mines_candidate(dungeon) and memory.temple_entry is not None
    if isinstance(leg, FindOracleLeg):
        from nethack_agent.targets import oracle_adjacent

        observation = memory.live_observation
        return observation is not None and oracle_adjacent(
            observation, sum(level.oracle_attacks for level in dungeon.levels.values())
        )
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
