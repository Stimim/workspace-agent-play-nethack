from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from nle import nethack

from nethack_agent.decision import (
    STAIR_DESTINATIONS,
    ActionIntent,
    DestinationKind,
    IntentDestination,
    MapCell,
    StuckReason,
)
from nethack_agent.environment import LegalAction
from nethack_agent.navigation import (
    MOVE_ACTION_NAMES,
    ORTHOGONAL_DELTAS,
    ActionKind,
    ActionRecord,
    CellKind,
    LevelMemory,
    Point,
    RouteTree,
    route_tree,
)
from nethack_agent.observation import (
    BucStatus,
    InventoryItem,
    ProjectedObservation,
)
from nethack_agent.traversal import (
    DUNGEONS_OF_DOOM,
    STAND_ON_DOWNSTAIRS,
    Goal,
    LevelKey,
    StairDirection,
    StairTarget,
    TraverseStairsGoal,
    candidate_tier,
)

# Each search finds an adjacent hidden door or corridor with probability 1/7
# at Luck 0 (NetHackWiki "Search"); ten searches find it about 79% of the time.
SEARCHES_PER_ROUND: Final = 10
MONSTER_WAIT_LIMIT: Final = 8
KICKS_PER_DOOR: Final = 8
SEARCH_DENSITY_RADIUS: Final = 4
MIN_SEARCH_SCORE: Final = 20
SEARCH_DISTANCE_WEIGHT: Final = 2
# Kicking doors is safe only where no shopkeeper or town watch can exist:
# shops are generated below dungeon level 1 and Minetown is in the Mines.
KICK_SAFE_LEVEL: Final = LevelKey(DUNGEONS_OF_DOOM, 1)
_FRONTIER_PASSAGES: Final = frozenset(
    {
        CellKind.DOORWAY,
        CellKind.OPEN_DOOR,
        CellKind.CLOSED_DOOR,
        CellKind.CORRIDOR,
    }
)

_INVENTORY_LETTERS: Final = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_SAFE_RATION_DESCRIPTION: Final = re.compile(
    r"^(?P<count>a|an|the|[1-9]\d*) "
    r"(?:(?P<buc>blessed|uncursed|cursed) )?"
    r"(?:(?P<enchantment>[+-]\d+) )?"
    r"(?P<name>food ration|food rations)$"
)
_ITEM_SELECTION_PROMPT: Final = re.compile(
    r"^What do you want to eat\? \[(?P<letters>[A-Za-z]+) or \?\*\]$"
)


@dataclass(frozen=True, slots=True)
class SkillAction:
    action_index: int
    rationale: str
    record: ActionRecord
    # The map targets behind this action; None when it has none (prompt
    # answers).
    intent: ActionIntent | None


@dataclass(frozen=True, slots=True)
class ExploreResult:
    """Either one exploration action or the reason exploration is stuck."""

    action: SkillAction | None
    stuck: StuckReason | None

    def __post_init__(self) -> None:
        if (self.action is None) == (self.stuck is None):
            raise ValueError("exploration returns exactly one action or stuck reason")


_STAIR_NAMES: Final = {
    StairDirection.DOWN: "downstairs",
    StairDirection.UP: "upstairs",
}


def stair_candidates(memory: LevelMemory, target: StairTarget) -> dict[Point, int]:
    """Remembered staircases compatible with `target`, mapped to their tier.

    Tier 0 is an established match and tier 1 a probe of a staircase whose
    identity is not established (ADR 0004).
    """
    pair_known = memory.pair_known(target.direction)
    candidates: dict[Point, int] = {}
    for stair in memory.stairs(target.direction):
        tier = candidate_tier(target, memory.identity(stair), pair_known=pair_known)
        if tier is not None:
            candidates[stair] = tier
    return candidates


