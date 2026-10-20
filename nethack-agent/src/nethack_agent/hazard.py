"""Bounded public-observation clearance of hostile eyes and gas spores.

A throw is an owned item/direction transaction, never a model escape hatch.
The original melee exclusions stay in force. Unknown ray cells or attitudes
veto shooting; an eye has no ranged gaze retaliation, while a spore's death
explosion requires a separate radius-one collateral check.
"""

from __future__ import annotations

import re
from dataclasses import replace

from nle import nethack

from nethack_agent.decision import (
    ActionIntent,
    ActionSelectionSource,
    MapCell,
    Skill,
    ThrowEvidence,
)
from nethack_agent.navigation import (
    MOVE_ACTION_NAMES,
    ActionKind,
    ActionRecord,
    CellKind,
    route_tree,
)
from nethack_agent.observation import BucStatus
from nethack_agent.skills import (
    SkillAction,
    _best_stair,
    _frontier_goal,
    stair_candidates,
)
from nethack_agent.traversal import STAIR_GOAL_TYPES

WAIT_ALLOWANCE = 8
TARGET_ATTEMPT_LIMIT = 2
LEVEL_ATTEMPT_LIMIT = 4
ATTEMPT_COOLDOWN_TURNS = 20
_TARGET_NAMES = frozenset({"floating eye", "gas spore"})
_ITEM_PROMPT = re.compile(r"^What do you want to throw\? \[(.*?)\]$")
_DIRECTION_COMMANDS = {
    delta: int(nethack.CompassDirection[name.rsplit(".", 1)[1]])
    for delta, name in MOVE_ACTION_NAMES.items()
}
_UNSAFE_CONDITIONS = frozenset(
    {"blind", "blinded", "hallucinating", "confused", "stunned"}
)


def _offered_letter(letter, offer):
    # Same compact a-z convention as the native DROP offer parser.
    text = offer.split(" or ", 1)[0]
    for index, character in enumerate(text):
        if character == letter:
            return True
        if (
            character == "-"
            and 0 < index < len(text) - 1
            and text[index - 1] <= letter <= text[index + 1]
        ):
            return True
    return False


def throwable_dagger(inventory):
    """A real dagger glyph, not a named impostor or the wielded weapon.

    Cursed is an exact typed status: 'uncursed' is NOT rejected. Unknown BUC
    is allowed only for an unwielded dagger (welding cannot prevent its throw).
    No artifact/primary-weapon disposal or floor acquisition is introduced.
    """
    for item in inventory:
        index = item.glyph - nethack.GLYPH_OBJ_OFF
        if not 0 <= index < nethack.NUM_OBJECTS:
            continue
        if (
            item.object_class == 2
            and nethack.OBJ_NAME(nethack.objclass(index)) == "dagger"
            and item.buc is not BucStatus.CURSED
            and "unpaid" not in item.description
            and "weapon in hand" not in item.description
            and "wielded" not in item.description.replace("not wielded", "")
        ):
            return item
    return None


def _descriptions(observation):
    return {(cell.x, cell.y): cell.text for cell in observation.cell_descriptions or ()}


