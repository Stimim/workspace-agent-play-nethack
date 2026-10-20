from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from nle import nethack

from nethack_agent import navigation_budget
from nethack_agent.contracts import ContractError
from nethack_agent.coordinator import ActionGate, ActionGateError, AgentCoordinator
from nethack_agent.decision import (
    ActionCandidate,
    ActionDecision,
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DecisionMetrics,
    DestinationKind,
    IntentDestination,
    LocalRecoveryEvidence,
    MapCell,
    NavigationEvidence,
    Skill,
    SkillDecision,
    SkillSelectionSource,
    StuckReason,
)
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.evaluation import _action_is_valid, _replay_exhaustion
from nethack_agent.events import StepPayload
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.navigation import ActionKind, ActionRecord, DungeonMemory
from nethack_agent.observation import MapView, ObservationProjector, PromptState
from nethack_agent.planner import ObjectivePlanner
from nethack_agent.replay import (
    STUCK_RECONSULT_STEPS,
    ExplorationReplay,
    derive_action_record,
)
from nethack_agent.skills import SkillAction
from nethack_agent.tasks import GOAL_PRESETS, STAIRCASE_TASK, ActionProfile
from nethack_agent.traversal import STAND_ON_DOWNSTAIRS, LevelKey, StairDirection


@pytest.fixture
def context(tmp_path: Path):
    environment = NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    )
    try:
        observation = ObservationProjector().project(environment.reset(), step_index=0)
        actions = environment.legal_actions
    finally:
        environment.close()
    wall = nethack.GLYPH_CMAP_OFF + 1
    floor = nethack.GLYPH_CMAP_OFF + 19
    observation = replace(
        observation,
        map=MapView(
            rows=("|||", "|@|", "|||"),
            glyph_rows=((wall, wall, wall), (wall, floor, wall), (wall, wall, wall)),
            color_rows=(bytes(3),) * 3,
            special_rows=(bytes(3),) * 3,
            pet_rows=(bytes(3),) * 3,
        ),
        player=replace(observation.player, x=1, y=1),
        changed_cells=(),
        inventory=(),
        message="",
        prompt=PromptState(False, False, False),
    )
    dungeon = DungeonMemory()
    dungeon.observe(observation)
    search = next(action for action in actions if action.name == "Command.SEARCH")
    selection = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL,
        STAND_ON_DOWNSTAIRS,
        Skill.EXPLORE_LEVEL,
        SkillSelectionSource.ARBITER,
        None,
        search.index,
        "Search with bounded public evidence.",
        None,
    )
    return observation, actions, search, selection, dungeon


def evidence(memory, kind="search"):
    return NavigationEvidence(
        kind,
        MapCell(*memory.position),
        (MapCell(0, 1),),
        memory.knowledge,
        memory.navigation_elapsed,
        0,
    )


def payload(observation, action, selection):
    fallback = selection.source is ActionSelectionSource.MODEL_FALLBACK
    return StepPayload(
        selection=selection,
        skill_decision=None,
        skill_metrics=None,
        action_decision=(
            ActionDecision(
                (ActionCandidate(action.index, 1.0, "Search"),), action.index, "Search"
            )
            if fallback
            else None
        ),
        action_metrics=DecisionMetrics(1, 1, 0.0, False) if fallback else None,
        action=action,
        reward=0.0,
        terminated=False,
        truncated=False,
        end_status=0,
        is_ascended=False,
        outcome=None,
        observation=observation,
    )


def test_navigation_evidence_round_trip_and_legacy_intent() -> None:
    proof = NavigationEvidence("search", MapCell(1, 1), (MapCell(0, 1),), 7, 12, 0)
    intent = ActionIntent(None, None, None, navigation=proof)
    assert ActionIntent.from_json(intent.to_json()) == intent
    old = ActionIntent.from_json(
        {
            "destination": {"kind": "search_spot", "x": 1, "y": 1},
            "attack_target": None,
        }
    )
    assert old.navigation is None


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "other"},
        {"targets": ()},
        {"knowledge": -1},
        {"no_progress_turns": -1},
        {"waits": -1},
    ],
)
def test_navigation_evidence_rejects_invalid_fields(changes) -> None:
    proof = NavigationEvidence("search", MapCell(1, 1), (MapCell(0, 1),), 7, 12, 0)
    with pytest.raises((ContractError, TypeError)):
        replace(proof, **changes)


