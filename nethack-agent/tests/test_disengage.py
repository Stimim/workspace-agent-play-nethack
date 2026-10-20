"""Pure policy/recording tests; native transport has separate coverage."""

from dataclasses import fields, replace

import pytest
from nle import nethack

from nethack_agent.contracts import ContractError
from nethack_agent.decision import (
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DisengageEvidence,
    Skill,
    SkillSelectionSource,
    disengage_action_error,
    survival_action_selection_error,
)
from nethack_agent.disengage import DisengageRecovery
from nethack_agent.environment import LegalAction
from nethack_agent.navigation import LevelMemory
from nethack_agent.observation import (
    CellDescription,
    MapView,
    PlayerStats,
    ProjectedObservation,
    PromptState,
)
from nethack_agent.tasks import ActionProfile
from nethack_agent.traversal import STAND_ON_DOWNSTAIRS

READY = PromptState(False, False, False)
CHOICE = PromptState(True, False, False)
TEXT = PromptState(False, True, False)
MORE = PromptState(False, False, True)
TEXT_MORE = PromptState(False, True, True)
TEXT_PROMPT = "What do you want to write in the dust here? "
ACTIONS = {
    int(value): LegalAction(index, int(value), f"{type(value).__name__}.{value.name}")
    for index, value in enumerate(ActionProfile.NLE_SURVIVAL_ACTIONS.actions)
}


def observation(
    *,
    species="jackal",
    hp=3,
    maximum=12,
    hunger=0,
    step=0,
    turn=100,
    conditions=(),
    terrain=19,
):
    values = {field.name: 0 for field in fields(PlayerStats)}
    values.update(
        x=2,
        y=2,
        hit_points=hp,
        max_hit_points=maximum,
        hunger=hunger,
        dungeon_level=1,
        depth=1,
        turn=turn,
        conditions=conditions,
    )
    player = PlayerStats(**values)
    glyphs = [[nethack.GLYPH_CMAP_OFF + terrain for _ in range(5)] for _ in range(5)]
    monster = next(
        index
        for index in range(nethack.NUMMONS)
        if nethack.permonst(index).mname == species
    )
    glyphs[2][3] = nethack.GLYPH_MON_OFF + monster
    view = MapView(
        (".....", ".....", "..@d.", ".....", "....."),
        tuple(tuple(row) for row in glyphs),
        (bytes(5),) * 5,
        (bytes(5),) * 5,
        (bytes(5),) * 5,
    )
    before = ProjectedObservation(
        step,
        view,
        (),
        player,
        "",
        READY,
        (),
        cell_descriptions=(CellDescription(3, 2, species),),
    )
    memory = LevelMemory()
    memory.observe(before)
    return before, memory


def selection(evidence, *, source=None, skill=Skill.DISENGAGE):
    if source is None:
        source = (
            ActionSelectionSource.DETERMINISTIC_SKILL
            if evidence.phase in {"engrave", "look", "wait"}
            else ActionSelectionSource.DETERMINISTIC_PROMPT
        )
    action = ACTIONS[evidence.command]
    return ActionSelection(
        source,
        STAND_ON_DOWNSTAIRS,
        skill,
        SkillSelectionSource.ARBITER,
        None,
        action.index,
        "Combat recovery.",
        ActionIntent(None, None, None, disengage=evidence),
    )


def advance(
    recovery,
    before,
    memory,
    message="",
    prompt=READY,
    *,
    turn=None,
    hp=None,
    hunger=None,
    observe=True,
):
    evidence = recovery.expected(before)
    assert evidence is not None
    player = replace(
        before.player,
        turn=before.player.turn if turn is None else turn,
        hit_points=before.player.hit_points if hp is None else hp,
        hunger=before.player.hunger if hunger is None else hunger,
    )
    after = replace(
        before,
        step_index=before.step_index + 1,
        player=player,
        message=message,
        prompt=prompt,
    )
    recovery.advance(evidence, after)
    if observe:
        recovery.observe(after, memory)
    return after