def _safe_target(observation, memory, point):
    monster = memory.monsters.get(point)
    if monster is None or monster.pet or monster.name not in _TARGET_NAMES:
        return None
    descriptions = _descriptions(observation)
    # Exact ordinary look text is required; species alone is not hostility.
    if descriptions.get(point) != monster.name:
        return None
    if monster.glyph in memory.peaceful_glyphs:
        return None
    ox, oy = memory.position
    dx, dy = point[0] - ox, point[1] - oy
    if not (dx or dy) or (dx and dy and abs(dx) != abs(dy)):
        return None
    direction = ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
    distance = max(abs(dx), abs(dy))
    # Conservative upper bound: do not throw at something beyond native range.
    if distance > max(1, observation.player.strength_25 // 2):
        return None
    if monster.name == "gas spore":
        if distance < 2:
            return None
        for y in range(point[1] - 1, point[1] + 2):
            for x in range(point[0] - 1, point[0] + 2):
                near = (x, y)
                if not memory.in_bounds(near) or (
                    near != point and memory.kind(near) is CellKind.UNKNOWN
                ):
                    return None
                other = memory.monsters.get(near)
                if other is not None and near != point:
                    # No chains, pets, peacefuls or uncertain blast victims.
                    return None
    # Inspect the WHOLE possible ray, including overshoot after a miss. Walls
    # and closed doors stop missiles. Bars/other uncertain obstacles veto the
    # throw instead of being mistaken for a safe backstop. Boulders do not
    # provide a missile backstop.
    reached = False
    x, y = ox, oy
    for _ in range(max(memory.width, memory.height)):
        x, y = x + direction[0], y + direction[1]
        cell = (x, y)
        if not memory.in_bounds(cell):
            return direction if reached else None
        if cell == point:
            reached = True
            continue
        kind = memory.kind(cell)
        if kind in (CellKind.WALL, CellKind.CLOSED_DOOR):
            return direction if reached else None
        if kind in (CellKind.UNKNOWN, CellKind.OBSTACLE):
            return None
        if cell in memory.monsters:
            # A miss can strike ANY creature beyond the intended target.
            return None
    return None


def _route_blocker(memory, goal):
    tree = route_tree(memory)
    through = route_tree(memory, through_monsters=True)
    candidates = (
        stair_candidates(memory, goal.target)
        if isinstance(goal, STAIR_GOAL_TYPES)
        else {}
    )
    if _best_stair(tree, candidates) is not None:
        return None
    destination = _best_stair(through, candidates)
    if destination is None:
        # An unknown/incompatible exit is still served by ordinary exploration.
        # Match ExploreLevelSkill's reachable-frontier precedence and stair bias.
        stairs = tuple(candidates)
        if _frontier_goal(memory, tree, stairs) is not None:
            return None
        destination = _frontier_goal(memory, through, stairs)
    if destination is None:
        return None
    route = through.route(destination)
    if route is None:
        return None
    for point in route:
        if point in memory.monsters:
            return point
    return None


def expected_throw(observation, memory, goal=None):
    pending = memory.pending_throw
    if pending is not None:
        cancel = replace(pending, command=27)
        if not observation.prompt.active:
            return None
        if _UNSAFE_CONDITIONS.intersection(observation.player.conditions):
            return cancel
        direction = _safe_target(
            observation, memory, (pending.target.x, pending.target.y)
        )
        dagger = next(
            (item for item in observation.inventory if item.letter == pending.letter),
            None,
        )
        if (
            direction != pending.direction
            or dagger is None
            or throwable_dagger((dagger,)) is None
        ):
            return cancel
        message = observation.message.strip()
        if memory.throw_stage == "item":
            match = _ITEM_PROMPT.fullmatch(message)
            if match is not None and _offered_letter(pending.letter, match.group(1)):
                return replace(pending, command=ord(pending.letter))
        elif memory.throw_stage == "direction" and message == "In what direction?":
            return replace(pending, command=_DIRECTION_COMMANDS[pending.direction])
        return cancel
    if observation.prompt.active or _UNSAFE_CONDITIONS.intersection(
        observation.player.conditions
    ):
        return None
    if (
        memory.ranged_waits < WAIT_ALLOWANCE
        or memory.ranged_total_attempts >= LEVEL_ATTEMPT_LIMIT
    ):
        return None
    point = _route_blocker(memory, goal)
    if point is None:
        return None
    direction = _safe_target(observation, memory, point)
    if direction is None:
        return None
    monster = memory.monsters[point]
    key = (*point, monster.glyph)
    if memory.ranged_attempts.get(key, 0) >= TARGET_ATTEMPT_LIMIT:
        return None
    if (
        observation.player.turn
        - memory.ranged_last_turn.get(key, -ATTEMPT_COOLDOWN_TURNS)
        < ATTEMPT_COOLDOWN_TURNS
    ):
        return None
    dagger = throwable_dagger(observation.inventory)
    if dagger is None:
        return None
    return ThrowEvidence(dagger.letter, MapCell(*point), direction, ord("t"))


def record_throw(memory, evidence):
    """Commit once, via ActionRecord, identically in live play and replay."""
    if evidence.command == 27:
        memory.pending_throw = None
        memory.throw_stage = None
    elif memory.pending_throw is None:
        point = (evidence.target.x, evidence.target.y)
        monster = memory.monsters.get(point)
        if monster is None:
            return
        key = (*point, monster.glyph)
        memory.ranged_attempts[key] = memory.ranged_attempts.get(key, 0) + 1
        memory.ranged_last_turn[key] = memory.ranged_turn
        memory.ranged_total_attempts += 1
        memory.pending_throw = evidence
        memory.throw_stage = "item"
    elif memory.throw_stage == "item":
        memory.throw_stage = "direction"
    else:
        memory.pending_throw = None
        memory.throw_stage = None


def throw_at_blocker(observation, memory, actions_by_command, goal=None):
    evidence = expected_throw(observation, memory, goal)
    if evidence is None or evidence.command not in actions_by_command:
        return None
    return SkillAction(
        actions_by_command[evidence.command].index,
        "Cancel changed ranged evidence."
        if evidence.command == 27
        else f"Clear the hostile route blocker at ({evidence.target.x}, {evidence.target.y}) with a bounded dagger throw.",
        ActionRecord(ActionKind.OTHER, memory.position, throw=evidence),
        ActionIntent(None, None, None, throw=evidence),
    )


def throw_action_error(action, selection, before=None, memory=None):
    evidence = (
        None
        if selection is None or selection.intent is None
        else selection.intent.throw
    )
    if evidence is None:
        intent = None if selection is None else selection.intent
        other_prompt = (
            intent is not None
            and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
            and any((intent.food, intent.drop, intent.corpse))
        )
        if action.name == "Command.THROW" and not other_prompt:
            return "THROW requires deterministic ranged evidence"
        return None
    if selection.skill is not Skill.RANGED_THROW:
        return "only ranged clearance carries throw evidence"
    if action.command != evidence.command:
        return "throw action does not match its evidence command"
    # Check name/command identity too, not merely a forged command field.
    from nethack_agent.tasks import ActionProfile

    valid = {
        f"{member.__class__.__name__}.{member.name}": int(member)
        for member in ActionProfile.NLE_SURVIVAL_ACTIONS.actions
    }
    if valid.get(action.name) != action.command:
        return "throw action name and command disagree"
    if selection.source not in (
        ActionSelectionSource.DETERMINISTIC_SKILL,
        ActionSelectionSource.DETERMINISTIC_PROMPT,
    ):
        return "ranged clearance is never model-owned"
    if (
        selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
        and evidence.command != ord("t")
    ):
        return "only THROW initiates ranged clearance"
    if (
        selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
        and evidence.command
        not in {ord(evidence.letter), _DIRECTION_COMMANDS[evidence.direction], 27}
    ):
        return "invalid ranged prompt answer"
    if before is not None and memory is not None:
        if expected_throw(before, memory, selection.goal) != evidence:
            return "throw target, safety, prompt ownership or budget changed"
        source = (
            ActionSelectionSource.DETERMINISTIC_PROMPT
            if before.prompt.active
            else ActionSelectionSource.DETERMINISTIC_SKILL
        )
        if selection.source is not source:
            return "throw source does not match prompt ownership"
    return None
