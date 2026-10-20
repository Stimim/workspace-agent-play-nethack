from dataclasses import replace

import pytest
from test_skills import actions as actions_fixture
from test_skills import remembered, sketch
from test_skills import template as template_fixture

from nethack_agent.contracts import ContractError
from nethack_agent.decision import (
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DestinationKind,
    IntentDestination,
    MapCell,
    Skill,
    SkillSelectionSource,
    StuckReason,
)
from nethack_agent.navigation import ActionKind, ActionRecord, DungeonMemory, route_tree
from nethack_agent.navigation_budget import (
    MONSTER_WAIT_LIMIT,
    NO_PROGRESS_TURN_LIMIT,
    SEARCH_BATCH_SIZE,
    SEARCH_CANDIDATE_CAP,
    local_recovery_error,
    local_recovery_evidence,
    navigation_available,
    requires_local_recovery_marker,
    search_candidate,
    search_evidence,
    wait_evidence,
)
from nethack_agent.planner import ObjectivePlanner, leg_complete
from nethack_agent.skills import (
    ExploreLevelSkill,
    StaircaseNavigationSkill,
    _search,
    _search_targets,
)
from nethack_agent.traversal import (
    STAND_ON_DOWNSTAIRS,
    ApproachOracleGoal,
    EnterMinetownTempleLeg,
    ExploreDungeonLeg,
    FindOracleLeg,
    Objective,
    StairDirection,
    TraverseStairsGoal,
)

# Register the shared native-observation fixtures without importing names that
# collide with pytest's fixture-injection parameter names.
actions = actions_fixture
template = template_fixture

ROOM = ("       ", " ----- ", " |@..| ", " ----- ", "       ")


def test_least_covered_rotates_away_from_committed_stand(template, actions):
    memory = remembered(template, ROOM)
    first = search_candidate(memory, route_tree(memory))
    assert first is not None
    stand, targets = first
    memory.search_goal = stand
    for target in targets:
        memory.search_coverage[target] = 10
    other = search_candidate(memory, route_tree(memory))
    assert other is not None
    assert other[0] != stand
    assert min(memory.search_coverage.get(p, 0) for p in other[1]) == 0
    result = _search(memory, route_tree(memory), actions)
    assert result is not None
    assert result.intent.destination.kind is DestinationKind.SEARCH_SPOT


def test_per_target_cap_and_incidental_overlap(template, actions):
    arrived = ("       ", " ----- ", " |.@.| ", " ----- ", "       ")
    memory = remembered(template, ROOM, arrived)
    for point in route_tree(memory).distances:
        for target in _search_targets(memory, point):
            memory.search_coverage[target] = SEARCH_CANDIDATE_CAP
    assert search_evidence(memory, STAND_ON_DOWNSTAIRS.target) is None
    assert (
        _search(memory, route_tree(memory), actions, STAND_ON_DOWNSTAIRS.target) is None
    )
    # One remaining beneficial wall authorizes a search, even though the
    # neighbouring walls already reached their cap.
    targets = _search_targets(memory, memory.position)
    assert targets
    memory.search_coverage[targets[0]] = SEARCH_CANDIDATE_CAP - 1
    evidence = search_evidence(memory, STAND_ON_DOWNSTAIRS.target)
    assert evidence is not None
    assert tuple((cell.x, cell.y) for cell in evidence.targets) == (targets[0],)
    memory.record(
        ActionRecord(ActionKind.SEARCH, memory.position, search_spot=memory.position)
    )
    observation = sketch(template, arrived, step=2)
    memory.observe(observation)
    assert memory.search_coverage[targets[0]] == SEARCH_CANDIDATE_CAP
    assert any(memory.search_coverage[p] > SEARCH_CANDIDATE_CAP for p in targets[1:])
    assert search_evidence(memory, STAND_ON_DOWNSTAIRS.target) is None


def test_rearm_and_revisit_preserve_spent_allowances(template):
    dungeon = DungeonMemory()
    observation = sketch(template, ROOM)
    memory = dungeon.observe(observation)
    point = memory.position
    memory.search_coverage[point] = SEARCH_CANDIDATE_CAP
    memory.monster_waits = MONSTER_WAIT_LIMIT
    memory.navigation_turns = NO_PROGRESS_TURN_LIMIT
    memory.navigation_progress_turns = 0
    memory.abandoned_goals.add(point)
    memory.rearm()
    assert memory.search_coverage[point] == SEARCH_CANDIDATE_CAP
    assert memory.monster_waits == MONSTER_WAIT_LIMIT
    assert point in memory.abandoned_goals
    dungeon.observe(sketch(template, ("|@.|",), dungeon_level=2))
    restored = dungeon.observe(observation)
    assert restored is memory
    assert restored.navigation_elapsed == NO_PROGRESS_TURN_LIMIT
    assert restored.search_coverage[point] == SEARCH_CANDIDATE_CAP
    assert restored.monster_waits == MONSTER_WAIT_LIMIT
    assert search_evidence(restored) is None


