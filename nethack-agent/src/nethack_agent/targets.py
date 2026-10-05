"""Public location evidence shared by planning and replay; no native state."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from nle import nethack

if TYPE_CHECKING:
    from nethack_agent.navigation import DungeonMemory, LevelMemory
    from nethack_agent.observation import ProjectedObservation

ORACLE_SPECIES = next(
    i for i in range(nethack.NUMMONS) if nethack.permonst(i).mname == "Oracle"
)
ORACLE_GLYPH = nethack.GLYPH_MON_OFF + ORACLE_SPECIES
TEMPLE_MESSAGES = (
    '"Pilgrim, you enter a sacred place!"',
    '"Pilgrim, you enter a desecrated place!"',
    "You have a forbidding feeling...",
    "You have a strange forbidding feeling...",
    "You experience a sense of peace.",
    "You experience an unusual sense of peace.",
    "You have an eerie feeling...",
    "You feel like you are being watched.",
    "A shiver runs down your spine.",
)


def oracle_adjacent(observation: ProjectedObservation, attacks: int) -> bool:
    if attacks or "hallucinating" in observation.player.conditions:
        return False
    x, y = observation.player.x, observation.player.y
    return any(
        cell.text == "peaceful Oracle"
        and observation.map.glyph_rows[cell.y][cell.x] == ORACLE_GLYPH
        and max(abs(cell.x - x), abs(cell.y - y)) == 1
        for cell in observation.cell_descriptions or ()
    )


def mines_candidate(dungeon: DungeonMemory) -> bool:
    memory = dungeon.current
    if (
        memory.level is None
        or memory.level.dungeon_number != 2
        or memory.level.dungeon_level not in (3, 4)
    ):
        return False
    # Public dlevel is relative, not a counter of visits. A recorded actual
    # entrance crossing supplies provenance even after trap falls or revisits.
    return any(
        key.dungeon_number == 0
        and 2 <= key.dungeon_level <= 4
        and link.level.dungeon_number == 2
        and link.level.dungeon_level == 1
        and memory.live_observation is not None
        and memory.live_observation.player.depth
        == key.dungeon_level + memory.level.dungeon_level
        for key, level in dungeon.levels.items()
        for link in level.links.values()
    )


def town_layout(memory: LevelMemory) -> bool:
    # Mines filler is cavern terrain, not multiple constructed buildings.
    walls = sum(
        memory.cmap((x, y)) in range(1, 12)
        for y in range(memory.height)
        for x in range(memory.width)
    )
    doors = sum(
        memory.cmap((x, y)) in (12, 13, 14, 15, 16)
        for y in range(memory.height)
        for x in range(memory.width)
    )
    bars = sum(
        memory.cmap((x, y)) == 17
        for y in range(memory.height)
        for x in range(memory.width)
    )
    return walls >= 30 and (doors >= 3 or bars >= 6)


def altar_enclosure(
    memory: LevelMemory, altar: tuple[int, int]
) -> frozenset[tuple[int, int]]:
    """Interior floor flood; unknown/open/corridor edges never prove a room."""
    queue = deque([altar])
    inside = set()
    while queue:
        point = queue.popleft()
        if point in inside:
            continue
        inside.add(point)
        if len(inside) > 100:
            return frozenset()
        x, y = point
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p = (x + dx, y + dy)
            if not memory.in_bounds(p):
                return frozenset()
            cmap = memory.cmap(p)
            if cmap in (19, 20, 27, 31):
                queue.append(p)
            elif cmap not in range(1, 17):
                return frozenset()
    return frozenset(inside)


def update_target_evidence(
    memory: LevelMemory, observation: ProjectedObservation
) -> None:
    memory.live_observation = observation
    if "hallucinating" in observation.player.conditions:
        return
    for cell in observation.cell_descriptions or ():
        if "altar" in cell.text:
            memory.altars[(cell.x, cell.y)] = cell.text
            memory._cmap[cell.y][cell.x] = 27
    if (
        memory.level is None
        or memory.level.dungeon_number != 2
        or memory.level.dungeon_level not in (3, 4)
    ):
        return
    memory.town_identified = memory.town_identified or town_layout(memory)
    # These two spoken sentences are temple-specific in priest.c. Unlike
    # generic feelings, they do not need a completely observed enclosure.
    if any(text in observation.message for text in TEMPLE_MESSAGES[:2]):
        memory.town_identified = True
        memory.temple_entry = observation.message
    if not memory.town_identified:
        return
    for altar, description in memory.altars.items():
        if "unaligned altar" in description:
            # Alignment must be current on the occupied cell, not stale memory.
            if any(
                (c.x, c.y) == memory.position == altar and "unaligned altar" in c.text
                for c in observation.cell_descriptions or ()
            ):
                memory.temple_entry = "orcish-town: occupied publicly unaligned altar"
            continue
        enclosure = altar_enclosure(memory, altar)
        if memory.position == altar or memory.position in enclosure:
            memory.temple_entry = (
                "altar occupancy"
                if memory.position == altar
                else "enclosed altar interior occupancy"
            )
        if any(text in observation.message for text in TEMPLE_MESSAGES) and (
            memory.position in enclosure or memory.position == altar
        ):
            memory.temple_entry = observation.message