def test_navigation_intent_rejects_mixed_attack_and_path() -> None:
    proof = NavigationEvidence("search", MapCell(1, 1), (MapCell(0, 1),), 7, 12, 0)
    with pytest.raises(ContractError):
        ActionIntent(None, MapCell(0, 1), None, navigation=proof)
    with pytest.raises(ContractError):
        ActionIntent(
            IntentDestination(DestinationKind.SEARCH_SPOT, 1, 1),
            None,
            (MapCell(1, 1),),
            navigation=proof,
        )


def test_step_payload_checks_navigation_command_shape(context) -> None:
    observation, actions, search, selection, dungeon = context
    proof = evidence(dungeon.current)
    selection = replace(
        selection, intent=ActionIntent(None, None, None, navigation=proof)
    )
    assert payload(observation, search, selection).selection.intent.navigation == proof
    move = next(action for action in actions if action.name == "CompassDirection.E")
    with pytest.raises(ContractError):
        payload(observation, move, replace(selection, action_index=move.index))
    with pytest.raises(ContractError):
        payload(observation, replace(search, command=ord(".")), selection)


def test_runtime_and_evaluator_require_current_search_evidence(
    context, monkeypatch
) -> None:
    observation, actions, search, selection, dungeon = context
    proof = evidence(dungeon.current)
    monkeypatch.setattr(
        navigation_budget, "search_evidence", lambda *args, **kwargs: proof
    )
    gate = ActionGate(actions)
    old_step = payload(observation, search, selection)
    assert StepPayload.from_json(old_step.to_json()).selection.intent is None
    with pytest.raises(ActionGateError):
        gate.resolve(
            search.index,
            before=observation,
            selection=selection,
            memory=dungeon.current,
        )
    assert not _action_is_valid(
        old_step,
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )
    valid = replace(selection, intent=ActionIntent(None, None, None, navigation=proof))
    assert (
        gate.resolve(
            search.index, before=observation, selection=valid, memory=dungeon.current
        )
        == search
    )
    assert _action_is_valid(
        payload(observation, search, valid),
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )
    forged = replace(
        valid,
        intent=ActionIntent(
            None, None, None, navigation=replace(proof, knowledge=proof.knowledge + 1)
        ),
    )
    with pytest.raises(ActionGateError):
        gate.resolve(
            search.index, before=observation, selection=forged, memory=dungeon.current
        )
    assert not _action_is_valid(
        payload(observation, search, forged),
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )


@pytest.mark.parametrize("exhaustion", ["coverage", "turns"])
def test_actual_budget_helper_controls_runtime_and_evaluator(
    context, exhaustion
) -> None:
    observation, actions, search, selection, dungeon = context
    memory = dungeon.current
    proof = navigation_budget.search_evidence(memory, selection.goal.target)
    assert proof is not None
    selection = replace(
        selection, intent=ActionIntent(None, None, None, navigation=proof)
    )
    gate = ActionGate(actions)
    assert (
        gate.resolve(
            search.index, before=observation, selection=selection, memory=memory
        )
        == search
    )
    step = payload(observation, search, selection)
    assert _action_is_valid(
        step,
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )
    if exhaustion == "coverage":
        for row in range(3):
            for column in range(3):
                memory.search_coverage[column, row] = (
                    navigation_budget.SEARCH_CANDIDATE_CAP
                )
    else:
        memory.navigation_turns = (
            memory.navigation_progress_turns + navigation_budget.NO_PROGRESS_TURN_LIMIT
        )
    assert navigation_budget.search_evidence(memory, selection.goal.target) is None
    with pytest.raises(ActionGateError):
        gate.resolve(
            search.index, before=observation, selection=selection, memory=memory
        )
    assert not _action_is_valid(
        step,
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )


def test_exploration_replay_validates_current_navigation_evidence(context) -> None:
    observation, actions, search, selection, dungeon = context
    proof = navigation_budget.search_evidence(dungeon.current, selection.goal.target)
    assert proof is not None
    valid = replace(selection, intent=ActionIntent(None, None, None, navigation=proof))
    replay = ExplorationReplay(STAIRCASE_TASK, actions, observation)
    assert replay.step(payload(observation, search, valid)) is None
    replay = ExplorationReplay(STAIRCASE_TASK, actions, observation)
    assert replay.step(payload(observation, search, selection)) is not None
    forged = replace(
        valid,
        intent=ActionIntent(
            None,
            None,
            None,
            navigation=replace(proof, no_progress_turns=proof.no_progress_turns + 1),
        ),
    )
    replay = ExplorationReplay(STAIRCASE_TASK, actions, observation)
    assert replay.step(payload(observation, search, forged)) is not None