def test_frontier_precedes_search_even_after_time_budget(template, actions):
    memory = remembered(template, ("       ", "  @##  ", "       "))
    memory.navigation_turns = memory.navigation_progress_turns + NO_PROGRESS_TURN_LIMIT
    result = ExploreLevelSkill().select_action(memory, actions, target=None)
    assert result.action is not None
    assert result.action.record.kind is ActionKind.MOVE
    assert result.action.intent.navigation is None
    assert search_evidence(memory) is None


def test_wait_limits_and_frontier_preference(template, actions):
    memory = remembered(
        template,
        ("-------", "|@..>.|", "-------"),
        ("-------", "|@e.>.|", "-------"),
    )
    blocker = (2, 1)
    evidence = wait_evidence(memory, blocker, STAND_ON_DOWNSTAIRS.target)
    assert evidence is not None
    assert evidence.kind == "blocker_wait"
    proposal = StaircaseNavigationSkill().select_action(memory, actions)
    assert proposal is not None
    assert proposal.intent.navigation == evidence
    memory.monster_waits = MONSTER_WAIT_LIMIT
    assert wait_evidence(memory, blocker, STAND_ON_DOWNSTAIRS.target) is None
    memory.monster_waits = 0
    memory.navigation_turns = memory.navigation_progress_turns + NO_PROGRESS_TURN_LIMIT
    assert wait_evidence(memory, blocker, STAND_ON_DOWNSTAIRS.target) is None


def test_blocked_stairs_defer_to_reachable_frontier(template, actions):
    memory = remembered(
        template, ("         ", "  @f>    ", "  #      ", "  #      ", "         ")
    )
    assert wait_evidence(memory, (3, 1), STAND_ON_DOWNSTAIRS.target) is None
    assert StaircaseNavigationSkill().select_action(memory, actions) is None
    result = ExploreLevelSkill().select_action(memory, actions)
    assert result.action is not None
    assert result.action.record.kind is ActionKind.MOVE


def test_elapsed_game_turns_suppress_search_not_defense(template, actions):
    memory = remembered(template, ROOM)
    memory.navigation_turns = memory.navigation_progress_turns + NO_PROGRESS_TURN_LIMIT
    result = ExploreLevelSkill().select_action(memory, actions)
    assert result.stuck is StuckReason.NAVIGATION_BUDGET_EXHAUSTED
    hostile = remembered(template, ("------", "|@j..|", "------"))
    hostile.navigation_turns = (
        hostile.navigation_progress_turns + NO_PROGRESS_TURN_LIMIT
    )
    result = ExploreLevelSkill().select_action(hostile, actions)
    assert result.action is not None
    assert result.action.intent.attack_target is not None


def test_public_turn_deltas_not_step_indices_spend_time(template):
    before = sketch(template, ROOM)
    memory = remembered(template, ROOM)
    after = replace(
        before,
        step_index=1,
        player=replace(before.player, turn=before.player.turn + 17),
    )
    memory.observe(after)
    assert memory.navigation_elapsed == 17
    memory.observe(replace(after, step_index=2))
    assert memory.navigation_elapsed == 17


def test_batch_bookkeeping_never_refills_candidate_coverage(template):
    memory = remembered(template, ROOM)
    origin = memory.position
    targets = _search_targets(memory, origin)
    for _ in range(SEARCH_BATCH_SIZE):
        memory.record(ActionRecord(ActionKind.SEARCH, origin, search_spot=origin))
    assert memory.search_turns_remaining == 0
    assert all(
        memory.search_coverage[target] == SEARCH_BATCH_SIZE for target in targets
    )
    memory.rearm()
    assert memory.search_turns_remaining == 0
    assert all(
        memory.search_coverage[target] == SEARCH_BATCH_SIZE for target in targets
    )


def cover_geometry(memory):
    for point in route_tree(memory).distances:
        for cell in _search_targets(memory, point):
            memory.search_coverage[cell] = SEARCH_CANDIDATE_CAP


