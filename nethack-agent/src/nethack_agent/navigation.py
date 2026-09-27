"""Per-level terrain memory and NetHack 3.6.7 movement rules.

Deterministic skills route over this memory instead of raw glyphs: NetHack
draws the hero, monsters, and objects over the terrain they stand on, so the
last terrain glyph seen at each cell is remembered for the current level.

Movement rules follow NetHack 3.6.7 ``test_move`` (``src/hack.c``):

- a diagonal move into or out of a doorway is refused unless the doorway is
  doorless (no door or a broken door, drawn as ``S_ndoor``); open doors
  (``S_vodoor``/``S_hodoor``) and closed doors therefore allow only orthogonal
  entry and exit;
- moving into a closed door with the adapter's explicit ``autoopen`` option
  tries to open it without moving, and reports ``This door is locked.`` for a
  locked door;
- a diagonal squeeze between two rock or wall cells is allowed outside Sokoban
  for a medium-sized hero carrying at most 600 weight units, which covers the
  fixed dwarven Valkyrie on dungeon level 1;
- boulders are never routed through (pushing is not modelled).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Final

from nle import nethack

from nethack_agent.observation import ProjectedObservation

type Point = tuple[int, int]
type Edge = tuple[Point, Point]

MOVE_ACTION_NAMES: Final[dict[Point, str]] = {
    (0, -1): "CompassDirection.N",
    (1, 0): "CompassDirection.E",
    (0, 1): "CompassDirection.S",
    (-1, 0): "CompassDirection.W",
    (1, -1): "CompassDirection.NE",
    (1, 1): "CompassDirection.SE",
    (-1, 1): "CompassDirection.SW",
    (-1, -1): "CompassDirection.NW",
}
DELTAS: Final[tuple[Point, ...]] = tuple(MOVE_ACTION_NAMES)
ORTHOGONAL_DELTAS: Final[tuple[Point, ...]] = ((0, -1), (1, 0), (0, 1), (-1, 0))
HISTORY_LENGTH: Final = 24
# A route that revisits at most half as many cells as moves made, with no new
# map knowledge, is dithering between goals.
OSCILLATION_WINDOW: Final = 12
OSCILLATION_MAX_CELLS: Final = 6
STALE_MOVE_LIMIT: Final = 100
# Explicit test_move refusals reported with the `mention_walls` option NLE sets.
_TERRAIN_REFUSALS: Final = (
    "it's a wall",
    "it's solid stone",
    "diagonally",
    "cannot pass",
    "too much to get through",
    "too large to fit",
    "in vain",
    "cannot move past",
)
# Failed moves caused by the hero's condition or a monster, not by terrain.
_TRANSIENT_FAILURES: Final = (
    "trap",
    "pit",
    "web",
    "stuck",
    "caught",
    "cannot escape",
    "in the way",
    "you stop",
)
_GENERIC_FAILURE_LIMIT: Final = 3
_DOOR_OPEN_ATTEMPT_LIMIT: Final = 5
# dokick.c messages for a kicked door that broke ("crashes open") or was
# destroyed ("shatters to pieces").
_DOOR_BROKEN_MESSAGES: Final = ("crashes open", "shatters")


class CellKind(Enum):
    UNKNOWN = "unknown"
    WALL = "wall"
    OBSTACLE = "obstacle"
    FLOOR = "floor"
    CORRIDOR = "corridor"
    DOORWAY = "doorway"
    OPEN_DOOR = "open_door"
    CLOSED_DOOR = "closed_door"
    TRAP = "trap"
    DOWNSTAIRS = "downstairs"


def _cmap_kind(index: int) -> CellKind | None:
    """Classify a NetHack 3.6.7 ``defsym.h`` cmap index; None means transient."""
    if index == 0:
        return CellKind.UNKNOWN
    if 1 <= index <= 11:
        return CellKind.WALL
    if index == 12:
        return CellKind.DOORWAY
    if index in (13, 14):
        return CellKind.OPEN_DOOR
    if index in (15, 16):
        return CellKind.CLOSED_DOOR
    if index in (19, 20, 23, 25, 26, 27, 28, 29, 30, 31, 33, 35, 36, 64):
        return CellKind.FLOOR
    if index in (21, 22):
        return CellKind.CORRIDOR
    if index == 24:
        return CellKind.DOWNSTAIRS
    if 42 <= index <= 63:
        return CellKind.TRAP
    if index in (17, 18, 32, 34, 37, 38, 39, 40, 41):
        return CellKind.OBSTACLE
    return None


_CMAP_KINDS: Final = tuple(_cmap_kind(index) for index in range(nethack.MAXPCHARS))
_STRAIGHT_WALL_CMAPS: Final = frozenset({1, 2})
_DOORWAY_CMAP: Final = 12
_OPEN_DOOR_CMAP: Final = 13
PASSABLE_KINDS: Final = frozenset(
    {
        CellKind.FLOOR,
        CellKind.CORRIDOR,
        CellKind.DOORWAY,
        CellKind.OPEN_DOOR,
        CellKind.DOWNSTAIRS,
    }
)
_DOOR_KINDS: Final = frozenset({CellKind.OPEN_DOOR, CellKind.CLOSED_DOOR})
_BOULDER_OBJECT: Final = next(
    index
    for index in range(nethack.NUM_OBJECTS)
    if nethack.OBJ_NAME(nethack.objclass(index)) == "boulder"
)
# Passive-response monsters that must never be meleed by a level-1 hero
# (NetHackWiki "Passive"; floating eye paralysis and mold/jelly/spore damage).
_NEVER_MELEE: Final = frozenset(
    {
        "floating eye",
        "gas spore",
        "brown mold",
        "yellow mold",
        "green mold",
        "red mold",
        "blue jelly",
        "spotted jelly",
        "ochre jelly",
    }
)


class ActionKind(Enum):
    MOVE = "move"
    OPEN_DOOR = "open_door"
    KICK = "kick"
    KICK_DIRECTION = "kick_direction"
    SEARCH = "search"
    WAIT = "wait"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """What an executed action attempted, interpreted on the next observation.

    `goal` is the route goal of a skill move; it is abandoned for the rest of
    the current map knowledge when routing to it oscillates or stalls.
    `search_spot` commits exploration to one search spot until it is spent.
    """

    kind: ActionKind
    origin: Point
    target: Point | None = None
    target_glyph: int | None = None
    goal: Point | None = None
    search_spot: Point | None = None


@dataclass(frozen=True, slots=True)
class Monster:
    glyph: int
    name: str
    pet: bool

    @property
    def never_melee(self) -> bool:
        return self.name in _NEVER_MELEE


class LevelMemory:
    """Bounded per-level knowledge owned by the coordinator.

    Every structure is keyed by map cells or cell pairs of one level, so its
    size is bounded by the 21x79 map. The memory resets on episode start and
    whenever the dungeon level changes.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.level: tuple[int, int] | None = None
        self.width = 0
        self.height = 0
        self.step_index = -1
        self.position: Point = (0, 0)
        self._cmap: list[list[int]] = []
        self._observed: list[bytearray] = []
        self.visited: set[Point] = set()
        self.monsters: dict[Point, Monster] = {}
        self.boulders: frozenset[Point] = frozenset()
        self.objects: frozenset[Point] = frozenset()
        self.search_coverage: dict[Point, int] = {}
        self.edge_failures: dict[Edge, int] = {}
        # Explicit terrain refusals hold for the level; generic repeated failures
        # are only suspected and are forgiven when exploration is re-armed.
        self.blocked_edges: set[Edge] = set()
        self.suspect_edges: set[Edge] = set()
        self.locked_doors: set[Point] = set()
        self.door_attempts: dict[Point, int] = {}
        self.kicks: dict[Point, int] = {}
        self.peaceful_glyphs: set[int] = set()
        self.abandoned_goals: set[Point] = set()
        self.search_goal: Point | None = None
        self.history: deque[tuple[Point, int, bool]] = deque(maxlen=HISTORY_LENGTH)
        self.stale_moves = 0
        self.knowledge = 0
        self.search_round = 0
        self.monster_waits = 0
        self.stuck_consult_step: int | None = None
        self.pending_kick: Point | None = None
        self._pending: ActionRecord | None = None

    # -- observation updates -------------------------------------------------

    def observe(self, observation: ProjectedObservation) -> None:
        """Fold one observation into memory; repeated calls are idempotent."""
        if observation.step_index == self.step_index and self.level is not None:
            return
        player = observation.player
        level = (player.dungeon_number, player.dungeon_level)
        if level != self.level:
            self.reset()
            self.level = level
            self.height = len(observation.map.glyph_rows)
            self.width = len(observation.map.glyph_rows[0])
            self._cmap = [[-1] * self.width for _ in range(self.height)]
            self._observed = [bytearray(self.width) for _ in range(self.height)]
        self.step_index = observation.step_index
        self.position = (player.x, player.y)
        self._update_cells(observation)
        record, self._pending = self._pending, None
        if record is not None:
            self._learn(record, observation)
        self.visited.add(self.position)
        x, y = self.position
        self._correct_terrain_here(observation.message.lower())
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if self.in_bounds((x + dx, y + dy)):
                    self._observed[y + dy][x + dx] = 1
        knowledge = self._knowledge()
        routed = (
            record is not None
            and record.goal is not None
            and record.target_glyph is None
            and record.kind in (ActionKind.MOVE, ActionKind.OPEN_DOOR)
        )
        if knowledge != self.knowledge:
            self.knowledge = knowledge
            self.abandoned_goals.clear()
            self.monster_waits = 0
            self.stale_moves = 0
        elif routed:
            self.stale_moves += 1
        self.history.append((self.position, self.knowledge, routed))
        if (
            routed
            and record is not None
            and record.goal is not None
            and (self.oscillating() or self.stale_moves >= STALE_MOVE_LIMIT)
        ):
            self.abandoned_goals.add(record.goal)
            if self.search_goal == record.goal:
                self.search_goal = None
            self.history.clear()
            self.stale_moves = 0

    def rearm(self) -> None:
        """Start another bounded search round after a stuck consultation."""
        self.search_round += 1
        self.edge_failures.clear()
        self.suspect_edges.clear()
        self.abandoned_goals.clear()
        self.search_goal = None
        self.monster_waits = 0
        self.history.clear()
        self.stale_moves = 0

    def _correct_terrain_here(self, message: str) -> None:
        """Fix a remembered closed door the hero is evidently standing in.

        An object or monster drawn over a door hides its later state, so a door
        last seen closed can be open or broken once the hero stands in it. The
        look-here message names the doorway state when there is one.
        """
        x, y = self.position
        if "broken door here" in message or "doorway here" in message:
            self._cmap[y][x] = _DOORWAY_CMAP
        elif (
            "open door here" in message
            or self.kind(self.position) is CellKind.CLOSED_DOOR
        ):
            self._cmap[y][x] = _OPEN_DOOR_CMAP

    def record(self, record: ActionRecord) -> None:
        """Remember the executed action so the next observation can explain it."""
        self._pending = record
        if record.kind in (ActionKind.MOVE, ActionKind.OPEN_DOOR, ActionKind.SEARCH):
            self.search_goal = record.search_spot
        if record.kind in (ActionKind.SEARCH, ActionKind.WAIT):
            if record.kind is ActionKind.WAIT:
                self.monster_waits += 1
            x, y = record.origin
            for dx, dy in DELTAS:
                point = (x + dx, y + dy)
                if self.in_bounds(point):
                    self.search_coverage[point] = self.search_coverage.get(point, 0) + 1
        elif record.kind is ActionKind.KICK:
            self.pending_kick = record.target
        elif record.kind is ActionKind.KICK_DIRECTION and record.target is not None:
            self.kicks[record.target] = self.kicks.get(record.target, 0) + 1
            self.pending_kick = None
        if record.kind is not ActionKind.KICK:
            self.pending_kick = None

    def _update_cells(self, observation: ProjectedObservation) -> None:
        monsters: dict[Point, Monster] = {}
        boulders: set[Point] = set()
        objects: set[Point] = set()
        for y, glyphs in enumerate(observation.map.glyph_rows):
            cmap_row = self._cmap[y]
            for x, glyph in enumerate(glyphs):
                if nethack.glyph_is_cmap(glyph):
                    index = nethack.glyph_to_cmap(glyph)
                    if _CMAP_KINDS[index] is not None:
                        cmap_row[x] = index
                elif nethack.glyph_is_object(glyph):
                    if (
                        not nethack.glyph_is_statue(glyph)
                        and nethack.glyph_to_obj(glyph) == _BOULDER_OBJECT
                    ):
                        boulders.add((x, y))
                    else:
                        objects.add((x, y))
                elif nethack.glyph_is_monster(glyph) and (x, y) != self.position:
                    monsters[(x, y)] = Monster(
                        glyph,
                        nethack.permonst(nethack.glyph_to_mon(glyph)).mname,
                        bool(nethack.glyph_is_pet(glyph)),
                    )
        self.monsters = monsters
        self.boulders = frozenset(boulders)
        self.objects = frozenset(objects)

    def _learn(self, record: ActionRecord, observation: ProjectedObservation) -> None:
        message = observation.message.lower()
        target = record.target
        if record.kind is ActionKind.MOVE and target is not None:
            if self.position != record.origin:
                self.edge_failures.pop((record.origin, target), None)
                return
            if "really attack" in message:
                if record.target_glyph is not None:
                    self.peaceful_glyphs.add(record.target_glyph)
                return
            if record.target_glyph is not None or any(
                word in message for word in _TRANSIENT_FAILURES
            ):
                return
            edge = (record.origin, target)
            if any(word in message for word in _TERRAIN_REFUSALS):
                self.blocked_edges.add(edge)
                return
            failures = self.edge_failures.get(edge, 0) + 1
            self.edge_failures[edge] = failures
            if failures >= _GENERIC_FAILURE_LIMIT:
                self.suspect_edges.add(edge)
        elif record.kind is ActionKind.OPEN_DOOR and target is not None:
            if "locked" in message:
                self.locked_doors.add(target)
            elif self.kind(target) is CellKind.CLOSED_DOOR:
                attempts = self.door_attempts.get(target, 0) + 1
                self.door_attempts[target] = attempts
                if attempts >= _DOOR_OPEN_ATTEMPT_LIMIT:
                    self.locked_doors.add(target)
        elif record.kind is ActionKind.KICK_DIRECTION and target is not None:
            if any(word in message for word in _DOOR_BROKEN_MESSAGES):
                # A monster may step into the broken doorway at once and hide it.
                self._cmap[target[1]][target[0]] = _DOORWAY_CMAP
            if self.kind(target) is not CellKind.CLOSED_DOOR:
                self.locked_doors.discard(target)

    def _knowledge(self) -> int:
        """Count known terrain and observed cells; any increase is progress."""
        total = 0
        for cmap_row, observed_row in zip(self._cmap, self._observed, strict=True):
            total += sum(1 for index in cmap_row if index > 0)
            total += sum(observed_row)
        return total

    # -- queries ---------------------------------------------------------------

    def in_bounds(self, point: Point) -> bool:
        x, y = point
        return 0 <= x < self.width and 0 <= y < self.height

    def cmap(self, point: Point) -> int:
        return self._cmap[point[1]][point[0]]

    def kind(self, point: Point) -> CellKind:
        index = self._cmap[point[1]][point[0]]
        if index <= 0:
            # A displayed object or the hero's own footsteps prove the cell is
            # not solid rock even when its terrain was never drawn (for example
            # a corpse left in a dark corridor where a monster stood).
            if point in self.objects or point in self.visited or point == self.position:
                return CellKind.FLOOR
            return CellKind.UNKNOWN
        kind = _CMAP_KINDS[index]
        return CellKind.UNKNOWN if kind is None else kind

    def straight_wall(self, point: Point) -> bool:
        return self.cmap(point) in _STRAIGHT_WALL_CMAPS

    def observed(self, point: Point) -> bool:
        return bool(self._observed[point[1]][point[0]])

    def unexplored(self, point: Point) -> bool:
        """Blank cell the hero has never been adjacent to."""
        return (
            self.kind(point) is CellKind.UNKNOWN
            and not self.observed(point)
            and point not in self.monsters
            and point not in self.boulders
        )

    def passable(self, point: Point) -> bool:
        return (
            self.in_bounds(point)
            and self.kind(point) in PASSABLE_KINDS
            and point not in self.boulders
        )

    def openable_door(self, point: Point) -> bool:
        return (
            self.in_bounds(point)
            and self.kind(point) is CellKind.CLOSED_DOOR
            and point not in self.locked_doors
        )

    def downstairs(self) -> tuple[Point, ...]:
        return tuple(
            (x, y)
            for y, row in enumerate(self._cmap)
            for x, index in enumerate(row)
            if index >= 0 and _CMAP_KINDS[index] is CellKind.DOWNSTAIRS
        )

    def cells(self) -> Iterator[Point]:
        for y in range(self.height):
            for x in range(self.width):
                yield (x, y)

    def neighbors(self, point: Point) -> Iterator[Point]:
        x, y = point
        for dx, dy in DELTAS:
            candidate = (x + dx, y + dy)
            if self.in_bounds(candidate):
                yield candidate

    def step_allowed(self, origin: Point, target: Point) -> bool:
        """Whether a single move between adjacent cells obeys the door rules."""
        edge = (origin, target)
        if edge in self.blocked_edges or edge in self.suspect_edges:
            return False
        if origin[0] != target[0] and origin[1] != target[1]:
            return (
                self.kind(origin) not in _DOOR_KINDS
                and self.kind(target) not in _DOOR_KINDS
            )
        return True

    def hostile_blocker(self, point: Point) -> Monster | None:
        """A displayed monster at `point` that may be attacked by moving into it."""
        monster = self.monsters.get(point)
        if (
            monster is None
            or monster.pet
            or monster.never_melee
            or monster.glyph in self.peaceful_glyphs
        ):
            return None
        return monster

    def oscillating(self) -> bool:
        """Recent routed moves revisit a few cells without gaining knowledge."""
        if len(self.history) < OSCILLATION_WINDOW:
            return False
        recent = list(self.history)[-OSCILLATION_WINDOW:]
        return (
            all(routed for _, _, routed in recent)
            and len({position for position, _, _ in recent}) <= OSCILLATION_MAX_CELLS
            and len({knowledge for _, knowledge, _ in recent}) == 1
        )


