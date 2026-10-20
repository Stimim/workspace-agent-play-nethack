"""Elbereth classification uses public glyphs, not a positive species allowlist."""

from dataclasses import fields, replace

import pytest
from nle import nethack

from nethack_agent.disengage import (
    DisengageRecovery,
    elbereth_monster_error,
    passive_resting_monster,
)
from nethack_agent.navigation import LevelMemory, Monster
from nethack_agent.observation import (
    CellDescription,
    MapView,
    PlayerStats,
    ProjectedObservation,
    PromptState,
)

READY = PromptState(False, False, False)
CHOICE = PromptState(True, False, False)
TEXT = PromptState(False, True, False)
TEXT_PROMPT = "What do you want to write in the dust here? "
PASSIVE_SPECIES = (
    "gas spore",
    "floating eye",
    "brown mold",
    "yellow mold",
    "green mold",
    "red mold",
    "acid blob",
    "blue jelly",
    "spotted jelly",
    "shrieker",
)


def public_monster(species, *, human_form=False, pet=False):
    human_class = next(
        nethack.permonst(index).mlet
        for index in range(nethack.NUMMONS)
        if nethack.permonst(index).mname == "human"
    )
    index = next(
        index
        for index in range(nethack.NUMMONS)
        if nethack.permonst(index).mname == species
        and (not human_form or nethack.permonst(index).mlet == human_class)
    )
    glyph = (nethack.GLYPH_PET_OFF if pet else nethack.GLYPH_MON_OFF) + index
    public_species = nethack.permonst(nethack.glyph_to_mon(glyph))
    return Monster(glyph, public_species.mname, bool(nethack.glyph_is_pet(glyph)))


def observation(species="goblin", *, description=None, pet=False, step=0):
    values = {field.name: 0 for field in fields(PlayerStats)}
    values.update(
        x=2,
        y=2,
        hit_points=3,
        max_hit_points=12,
        dungeon_level=1,
        depth=1,
        turn=100,
        conditions=(),
    )
    monster = public_monster(species, pet=pet)
    glyphs = [[nethack.GLYPH_CMAP_OFF + 19 for _ in range(5)] for _ in range(5)]
    glyphs[2][3] = monster.glyph
    view = MapView(
        (".....", ".....", "..@..", ".....", "....."),
        tuple(tuple(row) for row in glyphs),
        (bytes(5),) * 5,
        (bytes(5),) * 5,
        (bytes(5),) * 5,
    )
    before = ProjectedObservation(
        step,
        view,
        (),
        PlayerStats(**values),
        "",
        READY,
        (),
        cell_descriptions=(
            CellDescription(3, 2, species if description is None else description),
        ),
    )
    memory = LevelMemory()
    memory.observe(before)
    return before, memory


def advance(recovery, before, memory, message="", prompt=READY, *, elapsed=0):
    evidence = recovery.expected(before)
    assert evidence is not None
    after = replace(
        before,
        step_index=before.step_index + 1,
        message=message,
        prompt=prompt,
        player=replace(before.player, turn=before.player.turn + elapsed),
    )
    recovery.advance(evidence, after)
    recovery.observe(after, memory)
    return after


def established_recovery():
    before, memory = observation()
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before).phase == "engrave"
    before = advance(
        recovery, before, memory, "What do you want to write with? [- a or ?*]", CHOICE
    )
    before = advance(recovery, before, memory, TEXT_PROMPT, TEXT)
    for index, letter in enumerate("Elbereth"):
        assert recovery.expected(before).command == ord(letter)
        before = advance(
            recovery, before, memory, TEXT_PROMPT + "Elbereth"[: index + 1], TEXT
        )
    before = advance(recovery, before, memory, elapsed=1)
    assert recovery.expected(before).phase == "look"
    before = advance(recovery, before, memory, 'You read: "Elbereth".')
    assert recovery.protected(before)
    assert recovery.expected(before).phase == "wait"
    return recovery, before, memory


@pytest.mark.parametrize("species", ["pony", "goblin", "cobra", "winter wolf"])
def test_ordinary_sighted_species_are_eligible_without_observed_ranged_attack(species):
    assert elbereth_monster_error(public_monster(species), species) is None
    before, memory = observation(species)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before).phase == "engrave"


@pytest.mark.parametrize(
    "species",
    [
        "human",
        "elf",
        "Woodland-elf",
        "Green-elf",
        "Grey-elf",
        "elf-lord",
        "Elvenking",
        "wererat",
        "werejackal",
        "werewolf",
    ],
)
def test_public_human_class_including_human_form_weres_is_immune(species):
    monster = public_monster(species, human_form=True)
    assert elbereth_monster_error(monster, species) == "elbereth_immune_monster"


