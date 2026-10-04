from dataclasses import replace
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.navigation import ActionKind, ActionRecord, DungeonMemory
from nethack_agent.observation import (
    MapView,
    ObservationProjector,
    ProjectedObservation,
    PromptState,
)
from nethack_agent.planner import (
    ObjectivePlanner,
    ObjectivePlanningError,
    PlannedGoal,
    branch_stairs,
    leg_complete,
    main_stairs,
)
from nethack_agent.traversal import (
    STAIRCASE_OBJECTIVE,
    STAND_ON_DOWNSTAIRS,
    EnterDungeonLeg,
    ExploreDungeonLeg,
    ExploreLevelGoal,
    FindOracleLeg,
    LevelKey,
    Objective,
    ReachLevelLeg,
    StairConnection,
    StairDirection,
    StairTarget,
    StandOnStairsGoal,
    StandOnStairsLeg,
)

DOWN = StairDirection.DOWN
UP = StairDirection.UP
_CMAP = nethack.GLYPH_CMAP_OFF
_GLYPHS = {
    " ": _CMAP,
    "|": _CMAP + 1,
    ".": _CMAP + 19,
    "<": _CMAP + 23,
    ">": _CMAP + 24,
    "@": nethack.GLYPH_MON_OFF
    + next(
        index
        for index in range(nethack.NUMMONS)
        if nethack.permonst(index).mname == "valkyrie"
    ),
}


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> ProjectedObservation:
    directory: Path = tmp_path_factory.mktemp("planner")
    environment = NleEnvironment(ScenarioConfig(seed=6, artifact_directory=directory))
    try:
        return ObservationProjector().project(environment.reset(), step_index=0)
    finally:
        environment.close()


class Walk:
    """Drive a DungeonMemory through one-row sketched levels."""

    def __init__(self, template: ProjectedObservation) -> None:
        self.template = template
        self.dungeon = DungeonMemory()
        self.step = 0

    def at(self, level: LevelKey, row: str) -> "Walk":
        hero = row.index("@")
        self.dungeon.observe(
            ProjectedObservation(
                step_index=self.step,
                map=MapView(
                    rows=(row,),
                    glyph_rows=(tuple(_GLYPHS[char] for char in row),),
                    color_rows=(bytes(len(row)),),
                    special_rows=(bytes(len(row)),),
                    pet_rows=(bytes(len(row)),),
                ),
                changed_cells=(),
                player=replace(
                    self.template.player,
                    x=hero,
                    y=0,
                    dungeon_number=level.dungeon_number,
                    dungeon_level=level.dungeon_level,
                ),
                message="",
                prompt=PromptState(False, False, False),
                inventory=(),
            )
        )
        self.step += 1
        return self

    def use_stairs(self, level: LevelKey, row: str) -> "Walk":
        """Use the staircase under the hero and arrive at `row` on `level`."""
        current = self.dungeon.current
        current.record(ActionRecord(ActionKind.TRAVERSE, current.position))
        return self.at(level, row)

    def exhaust(self) -> "Walk":
        self.dungeon.current.mark_exhausted()
        return self


def plan(objective: Objective, walk: Walk, leg: int = 0) -> PlannedGoal:
    return ObjectivePlanner(objective).plan(leg, walk.dungeon)


def reach(dungeon_number: int, dungeon_level: int) -> Objective:
    return Objective((ReachLevelLeg(LevelKey(dungeon_number, dungeon_level)),))


MINES = Objective((EnterDungeonLeg(2),))


def test_standing_and_level_legs_choose_the_staircase_direction(
    template: ProjectedObservation,
) -> None:
    walk = Walk(template).at(LevelKey(0, 3), "|.@.>|")
    assert plan(STAIRCASE_OBJECTIVE, walk) == PlannedGoal(STAND_ON_DOWNSTAIRS)
    up_any = StairTarget(UP, StairConnection.ANY, None)
    assert plan(Objective((StandOnStairsLeg(up_any),)), walk) == PlannedGoal(
        StandOnStairsGoal(up_any)
    )
    assert plan(reach(0, 5), walk) == PlannedGoal(main_stairs(DOWN))
    assert plan(reach(0, 1), walk) == PlannedGoal(main_stairs(UP))
    with pytest.raises(ObjectivePlanningError, match="completed level leg"):
        plan(reach(0, 3), walk)