@dataclass(frozen=True, slots=True)
class RouteTree:
    """Breadth-first shortest paths from the hero over remembered terrain."""

    origin: Point
    parents: dict[Point, Point | None]
    distances: dict[Point, int]

    def route(self, target: Point) -> tuple[Point, ...] | None:
        """The shortest route's cells after the origin, ending at `target`.

        None when `target` is unreachable or is the origin itself.
        """
        if target not in self.parents or target == self.origin:
            return None
        cells = [target]
        parent = self.parents[target]
        while parent is not None and parent != self.origin:
            cells.append(parent)
            parent = self.parents[parent]
        cells.reverse()
        return tuple(cells)


def route_tree(
    memory: LevelMemory,
    *,
    through_monsters: bool = False,
    extra_passable: frozenset[Point] = frozenset(),
) -> RouteTree:
    """Shortest routes over passable cells, opening closed doors orthogonally.

    Visible non-pet monsters block routes unless `through_monsters` is set;
    pets are displaced by walking into them. Closed, not known-locked doors are
    route nodes entered only orthogonally, because moving into one opens it.
    """
    origin = memory.position
    parents: dict[Point, Point | None] = {origin: None}
    distances = {origin: 0}
    pending = deque([origin])
    while pending:
        current = pending.popleft()
        if current != origin and memory.kind(current) is CellKind.CLOSED_DOOR:
            continue  # A closed door must open before anything beyond it.
        for candidate in memory.neighbors(current):
            if candidate in parents:
                continue
            if not (
                memory.passable(candidate)
                or memory.openable_door(candidate)
                or candidate in extra_passable
            ):
                continue
            monster = memory.monsters.get(candidate)
            if monster is not None and not monster.pet and not through_monsters:
                continue
            if not memory.step_allowed(current, candidate):
                continue
            parents[candidate] = current
            distances[candidate] = distances[current] + 1
            pending.append(candidate)
    return RouteTree(origin, parents, distances)
