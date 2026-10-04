from __future__ import annotations

import re
from dataclasses import replace

from nethack_agent.decision import (
    ActionIntent,
    ActionSelectionSource,
    DropEvidence,
    Skill,
)
from nethack_agent.environment import LegalAction
from nethack_agent.navigation import ActionKind, ActionRecord
from nethack_agent.observation import InventoryItem, ProjectedObservation
from nethack_agent.skills import SkillAction

_DROP_PROMPT = re.compile(r"^What do you want to drop\? \[(.*?) or \?\*\]")
_REFUSALS = (
    "carrying so much stuff",
    "can't even move a handspan",
    "cannot move a handspan",
)
# Public conservative unit-value estimates, not unidentified glyph identities.
_CLASS_VALUE = {12: 1, 13: 1, 2: 10, 3: 10, 7: 45, 9: 60, 8: 100}


def item_count(item: InventoryItem) -> int:
    match = re.match(r"^(\d+) ", item.description)
    return int(match[1]) if match else 1


def drop_offered(observation: ProjectedObservation) -> frozenset[int] | None:
    if not observation.prompt.active:
        return None
    match = _DROP_PROMPT.match(observation.message)
    if match is None:
        return None
    text = match[1]
    commands: set[int] = set()
    i = 0
    while i < len(text):
        if i + 2 < len(text) and text[i + 1] == "-":
            commands.update(range(ord(text[i]), ord(text[i + 2]) + 1))
            i += 3
        else:
            commands.add(ord(text[i]))
            i += 1
    return frozenset(commands)


def drop_candidate(
    observation: ProjectedObservation, blocked: set[tuple[str, str]]
) -> tuple[InventoryItem, int] | None:
    inventory = observation.inventory
    weapons = [i for i in inventory if i.object_class == 2]
    wielded = next(
        (
            i
            for i in weapons
            if "weapon in hand" in i.description
            or "wielded" in i.description
            and "not wielded" not in i.description
        ),
        None,
    )
    # Preserve a held main weapon through a polymorph that unwields it.
    main = wielded or (weapons[0] if weapons else None)
    rations = [i for i in inventory if "food ration" in i.description]
    reserve = rations[0] if rations else None
    candidates = []
    for item in inventory:
        if (
            (item.letter, item.description) in blocked
            or item == main
            or "being worn" in item.description
            or "on left hand" in item.description
            or "on right hand" in item.description
        ):
            continue
        count = item_count(item)
        quantity = count
        if item.object_class == 7 and item == reserve:
            quantity -= 1
        if quantity > 0:
            candidates.append(
                (_CLASS_VALUE.get(item.object_class, 200), item.letter, item, quantity)
            )
    if not candidates:
        return None
    _, _, item, quantity = min(candidates, key=lambda x: (x[0], x[1]))
    return item, quantity


class BurdenRecovery:
    """Drop only after an observed load refusal, until Burdened or better."""

    def __init__(self) -> None:
        self.refusal_step: int | None = None
        self.pending: DropEvidence | None = None
        self.keys = ""
        self.blocked: set[tuple[str, str]] = set()
        self.stashed_food: set[tuple[int, int, int, int]] = set()

    @property
    def active(self) -> bool:
        return self.refusal_step is not None

    def observe(self, observation: ProjectedObservation) -> None:
        if observation.player.encumbrance <= 1:
            self.refusal_step = None
            self.pending = None
            self.keys = ""
            self.blocked.clear()
        elif any(text in observation.message.lower() for text in _REFUSALS):
            if self.refusal_step is None:
                self.refusal_step = observation.step_index

    def expected(self, observation: ProjectedObservation) -> DropEvidence | None:
        self.observe(observation)
        if self.refusal_step is None:
            return None
        if self.pending is not None:
            offered = drop_offered(observation)
            current = next(
                (
                    i
                    for i in observation.inventory
                    if i.letter == self.pending.letter
                    and i.description == self.pending.description
                ),
                None,
            )
            if (
                offered is None
                or current is None
                or ord(current.letter) not in offered
                or not self.keys
            ):
                return None
            return replace(self.pending, command=ord(self.keys[0]))
        if observation.prompt.active:
            return None
        candidate = drop_candidate(observation, self.blocked)
        if candidate is None:
            return None
        item, quantity = candidate
        return DropEvidence(
            item.letter, item.description, quantity, self.refusal_step, ord("d")
        )

    def select_action(
        self, observation: ProjectedObservation, actions: dict[int, LegalAction]
    ) -> SkillAction | None:
        evidence = self.expected(observation)
        if evidence is None or evidence.command not in actions:
            return None
        return SkillAction(
            actions[evidence.command].index,
            "Shed non-essential load after refusal, keeping one ration and equipment.",
            ActionRecord(
                ActionKind.OTHER, (observation.player.x, observation.player.y)
            ),
            ActionIntent(None, None, None, drop=evidence),
        )

    def advance(
        self, evidence: DropEvidence | None, after: ProjectedObservation
    ) -> None:
        if evidence is not None:
            if self.pending is None:
                self.pending = evidence
                item = next(
                    (i for i in after.inventory if i.letter == evidence.letter), None
                )
                self.keys = (
                    str(evidence.quantity)
                    if item is not None and evidence.quantity < item_count(item)
                    else ""
                ) + evidence.letter
            elif self.keys:
                self.keys = self.keys[1:]
            if not self.keys or not after.prompt.active:
                if any(
                    i.letter == evidence.letter
                    and i.description == evidence.description
                    for i in after.inventory
                ):
                    self.blocked.add((evidence.letter, evidence.description))
                elif "food ration" in evidence.description:
                    p = after.player
                    self.stashed_food.add((p.dungeon_number, p.dungeon_level, p.x, p.y))
                self.pending = None
                self.keys = ""
        self.observe(after)

    def excluded_food_cells(
        self, observation: ProjectedObservation
    ) -> frozenset[tuple[int, int]]:
        if not any(item.object_class == 7 for item in observation.inventory):
            return frozenset()
        p = observation.player
        return frozenset(
            (x, y)
            for dungeon, level, x, y in self.stashed_food
            if (dungeon, level) == (p.dungeon_number, p.dungeon_level)
        )


def burden_action_error(
    action: LegalAction,
    selection,
    before: ProjectedObservation | None,
    recovery: BurdenRecovery | None,
) -> str | None:
    evidence = (
        None if selection is None or selection.intent is None else selection.intent.drop
    )
    if evidence is None:
        return "DROP requires deterministic load-refusal evidence"
    if before is None or recovery is None or selection.skill is not Skill.BURDEN:
        return "DROP requires observed burden recovery state"
    expected = recovery.expected(before)
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
            "DROP item/quantity must match the offered prompt and protected inventory"
        )
    return None
