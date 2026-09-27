# 0012: Planned-path overlay

Date: 2026-09-27

## Question

"When the destination is multiple steps away, does the explore skill already
plan the steps?"

Yes, in part. The code has no persistent multi-step plan, but every routed step
computes a complete shortest route and then uses only its first cell:

- `navigation.route_tree` runs a breadth-first search from the hero over
  remembered terrain. It returns a `RouteTree` with a parent link and a
  distance for every reachable cell, so the full route to any reachable cell is
  already known.
- `ExploreLevelSkill` and `StaircaseNavigationSkill` build a new tree on every
  call. They pick a goal (frontier, search spot, the stand cell beside a locked
  door, or the nearest `>`), and until this change they took only the first
  step toward it. `RouteTree.first_step` walked the parent chain from the goal
  back to the hero and discarded everything except the cell next to the hero.
  The rationale's "(N steps)" is the tree distance.
- `AgentCoordinator` calls the skills once per step with the per-level
  `LevelMemory` and keeps no route between steps. Each step replans from fresh
  memory, so the next step may take a different route once more of the map is
  seen.

For each path kind, a full route is computed on this step:

| Path kind | Full route computed | Recorded as `path` |
| --- | --- | --- |
| Frontier (including opening a door on the way) | yes | yes |
| Walk to a search spot | yes | yes |
| Search at the spot | no route (in place) | `null` |
| Downstairs route and the step onto `>` | yes | yes |
| Wait on `>` | no route (in place) | `null` |
| Walk beside a locked door | yes, to the stand cell | yes, ending beside the door |
| Kick and kick direction | no route (in place) | `null` |
| Monster-blocked approach and attack | yes, through displayed monsters | yes |
| Wait for a blocking peaceful or passive monster | yes, but not taken | `null` |
| Adjacent-hostile defense | staircase: the route to `>` is computed but not taken; exploration: none | `null` |

## Change

`RouteTree.first_step` is replaced by `RouteTree.route(target)`. It walks the
same parent chain and returns every cell after the hero, in order, ending at
the target. `_route_step` now takes that route: it moves into `route[0]` and
records the whole route in the intent. The move and the displayed path
therefore come from the same computed route, and nothing is recomputed for
display. The goal recorded in `ActionRecord` is `route[-1]`, which is the same
cell as before.

`decision.ActionIntent` gained a required `path: tuple[MapCell, ...] | None`,
serialized as a JSON array of cells or `null`:

```json
"intent": {
  "destination": {"kind": "frontier", "x": 57, "y": 11},
  "attack_target": null,
  "path": [{"x": 58, "y": 12}, {"x": 57, "y": 11}]
}
```

A present path is validated by the contract:

- it has 1 to `MAX_INTENT_PATH_LENGTH` (21 × 79 = 1,659) cells, and an
  oversized JSON array is rejected before its cells are parsed;
- it requires a destination;
- it never revisits a cell;
- each consecutive pair of cells is king-move adjacent;
- it ends at the destination, except for `locked_door`, where it ends
  orthogonally beside the door (the kick stand);
