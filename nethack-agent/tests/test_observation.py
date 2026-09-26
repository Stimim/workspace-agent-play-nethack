import json
from dataclasses import replace
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent.contracts import ContractError
from nethack_agent.environment import NleEnvironment, ScenarioConfig
from nethack_agent.observation import ObservationProjector, ProjectedObservation


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
