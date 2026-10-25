"""Finite, evidence-backed allowances for hidden-passage recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nethack_agent.decision import (
    ActionSelectionSource,
    DestinationKind,
    LocalRecoveryEvidence,
    MapCell,
    NavigationEvidence,
    Skill,
)
from nethack_agent.navigation import MOVE_ACTION_NAMES, CellKind, route_tree

if TYPE_CHECKING:
    from nethack_agent.decision import ActionSelection
    from nethack_agent.environment import LegalAction
    from nethack_agent.navigation import LevelMemory, Point, RouteTree
    from nethack_agent.observation import ProjectedObservation
    from nethack_agent.traversal import Goal, StairTarget

SEARCH_CANDIDATE_CAP: Final = 20
NO_PROGRESS_TURN_LIMIT: Final = 400
SEARCH_BATCH_SIZE: Final = 10
MONSTER_WAIT_LIMIT: Final = 8
# The two constants below govern ONLY the explicit explore_dungeon leg's
# unbounded, round-scored search (ExploreLevelGoal / `target is None`): each
# search finds an adjacent hidden door or corridor with probability 1/7 at
# Luck 0 (NetHackWiki "Search"); ten searches find it about 79% of the time.
# This is the unchanged original algorithm, not the finite place-objective
# budget below.
SEARCHES_PER_ROUND: Final = 10
MIN_SEARCH_SCORE: Final = 20
SEARCH_DISTANCE_WEIGHT: Final = 2
SEARCH_DENSITY_RADIUS: Final = 3


def navigation_turn_limit(memory: LevelMemory) -> int:
    level = memory.level
    protected = level is not None and (
        (
            memory.oracle_navigation
            and level.dungeon_number == 0
            and 5 <= level.dungeon_level <= 9
        )
        or (
            memory.target_conduct
            and level.dungeon_number == 2
            and level.dungeon_level in (3, 4)
        )
    )
    return NO_PROGRESS_TURN_LIMIT * (4 if protected else 1)


def navigation_available(memory: LevelMemory) -> bool:
    return memory.navigation_elapsed < navigation_turn_limit(memory)


def legacy_navigation(memory: LevelMemory, target: StairTarget | None) -> bool:
    """Whether the round-based legacy search and blocker waits govern.

    They govern explore_dungeon legs (no stair target) and stair travel
    whose time budget is spent. A spent level with a departure permit is
    left by the planner before exploration runs; one without (a hidden
    downstairs on Dlvl 1, a reach_level task) would otherwise wait
    forever instead of searching (0059 development pass, Minetown seed 1).
    """
    return target is None or not navigation_available(memory)


def navigation_spent(memory: LevelMemory) -> bool:
    """The level's time budget has run out at least once.

    Departure uses this, not `navigation_available`: walking to the exit
    reveals cells, which restarts the clock and would otherwise withdraw the
    permit and send the hero back to searching (0059 Minetown 1362 smoke).
    """
    peak = max(memory.navigation_elapsed_peak, memory.navigation_elapsed)
    return peak >= navigation_turn_limit(memory)


def search_pass_complete(memory: LevelMemory) -> bool:
    """Every reachable candidate hit the finite place-objective cap.

    Used only by `local_recovery_evidence`'s protected-level guard: a full,
    uncapped-by-density pass, not elapsed time or routing quarantine, proves
    nothing concealed remains worth the M3/Oracle objective's attention.
    """
    from nethack_agent.skills import _search_targets

    tree = route_tree(memory, through_monsters=True)
    if any(
        memory.unexplored(near)
        or (near in memory.monsters and memory.kind(near) is CellKind.UNKNOWN)
        for point in tree.distances
        for near in memory.neighbors(point)
    ):
        return False
    return all(
        memory.search_coverage.get(cell, 0) >= SEARCH_CANDIDATE_CAP
        for point in tree.distances
        if point not in memory.monsters
        and memory.kind(point) is not CellKind.CLOSED_DOOR
        for cell in _search_targets(memory, point)
    )


def _ordinary_route(memory: LevelMemory, target: StairTarget | None) -> bool:
    from nethack_agent.skills import _frontier_goal, stair_candidates

    tree = route_tree(memory)
    stairs = {} if target is None else stair_candidates(memory, target)
    return (
        any(point in tree.distances for point in stairs)
        or _frontier_goal(memory, tree, tuple(stairs)) is not None
    )


def legacy_search_candidate(
    memory: LevelMemory, tree: RouteTree
) -> tuple[Point, tuple[Point, ...], int] | None:
    """Original density-gated, round-scored candidate (explore_dungeon only).

    Unlike `search_candidate`, this grows with `memory.search_round` (a
    stuck consultation re-arms it) and gives up on a candidate whose nearby
    unexplored density falls below `MIN_SEARCH_SCORE`, instead of insisting
    on a fixed per-cell cap everywhere. Never used for place-objective
    travel, whose finite budget must not grow on re-arm.
    """
    from nethack_agent.skills import _search_targets, _UnexploredDensity

    budget = SEARCHES_PER_ROUND * (memory.search_round + 1)
    density = _UnexploredDensity(memory, SEARCH_DENSITY_RADIUS)

    def evaluate(point: Point) -> tuple[int, int, tuple[Point, ...]] | None:
        if point in memory.monsters or memory.kind(point) is CellKind.CLOSED_DOOR:
            return None
        targets = tuple(
            cell
            for cell in _search_targets(memory, point)
            if memory.search_coverage.get(cell, 0) < budget
        )
        score = sum(density.around(cell) for cell in targets)
        if score < MIN_SEARCH_SCORE:
            return None
        return (
            score,
            min(memory.search_coverage.get(cell, 0) for cell in targets),
            targets,
        )

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
    return spot, evaluation[2], budget


def legacy_search_evidence(memory: LevelMemory) -> NavigationEvidence | None:
    candidate = legacy_search_candidate(memory, route_tree(memory))
    if candidate is None or candidate[0] != memory.position:
        return None
    return _evidence(memory, "search", candidate[1])


def legacy_wait_evidence(
    memory: LevelMemory, blocker: Point
) -> NavigationEvidence | None:
    """Original unconditional blocker wait (explore_dungeon only): no
    time-budget or ordinary-route gate, just the finite wait counter."""
    if (
        memory.monster_waits >= MONSTER_WAIT_LIMIT
        or blocker not in memory.monsters
        or memory.hostile_blocker(blocker) is not None
        or max(
            abs(blocker[0] - memory.position[0]), abs(blocker[1] - memory.position[1])
        )
        != 1
    ):
        return None
    return _evidence(memory, "blocker_wait", (blocker,))


def search_candidate(
    memory: LevelMemory, tree: RouteTree
) -> tuple[Point, tuple[Point, ...]] | None:
    """Least-covered reachable stand, with commitment only while equally useful."""
    from nethack_agent.skills import (
        SEARCH_DENSITY_RADIUS,
        _search_targets,
        _UnexploredDensity,
    )

    density = _UnexploredDensity(memory, SEARCH_DENSITY_RADIUS)
    candidates = {}
    for point, distance in tree.distances.items():
        if (
            point in memory.abandoned_goals
            or point in memory.monsters
            or memory.kind(point) is CellKind.CLOSED_DOOR
        ):
            continue
        targets = tuple(
            cell
            for cell in _search_targets(memory, point)
            if memory.search_coverage.get(cell, 0) < SEARCH_CANDIDATE_CAP
        )
        if not targets:
            continue
        least = min(memory.search_coverage.get(cell, 0) for cell in targets)
        key = (
            least,
            -len(targets),
            -sum(density.around(cell) for cell in targets),
            distance,
            point[1],
            point[0],
        )
        candidates[point] = (key, targets)
    if not candidates:
        return None
    best = min(candidates, key=lambda point: candidates[point][0])
    committed = memory.search_goal
    batch_done = (
        memory.search_location == committed and memory.search_turns_remaining == 0
    )
    # An arrived stand is searched for one batch before rotating: leaving it
    # unsearched for a better-ranked stand crossed whole levels, and the
    # newly observed cells on each walk restarted the no-progress clock
    # (0059 development pass 2, Minetown 1360).
    if committed in candidates and (
        (memory.search_location == committed and memory.search_turns_remaining > 0)
        or (memory.position == committed and not batch_done)
        or (
            memory.position != committed
            and candidates[committed][0][0] == candidates[best][0][0]
        )
    ):
        best = committed
    return best, candidates[best][1]


def _evidence(
    memory: LevelMemory, kind: str, targets: tuple[Point, ...]
) -> NavigationEvidence:
    return NavigationEvidence(
        kind,
        MapCell(*memory.position),
        tuple(MapCell(*point) for point in targets),
        memory.knowledge,
        memory.navigation_elapsed,
        memory.monster_waits,
    )


def search_evidence(
    memory: LevelMemory, target: StairTarget | None = None
) -> NavigationEvidence | None:
    if legacy_navigation(memory, target):
        return legacy_search_evidence(memory)
    if _ordinary_route(memory, target):
        return None
    candidate = search_candidate(memory, route_tree(memory))
    if candidate is None or candidate[0] != memory.position:
        return None
    return _evidence(memory, "search", candidate[1])


def wait_evidence(
    memory: LevelMemory, blocker: Point, target: StairTarget | None = None
) -> NavigationEvidence | None:
    if legacy_navigation(memory, target):
        return legacy_wait_evidence(memory, blocker)
    if (
        memory.monster_waits >= MONSTER_WAIT_LIMIT
        or _ordinary_route(memory, target)
        or blocker not in memory.monsters
        or memory.hostile_blocker(blocker) is not None
        or max(
            abs(blocker[0] - memory.position[0]), abs(blocker[1] - memory.position[1])
        )
        != 1
    ):
        return None
    from nethack_agent.skills import _frontier_goal, stair_candidates

    tree = route_tree(memory, through_monsters=True)
    stairs = {} if target is None else stair_candidates(memory, target)
    frontier = _frontier_goal(memory, tree, tuple(stairs))
    goals = tuple(stairs) + (() if frontier is None else (frontier,))
    if not any(
        route is not None and route[0] == blocker
        for goal in goals
        if (route := tree.route(goal)) is not None
    ):
        return None
    return _evidence(memory, "blocker_wait", (blocker,))


def navigation_action_error(
    action: LegalAction,
    selection: ActionSelection,
    before: ProjectedObservation | None = None,
    memory: LevelMemory | None = None,
) -> str | None:
    """Validate recorded shapes, and live allowances when memory is available."""
    intent = selection.intent
    evidence = None if intent is None else intent.navigation
    is_search = action.name == "Command.SEARCH" and action.command == 115
    # A prompt's inventory letter 's' is not routine navigation.
    if (
        before is not None
        and before.prompt.active
        and evidence is None
        and selection.source is ActionSelectionSource.DETERMINISTIC_PROMPT
    ):
        return None
    if evidence is None:
        if (memory is not None or before is not None) and is_search:
            return "routine SEARCH requires navigation evidence"
        return None
    if not is_search:
        return "navigation evidence requires Command.SEARCH (115)"
    if selection.source is not ActionSelectionSource.DETERMINISTIC_SKILL:
        return "navigation evidence requires deterministic_skill source"
    if intent is None or any(
        value is not None
        for value in (
            intent.path,
            intent.attack_target,
            intent.prayer,
            intent.corpse,
            intent.food,
            intent.drop,
            intent.disengage,
        )
    ):
        return "navigation evidence cannot accompany another action"
    if before is not None and evidence.origin != MapCell(
        before.player.x, before.player.y
    ):
        return "navigation evidence origin differs from the observed hero"
    if evidence.kind == "blocker_wait" and (
        len(evidence.targets) != 1
        or max(
            abs(evidence.targets[0].x - evidence.origin.x),
            abs(evidence.targets[0].y - evidence.origin.y),
        )
        != 1
    ):
        return "blocker wait requires one adjacent target"
    if evidence.kind == "search" and any(
        max(abs(cell.x - evidence.origin.x), abs(cell.y - evidence.origin.y)) != 1
        for cell in evidence.targets
    ):
        return "search targets must be adjacent to the origin"
    if memory is None:
        if before is not None:
            return "routine SEARCH requires level memory for its allowance"
        return None
    from nethack_agent.replay import stair_target

    target = stair_target(selection.goal)
    expected = (
        search_evidence(memory, target)
        if evidence.kind == "search"
        else wait_evidence(
            memory, (evidence.targets[0].x, evidence.targets[0].y), target
        )
    )
    if expected is None or expected != evidence:
        return "navigation evidence does not match the remaining allowance"
    return None


def local_recovery_evidence(
    memory: LevelMemory, objective_kind: str
) -> LocalRecoveryEvidence | None:
    """Authorize existing place-objective routing, never exploration credit."""
    from nethack_agent.skills import _search_targets

    if objective_kind not in ("find_oracle", "enter_minetown_temple"):
        return None
    level = memory.level
    if level is None:
        return None
    protected = (
        objective_kind == "find_oracle"
        and level.dungeon_number == 0
        and 5 <= level.dungeon_level <= 9
    ) or (
        objective_kind == "enter_minetown_temple"
        and level.dungeon_number == 2
        and level.dungeon_level in (3, 4)
    )
    # Quarantine is not evidence that a frontier was examined.
    tree = route_tree(memory)
    if any(
        any(memory.unexplored(near) for near in memory.neighbors(point))
        for point in tree.distances
    ):
        return None
    targets = {
        cell
        for point in tree.distances
        if point not in memory.monsters
        and memory.kind(point) is not CellKind.CLOSED_DOOR
        for cell in _search_targets(memory, point)
    }
    coverage_complete = all(
        memory.search_coverage.get(cell, 0) >= SEARCH_CANDIDATE_CAP for cell in targets
    )
    if objective_kind == "find_oracle" and (
        memory.oracle_seen
        or any(monster.name == "Oracle" for monster in memory.monsters.values())
    ):
        return None
    if (
        objective_kind == "enter_minetown_temple"
        and level.dungeon_number == 2
        and (memory.altars or memory.town_identified or memory.temple_entry is not None)
    ):
        return None
    if protected and (not coverage_complete or not search_pass_complete(memory)):
        return None
    spent = (
        navigation_spent(memory)
        or (bool(targets) and coverage_complete)
        or memory.monster_waits >= MONSTER_WAIT_LIMIT
    )
    if not spent:
        return None
    return LocalRecoveryEvidence(
        objective_kind,
        level,
        memory.knowledge,
        memory.navigation_elapsed,
        protected,
        coverage_complete,
    )


def requires_local_recovery_marker(
    selection: ActionSelection, action: LegalAction
) -> bool:
    intent = selection.intent
    return (
        selection.source is ActionSelectionSource.DETERMINISTIC_SKILL
        and selection.skill is Skill.STAIRCASE_NAVIGATION
        and intent is not None
        and intent.destination is not None
        and intent.destination.kind
        in (DestinationKind.UPSTAIRS, DestinationKind.DOWNSTAIRS)
        and intent.attack_target is None
        and all(
            value is None
            for value in (
                intent.prayer,
                intent.corpse,
                intent.food,
                intent.drop,
                intent.navigation,
            )
        )
        and (
            action.name in MOVE_ACTION_NAMES.values()
            or action.name in ("MiscDirection.UP", "MiscDirection.DOWN")
        )
    )


def local_recovery_error(
    action: LegalAction,
    selection: ActionSelection,
    before: ProjectedObservation | None = None,
    memory: LevelMemory | None = None,
) -> str | None:
    intent = selection.intent
    evidence = None if intent is None else intent.local_recovery
    if evidence is None:
        return None
    if not requires_local_recovery_marker(selection, action):
        return "local recovery evidence requires deterministic staircase navigation"
    if before is not None and (
        evidence.level.dungeon_number != before.player.dungeon_number
        or evidence.level.dungeon_level != before.player.dungeon_level
        or before.prompt.active
    ):
        return "local recovery evidence differs from the observed level or prompt"
    if (
        intent is not None
        and intent.level is not None
        and intent.level != evidence.level
    ):
        return "local recovery evidence differs from the intent level"
    if memory is not None:
        expected = local_recovery_evidence(memory, evidence.objective_kind)
        if expected is None or expected != evidence:
            return "local recovery evidence does not match the spent local allowance"
    elif before is not None:
        return "local recovery evidence requires level memory"
    return None


def local_recovery_plan_error(
    action: LegalAction,
    selection: ActionSelection,
    planned_goal: Goal | None,
    permit: LocalRecoveryEvidence | None,
) -> str | None:
    """Bind recorded recovery to the actual objective's goal and authorization."""
    intent = selection.intent
    recorded = None if intent is None else intent.local_recovery
    expected = permit if requires_local_recovery_marker(selection, action) else None
    if recorded != expected or (
        expected is not None and selection.goal != planned_goal
    ):
        return (
            "local recovery requires the objective planner's matching goal and permit"
        )
    return None
