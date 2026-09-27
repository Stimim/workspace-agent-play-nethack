# 0011: Map intent annotations

Date: 2026-09-27

## Change

Deterministic skills now expose the map targets they already compute, and the
browser draws them on the map. Every `ActionSelection` carries an optional typed
`intent` (`decision.ActionIntent`), persisted in step events:

```json
"intent": {
  "destination": {"kind": "frontier", "x": 57, "y": 11},
  "attack_target": null
}
```

`destination` is `null` or an object with a `DestinationKind` and zero-based
map coordinates; `attack_target` is `null` or a cell. At least one is present,
otherwise the whole intent is `null`. Each value comes from the skill's own
routing data, never from the action direction or the rationale text:

| Skill path | Destination | Attack target |
| --- | --- | --- |
| Staircase route, step onto `>`, wait on `>` | `downstairs`: the chosen `>` | none |
| Staircase defense against an adjacent hostile | `downstairs`: the already chosen `>` | the hostile |
| Exploration frontier route (including opening a door on the way) | `frontier`: the route goal | none |
| Route blocked by a monster: approach, wait, or attack | the route goal | the blocking hostile when attacked |
| Walk beside, kick, and aim a kick at a locked door | `locked_door`: the door | none |
| Walk to or search from a search spot | `search_spot`: the committed spot | none |
| Exploration defense against an adjacent hostile | none (fighting precedes frontier choice) | the hostile |
| Safe prompt answers, model fallbacks | intent `null` | |

The destination is the route goal, usually several cells beyond the adjacent
cell the action steps into; for kicking it is the door rather than the cell
beside it. `SkillAction` gained a required `intent`, and the coordinator copies
it into the selection. The contract rejects an intent on any selection whose
source is not `deterministic_skill`.

In seed 6 the first step moves north-east toward the frontier at (57, 11), two
steps away; steps 87-89 attack the sewer rat at (29, 5); steps 148-151 route to
the downstairs at (19, 14).

Seed 6 has no step that has both a destination and an attack target. In the
traced seeds such steps occur only as staircase defense, 3 of 1,956 steps; for
example, seed 9 step 100 attacks a newt at (37, 19) while keeping the
downstairs at (38, 16). The monster-blocked route's own attack branch never
appears in these traces, because the adjacent-hostile defense runs first in
both skills and handles the same adjacent hostile.

## Browser

`renderMap(pre, observation, intent)` marks the destination with a dashed
accent outline (`destination`) and the attack target with a solid danger-colored
outline (`attack-target`). Precedence per cell:

1. `player` replaces every other class, as before; a destination under the hero
   (a search spot being searched, or `>` while waiting) is not boxed.
2. `attack-target` wins over `destination` on the same cell.
3. The `pet` fill combines with either box.
4. Every non-player cell keeps its NetHack color class.

Intent boxes are raised above neighboring highlights, so an adjacent pet or
player outline cannot cover part of the box. The map shows the intent of the
step event that carries the displayed observation (`observationIntent`). The
annotation describes the decision that produced this observation: the hero has
already taken that step, and an attacked monster may have died. A status
snapshot that is newer than the latest received step shows no intent until its
step event arrives.

A legend under the map has focusable tooltips for Player, Pet, Destination, and
Attack target. Every Events decision shows an **Intent** row, for example
`destination: frontier (57, 11)`, `attack target: (29, 5)`, or `none recorded`.
Its value tooltip explains the destination kind and the attack target. All text
is inserted with `textContent`, styles live in `app.css`, and no asset was added.

## Layout

The fixed columns changed from 54rem/21rem to 50rem (primary) and 30rem
(inventory). At the 14 px root size, the three-column layout needs
50 + 30 + 24 (agent minimum) + 2 × 0.75 (gaps) + 2 × 0.75 (padding) = 107rem,
or 1,498 px. The old breakpoint kept 22 px of room for a vertical scrollbar
above the old 1,428 px layout. Keeping that room moves the breakpoint from 1450
to 1520 px in both `app.css` and `NARROW_AGENT_QUERY` in `app.js`.

The workspace `min-width` values omitted the border-box padding, so a
horizontally scrolled page lost its right padding. They now include it: +3rem
for three columns and +2.25rem for two. The 79-column map needs about 628 px, so
it fits the 677 px content box of the 50rem panel.

## Compatibility

Events stored before intents existed, including the accepted milestone 1
records, have no `intent` key. This follows the pet-evidence precedent (note
0010): `ActionSelection.from_json` lists `intent` as an optional field of
`contracts.object_value`, and an absent key and `null` both mean that no intent
was recorded. The reader never invents a target. A present intent stays strict:

- exact fields;
- a known `DestinationKind`;
- non-boolean, non-negative integer cells;
- cells inside the observation map;
- `deterministic_skill` sources only.

