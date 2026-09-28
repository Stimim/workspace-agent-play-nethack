# 0015: Typed traversal goals (ADR 0004 milestone A)

Date: 2026-09-28

## Why

After milestone 1, the roadmap called for dungeon play beyond standing on a
`>`. [ADR 0004](../decisions/0004-traversal-goals-and-task-progression.md)
planned typed traversal goals first (milestone A), then NLE task suites (B),
evidence-gated skills (C), and model-owned choices (D). This note records the
evidence behind milestone A and what was implemented. Suite schema 2, the
`staircase-v2` and `traversal-v1` suites, and report metrics are ADR step 7,
owned separately.

## Baseline on the non-Staircase tasks

A read-only survey ran the milestone policy (`hierarchical-explore-v1`, scripted
development model, 2,000-step cap) on `NetHackScore-v0`, `NetHackScout-v0`,
`NetHackGold-v0`, `NetHackEat-v0`, and `NetHackOracle-v0`, seeds 1-5. The
policy never reads the reward, so each seed's trajectory was the same on every
task. All 25 runs died on dungeon level 1:

| Seed | Steps | Death | Steps waiting on `>` | First Hungry turn |
| ---: | ---: | --- | ---: | ---: |
| 1 | 558 | fox, while waiting on `>` | 341 | - |
| 2 | 961 | newt, while Fainting on `>` | 917 | 751 |
| 3 | 1,065 | starvation, ration uneaten | 843 | 743 |
| 4 | 183 | fox, while waiting on `>` | 136 | - |
| 5 | 1,042 | starvation while fainted, ration uneaten | 0 | 731 |

- The wait branch of staircase navigation ran before its adjacent-hostile
  defense, so the hero did not fight back while waiting on `>`.
- Seed 5's `>` lay under two food rations. The hero stood on it twice and saw
  "There is a staircase down here."; memory ignored the message.
- Rewards: Scout 354, 262, 537, 220, 615; Gold 2, 0, -0.01, 0, 5.98; Eat and
  Oracle never above 0.
- No run had an unhandled prompt, a stuck report, or a model fallback.
- NLE 1.3.0 facts: only the Staircase family has a success state; every task
  but Challenge uses the 23 `TASK_ACTIONS`, which cannot select the food
  ration `d`; the adapter's options skipped Gold's `pickup_types:$`; and caps
  above 5,000 ended as `error` because NLE's own abort fired first.

A throwaway descent probe on `NetHackScore-v0` (seeds 1-10, pressing `>` on any
reached `>`) showed that `<` on the level-1 start is declined by NLE's prompt
handling, that the arrival cell after a descent is the `<` (24 of 24 checked),
that seeds 4 and 7 entered the Gnomish Mines at `(2, 1)` from `(0, 2)` with the
same glyphs as main stairs, and that three ascents landed on the `>` taken.

## What changed

| Commit | Change |
| --- | --- |
| `3211405` | ADR 0004 and the `traversal` value types |
| `8345ae3` | Typed `Goal` union replaces the enum; legacy `stand_on_downstairs` reads exactly; model goals by per-call token |
| `86391bc` | Typed `TaskSpec` (NLE task, action profile, objective), truncating step caps above 5,000, `runs.task`, API/CLI `task` |
| `6383c48` | `DungeonMemory` per `(dungeon_number, dungeon_level)`, stair links and identities, look-here stair messages |
| `e2286e3` | Stair identity and level on intents, `upstairs`, `objective_complete`, cross-level intent hiding in the UI |
| `6fdcdb4` | `TraversalPermit` gate and the shared `level_change_error` predicate in the coordinator, event reader, and evaluator audit |
| `eee64f3` | `staircase-v1` refused under any policy but `hierarchical-explore-v1` |
| `d3a2f5e` | `ObjectivePlanner`, goal-aware staircase navigation and exploration, leg completion |
| this change | Policy `hierarchical-traversal-v1`, bundle `staircase-reviewed-v3`, intent `pair_known`, reachable-dungeon objectives, goal-aware prompts |

The last change:

- **Policy and knowledge.** `POLICY_VERSION` is `hierarchical-traversal-v1`.
  Bundle `staircase-reviewed-v3` replaces `staircase-goal.md` with
  `stairs-traversal.md`. The new card keeps the four cited pages, rechecked
  against the local dump, and adds the level-1 exit warning. It states no
  stand-or-use policy; the goal-derived prompt says whether to stand on or use
  a staircase. The rendered context is 4,546 characters (1,137 estimated
  tokens).
- **Prompts.** The skill prompt lists every offered goal with its token and
  constraint. The stuck text names the staircase the goals need. The fallback
  prompt says a fallback never changes level, because `<` and `>` are not
  offered.
- **Stair evidence.** Stair intents record `pair_known`: whether memory held
  two staircases of that direction, the evidence for probing an unknown
  staircase as a branch. The coordinator refuses a permit if the recorded value
  differs from memory. Returning by a staircase the hero already used keeps its
  `traversed` evidence instead of downgrading it to `arrival`.
- **Objectives.** An objective naming a dungeon without a known staircase branch
  (for example the Quest, 3, or Fort Ludios, 5) is rejected when the task spec
  is parsed, so `POST /api/runs` returns 422 instead of failing run creation.