class StaircaseNavigationSkill:
    """Route to a remembered staircase matching the goal, then wait or use it.

    Candidates rank by tier (established before probe), then route distance,
    then map row and column. A stand_on_stairs goal waits on the chosen
    staircase; a traverse_stairs goal uses it with the level-change action,
    which only the coordinator's traversal permit lets through the gate.
    """

    def select_action(
        self,
        memory: LevelMemory,
        actions_by_name: dict[str, LegalAction],
        goal: Goal = STAND_ON_DOWNSTAIRS,
        level_change: LegalAction | None = None,
    ) -> SkillAction | None:
        target = goal.target
        candidates = stair_candidates(memory, target)
        if not candidates:
            return None
        name = _STAIR_NAMES[target.direction]
        kind = STAIR_DESTINATIONS[target.direction]
        origin = memory.position
        tree = route_tree(memory)
        chosen = _best_stair(tree, candidates)
        blocked: RouteTree | None = None
        if chosen is None:
            blocked = route_tree(memory, through_monsters=True)
            chosen = _best_stair(blocked, candidates)
            if chosen is None:
                return None
        destination = IntentDestination(
            kind,
            *chosen,
            memory.identity(chosen),
            memory.pair_known(target.direction),
        )
        if chosen == origin:
            here = ActionIntent(destination, None, None)
            defense = _attack_adjacent_hostile(memory, actions_by_name, destination)
            if defense is not None:
                return defense
            if isinstance(goal, TraverseStairsGoal):
                if level_change is None:
                    return None
                return SkillAction(
                    level_change.index,
                    f"Use the {name} at {_cell(origin)} "
                    f"({memory.identity(origin).kind.value} identity) for goal "
                    f"{goal.token}.",
                    ActionRecord(ActionKind.TRAVERSE, origin),
                    here,
                )
            wait = actions_by_name.get("MiscDirection.WAIT")
            if wait is None:
                return None
            return SkillAction(
                wait.index,
                f"Wait safely while already standing on the {name}.",
                ActionRecord(ActionKind.OTHER, origin),
                here,
            )
        if blocked is None and tree.distances[chosen] == 1:
            # Stepping onto the staircase completes or enables the goal at
            # once; that beats any fight.
            return _route_step(
                memory,
                tree.route(chosen),
                actions_by_name,
                f"Step onto the {name} at {_cell(chosen)}.",
                destination,
            )
        defense = _attack_adjacent_hostile(memory, actions_by_name, destination)
        if defense is not None:
            return defense
        if blocked is None:
            return _route_step(
                memory,
                tree.route(chosen),
                actions_by_name,
                f"Follow the known route to the {name} at {_cell(chosen)} "
                f"({tree.distances[chosen]} steps).",
                destination,
            )
        return _past_monster(
            memory, blocked, actions_by_name, chosen, name, destination
        )


class ExploreLevelSkill:
    """Frontier exploration, door handling, and bounded searching on one level."""

    def continue_kick(
        self,
        observation: ProjectedObservation,
        memory: LevelMemory,
        actions_by_name: dict[str, LegalAction],
    ) -> SkillAction | None:
        """Answer the direction prompt that follows this skill's kick command."""
        door = memory.pending_kick
        if (
            door is None
            or not observation.prompt.single_character_choice
            or "direction" not in observation.message.lower()
        ):
            return None
        origin = memory.position
        name = MOVE_ACTION_NAMES.get((door[0] - origin[0], door[1] - origin[1]))
        action = actions_by_name.get(name) if name else None
        if action is None:
            return None
        return SkillAction(
            action.index,
            f"Direct the kick at the locked door at {_cell(door)}.",
            ActionRecord(ActionKind.KICK_DIRECTION, origin, door),
            _toward(DestinationKind.LOCKED_DOOR, door),
        )

    def select_action(
        self,
        memory: LevelMemory,
        actions_by_name: dict[str, LegalAction],
        target: StairTarget = STAND_ON_DOWNSTAIRS.target,
    ) -> ExploreResult:
        """Explore, biased toward remembered staircases compatible with `target`."""
        defense = _attack_adjacent_hostile(memory, actions_by_name, None)
        if defense is not None:
            return ExploreResult(defense, None)
        stairs = tuple(stair_candidates(memory, target))
        tree = route_tree(memory)
        goal = _frontier_goal(memory, tree, stairs)
        if goal is not None:
            action = _route_step(
                memory,
                tree.route(goal),
                actions_by_name,
                f"Explore toward unexplored space next to {_cell(goal)} "
                f"({tree.distances[goal]} steps).",
                IntentDestination(DestinationKind.FRONTIER, *goal),
            )
            if action is not None:
                return ExploreResult(action, None)

        blocked_by_monster = False
        through = route_tree(memory, through_monsters=True)
        goal = _frontier_goal(memory, through, stairs)
        if goal is not None:
            action = _past_monster(
                memory,
                through,
                actions_by_name,
                goal,
                "unexplored space",
                IntentDestination(DestinationKind.FRONTIER, *goal),
            )
            if action is not None:
                return ExploreResult(action, None)
            blocked_by_monster = True

        action = _kick_locked_door(memory, tree, actions_by_name)
        if action is None:
            action = _search(memory, tree, actions_by_name)
        if action is not None:
            return ExploreResult(action, None)
        return ExploreResult(
            None,
            StuckReason.MONSTER_BLOCKED
            if blocked_by_monster
            else StuckReason.SEARCH_EXHAUSTED,
        )


