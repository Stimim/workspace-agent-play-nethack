"""Reviewed ranged dagger clearing of a displayed, aligned gas spore.

A gas spore cannot attack on its own; it has an on-death explosion (3x3,
Chebyshev radius 1) that triggers only when something deals it lethal HP
loss. The hero never melees one (existing `_NEVER_MELEE`), but mere
adjacency is not itself dangerous. This module adds one narrow, optional,
proactive capability: when a displayed non-pet gas spore is aligned with
the hero (same row, column, or diagonal) at Chebyshev distance >= 2, with
a clear ray and no pet/peaceful inside its blast radius, throw a reviewed
non-cursed dagger at it from outside the blast. Nothing here restricts any
existing move, search, or wait; there is no new trapped state.
"""

from __future__ import annotations

import re

from nethack_agent.decision import (
    ActionIntent,
    ActionSelectionSource,
    MapCell,
    Skill,
    ThrowEvidence,
)
from nethack_agent.environment import LegalAction
from nethack_agent.navigation import ActionKind, ActionRecord, LevelMemory, Point
from nethack_agent.observation import InventoryItem, ProjectedObservation
from nethack_agent.skills import SkillAction

_THROW_PROMPT = re.compile(
    r"^What do you want to throw\? \[(?P<letters>.*?) or \?\*\]$"
)
_DIRECTION_PROMPT = "In what direction?"
# NetHack's direction keys are the fixed vi-keys regardless of action
# profile; this mirrors burden.py hardcoding the DROP command ("d").
_DIRECTION_COMMANDS: dict[Point, int] = {
    (0, -1): ord("k"),
    (1, 0): ord("l"),
    (0, 1): ord("j"),
    (-1, 0): ord("h"),
    (1, -1): ord("u"),
    (1, 1): ord("n"),
    (-1, 1): ord("b"),
    (-1, -1): ord("y"),
}


def _cell(point: Point) -> str:
    return f"({point[0]}, {point[1]})"


def _throwable_dagger(inventory: tuple[InventoryItem, ...]) -> InventoryItem | None:
    for item in inventory:
        if (
            item.object_class == 2
            and "dagger" in item.description
            and "cursed" not in item.description
        ):
            return item
    return None


def _aligned_direction(origin: Point, target: Point) -> Point | None:
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    if dx == 0 and dy == 0:
        return None
    if dx != 0 and dy != 0 and abs(dx) != abs(dy):
        return None
    return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))


def safe_gas_spore_target(
    memory: LevelMemory, observation: ProjectedObservation
) -> tuple[MapCell, Point] | None:
    """The nearest gas spore the hero may safely throw a dagger at, if any."""
    origin = memory.position
    candidates = []
    for point, monster in memory.monsters.items():
        if monster.name != "gas spore" or monster.pet:
            continue
        direction = _aligned_direction(origin, point)
        if direction is None:
            continue
        distance = max(abs(point[0] - origin[0]), abs(point[1] - origin[1]))
        if distance < 2:
            continue
        x, y = origin
        blocked = False
        for _ in range(distance - 1):
            x, y = x + direction[0], y + direction[1]
            if (x, y) == point:
                break
            if not memory.passable((x, y)) or (x, y) in memory.monsters:
                blocked = True
                break
        if blocked:
            continue
        if any(
            (other.pet or other.glyph in memory.peaceful_glyphs)
            and max(abs(p[0] - point[0]), abs(p[1] - point[1])) <= 1
            for p, other in memory.monsters.items()
        ):
            continue
        candidates.append((distance, point[1], point[0], point, direction))
    if not candidates:
        return None
    _, _, _, point, direction = min(candidates)
    return MapCell(*point), direction


def expected_throw(
    observation: ProjectedObservation, memory: LevelMemory
) -> ThrowEvidence | None:
    """The one deterministic throw evidence this step authorizes, if any."""
    target = safe_gas_spore_target(memory, observation)
    if target is None:
        return None
    cell, direction = target
    if observation.prompt.active:
        stripped = observation.message.strip()
        match = _THROW_PROMPT.fullmatch(stripped)
        if match is not None:
            offered = frozenset(match.group("letters"))
            dagger = _throwable_dagger(observation.inventory)
            if dagger is None or dagger.letter not in offered:
                return None
            return ThrowEvidence(dagger.letter, cell, direction, ord(dagger.letter))
        if stripped == _DIRECTION_PROMPT:
            dagger = _throwable_dagger(observation.inventory)
            if dagger is None:
                return None
            return ThrowEvidence(
                dagger.letter, cell, direction, _DIRECTION_COMMANDS[direction]
            )
        return None
    dagger = _throwable_dagger(observation.inventory)
    if dagger is None:
        return None
    return ThrowEvidence(dagger.letter, cell, direction, ord("t"))


def throw_at_gas_spore(
    observation: ProjectedObservation,
    memory: LevelMemory,
    actions: dict[int, LegalAction],
) -> SkillAction | None:
    evidence = expected_throw(observation, memory)
    if evidence is None or evidence.command not in actions:
        return None
    return SkillAction(
        actions[evidence.command].index,
        f"Throw a reviewed non-cursed dagger at the gas spore at "
        f"{_cell((evidence.target.x, evidence.target.y))} from a safe distance.",
        ActionRecord(ActionKind.OTHER, memory.position),
        ActionIntent(None, None, None, throw=evidence),
    )


def throw_action_error(
    action: LegalAction,
    selection,
    before: ProjectedObservation | None,
    memory: LevelMemory | None,
) -> str | None:
    evidence = (
        None
        if selection is None or selection.intent is None
        else selection.intent.throw
    )
    if evidence is None:
        return "THROW requires deterministic gas-spore target evidence"
    if before is None or memory is None or selection.skill is not Skill.RANGED_THROW:
        return "THROW requires observed hazard state"
    expected = expected_throw(before, memory)
    source = (
        ActionSelectionSource.DETERMINISTIC_PROMPT
        if before.prompt.active
        else ActionSelectionSource.DETERMINISTIC_SKILL
    )
    if (
        expected != evidence
        or action.command != evidence.command
        or selection.source is not source
    ):
        return (
            "THROW target/letter/direction must match the offered prompt and "
            "current gas-spore evidence"
        )
    return None