def test_a_wrong_dungeon_is_left_by_the_recorded_branch_link(
    template: ProjectedObservation,
) -> None:
    walk = (
        Walk(template)
        .at(LevelKey(0, 2), "|.>@>|")
        .at(LevelKey(0, 2), "|.>.@|")
        .use_stairs(LevelKey(2, 1), "|.@.>|")
    )
    # Standing on the arrival `<` of the Mines: climb that branch staircase.
    assert plan(reach(0, 3), walk) == PlannedGoal(branch_stairs(UP, 0))
    walk.at(LevelKey(2, 1), "|.<.@|").use_stairs(LevelKey(2, 2), "|@..>|")
    # Deeper in the Mines, main stairs lead back to the linked level first.
    assert plan(reach(0, 3), walk) == PlannedGoal(main_stairs(UP))


def test_mines_search_descends_to_the_range_then_searches_each_level(
    template: ProjectedObservation,
) -> None:
    walk = Walk(template).at(LevelKey(0, 1), "|@.>|")
    # Above the DL2-4 branch range: descend by the main staircase.
    assert plan(MINES, walk) == PlannedGoal(main_stairs(DOWN))

    walk.at(LevelKey(0, 1), "|..@|").use_stairs(LevelKey(0, 2), "|@.>.|")
    # In range and not yet exhausted: look for the branch staircase here.
    assert plan(MINES, walk) == PlannedGoal(branch_stairs(DOWN, 2))
    # Exhausted with a single `>`: move on to the next unvisited range level.
    walk.exhaust()
    assert plan(MINES, walk) == PlannedGoal(main_stairs(DOWN))


def test_two_downstairs_are_probed_and_elimination_finds_the_branch(
    template: ProjectedObservation,
) -> None:
    walk = Walk(template).at(LevelKey(0, 2), "|>.@.>|").exhaust()
    # Two `>` prove a branch level; stay and probe even when exhausted.
    assert plan(MINES, walk) == PlannedGoal(branch_stairs(DOWN, 2))

    walk.at(LevelKey(0, 2), "|>...@|").use_stairs(LevelKey(0, 3), "|.@.|")
    # The probe was the main staircase: go back up to the identified branch.
    assert plan(MINES, walk) == PlannedGoal(main_stairs(UP))
    walk.use_stairs(LevelKey(0, 2), "|>...@|")
    assert plan(MINES, walk) == PlannedGoal(branch_stairs(DOWN, 2))


def test_exhausted_range_levels_are_rearmed_once_from_below(
    template: ProjectedObservation,
) -> None:
    walk = Walk(template)
    for level in (2, 3, 4):
        walk.at(LevelKey(0, level), "|<.@>|").exhaust()
    walk.at(LevelKey(0, 5), "|<@.>|")
    # Below the range with every range level exhausted: climb back to DL4.
    assert plan(MINES, walk) == PlannedGoal(main_stairs(UP))

    walk.at(LevelKey(0, 4), "|<.@>|")
    assert plan(MINES, walk) == PlannedGoal(branch_stairs(DOWN, 2), rearm=True)
    walk.dungeon.current.rearm_for_branch()
    assert plan(MINES, walk) == PlannedGoal(branch_stairs(DOWN, 2))

    walk.exhaust()
    # DL4 was re-armed already; the nearest remaining candidate is DL3.
    assert plan(MINES, walk) == PlannedGoal(main_stairs(UP))
    for level in (3, 2):
        walk.at(LevelKey(0, level), "|<.@>|").dungeon.current.rearm_for_branch()
        walk.exhaust()
    # Every range level was searched twice: keep searching here.
    assert plan(MINES, walk) == PlannedGoal(branch_stairs(DOWN, 2))