def is_safe_food_ration(item: InventoryItem) -> bool:
    """Whether typed inventory evidence names exactly a food-ration stack."""
    if item.letter not in _INVENTORY_LETTERS or item.object_class != int(
        nethack.FOOD_CLASS
    ):
        return False
    match = _SAFE_RATION_DESCRIPTION.fullmatch(item.description)
    if match is None:
        return False
    count = match.group("count")
    plural = match.group("name") == "food rations"
    if count.isdigit():
        if (int(count) == 1) == plural:
            return False
    elif plural:
        return False
    described_buc = match.group("buc")
    expected_buc = (
        BucStatus.UNKNOWN if described_buc is None else BucStatus(described_buc)
    )
    return item.buc is expected_buc


def safe_food_rations(
    observation: ProjectedObservation,
) -> tuple[InventoryItem, ...]:
    return tuple(
        sorted(
            (item for item in observation.inventory if is_safe_food_ration(item)),
            key=lambda item: item.letter,
        )
    )


def item_selection_commands(
    observation: ProjectedObservation,
) -> frozenset[int] | None:
    """Literal inventory letters offered by the exact NLE eat-item prompt."""
    if not observation.prompt.single_character_choice:
        return None
    match = _ITEM_SELECTION_PROMPT.fullmatch(observation.message.strip())
    if match is None:
        return None
    return frozenset(ord(letter) for letter in match.group("letters"))


def _same_ration(first: InventoryItem, second: InventoryItem) -> bool:
    return (
        first.description == second.description
        and first.glyph == second.glyph
        and first.object_class == second.object_class
        and first.buc is second.buc
    )


class HungerSkill:
    """Eat one known food ration at Hungry or worse, then answer its one prompt."""

    def __init__(self) -> None:
        self._pending: InventoryItem | None = None

    def reset(self) -> None:
        self._pending = None

    def select_action(
        self,
        observation: ProjectedObservation,
        actions_by_name: dict[str, LegalAction],
        actions_by_command: dict[int, LegalAction],
    ) -> SkillAction | None:
        origin = (observation.player.x, observation.player.y)
        if self._pending is not None:
            pending = self._pending
            self._pending = None
            if not observation.prompt.active:
                return None
            offered = item_selection_commands(observation)
            if offered is None:
                return None
            if offered:
                matches = tuple(
                    item
                    for item in safe_food_rations(observation)
                    if _same_ration(pending, item)
                )
                if len(matches) == 1:
                    letter = matches[0].letter
                    action = actions_by_command.get(ord(letter))
                    if ord(letter) in offered and action is not None:
                        return SkillAction(
                            action.index,
                            "Select the verified food ration in inventory slot "
                            f"{letter}.",
                            ActionRecord(ActionKind.OTHER, origin),
                            None,
                        )
            cancel = actions_by_command.get(27)
            if cancel is not None:
                return SkillAction(
                    cancel.index,
                    "Cancel the item prompt because its ration evidence changed.",
                    ActionRecord(ActionKind.OTHER, origin),
                    None,
                )
            return None

        offered = item_selection_commands(observation)
        if offered is not None:
            cancel = actions_by_command.get(27)
            if cancel is not None:
                return SkillAction(
                    cancel.index,
                    "Cancel an item prompt not started by the bounded hunger skill.",
                    ActionRecord(ActionKind.OTHER, origin),
                    None,
                )
            return None
        if observation.prompt.active or observation.player.hunger < 2:
            return None
        rations = safe_food_rations(observation)
        eat = actions_by_name.get("Command.EAT")
        if not rations or eat is None:
            return None
        self._pending = rations[0]
        return SkillAction(
            eat.index,
            "Eat the first verified inventory food ration because hunger is Hungry "
            "or worse.",
            ActionRecord(ActionKind.OTHER, origin),
            None,
        )


