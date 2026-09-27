import json
from dataclasses import replace
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent.contracts import ContractError
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.observation import (
    BucStatus,
    ObservationProjector,
    ProjectedObservation,
    _buc_status,
)


def test_projection_copies_compact_public_state(tmp_path: Path) -> None:
    projector = ObservationProjector()
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        raw = environment.reset()
        projected = projector.project(raw, step_index=environment.step_index)

        assert projected.map.rows[projected.player.y][projected.player.x] == "@"
        assert projected.player.hit_points > 0
        assert projected.player.max_hit_points >= projected.player.hit_points
        assert not projected.prompt.active
        assert projected.inventory
        assert all(len(item.letter) == 1 for item in projected.inventory)
        assert all("\0" not in item.description for item in projected.inventory)
        assert projected.changed_cells == ()
        json.dumps(projected.to_json())
        serialized = projected.to_json()
        assert "single_character_choice" in serialized["prompt"]
        assert "yes_no" not in serialized["prompt"]
        assert serialized["map"]["glyph_rows"]
        assert ProjectedObservation.from_json(serialized) == projected
        assert [item.buc for item in projected.inventory] == [
            BucStatus.UNKNOWN,
            BucStatus.UNKNOWN,
            BucStatus.UNCURSED,
            BucStatus.UNCURSED,
        ]
        assert [item["buc"] for item in serialized["inventory"]] == [
            "unknown",
            "unknown",
            "uncursed",
            "uncursed",
        ]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("a blessed potion of healing", BucStatus.BLESSED),
        ("an uncursed food ration", BucStatus.UNCURSED),
        ("2 cursed darts", BucStatus.CURSED),
        ("a +1 long sword", BucStatus.UNKNOWN),
        ("a scroll labeled CURSED", BucStatus.UNKNOWN),
        ("a wand called cursed hope", BucStatus.UNKNOWN),
        ("a cursed-looking potion", BucStatus.UNKNOWN),
    ],
)
def test_buc_uses_only_an_exact_leading_inventory_adjective(
    description: str, expected: BucStatus
) -> None:
    assert _buc_status(description) is expected


def test_nle_map_glyph_is_one_display_category_not_layered_terrain(
    tmp_path: Path,
) -> None:
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        raw = environment.reset()
        object_glyph = next(
            int(glyph)
            for letter, glyph in zip(raw.inv_letters, raw.inv_glyphs, strict=True)
            if int(letter)
        )

    downstairs_glyph = nethack.GLYPH_CMAP_OFF + 24
    assert nethack.glyph_is_cmap(downstairs_glyph)
    assert not nethack.glyph_is_object(downstairs_glyph)
    assert nethack.glyph_is_object(object_glyph)
    assert not nethack.glyph_is_cmap(object_glyph)
    # Each observed cell is one scalar glyph category. NLE has no public
    # parallel terrain layer from which a stair under the object can be read.
    assert raw.glyphs.shape == raw.chars.shape == (21, 79)


def test_projection_survives_next_nle_step_and_reports_map_delta(
    tmp_path: Path,
) -> None:
    projector = ObservationProjector()
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        initial = projector.project(environment.reset(), step_index=0)
        old_x = initial.player.x
        old_y = initial.player.y

        transition = environment.step(2)  # CompassDirection.E
        current = projector.project(
            transition.observation, step_index=transition.step_index
        )

        assert (current.player.x, current.player.y) == (old_x + 1, old_y)
        assert initial.map.rows[old_y][old_x] == "@"
        assert current.map.rows[old_y][old_x] != "@"
        changed_positions = {(cell.x, cell.y) for cell in current.changed_cells}
        assert {(old_x, old_y), (old_x + 1, old_y)} <= changed_positions


def test_projection_reports_a_glyph_only_change(tmp_path: Path) -> None:
    projector = ObservationProjector()
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        raw = environment.reset()
        initial = projector.project(raw, step_index=0)
        glyphs = raw.glyphs.copy()
        glyphs[0, 0] = int(glyphs[0, 0]) + 1

        current = projector.project(replace(raw, glyphs=glyphs), step_index=1)

    assert initial.map.rows == current.map.rows
    assert initial.map.color_rows == current.map.color_rows
    assert initial.map.special_rows == current.map.special_rows
    assert current.map.glyph_rows[0][0] == int(glyphs[0, 0])
    assert len(current.changed_cells) == 1
    change = current.changed_cells[0]
    assert (change.x, change.y) == (0, 0)
    assert change.glyph == int(glyphs[0, 0])
    assert current.to_json()["changed_cells"][0]["glyph"] == int(glyphs[0, 0])


def test_projection_exposes_pet_evidence_and_uses_stable_display_glyphs(
    tmp_path: Path,
) -> None:
    projector = ObservationProjector()
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        raw = environment.reset()
        characters = raw.chars.copy()
        glyphs = raw.glyphs.copy()
        boulder = next(
            index
            for index in range(nethack.NUM_OBJECTS)
            if nethack.objdescr.from_idx(index).oc_name == "boulder"
        )
        monsters = {
            nethack.permonst(index).mname: index for index in range(nethack.NUMMONS)
        }
        cells = {
            0: nethack.GLYPH_OBJ_OFF + boulder,
            1: nethack.GLYPH_MON_OFF + monsters["ghost"],
            2: nethack.GLYPH_MON_OFF + monsters["shade"],
            3: nethack.GLYPH_PET_OFF + monsters["jackal"],
            4: nethack.GLYPH_MON_OFF + monsters["jackal"],
        }
        for x, glyph in cells.items():
            characters[0, x] = ord("?")
            glyphs[0, x] = glyph

        # Even a ghost-class glyph cannot replace the player display.
        player_x = int(raw.blstats[nethack.NLE_BL_X])
        player_y = int(raw.blstats[nethack.NLE_BL_Y])
        glyphs[player_y, player_x] = nethack.GLYPH_MON_OFF + monsters["ghost"]
        characters[player_y, player_x] = ord("@")
        projected = projector.project(
            replace(raw, chars=characters, glyphs=glyphs), step_index=0
        )

    assert projected.map.rows[0][:5] == "0XX??"
    assert projected.map.rows[player_y][player_x] == "@"
    assert projected.map.glyph_rows[0][:5] == tuple(cells.values())
    assert projected.map.color_rows == tuple(bytes(row) for row in raw.colors)
    assert projected.map.pet_rows[0][:5] == b"\x00\x00\x00\x01\x00"
    assert projected.map.pet_rows[player_y][player_x] == 0
    serialized = projected.to_json()
    assert serialized["map"]["pet_rows"][0][:10] == "0000000100"
    assert ProjectedObservation.from_json(serialized) == projected