def test_legs_complete_only_on_their_level_dungeon_or_matching_stair(
    template: ProjectedObservation,
) -> None:
    walk = Walk(template).at(LevelKey(0, 2), "|.>@.|")
    assert leg_complete(ReachLevelLeg(LevelKey(0, 2)), walk.dungeon)
    assert not leg_complete(ReachLevelLeg(LevelKey(2, 2)), walk.dungeon)
    assert not leg_complete(EnterDungeonLeg(2), walk.dungeon)
    stand = StandOnStairsLeg(STAND_ON_DOWNSTAIRS.target)
    assert not leg_complete(stand, walk.dungeon)
    walk.at(LevelKey(0, 2), "|.@..|")
    assert leg_complete(stand, walk.dungeon)

    objective = Objective(
        (ReachLevelLeg(LevelKey(0, 2)), stand, ReachLevelLeg(LevelKey(0, 3)))
    )
    # Completed legs are skipped in order; the first open leg stops advancing.
    assert ObjectivePlanner(objective).advance(0, walk.dungeon) == 2


EXPLORE_THREE = Objective((ExploreDungeonLeg(3),))


def test_explore_dungeon_explores_each_level_before_descending_the_main_stairs(
    template: ProjectedObservation,
) -> None:
    walk = Walk(template).at(LevelKey(0, 1), "|@.>|")
    assert plan(EXPLORE_THREE, walk) == PlannedGoal(ExploreLevelGoal(LevelKey(0, 1)))

    walk.exhaust()
    assert plan(EXPLORE_THREE, walk) == PlannedGoal(main_stairs(DOWN))
    # Knowledge growth clears `exhausted`, but the level stays explored.
    walk.at(LevelKey(0, 1), "|.@>|")
    assert not walk.dungeon.current.exhausted
    assert plan(EXPLORE_THREE, walk) == PlannedGoal(main_stairs(DOWN))

    walk.use_stairs(LevelKey(0, 2), "|<@.|")
    assert plan(EXPLORE_THREE, walk) == PlannedGoal(ExploreLevelGoal(LevelKey(0, 2)))
    assert not leg_complete(EXPLORE_THREE.legs[0], walk.dungeon)


def test_explore_dungeon_climbs_back_to_a_skipped_level_and_leaves_branches(
    template: ProjectedObservation,
) -> None:
    # A trap door dropped the hero from an unexplored first level to level 3.
    walk = Walk(template).at(LevelKey(0, 1), "|@.>|").at(LevelKey(0, 3), "|.@<|")
    assert plan(EXPLORE_THREE, walk) == PlannedGoal(main_stairs(UP))

    # A probe of a branch staircase is retraced by its recorded link.
    mines = (
        Walk(template)
        .at(LevelKey(0, 2), "|.>@>|")
        .at(LevelKey(0, 2), "|.>.@|")
        .use_stairs(LevelKey(2, 1), "|.@.>|")
    )
    assert plan(EXPLORE_THREE, mines) == PlannedGoal(branch_stairs(UP, 0))


def test_explore_dungeon_completes_when_every_required_level_is_explored(
    template: ProjectedObservation,
) -> None:
    walk = Walk(template).at(LevelKey(0, 1), "|@>|").exhaust()
    walk.use_stairs(LevelKey(0, 2), "|<@>|").exhaust()
    leg = ExploreDungeonLeg(2)
    objective = Objective((leg,))

    assert leg_complete(leg, walk.dungeon)
    assert not leg_complete(ExploreDungeonLeg(3), walk.dungeon)
    assert ObjectivePlanner(objective).advance(0, walk.dungeon) == 1
    with pytest.raises(ObjectivePlanningError, match="explored dungeon leg"):
        plan(objective, walk)


def test_oracle_searches_each_candidate_level_before_descending(
    template: ProjectedObservation,
) -> None:
    objective = Objective((FindOracleLeg(),))
    walk = Walk(template).at(LevelKey(0, 4), "|@>|")
    assert plan(objective, walk) == PlannedGoal(main_stairs(DOWN))
    walk.use_stairs(LevelKey(0, 5), "|<@>|")
    from nethack_agent.traversal import ApproachOracleGoal

    assert plan(objective, walk) == PlannedGoal(ApproachOracleGoal(LevelKey(0, 5)))
    walk.exhaust()
    assert plan(objective, walk) == PlannedGoal(main_stairs(DOWN))
    assert not leg_complete(FindOracleLeg(), walk.dungeon)