def engrave(recovery, before, memory, *, overwrite=False):
    assert recovery.expected(before).phase == "engrave"
    before = advance(
        recovery, before, memory, "What do you want to write with? [- a or ?*]", CHOICE
    )
    assert recovery.expected(before).command == ord("-")
    if overwrite:
        before = advance(
            recovery,
            before,
            memory,
            "Do you want to add to the current engraving? [ynq] (y) ",
            CHOICE,
        )
        assert recovery.expected(before).command == ord("n")
        before = advance(
            recovery,
            before,
            memory,
            "You wipe out the message that was written in the dust here.",
            MORE,
        )
    before = advance(
        recovery,
        before,
        memory,
        "You write in the dust with your fingertip.",
        TEXT_MORE,
    )
    assert recovery.expected(before).phase == "more"
    before = advance(recovery, before, memory, TEXT_PROMPT, TEXT)
    for index, letter in enumerate("Elbereth"):
        evidence = recovery.expected(before)
        assert evidence.phase == "text" and evidence.command == ord(letter)
        assert evidence.text_index == index
        before = advance(
            recovery, before, memory, TEXT_PROMPT + "Elbereth"[: index + 1], TEXT
        )
    assert recovery.expected(before).phase == "submit"
    before = advance(recovery, before, memory, turn=before.player.turn + 1)
    assert recovery.expected(before).phase == "look"
    assert not recovery.protected(before)
    return before


def readback(recovery, before, memory, text="Elbereth", pages=0):
    if pages:
        before = advance(
            recovery, before, memory, "Something is written here in the dust.", MORE
        )
        for _ in range(pages - 1):
            before = advance(
                recovery, before, memory, "There is a staircase up here.", MORE
            )
        return advance(recovery, before, memory, f'You read: "{text}".')
    return advance(recovery, before, memory, f'You read: "{text}".')


def protected_recovery():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    before = engrave(recovery, before, memory)
    before = readback(recovery, before, memory)
    assert recovery.protected(before)
    return recovery, before, memory


def test_expected_and_select_are_pure_until_recorded():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    expected = recovery.expected(before)
    for _ in range(3):
        recovery.observe(before, memory)
        assert recovery.expected(before) == expected
        assert recovery.select_action(before, ACTIONS).intent.disengage == expected
    assert expected.retries == 0 and expected.prompt_actions == 0
    assert not recovery.protected(before)


def test_complete_transaction_requires_look_and_handles_multiple_more():
    before, memory = observation(terrain=23)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    before = engrave(recovery, before, memory)
    before = readback(recovery, before, memory, pages=3)
    assert recovery.protected(before)
    assert recovery.expected(before).phase == "wait"
    before = advance(recovery, before, memory, turn=before.player.turn + 1)
    assert not recovery.protected(before)
    assert recovery.expected(before).phase == "look"


@pytest.mark.parametrize(
    "species", ["wolf", "imp", "cave spider", "rothe", "giant bat", "pony", "goblin"]
)
def test_reviewed_named_combat_threats_are_supported(species):
    before, memory = observation(species=species)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before).phase == "engrave"


def test_repair_overwrites_and_retry_budget_cannot_rearm_same_encounter():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    for attempt in range(3):
        before = engrave(recovery, before, memory, overwrite=attempt > 0)
        before = readback(recovery, before, memory, "ElbOreth", pages=2)
        assert not recovery.protected(before)
        if attempt < 2:
            assert recovery.expected(before).retries == attempt + 1
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "native_retry_budget"
    memory.rearm()
    memory.rearm_for_branch()
    recovery.observe(replace(before, step_index=before.step_index + 1), memory)
    assert recovery.expected(before) is None


def test_prayer_priority_blocks_critical_recovery_when_available():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory, prayer_available=True)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "prayer_available"
    after = replace(
        before, step_index=1, player=replace(before.player, hit_points=12, turn=103)
    )
    recovery.observe(after, memory, prayer_available=True)
    assert recovery.expected(after) is None


def test_hungry_keeps_protection_but_stops_wait_and_repair():
    recovery, before, memory = protected_recovery()
    hungry = replace(
        before,
        step_index=before.step_index + 1,
        player=replace(before.player, hunger=2),
    )
    recovery.observe(hungry, memory)
    assert recovery.expected(hungry) is None
    assert recovery.protected(hungry)
    assert recovery.no_melee(hungry)
    recovery.advance(None, replace(hungry, step_index=hungry.step_index + 1))
    assert not recovery.protected(hungry)