class SafePromptHandler:
    """Answer only prompts with a conservative context-independent response."""

    @staticmethod
    def select_action(
        observation: ProjectedObservation,
        actions_by_name: dict[str, LegalAction],
        actions_by_command: dict[int, LegalAction],
    ) -> SkillAction | None:
        prompt = observation.prompt
        origin = (observation.player.x, observation.player.y)
        if prompt.wait_for_space or prompt.text_input:
            action = actions_by_name.get("MiscAction.MORE")
            if action is None:
                return None
            reason = (
                "Acknowledge the wait-for-space prompt."
                if prompt.wait_for_space
                else "Submit empty text to cancel the text-input prompt safely."
            )
            return SkillAction(
                action.index, reason, ActionRecord(ActionKind.OTHER, origin), None
            )
        if prompt.single_character_choice:
            message = observation.message.lower()
            if "[yn" not in message and "(y/n" not in message:
                return None
            action = actions_by_command.get(ord("n"))
            if action is None:
                return None
            return SkillAction(
                action.index,
                "Decline the yes/no prompt safely.",
                ActionRecord(ActionKind.OTHER, origin),
                None,
            )
        return None


def _cell(point: Point) -> str:
    return f"({point[0]}, {point[1]})"


def _toward(kind: DestinationKind, point: Point) -> ActionIntent:
    """An intent for an action taken in place, so no route is followed."""
    return ActionIntent(IntentDestination(kind, *point), None, None)


def _best_stair(tree: RouteTree, candidates: dict[Point, int]) -> Point | None:
    """The reachable candidate with the lowest tier, distance, row, and column."""
    reachable = [
        (tier, tree.distances[stair], stair[1], stair[0], stair)
        for stair, tier in candidates.items()
        if stair in tree.distances
    ]
    return min(reachable)[4] if reachable else None


def _route_step(
    memory: LevelMemory,
    route: tuple[Point, ...] | None,
    actions_by_name: dict[str, LegalAction],
    rationale: str,
    destination: IntentDestination,
    *,
    attack_target: MapCell | None = None,
    search_spot: Point | None = None,
) -> SkillAction | None:
    """Take the first step of `route`, whose last cell is the route goal."""
    if route is None:
        return None
    step = route[0]
    goal = route[-1]
    origin = memory.position
    action = actions_by_name.get(
        MOVE_ACTION_NAMES[(step[0] - origin[0], step[1] - origin[1])]
    )
    if action is None:
        return None
    intent = ActionIntent(
        destination, attack_target, tuple(MapCell(*point) for point in route)
    )
    monster = memory.monsters.get(step)
    if memory.kind(step) is CellKind.CLOSED_DOOR:
        return SkillAction(
            action.index,
            f"Open the closed door at {_cell(step)} by moving into it; {rationale}",
            ActionRecord(ActionKind.OPEN_DOOR, origin, step, None, goal, search_spot),
            intent,
        )
    return SkillAction(
        action.index,
        rationale,
        ActionRecord(
            ActionKind.MOVE,
            origin,
            step,
            monster.glyph if monster is not None else None,
            goal,
            search_spot,
        ),
        intent,
    )


def _attack_adjacent_hostile(
    memory: LevelMemory,
    actions_by_name: dict[str, LegalAction],
    destination: IntentDestination | None,
) -> SkillAction | None:
    """Fight back against an adjacent displayed monster that may be meleed.

    Pets, monsters that answered a "Really attack?" prompt (peaceful), and
    passive-damage monsters are excluded. NetHack resolves an attack before
    its movement rules, so diagonal attacks out of doorways are allowed.
    `destination` is the calling skill's already chosen route goal, if any.
    """
    origin = memory.position
    for point in sorted(memory.neighbors(origin), key=lambda p: (p[1], p[0])):
        monster = memory.hostile_blocker(point)
        if monster is None:
            continue
        action = actions_by_name.get(
            MOVE_ACTION_NAMES[(point[0] - origin[0], point[1] - origin[1])]
        )
        if action is None:
            continue
        return SkillAction(
            action.index,
            f"Attack the adjacent {monster.name} at {_cell(point)} before exploring.",
            ActionRecord(ActionKind.MOVE, origin, point, monster.glyph),
            ActionIntent(destination, MapCell(*point), None),
        )
    return None