def test_map_delta_reports_pet_identity_change(tmp_path: Path) -> None:
    projector = ObservationProjector()
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        raw = environment.reset()
        monsters = {
            nethack.permonst(index).mname: index for index in range(nethack.NUMMONS)
        }
        glyphs = raw.glyphs.copy()
        glyphs[0, 0] = nethack.GLYPH_MON_OFF + monsters["jackal"]
        projector.project(replace(raw, glyphs=glyphs), step_index=0)
        glyphs[0, 0] = nethack.GLYPH_PET_OFF + monsters["jackal"]
        current = projector.project(replace(raw, glyphs=glyphs), step_index=1)

    assert len(current.changed_cells) == 1
    assert current.changed_cells[0].pet is True
    assert current.to_json()["changed_cells"][0]["pet"] is True


def test_observation_contract_rejects_inconsistent_map_shapes(tmp_path: Path) -> None:
    projector = ObservationProjector()
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        projected = projector.project(environment.reset(), step_index=0)
    serialized = projected.to_json()
    serialized["map"]["glyph_rows"][0].pop()

    with pytest.raises(ContractError, match="shape does not match"):
        ProjectedObservation.from_json(serialized)


def _stepped_observation(tmp_path: Path) -> ProjectedObservation:
    projector = ObservationProjector()
    with NleEnvironment(
        ScenarioConfig(seed=6, artifact_directory=tmp_path, max_episode_steps=20)
    ) as environment:
        projector.project(environment.reset(), step_index=0)
        transition = environment.step(2)  # CompassDirection.E
        return projector.project(
            transition.observation, step_index=transition.step_index
        )


def test_observation_stored_before_pet_evidence_reads_as_unknown(
    tmp_path: Path,
) -> None:
    current = _stepped_observation(tmp_path)
    legacy = current.to_json()
    del legacy["map"]["pet_rows"]
    for cell in legacy["changed_cells"]:
        del cell["pet"]
    assert legacy["changed_cells"]

    restored = ProjectedObservation.from_json(legacy)

    # Unknown is not "no pets": no all-zero mask is invented.
    assert restored.map.pet_rows is None
    assert all(cell.pet is None for cell in restored.changed_cells)
    assert restored.map.rows == current.map.rows
    assert restored.map.glyph_rows == current.map.glyph_rows
    serialized = restored.to_json()
    assert serialized["map"]["pet_rows"] is None
    assert all(cell["pet"] is None for cell in serialized["changed_cells"])
    assert ProjectedObservation.from_json(serialized) == restored


def test_observation_stored_before_buc_evidence_reads_as_unknown(
    tmp_path: Path,
) -> None:
    current = _stepped_observation(tmp_path)
    legacy = current.to_json()
    for item in legacy["inventory"]:
        del item["buc"]

    restored = ProjectedObservation.from_json(legacy)

    assert restored.inventory
    assert all(item.buc is BucStatus.UNKNOWN for item in restored.inventory)
    serialized = restored.to_json()
    assert all(item["buc"] == "unknown" for item in serialized["inventory"])
    assert ProjectedObservation.from_json(serialized) == restored


@pytest.mark.parametrize(
    ("corrupt", "message"),
    [
        (lambda s: s["map"].update(pet_rows="00"), "must be an array"),
        (lambda s: s["map"]["pet_rows"].__setitem__(0, "zz"), "hexadecimal"),
        (
            lambda s: s["map"]["pet_rows"].__setitem__(0, s["map"]["pet_rows"][0][2:]),
            "shape does not match",
        ),
        (
            lambda s: s["map"]["pet_rows"].__setitem__(
                0, "02" + s["map"]["pet_rows"][0][2:]
            ),
            "must be 0 or 1",
        ),
        (lambda s: s["map"].update(pets=None), "unexpected \\['pets'\\]"),
        (lambda s: s["changed_cells"][0].update(pet=1), "must be a boolean"),
        (lambda s: s["changed_cells"][0].update(tame=True), "unexpected \\['tame'\\]"),
    ],
)
def test_observation_contract_rejects_malformed_present_pet_evidence(
    tmp_path: Path, corrupt, message: str
) -> None:
    serialized = _stepped_observation(tmp_path).to_json()
    corrupt(serialized)

    with pytest.raises(ContractError, match=message):
        ProjectedObservation.from_json(serialized)


def test_observation_contract_rejects_invalid_buc_status(tmp_path: Path) -> None:
    serialized = _stepped_observation(tmp_path).to_json()
    serialized["inventory"][0]["buc"] = "probably"

    with pytest.raises(ContractError, match="inventory buc must be one of"):
        ProjectedObservation.from_json(serialized)