@pytest.mark.parametrize(
    "conditions",
    [("blind",), ("confused",), ("stunned",), ("hallucinating",), ("levitating",)],
)
def test_condition_exclusions(conditions):
    before, memory = observation(conditions=conditions)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "excluded_condition"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("hit_dice", 2, "unsupported_polymorph"),
        ("encumbrance", 4, "cannot_engrave_while_overtaxed"),
        ("dungeon_number", 1, "unsupported_branch"),
    ],
)
def test_public_body_capacity_and_branch_exclusions(field, value, reason):
    before, memory = observation()
    before = replace(before, player=replace(before.player, **{field: value}))
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == reason


@pytest.mark.parametrize("terrain", [0, 25, 27, 28, 29, 31, 32, 33])
def test_terrain_exclusions(terrain):
    before, memory = observation(terrain=terrain)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "unsafe_or_unknown_terrain"


@pytest.mark.parametrize("species", ["minotaur", "human", "aligned priest"])
def test_source_immune_species_exclusions(species):
    before, memory = observation(species=species)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "elbereth_immune_monster"


@pytest.mark.parametrize("species", ["floating eye", "gas spore"])
def test_passive_species_alone_never_trigger_recovery(species):
    before, memory = observation(species=species)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason != "elbereth_immune_monster"


@pytest.mark.parametrize(
    "location", ["a shop", "a temple", "an altar", "a fountain", "a grave"]
)
def test_public_location_descriptions_exclude_engraving(location):
    before, memory = observation()
    before = replace(
        before,
        cell_descriptions=before.cell_descriptions + (CellDescription(2, 2, location),),
    )
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None


def test_shop_memory_and_missing_public_threat_description_exclude():
    before, memory = observation()
    memory.shop_cells.add((2, 2))
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.fallback_reason == "shop_or_temple"
    memory.shop_cells.clear()
    before = replace(before, step_index=1, cell_descriptions=None)
    recovery.observe(before, memory)
    assert recovery.fallback_reason == "unknown_public_monster"


def test_ranged_damage_and_failed_protection_persist_until_threat_gone():
    recovery, before, memory = protected_recovery()
    before = advance(
        recovery,
        before,
        memory,
        "An arrow hits you!",
        turn=before.player.turn + 1,
        hp=2,
    )
    assert not recovery.protected(before)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason in {"ranged_damage", "damage_under_protection"}
    before = replace(before, step_index=before.step_index + 1, message="")
    recovery.observe(before, memory)
    assert recovery.expected(before) is None


def test_hungry_corrupted_readback_does_not_start_repair():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    before = engrave(recovery, before, memory)
    before = replace(before, player=replace(before.player, hunger=2))
    before = readback(recovery, before, memory, "ElbOreth")
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "hungry"


def test_recovery_budget_and_no_heal_periods():
    recovery, before, memory = protected_recovery()
    before = replace(
        before,
        step_index=before.step_index + 1,
        player=replace(before.player, turn=before.player.turn + 201),
    )
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "recovery_turn_budget"
    recovery, before, memory = protected_recovery()
    for _ in range(2):
        before = replace(
            before,
            step_index=before.step_index + 1,
            player=replace(before.player, turn=before.player.turn + 20),
        )
        recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "no_healing"


def test_evidence_json_strictness_and_exclusive_intent():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    evidence = recovery.expected(before)
    intent = ActionIntent(None, None, None, disengage=evidence)
    assert ActionIntent.from_json(intent.to_json()) == intent
    with pytest.raises(ContractError):
        DisengageEvidence.from_json({**evidence.to_json(), "extra": True})
    for key, value in [
        ("command", True),
        ("retries", 3),
        ("prompt_actions", 25),
        ("recovery_turns", 201),
    ]:
        with pytest.raises(ContractError):
            DisengageEvidence.from_json({**evidence.to_json(), key: value})