- it starts at the attack target when both are present (the monster-blocked
  attack moves into the route's first cell);
- every cell lies inside the observation map (`StepPayload` checks this with the
  destination and attack target);
- path cells have exactly `x` and `y` as non-negative, non-boolean integers.

The step event does not store the hero's pre-step position, so the reader
cannot check that the path starts next to it. Skill tests check this, and so
does a real-level test that runs the coordinator on seeds 2, 4, and 58: every
recorded path starts with the move the step executed, and a hero who moved now
stands on its first cell.

In the stored step event, the observation is the one after the action. When the
move succeeds, the hero stands on `path[0]`, so the displayed path is the
remainder of the route from the hero's cell.

`POLICY_VERSION` is unchanged; no action choice changed.

## Browser

`renderMap(pre, observation, intent, showPath = true)` adds the `path` class to
recorded path cells. The class draws a faint accent background image and a
dotted accent underline and keeps the NetHack foreground color. Precedence per
cell:

1. `player` replaces every other class (the hero usually stands on `path[0]`);
2. `attack-target` wins over `destination`, which wins over `path`;
3. `pet` combines with any of them. The tint is a `background-image`, so the
   pet's background color stays visible beneath it.

A **Show path** checkbox sits beside the legend and is on by default. It is
stored in `localStorage` under `nethack-agent.showPath` (only the string
`"false"` turns it off; unavailable storage keeps the default). Toggling it
hides only the path tint and schedules a local redraw with no request. The
legend gained a **Path** entry with a tooltip. Every Events step decision shows
a **Path** row, for example `8 steps: (44, 4) to (37, 5)`, whose value tooltip
names the first and last cells, or `none recorded`. All text goes through
`textContent`, styles live in `app.css`, and no asset was added.

## Compatibility

An absent `path` key reads the same as `null`: no route was recorded. This
follows the precedents for pet evidence (note 0010) and intents (note 0011).
`ActionIntent.from_json` lists `path` as an optional field of
`contracts.object_value`, and the UI shows no tint and "none recorded". The
reader never rebuilds a route from the destination. Two shapes stay readable:

- Milestone 1 records have no `intent` key.
  `to_milestone_1_shape` in `tests/conftest.py` still removes the whole
  intent.
- Intents written by the note 0011 feature have no `path` key.
  `to_pathless_intent_shape` reproduces this shape, and the API and
  evaluation-audit tests read it.

## Payload size

On the traced suite (1,956 steps), the added `path` key costs 83.8 bytes per
step event on average in the store's compact JSON. Steps without an intent add
nothing, `"path":null` adds 12 bytes, and the longest route (63 cells, seed 7)
adds 983 bytes. Seed 6's 72 stored step events average 22,696 bytes, so the
average growth is about 0.4%.

## Verification

- Behavior: a throwaway trace ran the scripted development model on suite seeds
  1-10 and seed 58 with 1,000-step caps, before and after the change. All 1,956
  steps matched in action index, source, skill, skill-selection source, stuck
  reason, rationale, and outcome (all 11 runs `task_success`). Each step's
  `destination` and `attack_target` also matched. Of these steps, 1,885
  recorded a path: 1,711 frontier, 133 search-spot walks, and 41 downstairs.
  The mean path had 5.0 cells and the longest 63. The 71 steps without a path
  were 44 exploration-defense attacks, 3 staircase-defense attacks, 22
  searches in place, 1 kick, and 1 kick direction. The traces contain no
  locked-door walk, monster-blocked approach, or wait for a blocker, so those
  are covered by skill tests only.
- Milestone 1 data: a copy of `data/evaluations/staircase-v1-explore` (10 runs,
  1,888 events) read through `RunStore` with every step intent `None`.
  `summarize_run` reported integrity OK and `task_success` for all 10 seeds.
- `uv run pytest -q`: 226 passed on the combined tree, which includes the
  concurrent Messages-tab change. New or changed behavior tests cover:
  - skill routes for the multi-step staircase walk, a seven-step frontier, a
    route that bends around a boulder and through an open door, the
    locked-door walk ending beside the door, monster-blocked approach and wait,
    the blocked-route attack, and search walks and in-place searches. Each
    compares the exact recorded cells, or checks the start next to the hero,
    the first cell equal to the step taken, and the end at the goal. The
    contract enforces contiguity when an intent is constructed;
  - the real-level path invariant on seeds 2, 4, and 58;
  - a contract round trip, legacy absent-intent and absent-path shapes, a
    valid locked-door route, and 13 malformed path variants (non-contiguous,
    wrong end, out of map, no destination, extra cell field, empty, non-array,
    too long, revisit, boolean coordinate, two locked-door ends, and an
    attack-target mismatch);
  - API serving of new and path-less intents, and the evaluation audit of
    path-less and milestone 1 records;
  - renderer precedence (player, attack target, destination, path, pet), the
    hidden and missing-path cases, and the Path decision text.
- `mkdocs build --strict` (pinned versions in `docs/development.md`): passed.
- `uv run ruff check .`, `uv run ruff format --check .`, and `node --check` on
  `app.js`, `render.js`, and `client.js`: passed.
- Real browser: headless Windows Edge was driven over CDP by a throwaway
  PowerShell script against `serve --development-scripted-model` on a scratch
  data directory at 1920x1080. It started seed 6 through the UI and clicked
  **Step** 72 times:
  - The API intent was a frontier at (37, 5) with an 8-cell path from (44, 4).
    The map drew `player` at (44, 4), `path c7` on the six cells from (43, 4)
    to (38, 5), and `destination c7` on (37, 5).
  - The Events row read `Path: 8 steps: (44, 4) to (37, 5)` with its tooltip.
    The legend **Path** tooltip had `role=tooltip` and opacity 1, and stayed
    inside the viewport.
  - Before the first toggle, the checkbox was checked and nothing was stored.
    Unchecking it removed every `path` span, kept the destination box, and
    stored `"false"`. The page's resource-timing count stayed at 80, so no
    request was made. After a reload, the checkbox was still unchecked and no
    path was drawn. Checking it and reloading restored the six path cells.
  - Screenshots (Windows `C:\Temp\`): `nethack-path-wide-on.png`,
    `nethack-path-wide-off.png`, `nethack-path-zoom.png` (3x zoom of the path
    and destination), `nethack-path-wide-events.png`, and
    `nethack-path-wide-legend-tooltip.png`.

## Limitations

- The path is the route at decision time. Later steps replan, so a route drawn
  at one step can differ from the one the hero eventually walks.
- Waiting for a blocker and staircase defense compute a route that the step
  does not follow; it is not recorded.