def test_model_fallback_search_has_no_budget_exemption(context) -> None:
    observation, actions, search, selection, dungeon = context
    selection = replace(selection, source=ActionSelectionSource.MODEL_FALLBACK)
    assert not _action_is_valid(
        payload(observation, search, selection),
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )
    record = derive_action_record(selection, search.name, dungeon.current)
    assert record.kind is ActionKind.SEARCH


@pytest.mark.parametrize(
    "kind,expected", [("search", ActionKind.SEARCH), ("blocker_wait", ActionKind.WAIT)]
)
def test_replay_reconstructs_search_and_wait_coverage(context, kind, expected) -> None:
    _, _, search, selection, dungeon = context
    memory = dungeon.current
    proof = evidence(memory, kind)
    selection = replace(
        selection, intent=ActionIntent(None, None, None, navigation=proof)
    )
    record = derive_action_record(selection, search.name, memory)
    assert record.kind is expected
    before = dict(memory.search_coverage)
    memory.record(record)
    assert memory.search_coverage != before


def test_survival_prompt_letter_s_is_not_routine_search(context) -> None:
    observation, _, search, selection, dungeon = context
    prompt = replace(
        selection, source=ActionSelectionSource.DETERMINISTIC_PROMPT, skill=Skill.HUNGER
    )
    before = replace(observation, prompt=PromptState(True, False, False))
    assert (
        navigation_budget.navigation_action_error(
            search, prompt, before, dungeon.current
        )
        is None
    )
    assert (
        derive_action_record(prompt, search.name, dungeon.current).kind
        is ActionKind.OTHER
    )


def test_local_recovery_evidence_round_trip_and_exclusivity() -> None:
    proof = LocalRecoveryEvidence("find_oracle", LevelKey(0, 5), 12, 400, False, True)
    intent = ActionIntent(
        IntentDestination(DestinationKind.DOWNSTAIRS, 2, 1),
        None,
        (MapCell(2, 1),),
        local_recovery=proof,
    )
    assert ActionIntent.from_json(intent.to_json()) == intent
    for change in (
        {"objective_kind": "explore_dungeon"},
        {"knowledge": -1},
        {"no_progress_turns": -1},
        {"protected_target_level": 1},
        {"coverage_complete": 1},
    ):
        with pytest.raises((ContractError, TypeError)):
            replace(proof, **change)
    with pytest.raises(ContractError):
        replace(intent, attack_target=MapCell(2, 1))
    with pytest.raises(ContractError):
        replace(intent, destination=IntentDestination(DestinationKind.FRONTIER, 2, 1))
    with pytest.raises(ContractError):
        replace(
            intent,
            navigation=NavigationEvidence(
                "search", MapCell(1, 1), (MapCell(0, 1),), 12, 400, 0
            ),
        )


@pytest.fixture
def local_recovery_context(context, monkeypatch):
    observation, actions, _, selection, _ = context
    glyphs = observation.map.glyph_rows
    observation = replace(
        observation,
        map=replace(
            observation.map,
            rows=("|||", "|@>", "|||"),
            glyph_rows=(
                glyphs[0],
                (glyphs[1][0], glyphs[1][1], nethack.GLYPH_CMAP_OFF + 24),
                glyphs[2],
            ),
        ),
    )
    dungeon = DungeonMemory()
    dungeon.observe(observation)
    memory = dungeon.current
    proof = LocalRecoveryEvidence(
        "find_oracle",
        memory.level,
        memory.knowledge,
        memory.navigation_elapsed,
        False,
        True,
    )
    monkeypatch.setattr(
        navigation_budget,
        "local_recovery_evidence",
        lambda memory, kind: proof if kind == proof.objective_kind else None,
    )
    east = next(action for action in actions if action.name == "CompassDirection.E")
    selection = replace(
        selection,
        action_index=east.index,
        skill=Skill.STAIRCASE_NAVIGATION,
        intent=ActionIntent(
            IntentDestination(DestinationKind.DOWNSTAIRS, 2, 1),
            None,
            (MapCell(2, 1),),
            level=memory.level,
            local_recovery=proof,
        ),
    )
    return observation, actions, east, selection, dungeon, proof


@pytest.mark.parametrize(
    "change",
    [
        {"level": LevelKey(0, 2)},
        {"knowledge": 9999},
        {"no_progress_turns": 9999},
        {"objective_kind": "enter_minetown_temple"},
        {"protected_target_level": True},
        {"coverage_complete": False},
    ],
)
def test_evaluator_rejects_forged_local_recovery(
    local_recovery_context, change
) -> None:
    observation, actions, east, selection, dungeon, proof = local_recovery_context
    valid = payload(observation, east, selection)
    assert _action_is_valid(
        valid,
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )
    forged_proof = replace(proof, **change)
    forged = replace(
        selection,
        intent=replace(
            selection.intent, level=forged_proof.level, local_recovery=forged_proof
        ),
    )
    assert not _action_is_valid(
        payload(observation, east, forged),
        actions,
        observation,
        False,
        ActionProfile.NLE_TASK_ACTIONS,
        dungeon_memory=dungeon,
    )