def test_protected_oracle_requires_coverage_even_after_extended_time(template):
    dungeon = DungeonMemory()
    memory = dungeon.observe(sketch(template, ROOM, dungeon_level=5))
    planner = ObjectivePlanner(Objective((FindOracleLeg(),)))
    assert isinstance(planner.plan(0, dungeon).goal, ApproachOracleGoal)
    memory.navigation_turns = memory.navigation_progress_turns + NO_PROGRESS_TURN_LIMIT
    assert navigation_available(memory)
    memory.navigation_turns += 3 * NO_PROGRESS_TURN_LIMIT
    assert not navigation_available(memory)
    assert local_recovery_evidence(memory, "find_oracle") is None
    cover_geometry(memory)
    planned = planner.plan(0, dungeon)
    assert isinstance(planned.goal, TraverseStairsGoal)
    assert planned.goal.target.direction is StairDirection.DOWN
    assert planned.local_recovery is not None
    assert planned.local_recovery.protected_target_level
    assert planned.local_recovery.coverage_complete
    assert not memory.explored
    assert not leg_complete(FindOracleLeg(), dungeon)
    assert not leg_complete(ExploreDungeonLeg(5), dungeon)
    memory.oracle_seen = True
    assert local_recovery_evidence(memory, "find_oracle") is None
    assert isinstance(planner.plan(0, dungeon).goal, ApproachOracleGoal)


def test_quarantined_frontier_cannot_authorize_local_recovery(template):
    memory = remembered(template, ("       ", "  @##  ", "       "))
    memory.navigation_turns = NO_PROGRESS_TURN_LIMIT * 4
    memory.abandoned_goals.update(route_tree(memory).distances)
    cover_geometry(memory)
    assert local_recovery_evidence(memory, "find_oracle") is None


def test_mines_target_guard_and_known_town_cues(template):
    dungeon = DungeonMemory()
    memory = dungeon.observe(sketch(template, ROOM, dungeon_number=2, dungeon_level=3))
    planner = ObjectivePlanner(Objective((EnterMinetownTempleLeg(),)))
    planner.plan(0, dungeon)
    memory.navigation_turns = (
        memory.navigation_progress_turns + 4 * NO_PROGRESS_TURN_LIMIT
    )
    assert local_recovery_evidence(memory, "enter_minetown_temple") is None
    cover_geometry(memory)
    assert planner.plan(0, dungeon).local_recovery is not None
    memory.altars[(3, 2)] = "aligned altar"
    assert local_recovery_evidence(memory, "enter_minetown_temple") is None
    assert planner.plan(0, dungeon).local_recovery is None
    assert not memory.explored


def test_non_target_spent_branch_candidate_routes_without_exploration_credit(template):
    dungeon = DungeonMemory()
    memory = dungeon.observe(sketch(template, ROOM, dungeon_level=2))
    planner = ObjectivePlanner(Objective((EnterMinetownTempleLeg(),)))
    memory.navigation_turns = memory.navigation_progress_turns + NO_PROGRESS_TURN_LIMIT
    planned = planner.plan(0, dungeon)
    assert isinstance(planned.goal, TraverseStairsGoal)
    assert planned.goal.target.direction is StairDirection.DOWN
    assert planned.local_recovery is not None
    assert not planned.local_recovery.protected_target_level
    assert not memory.explored
    assert not leg_complete(ExploreDungeonLeg(2), dungeon)


def test_spent_departure_survives_knowledge_found_on_the_way_out(template):
    # 0059 Minetown 1362 smoke: walking to the exit revealed cells, the clock
    # restarted, and the permit flipped back to the branch search.
    def at(lines, step, turn):
        observation = sketch(template, lines, step=step, dungeon_level=2)
        return replace(observation, player=replace(observation.player, turn=turn))

    dungeon = DungeonMemory()
    planner = ObjectivePlanner(Objective((EnterMinetownTempleLeg(),)))
    memory = dungeon.observe(at(ROOM, 0, 1))
    memory = dungeon.observe(at(ROOM, 1, 1 + NO_PROGRESS_TURN_LIMIT))
    assert not navigation_available(memory)
    spent = planner.plan(0, dungeon)
    assert spent.goal.target.direction is StairDirection.DOWN
    assert spent.local_recovery is not None
    memory.record(ActionRecord(ActionKind.MOVE, memory.position, (4, 2)))
    walked = (*ROOM[:2], " |..@| ", *ROOM[3:])
    memory = dungeon.observe(at(walked, 2, 2 + NO_PROGRESS_TURN_LIMIT))
    assert memory.navigation_elapsed == 0
    assert navigation_available(memory)
    planned = planner.plan(0, dungeon)
    assert planned.goal == spent.goal
    assert planned.local_recovery is not None
    assert planned.local_recovery == local_recovery_evidence(
        memory, "enter_minetown_temple"
    )