def test_shared_guard_rejects_forged_byte_stale_evidence_and_unowned_prompts():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    evidence = recovery.expected(before)
    selected = selection(evidence)
    action = ACTIONS[evidence.command]
    assert disengage_action_error(action, selected, before, recovery) is None
    assert disengage_action_error(action, selected, structural_only=True) is None
    assert disengage_action_error(
        replace(action, command=ord("e")), selected, structural_only=True
    )
    assert disengage_action_error(
        action, selected, replace(before, step_index=1), recovery
    )
    assert survival_action_selection_error(
        action.name,
        replace(selected, source=ActionSelectionSource.MODEL_FALLBACK, intent=None),
    )
    before = advance(
        recovery, before, memory, "What do you want to write with? [- a or ?*]", CHOICE
    )
    unowned = replace(selected, skill=Skill.EXPLORE_LEVEL, intent=None)
    assert disengage_action_error(ACTIONS[ord("n")], unowned, before, recovery)


def test_text_eat_and_movement_collisions_require_exact_owned_evidence():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    before = advance(
        recovery, before, memory, "What do you want to write with? [- a or ?*]", CHOICE
    )
    before = advance(
        recovery,
        before,
        memory,
        "You write in the dust with your fingertip.",
        TEXT_MORE,
    )
    before = advance(recovery, before, memory, TEXT_PROMPT, TEXT)
    for index in range(8):
        evidence = recovery.expected(before)
        selected = selection(evidence)
        action = ACTIONS[evidence.command]
        assert survival_action_selection_error(action.name, selected) is None
        assert disengage_action_error(action, selected, before, recovery) is None
        assert disengage_action_error(
            action,
            replace(
                selected,
                skill=Skill.HUNGER,
                source=ActionSelectionSource.DETERMINISTIC_SKILL,
            ),
            before,
            recovery,
        )
        before = advance(
            recovery, before, memory, TEXT_PROMPT + "Elbereth"[: index + 1], TEXT
        )


def test_protected_guard_rejects_actual_bump_even_without_attack_intent():
    recovery, before, memory = protected_recovery()
    evidence = recovery.expected(before)
    unowned = replace(selection(evidence), skill=Skill.EXPLORE_LEVEL, intent=None)
    assert disengage_action_error(ACTIONS[ord("l")], unowned, before, recovery)
    assert disengage_action_error(ACTIONS[ord("h")], unowned, before, recovery) is None
    assert disengage_action_error(ACTIONS[ord(".")], unowned, before, recovery) is None


def test_prompt_cap_stops_repeated_more_without_reset():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    before = advance(
        recovery, before, memory, "What do you want to write with? [- a or ?*]", CHOICE
    )
    before = advance(recovery, before, memory, "You write in the dust.", MORE)
    for _ in range(23):
        if recovery.expected(before) is None:
            break
        before = advance(recovery, before, memory, "More information.", MORE)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == "prompt_action_budget"


def test_existing_hunger_inventory_letter_e_is_not_an_engraving_open():
    before, memory = observation()
    recovery = DisengageRecovery()
    before = replace(
        before, prompt=CHOICE, message="What do you want to eat? [E or ?*]"
    )
    selected = ActionSelection(
        ActionSelectionSource.DETERMINISTIC_PROMPT,
        STAND_ON_DOWNSTAIRS,
        Skill.HUNGER,
        SkillSelectionSource.ARBITER,
        None,
        ACTIONS[ord("E")].index,
        "Select the observed inventory food.",
        None,
    )
    assert survival_action_selection_error("Command.ENGRAVE", selected) is None
    assert (
        disengage_action_error(ACTIONS[ord("E")], selected, structural_only=True)
        is None
    )
    assert disengage_action_error(ACTIONS[ord("E")], selected, before, recovery) is None
    assert disengage_action_error(
        ACTIONS[ord("E")], selected, replace(before, prompt=READY), recovery
    )


def test_healthy_scene_does_not_claim_recovery_fallback():
    before, memory = observation(species="human", hp=12)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason is None


def test_distant_visible_melee_threat_can_trigger_combat_recovery():
    before, memory = observation()
    monster = memory.monsters.pop((3, 2))
    memory.monsters[(4, 4)] = monster
    before = replace(before, cell_descriptions=(CellDescription(4, 4, "jackal"),))
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before).phase == "engrave"


def test_target_hp_stops_wait_but_keeps_verified_no_melee_latch():
    recovery, before, memory = protected_recovery()
    recovered = replace(
        before,
        step_index=before.step_index + 1,
        player=replace(before.player, hit_points=9),
    )
    recovery.observe(recovered, memory)
    assert recovery.expected(recovered) is None
    assert recovery.protected(recovered)
    assert recovery.blocks_attack(ord("l"), recovered)
    assert recovery.fallback_reason == "recovered_hp"


