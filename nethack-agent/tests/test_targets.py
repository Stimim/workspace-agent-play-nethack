from dataclasses import replace
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent.conduct import attack_evidence, conduct_error
from nethack_agent.environment import LegalAction, NleEnvironment, ScenarioConfig
from nethack_agent.navigation import (
    ActionKind,
    ActionRecord,
    DungeonMemory,
    LevelMemory,
)
from nethack_agent.observation import (
    CellDescription,
    MapView,
    ObservationProjector,
    ProjectedObservation,
)
from nethack_agent.planner import ObjectivePlanner, leg_complete, main_stairs
from nethack_agent.targets import ORACLE_GLYPH, altar_enclosure, oracle_adjacent
from nethack_agent.traversal import (
    EnterMinetownTempleLeg,
    EnterTempleGoal,
    LevelKey,
    Objective,
    StairDirection,
)


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> ProjectedObservation:
    with NleEnvironment(
        ScenarioConfig(4, Path(tmp_path_factory.mktemp("targets")))
    ) as env:
        return ObservationProjector().project(env.reset(), step_index=0)


def oracle_observation(
    template: ProjectedObservation,
    description: str = "peaceful Oracle",
    distance: int = 1,
) -> ProjectedObservation:
    rows = [list(row) for row in template.map.glyph_rows]
    x, y = template.player.x, template.player.y
    rows[y][x - distance] = ORACLE_GLYPH
    return replace(
        template,
        map=replace(template.map, glyph_rows=tuple(tuple(row) for row in rows)),
        cell_descriptions=(CellDescription(x - distance, y, description),),
    )


def test_oracle_requires_current_peaceful_exact_glyph_adjacent_and_no_attacks(
    template: ProjectedObservation,
) -> None:
    current = oracle_observation(template)
    assert oracle_adjacent(current, 0)
    assert not oracle_adjacent(current, 1)
    assert not oracle_adjacent(oracle_observation(template, "Oracle"), 0)
    assert not oracle_adjacent(oracle_observation(template, distance=2), 0)
    assert not oracle_adjacent(replace(current, cell_descriptions=None), 0)
    assert not oracle_adjacent(
        replace(current, player=replace(current.player, conditions=("hallucinating",))),
        0,
    )
    rows = [list(row) for row in current.map.glyph_rows]
    cell = current.cell_descriptions[0]
    rows[cell.y][cell.x] = nethack.GLYPH_CMAP_OFF + 31
    assert not oracle_adjacent(
        replace(
            current,
            map=replace(current.map, glyph_rows=tuple(tuple(row) for row in rows)),
        ),
        0,
    )


def temple_observation(
    template: ProjectedObservation,
    *,
    step: int,
    branch: int = 2,
    level: int = 3,
    altar: str = "lawful altar",
    hero: tuple[int, int] = (2, 2),
    message: str = "",
) -> ProjectedObservation:
    rows = ("||||||||||", "|........|", "|........|", "|........|", "||||||||||")
    glyphs = tuple(
        tuple(nethack.GLYPH_CMAP_OFF + (1 if c == "|" else 19) for c in row)
        for row in rows
    )
    shape = tuple(bytes(len(row)) for row in rows)
    return replace(
        template,
        step_index=step,
        map=MapView(rows, glyphs, shape, shape, shape),
        changed_cells=(),
        player=replace(
            template.player,
            x=hero[0],
            y=hero[1],
            dungeon_number=branch,
            dungeon_level=level,
            depth=level + 2,
        ),
        message=message,
        cell_descriptions=(CellDescription(5, 2, altar),),
    )


def linked_mines(template: ProjectedObservation) -> DungeonMemory:
    dungeon = DungeonMemory()
    origin = temple_observation(
        template, step=0, branch=0, level=2, message="There is a staircase down here."
    )
    dungeon.observe(origin).record(ActionRecord(ActionKind.TRAVERSE, (2, 2)))
    dungeon.observe(temple_observation(template, step=1, level=1))
    return dungeon


def test_temple_fallback_requires_complete_enclosure_and_branch_provenance(
    template: ProjectedObservation,
) -> None:
    dungeon = linked_mines(template)
    observation = temple_observation(template, step=2)
    memory = dungeon.observe(observation)
    memory.town_identified = True
    # Refresh evidence after public town layout has been established.
    dungeon.observe(replace(observation, step_index=3))
    assert (2, 2) in altar_enclosure(memory, (5, 2))
    assert leg_complete(EnterMinetownTempleLeg(), dungeon)
    unrelated = DungeonMemory()
    unrelated.observe(observation).town_identified = True
    unrelated.observe(replace(observation, step_index=3))
    assert not leg_complete(EnterMinetownTempleLeg(), unrelated)
    memory._cmap[1][4] = -1
    assert not altar_enclosure(memory, (5, 2))


def test_orcish_town_requires_current_on_cell_unaligned_description(
    template: ProjectedObservation,
) -> None:
    dungeon = linked_mines(template)
    obs = temple_observation(template, step=2, altar="unaligned altar")
    memory = dungeon.observe(obs)
    memory.town_identified = True
    dungeon.observe(replace(obs, step_index=3))
    assert not leg_complete(EnterMinetownTempleLeg(), dungeon)
    dungeon.observe(
        replace(
            obs,
            step_index=4,
            player=replace(obs.player, x=5, y=2),
            cell_descriptions=(),
        )
    )
    assert not leg_complete(EnterMinetownTempleLeg(), dungeon)
    dungeon.observe(replace(obs, step_index=5, player=replace(obs.player, x=5, y=2)))
    assert leg_complete(EnterMinetownTempleLeg(), dungeon)


def test_minetown_planner_stops_descent_at_identified_town(
    template: ProjectedObservation,
) -> None:
    dungeon = linked_mines(template)
    planner = ObjectivePlanner(Objective((EnterMinetownTempleLeg(),)))
    assert planner.plan(0, dungeon).goal == main_stairs(StairDirection.DOWN)
    memory = dungeon.observe(temple_observation(template, step=2))
    assert planner.plan(0, dungeon).goal == EnterTempleGoal(LevelKey(2, 3))
    memory.mark_exhausted()
    assert planner.plan(0, dungeon).goal == main_stairs(StairDirection.DOWN)
    memory.town_identified = True
    assert planner.plan(0, dungeon).goal == EnterTempleGoal(LevelKey(2, 3))


def test_conduct_blocks_oracle_even_hostile_and_does_not_count_pet_swaps(
    template: ProjectedObservation,
) -> None:
    west = LegalAction(0, ord("h"), "CompassDirection.W")
    hostile = oracle_observation(template, "Oracle")
    assert conduct_error(west, hostile, LevelMemory()) is not None
    peaceful = oracle_observation(template, "peaceful Oracle")
    assert attack_evidence(west, peaceful) == ("Oracle", True)
    rows = [list(row) for row in peaceful.map.glyph_rows]
    cell = peaceful.cell_descriptions[0]
    rows[cell.y][cell.x] = nethack.GLYPH_PET_OFF + next(
        i for i in range(nethack.NUMMONS) if nethack.permonst(i).mname == "little dog"
    )
    pet = replace(
        peaceful,
        map=replace(peaceful.map, glyph_rows=tuple(tuple(row) for row in rows)),
    )
    assert attack_evidence(west, pet) == (None, False)
    assert conduct_error(west, pet, LevelMemory()) is None