def test_local_recovery_marker_only_covers_stair_navigation(template, actions):
    dungeon = DungeonMemory()
    memory = dungeon.observe(sketch(template, ROOM, dungeon_level=2))
    memory.navigation_turns = memory.navigation_progress_turns + NO_PROGRESS_TURN_LIMIT
    planned = ObjectivePlanner(Objective((EnterMinetownTempleLeg(),))).plan(0, dungeon)
    evidence = planned.local_recovery
    assert evidence is not None
    action = actions["CompassDirection.E"]
    selection = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        planned.goal,
        Skill.STAIRCASE_NAVIGATION,
        SkillSelectionSource.ARBITER,
        None,
        action.index,
        "Continue the existing objective after local recovery is spent.",
        ActionIntent(
            IntentDestination(DestinationKind.DOWNSTAIRS, 3, 2),
            None,
            (MapCell(3, 2),),
            level=memory.level,
            local_recovery=evidence,
        ),
    )
    assert requires_local_recovery_marker(selection, action)
    assert local_recovery_error(action, selection, memory=memory) is None
    assert (
        local_recovery_error(
            actions["Command.SEARCH"],
            selection,
            memory=memory,
        )
        is not None
    )
    with pytest.raises(ContractError):
        replace(selection, source=ActionSelectionSource.MODEL_FALLBACK)


def test_protected_monster_isolated_frontier_is_not_cleared(template):
    dungeon = DungeonMemory()
    dungeon.observe(
        sketch(
            template,
            ("          ", " |@.##    ", " -------- ", "          "),
            dungeon_level=5,
        )
    )
    memory = dungeon.observe(
        sketch(
            template,
            ("          ", " |@f##    ", " -------- ", "          "),
            step=1,
            dungeon_level=5,
        )
    )
    ObjectivePlanner(Objective((FindOracleLeg(),))).plan(0, dungeon)
    memory.navigation_turns = (
        memory.navigation_progress_turns + 4 * NO_PROGRESS_TURN_LIMIT
    )
    cover_geometry(memory)
    assert local_recovery_evidence(memory, "find_oracle") is None


def test_legacy_explore_dungeon_leg_grows_on_rearm_ignoring_turn_limit(
    template, actions
):
    """ExploreLevelGoal (target=None) keeps the original unbounded,
    density-gated, round-scored algorithm; the new finite place-objective
    budget (NO_PROGRESS_TURN_LIMIT, SEARCH_CANDIDATE_CAP) never governs it."""
    memory = remembered(template, ROOM)
    memory.navigation_turns = 10 * NO_PROGRESS_TURN_LIMIT
    skill = ExploreLevelSkill()
    for point in route_tree(memory).distances:
        for cell in _search_targets(memory, point):
            memory.search_coverage[cell] = 10
    exhausted = skill.select_action(memory, actions, None)
    assert exhausted.action is None
    assert exhausted.stuck is StuckReason.SEARCH_EXHAUSTED
    memory.rearm(legacy=True)
    assert memory.search_round == 1
    # Growth un-sticks exploration; a new round makes previously-capped
    # cells searchable again, something the finite place-objective path
    # never does.
    rearmed = skill.select_action(memory, actions, None)
    assert rearmed.action is not None
    assert (
        skill.select_action(memory, actions, STAND_ON_DOWNSTAIRS.target).stuck
        is StuckReason.NAVIGATION_BUDGET_EXHAUSTED
    )


def test_protected_unknown_floor_under_monster_is_not_cleared(template):
    dungeon = DungeonMemory()
    memory = dungeon.observe(
        sketch(
            template,
            ("          ", " |@f##    ", " -------- ", "          "),
            dungeon_level=5,
        )
    )
    ObjectivePlanner(Objective((FindOracleLeg(),))).plan(0, dungeon)
    memory.navigation_turns = 4 * NO_PROGRESS_TURN_LIMIT
    cover_geometry(memory)
    assert local_recovery_evidence(memory, "find_oracle") is None


def test_executed_batch_finishes_then_rotates_without_refilling(template, actions):
    arrived = ("       ", " ----- ", " |.@.| ", " ----- ", "       ")
    memory = remembered(template, ROOM, arrived, ROOM)
    stand = memory.position
    first = search_candidate(memory, route_tree(memory))
    assert first is not None and first[0] == stand
    record = ActionRecord(ActionKind.SEARCH, stand, search_spot=stand)
    memory.record(record)
    # An executed batch is finite commitment, not a walk after every SEARCH.
    assert search_candidate(memory, route_tree(memory))[0] == stand
    assert memory.search_turns_remaining == SEARCH_BATCH_SIZE - 1
    for _ in range(SEARCH_BATCH_SIZE - 1):
        memory.record(record)
    assert memory.search_turns_remaining == 0
    rotated = search_candidate(memory, route_tree(memory))
    assert rotated is not None and rotated[0] != stand
    assert min(memory.search_coverage.get(p, 0) for p in rotated[1]) < SEARCH_BATCH_SIZE
