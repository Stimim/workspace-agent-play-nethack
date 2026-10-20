"""Consumer contracts; route eligibility itself is covered by hazard tests."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from nle import nethack

from nethack_agent import evaluation, hazard
from nethack_agent.contracts import ContractError
from nethack_agent.coordinator import ActionGate, ActionGateError
from nethack_agent.decision import (
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    MapCell,
    Skill,
    SkillSelectionSource,
    ThrowEvidence,
    survival_action_selection_error,
)
from nethack_agent.environment import LegalAction
from nethack_agent.events import StepPayload
from nethack_agent.navigation import ActionKind, LevelMemory
from nethack_agent.observation import (
    MapView,
    PlayerStats,
    ProjectedObservation,
    PromptState,
)
from nethack_agent.replay import derive_action_record
from nethack_agent.tasks import ActionProfile, ActionRole
from nethack_agent.traversal import STAND_ON_DOWNSTAIRS

PROFILE = ActionProfile.NLE_SURVIVAL_ACTIONS
ACTIONS = tuple(
    LegalAction(index, int(action), f"{type(action).__name__}.{action.name}")
    for index, action in enumerate(PROFILE.actions)
)
BY_COMMAND = {action.command: action for action in ACTIONS}


def observation() -> ProjectedObservation:
    return ProjectedObservation(
        step_index=0,
        map=MapView(
            rows=(".....",) * 3,
            glyph_rows=((nethack.GLYPH_CMAP_OFF + 19,) * 5,) * 3,
            color_rows=(bytes(5),) * 3,
            special_rows=(bytes(5),) * 3,
            pet_rows=None,
        ),
        changed_cells=(),
        player=PlayerStats(
            x=0,
            y=0,
            strength_25=16,
            strength_125=16,
            dexterity=10,
            constitution=10,
            intelligence=10,
            wisdom=10,
            charisma=10,
            score=0,
            hit_points=10,
            max_hit_points=10,
            depth=1,
            gold=0,
            energy=0,
            max_energy=0,
            armor_class=6,
            hit_dice=0,
            experience_level=1,
            experience_points=0,
            turn=1,
            hunger=0,
            encumbrance=0,
            dungeon_number=0,
            dungeon_level=1,
            alignment=0,
            conditions=(),
        ),
        message="",
        prompt=PromptState(False, False, False),
        inventory=(),
    )


def selection(action: LegalAction, *, letter: str = "e") -> ActionSelection:
    return ActionSelection(
        ActionSelectionSource.DETERMINISTIC_SKILL
        if action.command == ord("t")
        else ActionSelectionSource.DETERMINISTIC_PROMPT,
        STAND_ON_DOWNSTAIRS,
        Skill.RANGED_THROW,
        SkillSelectionSource.ARBITER,
        None,
        action.index,
        "Clear the publicly observed route blocker.",
        ActionIntent(
            None,
            None,
            None,
            throw=ThrowEvidence(
                letter,
                MapCell(3, 0),
                (-1, -1) if action.command == ord("y") else (1, 0),
                action.command,
            ),
        ),
    )


def step(action: LegalAction, selected: ActionSelection) -> StepPayload:
    return StepPayload(
        selected,
        None,
        None,
        None,
        None,
        action,
        0.0,
        False,
        False,
        0,
        False,
        None,
        observation(),
    )


@pytest.mark.parametrize(
    "command", [ord("t"), ord("e"), ord("d"), ord("y"), ord("l"), ord("$"), 27]
)
def test_throw_permit_survives_all_consumers_and_json(command, monkeypatch) -> None:
    action = BY_COMMAND[command]
    selected = selection(
        action,
        letter=chr(command) if command not in (27, ord("l"), ord("y")) else "e",
    )
    evidence = selected.intent.throw
    # Isolate consumers from route finding, retaining the real shared validator.
    monkeypatch.setattr(hazard, "expected_throw", lambda *args, **kwargs: evidence)
    before = replace(
        observation(),
        prompt=PromptState(command != ord("t"), False, False),
    )
    memory = LevelMemory()
    gate = ActionGate(ACTIONS, PROFILE)
    assert (
        gate.resolve(action.index, selection=selected, before=before, memory=memory)
        == action
    )
    payload = step(action, selected)
    assert StepPayload.from_json(json.loads(json.dumps(payload.to_json()))) == payload
    assert survival_action_selection_error(action.name, selected) is None
    assert evaluation._action_is_valid(
        payload,
        ACTIONS,
        before,
        True,
        PROFILE,
        dungeon_memory=SimpleNamespace(current=memory),
    )
    record = derive_action_record(selected, action.name, memory)
    assert record.kind is ActionKind.OTHER
    assert record.throw == evidence


def test_throw_role_precedes_prompt_key_and_is_not_model_offered() -> None:
    assert PROFILE.role(nethack.Command.THROW) is ActionRole.RANGED_THROW
    assert BY_COMMAND[ord("t")] not in ActionGate(ACTIONS, PROFILE).allowed_actions


@pytest.mark.parametrize("command", [ord("t"), ord("e"), ord("y"), ord("l"), 27])
def test_forged_command_rejected_by_all_validation_surfaces(
    command, monkeypatch
) -> None:
    action = BY_COMMAND[command]
    selected = selection(action)
    valid_evidence = selected.intent.throw
    forged = replace(
        selected,
        intent=replace(
            selected.intent,
            throw=replace(valid_evidence, command=ord("z")),
        ),
    )
    monkeypatch.setattr(
        hazard, "expected_throw", lambda *args, **kwargs: valid_evidence
    )
    before = replace(
        observation(),
        prompt=PromptState(command != ord("t"), False, False),
    )
    memory = LevelMemory()
    with pytest.raises(ContractError):
        step(action, forged)
    assert survival_action_selection_error(action.name, forged) is not None
    with pytest.raises(ActionGateError):
        ActionGate(ACTIONS, PROFILE).resolve(
            action.index,
            selection=forged,
            before=before,
            memory=memory,
        )
    # Audit must reject corrupted persisted data independently of StepPayload.
    payload = SimpleNamespace(action=action, selection=forged)
    assert not evaluation._action_is_valid(
        payload,
        ACTIONS,
        before,
        True,
        PROFILE,
        dungeon_memory=SimpleNamespace(current=memory),
    )


def test_missing_or_wrong_skill_throw_evidence_is_rejected() -> None:
    action = BY_COMMAND[ord("t")]
    selected = selection(action)
    with pytest.raises(ContractError):
        replace(selected, intent=None)
    with pytest.raises(ContractError):
        replace(selected, skill=Skill.EXPLORE_LEVEL)
    with pytest.raises(ContractError):
        replace(selected, source=ActionSelectionSource.MODEL_FALLBACK)
    unpermitted = replace(selected, skill=Skill.EXPLORE_LEVEL, intent=None)
    assert survival_action_selection_error(action.name, unpermitted) is not None
    with pytest.raises(ContractError):
        step(action, unpermitted)
    with pytest.raises(ActionGateError):
        ActionGate(ACTIONS, PROFILE).resolve(action.index, selection=unpermitted)
    assert not evaluation._action_is_valid(
        SimpleNamespace(action=action, selection=unpermitted),
        ACTIONS,
        observation(),
        True,
        PROFILE,
    )


def test_old_intent_schema_remains_readable() -> None:
    intent = ActionIntent.from_json(
        {
            "destination": None,
            "attack_target": {"x": 1, "y": 0},
        }
    )
    assert intent.throw is None
    assert "throw" not in intent.to_json()


@pytest.mark.parametrize("direction", [(True, 0), (0, 0), (2, 0), (1,), [1, 0]])
def test_throw_direction_rejects_forged_shapes(direction) -> None:
    with pytest.raises(ContractError):
        ThrowEvidence("e", MapCell(3, 0), direction, ord("t"))


def test_throw_runtime_requires_matching_target_and_state(monkeypatch) -> None:
    action = BY_COMMAND[ord("t")]
    selected = selection(action)
    payload = step(action, selected)
    before = observation()
    memory = LevelMemory()
    monkeypatch.setattr(
        hazard,
        "expected_throw",
        lambda *args, **kwargs: replace(selected.intent.throw, target=MapCell(4, 0)),
    )
    with pytest.raises(ActionGateError):
        ActionGate(ACTIONS, PROFILE).resolve(
            action.index,
            selection=selected,
            before=before,
            memory=memory,
        )
    assert not evaluation._action_is_valid(
        payload,
        ACTIONS,
        before,
        True,
        PROFILE,
        dungeon_memory=SimpleNamespace(current=memory),
    )
    assert not evaluation._action_is_valid(payload, ACTIONS, None, True, PROFILE)
    with pytest.raises(ActionGateError):
        ActionGate(ACTIONS, PROFILE).resolve(action.index, selection=selected)


def test_throw_item_letter_can_collide_with_throw_command(monkeypatch) -> None:
    action = BY_COMMAND[ord("t")]
    selected = replace(
        selection(action, letter="t"),
        source=ActionSelectionSource.DETERMINISTIC_PROMPT,
    )
    monkeypatch.setattr(
        hazard, "expected_throw", lambda *args, **kwargs: selected.intent.throw
    )
    before = replace(observation(), prompt=PromptState(True, False, False))
    memory = LevelMemory()
    assert (
        ActionGate(ACTIONS, PROFILE).resolve(
            action.index,
            selection=selected,
            before=before,
            memory=memory,
        )
        == action
    )
    payload = step(action, selected)
    assert evaluation._action_is_valid(
        payload,
        ACTIONS,
        before,
        True,
        PROFILE,
        dungeon_memory=SimpleNamespace(current=memory),
    )
    assert (
        derive_action_record(selected, action.name, memory).throw
        == selected.intent.throw
    )


def test_throw_structural_gate_rejects_forged_action_name() -> None:
    action = BY_COMMAND[ord("t")]
    selected = selection(action)
    forged_action = replace(action, name="Command.EAT")
    with pytest.raises(ContractError):
        step(forged_action, selected)