Unknown extra selection fields are still rejected. The test fixture that
rewrites fresh events to the milestone 1 shape now removes `selection.intent`
together with the pet fields (`to_milestone_1_shape` in `tests/conftest.py`).

## Verification

- Deterministic behavior: a throwaway trace ran the scripted development model
  on suite seeds 1-10 and seed 58, with 1,000-step caps, before and after the
  change. Every action index, source, skill, skill-selection source, stuck
  reason, rationale, and outcome was identical (all 11 `task_success`, 1,956
  steps). Every traced step carried an intent: 1,711 frontier, 155 search spot,
  44 downstairs, 2 locked door, and 47 attack targets (3 of them with a
  destination). The new code's action indices and rationales also match all
  1,868 steps of the accepted milestone 1 records for seeds 1-10.
  `POLICY_VERSION` is unchanged.
- Milestone 1 data: on a copy of `data/evaluations/staircase-v1-explore`
  (10 runs, 1,888 events, no stored `intent` key), `RunStore` read every event
  with `intent` `None`. `summarize_run` reported integrity OK and
  `task_success` for all 10 seeds. The service on that copy served the seed-6
  run with `"intent": null`.
- `uv run pytest -q`: 205 passed. New behavior tests cover:
  - skill intents for multi-step staircase routes, waiting on `>`, staircase
    defense (downstairs plus attack), a frontier seven steps away, exploration
    defense (attack only), locked-door kick and kick direction, and search
    spots;
  - a contract round trip, legacy absence and `null`, and 13 malformed
    variants;
  - API serving of new and milestone 1-shaped events, and the evaluation audit
    of legacy-shaped records;
  - renderer precedence and colors, and which step's intent is displayed.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
  `node --check` passed for `app.js`, `render.js`, and `client.js`.
- `mkdocs build --strict` (pinned versions in `docs/development.md`): passed.
- Real browser: headless Windows Edge was driven over CDP by a throwaway
  PowerShell script, because WSL Chromium lacks `libnspr4`. The service used
  `--development-scripted-model` on the scratch milestone-1 copy. The script
  started seed 6 through the UI:
  - Step 1 (1920x1080): the only boxed cell was `destination c7` at (57, 11),
    equal to the API intent, while the player stood at (58, 12). The expanded
    decision read `Intent: destination: frontier (57, 11)`; exactly one
    decision was open.
  - Step 88: `attack-target c3` on the sewer rat at (29, 5), equal to the API
    intent, with the separate `pet c15` and `player` spans.
  - Legend and Intent tooltips had `role=tooltip`, were linked through
    `aria-describedby`, had opacity 1, and stayed inside the viewport. The
    driver enabled CDP focus emulation because headless pages lack OS focus.
  - Layout: at 1920 px, 1521 px, and 900 px the columns measured 700 px and
    420 px. The agent column measured 743 px at 1920 px and 344 px at 1521 px,
    with no horizontal overflow at 1521 px (client width 1,506 px). At 1520 px
    the agent column was hidden and **Agent info** was shown. At 900 px the
    page scroll width was 1,152 px, which includes the right padding. At every
    width the map had equal client and scroll sizes (628x325), with its right
    edge and the legend inside the panel content box.
  - At 900x1000, the overlay showed the step-88 Intent row. Step 148 boxed the
    downstairs at (19, 14) three rows below the hero.
  - Legacy: attaching the milestone 1 seed-6 run showed `Intent: none
    recorded`. That run's final observation is NLE's blank terminal frame, so a
    browser-side call to the shipped `renderMap` and `observationIntent` drew
    its stored step-88 event. The rationale reads "Attack the adjacent sewer
    rat", yet the frame drew no box, because no intent is inferred.
  - A browser-side fixture drew a destination and an attack target in the same
    frame through the shipped `renderMap`.
  - Screenshots (Windows `C:\Temp\`):
    - `nethack-intent-wide-destination.png` and
      `nethack-intent-destination-zoom.png`;
    - `nethack-intent-wide-legend-tooltip.png`;
    - `nethack-intent-wide-attack.png` and `nethack-intent-attack-zoom.png`;
    - `nethack-intent-wide-intent-tooltip.png`;
    - `nethack-intent-narrow-attack.png`,
      `nethack-intent-narrow-overlay-intent.png`, and
      `nethack-intent-narrow-downstairs.png`;
    - `nethack-intent-wide-legacy.png` (map region from the legacy step-88
      fixture render);
    - `nethack-intent-fixture-zoom.png`.

## Limitations

- The map shows only the latest step's intent. Selecting an older event to
  redraw its map and intent belongs to the historical-replay roadmap item.
- A destination on the hero's own cell is not boxed; the Events row still
  names it.