def _past_monster(
    memory: LevelMemory,
    tree: RouteTree,
    actions_by_name: dict[str, LegalAction],
    goal: Point,
    purpose: str,
    destination: IntentDestination,
) -> SkillAction | None:
    """Advance on a route that is blocked only by displayed monsters."""
    route = tree.route(goal)
    if route is None:
        return None
    step = route[0]
    monster = memory.monsters.get(step)
    if monster is None:
        return _route_step(
            memory,
            route,
            actions_by_name,
            f"Approach the {purpose} near {_cell(goal)} along a route a monster "
            "currently blocks further ahead.",
            destination,
        )
    if memory.hostile_blocker(step) is not None:
        # NLE's Staircase action set has no fight command; moving into a
        # displayed hostile monster attacks it.
        return _route_step(
            memory,
            route,
            actions_by_name,
            f"Attack the {monster.name} blocking the route to the {purpose} "
            f"near {_cell(goal)} by moving into it.",
            destination,
            attack_target=MapCell(*step),
        )
    search = actions_by_name.get("Command.SEARCH")
    if search is None or memory.monster_waits >= MONSTER_WAIT_LIMIT:
        return None
    return SkillAction(
        search.index,
        f"Wait in place for the {monster.name} blocking the route to the "
        f"{purpose} to move; it is peaceful or unsafe to melee.",
        ActionRecord(ActionKind.WAIT, memory.position),
        ActionIntent(destination, None, None),
    )


def _frontier_goal(
    memory: LevelMemory, tree: RouteTree, stairs: tuple[Point, ...]
) -> Point | None:
    """Nearest reachable known cell next to space the hero has never observed.

    Passages (doorways, doors, and corridors) win distance ties over room
    floor. A remembered but unreachable downstairs biases the search toward it.
    """
    best: tuple[int, int, int, int] | None = None
    goal: Point | None = None
    for point, distance in tree.distances.items():
        if point in memory.abandoned_goals:
            continue
        if not any(memory.unexplored(near) for near in memory.neighbors(point)):
            continue
        bias = (
            min(max(abs(point[0] - s[0]), abs(point[1] - s[1])) for s in stairs)
            if stairs
            else 0
        )
        rank = 0 if memory.kind(point) in _FRONTIER_PASSAGES else 1
        key = (distance + bias, rank, point[1], point[0])
        if best is None or key < best:
            best = key
            goal = point
    return goal


def _kick_locked_door(
    memory: LevelMemory, tree: RouteTree, actions_by_name: dict[str, LegalAction]
) -> SkillAction | None:
    """Kick a known-locked door that is the only way into unexplored space."""
    kick = actions_by_name.get("Command.KICK")
    if kick is None or memory.level != KICK_SAFE_LEVEL:
        return None
    candidates: list[tuple[int, int, int, Point, Point]] = []
    for door in sorted(memory.locked_doors):
        if (
            memory.kind(door) is not CellKind.CLOSED_DOOR
            or door in memory.monsters
            or memory.kicks.get(door, 0) >= KICKS_PER_DOOR
            or not any(memory.unexplored(near) for near in memory.neighbors(door))
        ):
            continue
        for dx, dy in ORTHOGONAL_DELTAS:
            stand = (door[0] + dx, door[1] + dy)
            if stand in tree.distances and stand not in memory.monsters:
                candidates.append(
                    (tree.distances[stand], stand[1], stand[0], stand, door)
                )
    if not candidates:
        return None
    _, _, _, stand, door = min(candidates)
    origin = memory.position
    if stand == origin:
        return SkillAction(
            kick.index,
            f"Kick the locked door at {_cell(door)}: no other unexplored space is "
            "reachable, and dungeon level 1 has no shopkeeper or watch to anger.",
            ActionRecord(ActionKind.KICK, origin, door),
            _toward(DestinationKind.LOCKED_DOOR, door),
        )
    return _route_step(
        memory,
        tree.route(stand),
        actions_by_name,
        f"Move beside the locked door at {_cell(door)} to kick it open.",
        IntentDestination(DestinationKind.LOCKED_DOOR, *door),
    )


