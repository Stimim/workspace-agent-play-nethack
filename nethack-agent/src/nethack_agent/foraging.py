"""Reviewed non-shop floor meals and bounded unburdened collection."""

from __future__ import annotations

from dataclasses import dataclass

from nethack_agent.decision import (
    ActionIntent,
    ActionSelection,
    ActionSelectionSource,
    DestinationKind,
    FoodEvidence,
    IntentDestination,
    MapCell,
    Skill,
)
from nethack_agent.environment import LegalAction
from nethack_agent.food import (
    food_description_name,
    food_underfoot_name,
    glyph_food_name,
    is_floor_eat_prompt,
    parse_floor_food_prompt,
    safe_food_name,
)
from nethack_agent.navigation import (
    MOVE_ACTION_NAMES,
    ActionKind,
    ActionRecord,
    LevelMemory,
    route_tree,
)
from nethack_agent.observation import ProjectedObservation
from nethack_agent.skills import SkillAction, _route_step, item_selection_commands

MAX_FOOD_ROUTE = 5


@dataclass(frozen=True, slots=True)
class FoodPermit:
    evidence: FoodEvidence
    arrived: FoodEvidence | None = None
    pending: FoodEvidence | None = None


def eligible_food(
    cell: MapCell,
    observation: ProjectedObservation,
    memory: LevelMemory,
    *,
    arrived: FoodEvidence | None = None,
) -> FoodEvidence | None:
    x, y = cell.x, cell.y
    if (
        observation.prompt.active
        or (x, y) in memory.shop_cells
        or not (
            0 <= y < len(observation.map.glyph_rows)
            and 0 <= x < len(observation.map.glyph_rows[y])
        )
    ):
        return None
    reached = False
    if (x, y) == (observation.player.x, observation.player.y):
        name = food_underfoot_name(observation.message)
        if (
            name is None
            and observation.message
            in (
                "",
                "There are several objects here.",
                "There are many objects here.",
            )
            and arrived is not None
            and arrived.cell == cell
        ):
            name, reached = arrived.name, True
    else:
        name = glyph_food_name(observation.map.glyph_rows[y][x])
    if name is None or not safe_food_name(name, observation):
        return None
    if observation.player.encumbrance != 0 and observation.player.hunger < 2:
        return None
    return FoodEvidence(name, cell, reached)


def food_prompt_command(
    observation: ProjectedObservation,
    evidence: FoodEvidence,
    memory: LevelMemory,
) -> int | None:
    valid = (
        (observation.player.x, observation.player.y)
        == (evidence.cell.x, evidence.cell.y)
        and (evidence.cell.x, evidence.cell.y) not in memory.shop_cells
        and safe_food_name(evidence.name, observation)
    )
    menu = observation.pickup_menu
    if menu is not None:
        if not valid or observation.player.encumbrance != 0:
            return 27
        selected = [item for item in menu.choices if item.selected]
        if selected:
            return (
                13
                if all(
                    food_description_name(item.description) == evidence.name
                    for item in selected
                )
                else 27
            )
        offered = [
            item
            for item in menu.choices
            if food_description_name(item.description) == evidence.name
        ]
        if offered:
            return ord(offered[0].letter)
        return ord(">") if menu.page < menu.pages else 27
    if observation.prompt.single_character_choice and is_floor_eat_prompt(
        observation.message
    ):
        return (
            ord("y")
            if (
                valid
                and observation.player.hunger >= 2
                and parse_floor_food_prompt(observation.message) == evidence.name
            )
            else ord("n")
        )
    if item_selection_commands(observation) is not None:
        return 27
    return None


def food_action_error(
    action: LegalAction,
    selection: ActionSelection,
    observation: ProjectedObservation,
    memory: LevelMemory | None,
    *,
    arrived: FoodEvidence | None = None,
    pending: FoodEvidence | None = None,
) -> str | None:
    """The execution gate and replay auditor share every new food predicate."""
    intent = selection.intent
    if (
        memory is None
        or intent is None
        or intent.food is None
        or selection.skill is not Skill.HUNGER
    ):
        return "floor food requires deterministic reviewed food evidence and map memory"
    if intent.level != memory.level:
        return "floor food evidence belongs to a different or unrecorded level"
    evidence = intent.food
    if selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT:
        if pending != evidence or action.command != food_prompt_command(
            observation, evidence, memory
        ):
            return (
                "food prompt answer does not match the preceding food "
                "action and exact public offer"
            )
        return None
    if selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL:
        return "floor food requires a deterministic food decision"
    if eligible_food(evidence.cell, observation, memory, arrived=arrived) != evidence:
        return "floor food identity or non-shop evidence is no longer supported"
    target = (evidence.cell.x, evidence.cell.y)
    if target == memory.position:
        if (
            intent.destination is not None
            or intent.path is not None
            or intent.attack_target is not None
        ):
            return "floor food command cannot carry a route or attack"
        expected = (
            "Command.PICKUP" if observation.player.encumbrance == 0 else "Command.EAT"
        )
        if action.name != expected or (
            expected == "Command.EAT" and observation.player.hunger < 2
        ):
            return (
                "collect food only unburdened; otherwise eat it only at Hungry or worse"
            )
        return None
    route = route_tree(memory).route(target)
    if route is None or not 1 <= len(route) <= MAX_FOOD_ROUTE:
        return "floor food route is not cheap and reachable"
    first = route[0]
    if (
        intent.destination != IntentDestination(DestinationKind.FOOD, *target)
        or intent.path != tuple(MapCell(*point) for point in route)
        or action.name
        != MOVE_ACTION_NAMES[
            (first[0] - memory.position[0], first[1] - memory.position[1])
        ]
    ):
        return "food route does not follow its recorded bounded path"
    return None


class FoodSkill:
    @staticmethod
    def select_action(
        observation: ProjectedObservation,
        memory: LevelMemory,
        actions: dict[str, LegalAction],
        commands: dict[int, LegalAction],
        *,
        arrived: FoodEvidence | None = None,
        pending: FoodEvidence | None = None,
    ) -> SkillAction | None:
        if pending is not None:
            command = food_prompt_command(observation, pending, memory)
            action = None if command is None else commands.get(command)
            if action is not None:
                return SkillAction(
                    action.index,
                    "Answer only the exact reviewed floor food offer.",
                    ActionRecord(ActionKind.OTHER, memory.position),
                    ActionIntent(None, None, None, food=pending),
                )
            return None
        if observation.prompt.active:
            return None
        candidates = []
        tree = route_tree(memory)
        for point in memory.objects | {memory.position}:
            evidence = eligible_food(
                MapCell(*point), observation, memory, arrived=arrived
            )
            if evidence is None:
                continue
            distance = tree.distances.get(point)
            if distance is not None and distance <= MAX_FOOD_ROUTE:
                candidates.append((distance, point[1], point[0], evidence))
        if not candidates:
            return None
        _, y, x, evidence = min(candidates)
        if (x, y) == memory.position:
            name = (
                "Command.PICKUP"
                if observation.player.encumbrance == 0
                else "Command.EAT"
            )
            action = actions.get(name)
            if action is None:
                return None
            return SkillAction(
                action.index,
                f"Recover the reviewed non-shop {evidence.name} underfoot.",
                ActionRecord(ActionKind.OTHER, memory.position),
                ActionIntent(None, None, None, food=evidence),
            )
        return _route_step(
            memory,
            tree.route((x, y)),
            actions,
            f"Approach the reviewed non-shop {evidence.name} within five steps.",
            IntentDestination(DestinationKind.FOOD, x, y),
            food=evidence,
        )
