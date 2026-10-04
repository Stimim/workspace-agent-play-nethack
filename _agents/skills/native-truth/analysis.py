"""Geometric route diagnosis, not a combat or door-opening simulation."""

from __future__ import annotations

import heapq
import itertools

BARRIERS = ("secret", "locked", "closed", "boulder", "peaceful_monster")
PASSABLE = {14, 15, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35}


def analyze(snapshot: dict, goal: tuple[int, int] | None = None) -> dict:
    grid = snapshot["terrain"]
    hero = snapshot["hero"]
    start = (hero["x"], hero["y"])
    if goal is None:
        stair = snapshot["stairs"]["dnstair"]
        if stair is None:
            return {"goal": None, "error": "current level has no main downstairs"}
        goal = (stair["x"], stair["y"])
    barriers: dict[tuple[int, int], set[str]] = {}
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            classes = set()
            if cell["typ"] in (14, 15):
                classes.add("secret")
            if cell["door_state"] == "LOCKED":
                classes.add("locked")
            elif cell["door_state"] == "CLOSED" and cell["typ"] != 14:
                classes.add("closed")
            if classes:
                barriers[x, y] = classes
    for collection, category in (
        ("boulders", "boulder"),
        ("peaceful_monsters", "peaceful_monster"),
    ):
        for item in snapshot.get(collection, []):
            barriers.setdefault((item["x"], item["y"]), set()).add(category)

    def accessible(point: tuple[int, int]) -> bool:
        x, y = point
        return 0 <= x < 79 and 0 <= y < 21 and grid[y][x]["typ"] in PASSABLE

    def intact_door(point: tuple[int, int]) -> bool:
        x, y = point
        cell = grid[y][x]
        return cell["typ"] == 14 or (
            cell["typ"] == 22 and cell["door_state"] not in ("BROKEN", "DOORWAY")
        )

    def route(blocked: set[str], fewest: bool = False) -> dict | None:
        queue = [(0, 0, start)]
        distances = {start: (0, 0)}
        previous = {}
        while queue:
            a, b, point = heapq.heappop(queue)
            if distances[point] != (a, b):
                continue
            if point == goal:
                path = [point]
                while path[-1] != start:
                    path.append(previous[path[-1]])
                path.reverse()
                blockers = [
                    {"x": x, "y": y, "classes": sorted(barriers[x, y])}
                    for x, y in path[1:]
                    if (x, y) in barriers
                ]
                return {
                    "steps": len(path) - 1,
                    "path": [list(p) for p in path],
                    "blockers": blockers,
                    "classes": sorted(
                        {c for item in blockers for c in item["classes"]}
                    ),
                }
            x, y = point
            for dx, dy in itertools.product((-1, 0, 1), repeat=2):
                if not dx and not dy:
                    continue
                destination = (x + dx, y + dy)
                if (
                    not accessible(destination)
                    or barriers.get(destination, set()) & blocked
                ):
                    continue
                if dx and dy:
                    if intact_door(point) or intact_door(destination):
                        continue
                    if not accessible((x + dx, y)) and not accessible((x, y + dy)):
                        continue
                cost = int(bool(barriers.get(destination)))
                distance = (a + cost, b + 1) if fewest else (a + 1, b + cost)
                if distance < distances.get(destination, (float("inf"), float("inf"))):
                    distances[destination] = distance
                    previous[destination] = point
                    heapq.heappush(queue, (*distance, destination))
        return None

    shortest = route(set())
    fewest = route(set(), True)
    minimal_sets = []
    # Inclusion-minimal sets of classes that must be relaxed to permit a route.
    for size in range(6):
        for subset in itertools.combinations(BARRIERS, size):
            enabled = set(subset)
            if any(set(prior).issubset(enabled) for prior in minimal_sets):
                continue
            if route(set(BARRIERS) - enabled) is not None:
                minimal_sets.append(list(subset))
    return {
        "goal": list(goal),
        "shortest": shortest,
        "fewest_blocker_cells": fewest,
        "minimal_blocker_sets": minimal_sets,
        "held_blocked": {category: route({category}) for category in BARRIERS},
        "dynamic_barriers_available": snapshot["dynamic_status"]
        in ("live", "last_live_before_terminal"),
    }


def render(
    snapshot: dict, known_rows: list[str] | tuple[str, ...] | None = None
) -> str:
    """True map and observed map, plus known glyph overlay on true terrain."""
    rows = []
    stairs = {
        (s["x"], s["y"]): "<" if s["up"] else ">"
        for s in snapshot["stairs"].values()
        if s
    }
    boulders = {(b["x"], b["y"]) for b in snapshot.get("boulders", [])}
    hero = (snapshot["hero"]["x"], snapshot["hero"]["y"])
    for y, row in enumerate(snapshot["terrain"]):
        chars = []
        for x, cell in enumerate(row):
            typ = cell["typ"]
            char = " " if typ == 0 else "#" if typ in range(1, 14) else "."
            char = {
                14: "S",
                15: "s",
                16: "~",
                17: "~",
                18: "~",
                19: "~",
                20: "~",
                21: "|",
                23: ":",
                31: "_",
                27: "{",
            }.get(typ, char)
            if typ == 22:
                char = {
                    "LOCKED": "L",
                    "CLOSED": "+",
                    "OPEN": "'",
                    "BROKEN": "/",
                    "DOORWAY": ".",
                }[cell["door_state"]]
            char = stairs.get((x, y), char)
            if (x, y) in boulders:
                char = "0"
            if (
                known_rows
                and known_rows[y][x] not in (" ", "@", "\0")
                and typ not in (14, 15, 25, 26)
            ):
                char = known_rows[y][x]
            if (x, y) == hero:
                char = "@"
            chars.append(char)
        rows.append("".join(chars) + (" | " + known_rows[y] if known_rows else ""))
    return (
        "true terrain + public overlay | recorded public map\n"
        + "\n".join(rows)
        + "\nS=secret door s=secret corridor L=locked +=closed "
        "'=open /=broken 0=boulder"
    )
