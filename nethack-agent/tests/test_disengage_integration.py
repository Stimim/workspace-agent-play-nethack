from dataclasses import replace

import pytest
from nle import nethack

from nethack_agent.conduct import noncombat_actions
from nethack_agent.coordinator import ActionGateError, AgentCoordinator
from nethack_agent.decision import (
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    Skill,
    SkillSelectionSource,
)
from nethack_agent.disengage import DisengageRecovery
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.evaluation import _action_is_valid
from nethack_agent.events import StepPayload
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.navigation import Monster
from nethack_agent.observation import CellDescription, ObservationProjector, PromptState
from nethack_agent.tasks import ActionProfile, NleTask, TaskSpec
from nethack_agent.traversal import LevelKey, Objective, ReachLevelLeg


@pytest.fixture
def combat(tmp_path):
    task = TaskSpec(
        NleTask.SCORE,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ReachLevelLeg(LevelKey(0, 5)),)),
    )
    agent = AgentCoordinator(
        NleEnvironment(ScenarioConfig(seed=6, artifact_directory=tmp_path, task=task)),
        ObservationProjector(),
        ScriptedDevelopmentModel(),
    )
    initial = agent.start()
    point = (initial.player.x + 1, initial.player.y)
    monster_id = next(
        i for i in range(nethack.NUMMONS) if nethack.permonst(i).mname == "jackal"
    )
    memory = agent._dungeon.current
    memory.monsters = {
        point: Monster(nethack.GLYPH_MON_OFF + monster_id, "jackal", False)
    }
    # Synthetic combat fixture has publicly established the starting upstairs.
    memory._cmap[initial.player.y][initial.player.x] = 23
    before = replace(
        initial,
        message="",
        player=replace(
            initial.player, hit_points=9, max_hit_points=30, turn=50, hunger=1
        ),
        cell_descriptions=(CellDescription(*point, "jackal"),),
    )
    try:
        yield agent, before, point
    finally:
        agent.stop()


def selection(agent, before, evidence):
    action = agent._gate.actions_by_command[evidence.command]
    return ActionSelection(
        ActionSelectionSource.DETERMINISTIC_PROMPT
        if before.prompt.active
        else ActionSelectionSource.DETERMINISTIC_SKILL,
        agent.snapshot().current_goal,
        Skill.DISENGAGE,
        SkillSelectionSource.ARBITER,
        None,
        action.index,
        "Owned recovery transaction.",
        ActionIntent(None, None, None, disengage=evidence),
    )


def payload(agent, chosen, after):
    return StepPayload(
        chosen,
        None,
        None,
        None,
        None,
        agent.legal_actions[chosen.action_index],
        0.0,
        False,
        False,
        0,
        False,
        None,
        after,
    )


def test_every_text_collision_passes_all_contracts_and_identical_replay(combat):
    agent, before, _ = combat
    recovery = agent._disengage
    replay = DisengageRecovery()
    memory = agent._dungeon.current
    # Scripted native observations isolate each contract surface; actual native
    # transport, pagination and corrupt dust are tested separately.
    responses = [
        ("What do you want to write with? [- ab or ?*] ", (1, 0, 0), 0),
        ("You write in the dust with your fingertip.", (0, 1, 1), 0),
        ("What do you want to write in the dust here? ", (0, 1, 0), 0),
    ]
    responses += [
        ("What do you want to write in the dust here? " + "Elbereth"[:i], (0, 1, 0), 0)
        for i in range(1, 9)
    ]
    responses += [
        ("", (0, 0, 0), 1),
        ("Something is written here in the dust.", (0, 0, 1), 0),
        ('You read: "Elbereth".', (0, 0, 0), 0),
    ]
    keys = []
    for message, flags, turn_delta in responses:
        recovery.observe(before, memory, prayer_available=False)
        replay.observe(before, memory, prayer_available=False)
        evidence = recovery.expected(before)
        assert evidence is not None
        assert evidence == replay.expected(before)
        chosen = selection(agent, before, evidence)
        action = agent.legal_actions[chosen.action_index]
        keys.append(action.command)
        assert (
            agent._gate.resolve(
                action.index,
                before=before,
                selection=chosen,
                memory=memory,
                disengage=recovery,
            )
            == action
        )
        after = replace(
            before,
            step_index=before.step_index + 1,
            message=message,
            prompt=PromptState(*(bool(f) for f in flags)),
            player=replace(before.player, turn=before.player.turn + turn_delta),
        )
        step = payload(agent, chosen, after)
        assert _action_is_valid(
            step,
            agent.legal_actions,
            before,
            True,
            ActionProfile.NLE_SURVIVAL_ACTIONS,
            dungeon_memory=agent._dungeon,
            disengage=replay,
        )
        # The ordinary permit builders must not interpret text e as EAT or
        # movement letters as unrelated prompt answers.
        assert agent._hunger_permit(chosen, before) is None
        assert agent._prompt_permit(chosen, before) is None
        recovery.advance(evidence, after)
        replay.advance(evidence, after)
        before = after
    assert keys == list(map(ord, "E-\rElbereth\r:\r"))
    recovery.observe(before, memory, prayer_available=False)
    replay.observe(before, memory, prayer_available=False)
    assert recovery.protected(before)
    assert recovery.expected(before) == replay.expected(before)
    assert recovery.expected(before).command == ord(".")


def test_critical_prayer_preempts_combat_engraving(combat):
    agent, before, _ = combat
    critical = replace(before, player=replace(before.player, turn=100, hit_points=3))
    plan = agent._decide(critical, None, lambda: False, 0)
    assert plan is not None
    assert plan.selection.skill is Skill.PRAYER


def test_model_cannot_open_engraving_or_type_owned_prompt(combat):
    agent, before, _ = combat
    recovery = agent._disengage
    recovery.observe(before, agent._dungeon.current, prayer_available=False)
    evidence = recovery.expected(before)
    chosen = selection(agent, before, evidence)
    for source in (
        ActionSelectionSource.MODEL_FALLBACK,
        ActionSelectionSource.DETERMINISTIC_SKILL,
    ):
        bad = replace(chosen, source=source, skill=Skill.EXPLORE_LEVEL, intent=None)
        with pytest.raises(ActionGateError):
            agent._gate.resolve(
                bad.action_index, before=before, selection=bad, disengage=recovery
            )
    offered = replace(
        before,
        step_index=1,
        message="What do you want to write with? [- ab or ?*] ",
        prompt=PromptState(True, False, False),
    )
    recovery.advance(evidence, offered)
    action = agent._gate.actions_by_command[ord("h")]
    bad = replace(
        chosen,
        source=ActionSelectionSource.MODEL_FALLBACK,
        skill=Skill.EXPLORE_LEVEL,
        action_index=action.index,
        intent=None,
    )
    with pytest.raises(ActionGateError):
        agent._gate.resolve(
            action.index, before=offered, selection=bad, disengage=recovery
        )


def test_protected_square_filters_existing_combat_without_new_retreat(combat):
    agent, before, point = combat
    filtered = noncombat_actions(agent._gate.actions_by_name, agent._dungeon.current)
    assert "CompassDirection.E" not in filtered
    assert "Command.KICK" not in filtered
    assert "MiscDirection.WAIT" in filtered
    # An ordinary non-combat command is unchanged; this is an attack filter,
    # not a new movement/retreat choice.
    assert filtered["Command.SEARCH"] == agent._gate.actions_by_name["Command.SEARCH"]
    assert point == (before.player.x + 1, before.player.y)
