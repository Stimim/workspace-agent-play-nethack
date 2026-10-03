"""Evidence of fresh, explicitly observed kills and visible floor corpses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from nle import nethack

from nethack_agent.decision import (
    ALLOWED_CORPSES,
    CorpseEvidence,
    MapCell,
    corpse_species_allowed,
    corpse_underfoot_matches,
    parse_floor_corpse_prompt,
)
from nethack_agent.environment import LegalAction
from nethack_agent.navigation import MOVE_ACTION_NAMES
from nethack_agent.observation import ProjectedObservation
from nethack_agent.traversal import LevelKey

MAX_CORPSE_AGE: Final = 19
_KILL: Final = re.compile(r"(?:^|(?<=\s))You kill the ([a-z][a-z -]*?)!(?=$|\s)")


@dataclass(frozen=True, slots=True)
class CorpseKill:
    name: str
    turn: int
    level: LevelKey
    cell: MapCell


def observed_corpse_kill(
    before: ProjectedObservation, action: LegalAction, after: ProjectedObservation
) -> CorpseKill | None:
    """Count only a kill of the monster visibly targeted by an attack move."""
    matches = tuple(_KILL.finditer(after.message))
    if len(matches) != 1:
        return None
    match = matches[0]
    if (
        before.prompt.active
        or before.player.dungeon_level < 1
        or after.player.dungeon_level < 1
        or "hallucinating" in before.player.conditions
        or "hallucinating" in after.player.conditions
    ):
        return None
    level = LevelKey(before.player.dungeon_number, before.player.dungeon_level)
    if level != LevelKey(after.player.dungeon_number, after.player.dungeon_level):
        return None
    delta = next(
        (point for point, name in MOVE_ACTION_NAMES.items() if action.name == name),
        None,
    )
    if delta is None:
        return None
    x, y = before.player.x + delta[0], before.player.y + delta[1]
    if not (
        0 <= y < len(before.map.glyph_rows) and 0 <= x < len(before.map.glyph_rows[y])
    ):
        return None
    if before.map.pet_rows is None or before.map.pet_rows[y][x]:
        return None
    glyph = before.map.glyph_rows[y][x]
    if not nethack.glyph_is_monster(glyph):
        return None
    if nethack.permonst(nethack.glyph_to_mon(glyph)).mname != match.group(1):
        return None
    if after.player.turn < before.player.turn:
        return None
    return CorpseKill(match.group(1), after.player.turn, level, MapCell(x, y))


def eligible_corpse(
    kill: CorpseKill,
    observation: ProjectedObservation,
    *,
    arrived: CorpseEvidence | None = None,
    lycanthropy_known: bool = False,
    shop_cells: set[tuple[int, int]] | frozenset[tuple[int, int]] = frozenset(),
) -> CorpseEvidence | None:
    """Require a public kill and freshness; probe a just-reached blank kill cell."""
    player = observation.player
    if (
        not corpse_species_allowed(
            kill.name, observation, lycanthropy_known=lycanthropy_known
        )
        or player.hunger < 1
        or observation.prompt.active
        or "hallucinating" in player.conditions
        or kill.level != LevelKey(player.dungeon_number, player.dungeon_level)
        or (kill.cell.x, kill.cell.y) in shop_cells
    ):
        return None
    age = player.turn - kill.turn
    if age < 0 or (kill.name != "lichen" and age > MAX_CORPSE_AGE):
        return None
    x, y = kill.cell.x, kill.cell.y
    if not (
        0 <= y < len(observation.map.glyph_rows)
        and 0 <= x < len(observation.map.glyph_rows[y])
    ):
        return None
    reached = (
        arrived is not None
        and arrived.name == kill.name
        and arrived.kill_turn == kill.turn
        and arrived.cell == kill.cell
    )
    here = (x, y) == (player.x, player.y)
    if here:
        if not corpse_underfoot_matches(kill.name, observation.message):
            if not (reached and observation.message == ""):
                return None
            return CorpseEvidence(kill.name, kill.turn, age, kill.cell, arrived=True)
    elif not nethack.glyph_is_body(observation.map.glyph_rows[y][x]):
        return None
    return CorpseEvidence(kill.name, kill.turn, age, kill.cell)


def eligible_lichen(
    cell: MapCell,
    observation: ProjectedObservation,
    *,
    arrived: CorpseEvidence | None = None,
    shop_cells: set[tuple[int, int]] | frozenset[tuple[int, int]] = frozenset(),
) -> CorpseEvidence | None:
    """Lichen alone is nonrotting, so a displayed body need not have a kill owner."""
    player = observation.player
    x, y = cell.x, cell.y
    if (
        player.hunger < 1
        or observation.prompt.active
        or "hallucinating" in player.conditions
        or (x, y) in shop_cells
        or not (
            0 <= y < len(observation.map.glyph_rows)
            and 0 <= x < len(observation.map.glyph_rows[y])
        )
    ):
        return None
    if (x, y) == (player.x, player.y):
        reached = (
            arrived is not None
            and arrived.name == "lichen"
            and arrived.kill_turn is None
            and arrived.cell == cell
            and observation.message == ""
        )
        if not (corpse_underfoot_matches("lichen", observation.message) or reached):
            return None
        return CorpseEvidence("lichen", None, None, cell, arrived=reached)
    glyph = observation.map.glyph_rows[y][x]
    if (
        not nethack.glyph_is_body(glyph)
        or nethack.permonst(glyph - nethack.GLYPH_BODY_OFF).mname != "lichen"
    ):
        return None
    return CorpseEvidence("lichen", None, None, cell)


__all__ = (
    "ALLOWED_CORPSES",
    "MAX_CORPSE_AGE",
    "CorpseKill",
    "observed_corpse_kill",
    "eligible_corpse",
    "parse_floor_corpse_prompt",
)
