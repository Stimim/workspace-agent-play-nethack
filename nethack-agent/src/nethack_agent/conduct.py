"""Public pre-action conduct predicates, also applied during stored replay."""

from __future__ import annotations

from nethack_agent.environment import LegalAction
from nethack_agent.navigation import MOVE_ACTION_NAMES, LevelMemory
from nethack_agent.observation import ProjectedObservation


def attack_evidence(
    action: LegalAction, observation: ProjectedObservation
) -> tuple[str | None, bool]:
    if observation.prompt.active:
        return None, False
    delta = next(
        (delta for delta, name in MOVE_ACTION_NAMES.items() if name == action.name),
        None,
    )
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
    # Ordinary direction movement swaps with tame pets; this profile has no
    # forced-fight command. It is not aggression.
    if not nethack.glyph_is_monster(glyph) or nethack.glyph_is_pet(glyph):
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
    name, peaceful = attack_evidence(action, observation)
    if name == "Oracle" or (name is not None and "centaur" in name):
        return "Oracle and living centaurs must never be attacked"
    if memory is not None and memory.target_conduct and name is not None:
        if peaceful or "hallucinating" in observation.player.conditions:
            return (
                "peaceful/tame creatures and hallucinated targets must not be attacked"
            )
        delta = next(
            delta for delta, name in MOVE_ACTION_NAMES.items() if name == action.name
        )
        point = (observation.player.x + delta[0], observation.player.y + delta[1])
        if not any(
            (cell.x, cell.y) == point for cell in observation.cell_descriptions or ()
        ):
            return "unknown public attitude must not be attacked"
    if action.name in ("Command.QUAFF", "Command.DIP"):
        return "fountain quaffing/dipping is unavailable"
    return None