@pytest.mark.parametrize(
    "species",
    [
        "minotaur",
        "shopkeeper",
        "guard",
        "aligned priest",
        "high priest",
        "Wizard of Yendor",
        "Angel",
        "couatl",
        "Aleax",
        "ki-rin",
        "Archon",
        "Death",
        "Pestilence",
        "Famine",
    ],
)
def test_source_defined_immune_species_are_rejected(species):
    assert (
        elbereth_monster_error(public_monster(species), species)
        == "elbereth_immune_monster"
    )


def test_public_glyph_not_cached_name_determines_species_immunity():
    human = replace(public_monster("human"), name="pony")
    goblin = replace(public_monster("goblin"), name="unreviewed species")
    assert elbereth_monster_error(human, "human") == "elbereth_immune_monster"
    assert elbereth_monster_error(goblin, "goblin") is None


@pytest.mark.parametrize("description", ["blind goblin", "a blind goblin"])
def test_public_blind_description_rejects_an_otherwise_eligible_monster(description):
    assert (
        elbereth_monster_error(public_monster("goblin"), description)
        == "publicly_blind_monster"
    )


@pytest.mark.parametrize(
    "glyph", [-1, 10**9, nethack.GLYPH_CMAP_OFF + 19, nethack.GLYPH_OBJ_OFF]
)
def test_unknown_or_nonmonster_glyph_is_not_elbereth_evidence(glyph):
    monster = Monster(glyph, "goblin", False)
    assert elbereth_monster_error(monster, "goblin") == "unknown_public_monster"
    assert not passive_resting_monster(monster)


@pytest.mark.parametrize("description", ["", "   "])
def test_missing_public_description_is_not_elbereth_evidence(description):
    assert (
        elbereth_monster_error(public_monster("goblin"), description)
        == "unknown_public_monster"
    )


@pytest.mark.parametrize("species", ["goblin", "shopkeeper", "minotaur"])
def test_publicly_peaceful_monster_does_not_fail_the_source_predicate(species):
    assert (
        elbereth_monster_error(public_monster(species), f"peaceful {species}") is None
    )


@pytest.mark.parametrize(
    "description,pet,remembered_peaceful",
    [
        ("peaceful goblin", False, False),
        ("tame goblin", False, False),
        ("goblin", True, False),
        ("goblin", False, True),
    ],
)
def test_harmless_public_monsters_neither_trigger_nor_interrupt_recovery(
    description, pet, remembered_peaceful
):
    before, memory = observation(description=description, pet=pet)
    if remembered_peaceful:
        memory.peaceful_glyphs.add(memory.monsters[(3, 2)].glyph)
    quiet = DisengageRecovery()
    quiet.observe(before, memory)
    assert quiet.expected(before) is None

    recovery, established, _ = established_recovery()
    before = replace(
        before,
        step_index=established.step_index + 1,
        player=established.player,
    )
    recovery.observe(before, memory)
    assert recovery.protected(before)
    assert recovery.expected(before).phase == "wait"


@pytest.mark.parametrize("species", PASSIVE_SPECIES)
def test_source_passive_species_are_safe_to_rest_near(species):
    monster = public_monster(species)
    assert passive_resting_monster(monster)
    assert elbereth_monster_error(monster, species) is None


@pytest.mark.parametrize("species", ["pony", "goblin", "cobra", "winter wolf"])
def test_active_species_are_not_classified_as_passive(species):
    assert not passive_resting_monster(public_monster(species))


@pytest.mark.parametrize("species", PASSIVE_SPECIES)
def test_passive_monster_alone_does_not_trigger_combat_recovery(species):
    before, memory = observation(species)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before) is None
    assert not recovery.protected(before)


@pytest.mark.parametrize("species", PASSIVE_SPECIES)
@pytest.mark.parametrize("ordinary_threat_remains", [False, True])
def test_passive_monster_does_not_interrupt_established_recovery(
    species, ordinary_threat_remains
):
    recovery, established, _ = established_recovery()
    before, memory = observation(species, step=established.step_index + 1)
    before = replace(before, player=established.player)
    if ordinary_threat_remains:
        memory.monsters[(1, 2)] = public_monster("goblin")
        before = replace(
            before,
            cell_descriptions=before.cell_descriptions
            + (CellDescription(1, 2, "goblin"),),
        )
    recovery.observe(before, memory)
    assert recovery.protected(before)
    assert recovery.expected(before).phase == "wait"
    assert recovery.fallback_reason is None


@pytest.mark.parametrize(
    "species,attack", [("cobra", "spits"), ("winter wolf", "breathes")]
)
def test_observed_ranged_damage_still_rejects_innately_ranged_species(species, attack):
    before, memory = observation(species)
    recovery = DisengageRecovery()
    recovery.observe(before, memory)
    assert recovery.expected(before).phase == "engrave"
    damaged = replace(
        before,
        step_index=before.step_index + 1,
        player=replace(before.player, hit_points=2, turn=before.player.turn + 1),
        message=f"The {species} {attack}!",
    )
    recovery.observe(damaged, memory)
    assert recovery.expected(damaged) is None
    assert recovery.fallback_reason == "ranged_damage"
