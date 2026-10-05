"""Public pre-action conduct predicates, also applied during stored replay."""

from __future__ import annotations

from typing import Final

from nethack_agent.environment import LegalAction
from nethack_agent.navigation import MOVE_ACTION_NAMES, LevelMemory, Point
from nethack_agent.observation import ProjectedObservation

# Every action in the survival profile that moves the hero into, or attacks,
# an adjacent cell in one step. `CompassDirection` is an ordinary one-step
# move; `CompassDirectionLonger` is the shift/`G`-prefixed run in the same
# direction, which still attacks on the very first step if something is
# there. `Command.FIGHT`, `Command.RUSH`, `Command.RUSH2`, and
# `Command.MOVEFAR` are also in the profile, but each is a bare prefix
# keypress with no direction of its own (confirmed empirically: issuing one
# alone changes neither position nor glyphs); the attack they enable always
# lands on the very next `CompassDirection`/`CompassDirectionLonger` action,
# which this mapping already covers.
ATTACK_DELTA_BY_ACTION_NAME: Final[dict[str, Point]] = {
    name: delta for delta, name in MOVE_ACTION_NAMES.items()
} | {
    f"CompassDirectionLonger.{name.rsplit('.', 1)[-1]}": delta
    for delta, name in MOVE_ACTION_NAMES.items()
}


def attack_evidence(
    action: LegalAction,
    observation: ProjectedObservation,
    memory: LevelMemory | None = None,
) -> tuple[str | None, bool]:
    if observation.prompt.active:
        return None, False
    delta = ATTACK_DELTA_BY_ACTION_NAME.get(action.name)
    if delta is None:
        return None, False
    x, y = observation.player.x + delta[0], observation.player.y + delta[1]
    from nle import nethack

    if not (
        0 <= y < len(observation.map.glyph_rows)
        and 0 <= x < len(observation.map.glyph_rows[y])
    ):
        return None, False
    glyph = observation.map.glyph_rows[y][x]
    force_fight = memory is not None and memory.pending_force_fight
    # Ordinary direction movement swaps with tame pets; a preceding
    # `Command.FIGHT` keypress instead force-attacks whatever occupies the
    # cell, pet or not, so the swap exemption must not apply then.
    if not nethack.glyph_is_monster(glyph) or (
        nethack.glyph_is_pet(glyph) and not force_fight
    ):
        return None, False
    description = next(
        (c.text for c in observation.cell_descriptions or () if (c.x, c.y) == (x, y)),
        "",
    )
    return nethack.permonst(nethack.glyph_to_mon(glyph)).mname, description.startswith(
        ("peaceful ", "tame ")
    )


def oracle_ascent_error(
    memory: LevelMemory | None, cell: tuple[int, int]
) -> str | None:
    from nethack_agent.traversal import StairIdentityKind

    if (
        memory is not None
        and memory.oracle_navigation
        and memory.level is not None
        and memory.level.dungeon_number == 0
        and 6 <= memory.level.dungeon_level <= 10
        and memory.identity(cell).kind is not StairIdentityKind.MAIN
    ):
        return "Oracle recovery requires a recorded main upstairs, never Sokoban's up-branch"
    return None


def conduct_error(
    action: LegalAction,
    observation: ProjectedObservation | None,
    memory: LevelMemory | None,
) -> str | None:
    if observation is None:
        return None
    if observation.prompt.active:
        if "Really attack?" in observation.message and action.command == ord("y"):
            return "Really attack confirmations must be declined"
        return None
    if action.name == "MiscDirection.UP" and memory is not None:
        error = oracle_ascent_error(memory, memory.position)
        if error is not None:
            return error
    name, peaceful = attack_evidence(action, observation, memory)
    if name == "Oracle" or (name is not None and "centaur" in name):
        return "Oracle and living centaurs must never be attacked"
    if memory is not None and memory.target_conduct and name is not None:
        if peaceful or "hallucinating" in observation.player.conditions:
            return (
                "peaceful/tame creatures and hallucinated targets must not be attacked"
            )
        delta = ATTACK_DELTA_BY_ACTION_NAME[action.name]
        point = (observation.player.x + delta[0], observation.player.y + delta[1])
        if not any(
            (cell.x, cell.y) == point for cell in observation.cell_descriptions or ()
        ):
            return "unknown public attitude must not be attacked"
    if action.name in ("Command.QUAFF", "Command.DIP"):
        return "fountain quaffing/dipping is unavailable"
    return None