def _search(
    memory: LevelMemory,
    tree: RouteTree,
    actions_by_name: dict[str, LegalAction],
) -> SkillAction | None:
    """Search at the reachable spot facing the most unexplored space.

    Spots are room cells beside straight walls (secret doors) and corridor
    dead ends (secret corridors). Every search covers the eight adjacent
    cells; a cell stops counting once searched `SEARCHES_PER_ROUND` times per
    round, so candidates rotate as coverage grows. The chosen spot stays
    committed until it is spent or unreachable, so travel does not dither
    between spots whose scores shift as walking reveals the map.
    """
    search = actions_by_name.get("Command.SEARCH")
    if search is None:
        return None
    budget = SEARCHES_PER_ROUND * (memory.search_round + 1)
    density = _UnexploredDensity(memory, SEARCH_DENSITY_RADIUS)

    def evaluate(point: Point) -> tuple[int, int] | None:
        if point in memory.monsters or memory.kind(point) is CellKind.CLOSED_DOOR:
            return None
        targets = [
            target
            for target in _search_targets(memory, point)
            if memory.search_coverage.get(target, 0) < budget
        ]
        score = sum(density.around(target) for target in targets)
        if score < MIN_SEARCH_SCORE:
            return None
        return score, min(memory.search_coverage.get(target, 0) for target in targets)

    spot = memory.search_goal
    evaluation = (
        evaluate(spot)
        if spot is not None
        and spot in tree.distances
        and spot not in memory.abandoned_goals
        else None
    )
    if evaluation is None:
        spot = None
        best: tuple[int, int, int, int] | None = None
        for point, distance in tree.distances.items():
            if point in memory.abandoned_goals:
                continue
            candidate = evaluate(point)
            if candidate is None:
                continue
            key = (
                -(candidate[0] - SEARCH_DISTANCE_WEIGHT * distance),
                distance,
                point[1],
                point[0],
            )
            if best is None or key < best:
                best = key
                spot = point
                evaluation = candidate
    if spot is None or evaluation is None:
        return None
    origin = memory.position
    if spot == origin:
        return SkillAction(
            search.index,
            f"Search for hidden passages at {_cell(spot)} "
            f"(least-searched neighbour {evaluation[1]}/{budget}).",
            ActionRecord(ActionKind.SEARCH, origin, search_spot=spot),
            _toward(DestinationKind.SEARCH_SPOT, spot),
        )
    return _route_step(
        memory,
        tree.route(spot),
        actions_by_name,
        f"Move to search spot {_cell(spot)} ({tree.distances[spot]} steps); "
        "no reachable unexplored space remains.",
        IntentDestination(DestinationKind.SEARCH_SPOT, *spot),
        search_spot=spot,
    )


def _search_targets(memory: LevelMemory, point: Point) -> tuple[Point, ...]:
    """Cells a search from `point` could reveal as hidden passages.

    Corridor dead ends (including corridor cells whose terrain is inferred
    from an object or a footstep) target their blank neighbours; room cells
    target adjacent straight walls, where secret doors are generated.
    """
    kind = memory.kind(point)
    inferred = kind is CellKind.FLOOR and memory.cmap(point) <= 0
    if kind is CellKind.CORRIDOR or inferred:
        if not _dead_end(memory, point):
            return ()
        return tuple(
            near
            for near in memory.neighbors(point)
            if memory.kind(near) is CellKind.UNKNOWN
        )
    if kind in (CellKind.FLOOR, CellKind.DOORWAY):
        return tuple(
            near for near in memory.neighbors(point) if memory.straight_wall(near)
        )
    return ()


def _dead_end(memory: LevelMemory, point: Point) -> bool:
    """All exits of `point` touch each other, so the passage ends here."""
    exits = [
        near
        for near in memory.neighbors(point)
        if memory.passable(near) or memory.kind(near) is CellKind.CLOSED_DOOR
    ]
    return bool(exits) and all(
        max(abs(first[0] - second[0]), abs(first[1] - second[1])) <= 1
        for first in exits
        for second in exits
    )


class _UnexploredDensity:
    """Summed-area table of never-observed blank cells."""

    def __init__(self, memory: LevelMemory, radius: int) -> None:
        self._radius = radius
        self._width = memory.width
        self._height = memory.height
        table = [[0] * (memory.width + 1) for _ in range(memory.height + 1)]
        for y in range(memory.height):
            running = 0
            for x in range(memory.width):
                running += memory.unexplored((x, y))
                table[y + 1][x + 1] = table[y][x + 1] + running
        self._table = table

    def around(self, point: Point) -> int:
        left = max(point[0] - self._radius, 0)
        top = max(point[1] - self._radius, 0)
        right = min(point[0] + self._radius + 1, self._width)
        bottom = min(point[1] + self._radius + 1, self._height)
        table = self._table
        return (
            table[bottom][right]
            - table[top][right]
            - table[bottom][left]
            + table[top][left]
        )
