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
    kill: CorpseKill, observation: ProjectedObservation
) -> CorpseEvidence | None:
    """Validate freshness and currently visible corpse or exact look-here identity."""
    player = observation.player
    if (
        kill.name not in ALLOWED_CORPSES
        or player.hunger < 1
        or observation.prompt.active
        or "hallucinating" in player.conditions
    ):
        return None
    if kill.level != LevelKey(player.dungeon_number, player.dungeon_level):
        return None
    age = player.turn - kill.turn
    if not 0 <= age <= MAX_CORPSE_AGE:
        return None
    x, y = kill.cell.x, kill.cell.y
    if not (
        0 <= y < len(observation.map.glyph_rows)
        and 0 <= x < len(observation.map.glyph_rows[y])
    ):
        return None
    here = (x, y) == (player.x, player.y)
    if here:
        if observation.message != f"You see here a {kill.name} corpse.":
            return None
    elif not nethack.glyph_is_body(observation.map.glyph_rows[y][x]):
        return None
    return CorpseEvidence(kill.name, kill.turn, age, kill.cell)


__all__ = (
    "ALLOWED_CORPSES",
    "MAX_CORPSE_AGE",
    "CorpseKill",
    "observed_corpse_kill",
    "eligible_corpse",
    "parse_floor_corpse_prompt",
)