@pytest.mark.parametrize(
    "recorded", ["matching", "missing", "wrong_objective", "wrong_goal", "unplanned"]
)
def test_local_recovery_replay_requires_planner_proof_without_completion(
    local_recovery_context, monkeypatch, recorded
) -> None:
    observation, actions, east, selection, _, proof = local_recovery_context
    replay = ExplorationReplay(STAIRCASE_TASK, actions, observation)
    planned_proof = None if recorded == "unplanned" else proof
    planned_goal = selection.goal
    monkeypatch.setattr(
        replay._planner,
        "plan",
        lambda *args: SimpleNamespace(
            goal=planned_goal, rearm=False, local_recovery=planned_proof
        ),
    )
    if recorded == "missing":
        selection = replace(
            selection, intent=replace(selection.intent, local_recovery=None)
        )
    elif recorded == "wrong_objective":
        selection = replace(
            selection,
            intent=replace(
                selection.intent,
                local_recovery=replace(proof, objective_kind="enter_minetown_temple"),
            ),
        )
    elif recorded == "wrong_goal":
        selection = replace(
            selection,
            goal=replace(
                selection.goal,
                target=replace(selection.goal.target, direction=StairDirection.UP),
            ),
        )
    problem = replay.step(payload(observation, east, selection))
    assert (problem is None) == (recorded == "matching")
    assert replay.explored == set()
    assert not replay._dungeon.current.explored


def test_step_payload_rejects_local_recovery_on_search(local_recovery_context) -> None:
    observation, actions, _, selection, _, _ = local_recovery_context
    search = next(action for action in actions if action.name == "Command.SEARCH")
    with pytest.raises(ContractError):
        payload(observation, search, replace(selection, action_index=search.index))


def test_step_payload_rejects_local_recovery_level_mismatch(
    local_recovery_context,
) -> None:
    observation, _, east, selection, _, proof = local_recovery_context
    selection = replace(
        selection,
        intent=replace(
            selection.intent, local_recovery=replace(proof, level=LevelKey(0, 2))
        ),
    )
    with pytest.raises(ContractError):
        payload(observation, east, selection)


def test_runtime_local_recovery_requires_planners_matching_permit(
    local_recovery_context,
):
    observation, actions, east, selection, dungeon, proof = local_recovery_context
    gate = ActionGate(actions)
    kwargs = {
        "before": observation,
        "selection": selection,
        "memory": dungeon.current,
        "local_recovery_goal": selection.goal,
    }
    assert gate.resolve(east.index, local_recovery_permit=proof, **kwargs) == east
    with pytest.raises(ActionGateError, match="planner"):
        gate.resolve(east.index, **kwargs)
    missing = replace(selection, intent=replace(selection.intent, local_recovery=None))
    with pytest.raises(ActionGateError, match="planner"):
        gate.resolve(
            east.index,
            before=observation,
            selection=missing,
            memory=dungeon.current,
            local_recovery_permit=proof,
        )
    forged = replace(proof, knowledge=proof.knowledge + 1)
    with pytest.raises(ActionGateError, match="spent local"):
        gate.resolve(
            east.index,
            before=observation,
            selection=replace(
                selection, intent=replace(selection.intent, local_recovery=forged)
            ),
            memory=dungeon.current,
            local_recovery_permit=forged,
            local_recovery_goal=selection.goal,
        )


def test_coordinator_stamps_only_objective_planned_staircase_action(
    local_recovery_context, tmp_path
):
    _, _, east, selection, dungeon, proof = local_recovery_context
    environment = NleEnvironment(ScenarioConfig(seed=6, artifact_directory=tmp_path))
    agent = AgentCoordinator(
        environment, ObservationProjector(), ScriptedDevelopmentModel()
    )
    try:
        agent._dungeon = dungeon
        agent._planned_local_recovery = proof
        proposal = SkillAction(
            east.index,
            "Follow the existing next-level route.",
            ActionRecord(ActionKind.MOVE, (1, 1), (2, 1)),
            replace(selection.intent, local_recovery=None),
        )
        planned = agent._skill_plan(
            proposal,
            selection.goal,
            Skill.STAIRCASE_NAVIGATION,
            SkillSelectionSource.ARBITER,
            None,
            None,
        )
        assert planned.selection.intent.local_recovery == proof
        unrelated = agent._skill_plan(
            proposal,
            selection.goal,
            Skill.EXPLORE_LEVEL,
            SkillSelectionSource.ARBITER,
            None,
            None,
        )
        assert unrelated.selection.intent.local_recovery is None
    finally:
        environment.close()