- **Documentation.** ARCHITECTURE.md now covers task specs, the adapter's
  options and caps, `runs.task`, the API `task` field, the planner, dungeon
  memory, and the permit gate. Reproducing `staircase-v1` requires commit
  `3211405` and a fresh data directory, because that checkout's strict reader
  rejects typed goals and stair intents written by later policies.

## Verification

All runs below used the explicit scripted development model; no real-model run
used the new policy.

- **Staircase behavior is unchanged.** Scripted `NetHackStaircase-v0` traces on
  seeds 1-10 and 58 (1,000-step cap) were compared with the pre-ADR tree
  `7cea327` after each coordinator-affecting commit and after this change. All
  1,967 rows (11 start observations and 1,956 steps) match in action, source,
  skill, skill selection, stuck reason, rationale, intent destination, attack
  target and path, outcome, message, and observation hash, with goals compared
  through the legacy mapping. Only new fields were added: `level` on 1,956
  intents and `stair` and `pair_known` on 44 stair intents. Every run ends
  `task_success` in 217, 44, 222, 47, 147, 151, 286, 222, 102, 430, and 88
  steps.
- **Traversal on real NLE** (`NetHackScore-v0`, 600-step cap):

  | Objective | Seed | Stair uses (step: levels, recorded identity) | End |
  | --- | ---: | --- | --- |
  | reach (0, 3), then (0, 1) | 6 | 152 and 316 down by unknown probes; 317 and 384 up by `main`/`arrival` | `objective_complete`, step 384 |
  | reach (0, 3) | 4 | 48 down; 183 down into Mines (2, 1) by unknown probe; 184 up by `branch`/`arrival`; 286 down by `main`/`elimination` | `objective_complete`, step 286 |
  | enter dungeon 2 | 4 | 48 down; 279 down to (0, 3) by unknown branch probe with `pair_known` true; 280 up by `main`/`arrival`; 358 down by `branch`/`elimination` into (2, 1) | `objective_complete`, step 358 |

  These sequences are permanent tests in `tests/test_coordinator.py`.
  Through the loopback service at `d3a2f5e`, `scenario run --task` on the
  seed 4 objective produced the same four stair uses and read back through the
  strict event reader. The evaluator audit of a `RunManager` round trip found
  no invalid actions; a tampered stair intent, or the same events without a
  task spec, were flagged.
- **Terminal observations.** NLE zeroes the bottom-line statistics of a
  terminal observation. Staircase seed 2 (success at step 44) and Score seed 9
  with objective reach (0, 12) (death at step 361 on (0, 5)) keep the last live
  level in the coordinator snapshot instead of failing.
- **Policy guard.** `eval run --suite evaluation/staircase-v1.json` exits 1
  with the bound-policy refusal and creates no data directory. The committed
  `staircase-v1` reports still re-render identically.
- **Objectives.** `POST /api/runs` with `enter_dungeon(3)` returns 422 with
  "objective dungeon 3 has no known staircase branch from the Dungeons of Doom".
- **Browser.** The managed Chromium daemon was unavailable, so headless
  Windows Edge 154 was driven over CDP by a throwaway PowerShell script
  against the scripted service. On a seed 4 `reach (0, 3)` run attached at
  step 182 and stepped with the UI's Step button:
  - the Goal field read `traverse_stairs:down:main`, with the typed tooltip
    naming the main downstairs target, and the Model field
    `policy hierarchical-traversal-v1`;
  - after step 183 the map showed the first Mines level (Depth 3, dungeon 2,
    level 1) with no destination box or path, while the Events row read
    `Intent: destination: downstairs (60, 17) [unknown]; level (0, 2)`;
  - after step 184 (back on (0, 2)) the Goal read
    `traverse_stairs:up:branch:0`, the map again drew no intent, and the Events
    row read `destination: upstairs (59, 11) [branch to 0 by arrival]; level
    (2, 1)`;
  - after step 185 the map drew one destination box and a 17-cell path on
    (0, 2). Screenshots: `C:\Temp\traversal-click-1.png` through
    `traversal-click-3.png`.
- `uv run pytest -q` on this change applied to `d3a2f5e`: 335 passed.
  `ruff check`, `ruff format --check`, `node --check` on every UI module, the
  pinned strict MkDocs build, and `git diff --check` passed. The knowledge
  bundle version is
  `staircase-reviewed-v3+sha256:410a76f351d072f29b15b42d90af7dbedb07f3e7641af295150db8840d0f0f4e`.

## Limitations

- Main versus branch stairs cannot be told apart before a traversal, arrival,
  elimination, or the exit rule establishes them. A Mines entrance behind a
  secret door can be missed; `enter_dungeon(2)` then re-arms each exhausted
  range level once and keeps searching.
- Sokoban's dungeon number (4) is inferred from `dungeon.def` order and has not
  been reached. Ladders, portals, trap doors, holes, and level teleports are not
  modelled as stair links.
- The combat, hunger, and prompt failures of the baseline are unchanged; they
  are milestone C work and will limit longer traversal episodes.
- No real-model run used the new policy yet; the evaluation worker owns the
  `staircase-v2` and `traversal-v1` suites.