def test_combat_recovery_continues_after_attackers_disappear_during_wait():
    recovery, before, memory = protected_recovery()
    memory.monsters.clear()
    before = advance(recovery, before, memory, turn=before.player.turn + 1)
    assert recovery.expected(before).phase == "look"
    before = readback(recovery, before, memory, pages=2)
    assert recovery.protected(before)
    assert recovery.expected(before).phase == "wait"
    assert recovery.fallback_reason is None


def test_complete_readback_when_attackers_flee_on_engraving_submission():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    before = engrave(recovery, before, memory)
    memory.monsters.clear()
    before = replace(before, step_index=before.step_index + 1)
    recovery.observe(before, memory)
    assert recovery.expected(before).phase == "look"
    before = readback(recovery, before, memory)
    assert recovery.expected(before).phase == "wait"


def test_quiet_wounds_without_prior_combat_never_start_rest():
    before, memory = observation()
    memory.monsters.clear()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert not recovery.protected(before)


def test_established_recovery_repairs_after_attackers_disappear_without_rearming():
    recovery, before, memory = protected_recovery()
    memory.monsters.clear()
    before = advance(recovery, before, memory, turn=before.player.turn + 1)
    before = readback(recovery, before, memory, "ElbOreth", pages=2)
    assert recovery.expected(before).phase == "engrave"
    assert recovery.expected(before).retries == 1
    before = engrave(recovery, before, memory, overwrite=True)
    before = readback(recovery, before, memory)
    assert recovery.expected(before).phase == "wait"
    # A successful repair resets the consecutive-failure budget.
    assert recovery.expected(before).retries == 0


def test_long_rest_survives_more_erosion_repairs_than_the_failure_budget():
    recovery, before, memory = protected_recovery()
    memory.monsters.clear()
    for _ in range(4):
        before = advance(recovery, before, memory, turn=before.player.turn + 1)
        before = readback(recovery, before, memory, "ElbOreth", pages=2)
        assert recovery.expected(before).phase == "engrave"
        before = engrave(recovery, before, memory, overwrite=True)
        before = readback(recovery, before, memory)
        assert recovery.expected(before).phase == "wait"
    assert recovery.fallback_reason is None


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("hunger", 2, "hungry"),
        ("turn", 400, "recovery_turn_budget"),
        ("conditions", ("blind",), "excluded_condition"),
    ],
)
def test_no_visible_threat_does_not_disable_recovery_exit_guards(field, value, reason):
    recovery, before, memory = protected_recovery()
    memory.monsters.clear()
    before = replace(
        before,
        step_index=before.step_index + 1,
        player=replace(before.player, **{field: value}),
    )
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert recovery.fallback_reason == reason


@pytest.mark.parametrize(("level", "period"), [(3, 9), (4, 8), (5, 7)])
def test_normal_regeneration_never_trips_no_heal_limit_while_recovering_alone(
    level, period
):
    recovery, before, memory = protected_recovery()
    memory.monsters.clear()
    start = before.player.turn
    for elapsed in range(1, 70):
        hp = min(9, 3 + elapsed // period)
        before = replace(before, player=replace(before.player, experience_level=level))
        before = advance(recovery, before, memory, turn=start + elapsed, hp=hp)
        before = readback(recovery, before, memory)
        assert recovery._no_heal == 0
        if recovery.expected(before) is None:
            break
        assert recovery.expected(before).phase == "wait"
    assert before.player.hit_points == 9
    assert recovery.fallback_reason == "recovered_hp"


def test_publicly_peaceful_creatures_neither_trigger_nor_interrupt_recovery():
    before, memory = observation()
    peaceful = replace(
        before, cell_descriptions=(CellDescription(3, 2, "peaceful jackal"),)
    )
    quiet = DisengageRecovery()
    quiet.observe(peaceful, memory)
    assert quiet.expected(peaceful) is None
    recovery, before, memory = protected_recovery()
    before = replace(
        before,
        step_index=before.step_index + 1,
        cell_descriptions=(CellDescription(3, 2, "peaceful jackal"),),
    )
    recovery.observe(before, memory)
    assert recovery.expected(before).phase == "wait"