def test_evaluator_replays_missing_local_marker_on_place_objective(
    local_recovery_context, monkeypatch
):
    observation, actions, east, selection, _, proof = local_recovery_context
    monkeypatch.setattr(
        ObjectivePlanner,
        "plan",
        lambda *args: SimpleNamespace(
            goal=selection.goal, rearm=False, local_recovery=proof
        ),
    )
    missing = replace(selection, intent=replace(selection.intent, local_recovery=None))
    _, problems = _replay_exhaustion(
        GOAL_PRESETS["oracle"],
        actions,
        observation,
        [payload(observation, east, missing)],
    )
    assert any("local recovery" in problem for problem in problems)


def test_replay_delayed_initial_selection_and_reconsultation_interval(context):
    observation, actions, _, selection, _ = context
    wait = next(action for action in actions if action.name == "MiscDirection.WAIT")
    selection = replace(selection, action_index=wait.index)
    replay = ExplorationReplay(STAIRCASE_TASK, actions, observation)

    def event(step, consult=False):
        after = replace(
            observation,
            step_index=step,
            player=replace(observation.player, turn=observation.player.turn + step),
        )
        chosen = replace(
            selection,
            skill_selection=SkillSelectionSource.MODEL
            if consult
            else SkillSelectionSource.ARBITER,
            stuck_reason=StuckReason.NAVIGATION_BUDGET_EXHAUSTED if consult else None,
        )
        result = payload(after, wait, chosen)
        return replace(
            result,
            skill_decision=SkillDecision(
                chosen.goal, Skill.EXPLORE_LEVEL, "Consult the scripted model."
            )
            if consult
            else None,
            skill_metrics=DecisionMetrics(1, 1, 0.0, False) if consult else None,
        )

    assert replay.step(event(1)) is None
    # The first model decision can arrive after survival/prompt steps. It is
    # still initial selection, not a stuck consultation.
    assert replay.step(event(2, True)) is None
    memory = replay._dungeon.current
    assert memory.stuck_consult_step is None
    memory.search_goal = (1, 1)
    assert replay.step(event(3, True)) is None
    assert memory.stuck_consult_step == 2
    assert memory.search_goal == (1, 1)  # budget exhaustion never re-arms
    assert "interval" in replay.step(event(4, True))


def test_replay_accepts_periodic_stuck_reconsultation_without_new_knowledge(
    context,
):
    """The coordinator re-asks the model every STUCK_RECONSULT_STEPS while stuck.

    Regression: replay rejected every re-consultation at an unchanged knowledge
    stamp (`eat-stuck-after-exhaustion-824`, `descend-d3-hidden-downstairs-701`).
    """
    observation, actions, _, selection, _ = context
    wait = next(action for action in actions if action.name == "MiscDirection.WAIT")
    # Still stuck on every step, so no ordinary decision ends the stuck spell.
    selection = replace(
        selection,
        action_index=wait.index,
        skill_selection=SkillSelectionSource.MODEL,
        stuck_reason=StuckReason.NAVIGATION_BUDGET_EXHAUSTED,
    )
    replay = ExplorationReplay(STAIRCASE_TASK, actions, observation)
    knowledge = replay._dungeon.current.knowledge

    def event(step, consult=False):
        result = payload(replace(observation, step_index=step), wait, selection)
        return replace(
            result,
            skill_decision=SkillDecision(
                selection.goal, Skill.EXPLORE_LEVEL, "Consult the scripted model."
            )
            if consult
            else None,
            skill_metrics=DecisionMetrics(1, 1, 0.0, False) if consult else None,
        )

    # Step n is decided on observation n - 1. Step 1 is initial selection.
    consults = {1, 2, 2 + STUCK_RECONSULT_STEPS, 2 + 2 * STUCK_RECONSULT_STEPS}
    for step in range(1, max(consults) + 1):
        assert replay.step(event(step, step in consults)) is None, step
    memory = replay._dungeon.current
    assert memory.stuck_consult_step == max(consults) - 1
    assert memory.knowledge == knowledge
    # One step short of the interval is still rejected.
    late = max(consults) + STUCK_RECONSULT_STEPS - 1
    for step in range(max(consults) + 1, late):
        assert replay.step(event(step)) is None, step
    assert "interval" in replay.step(event(late, True))
