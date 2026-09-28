# 0017: Scout and Eat task suites (ADR 0004 milestone B, first wave)

Date: 2026-09-28

## Why

ADR 0004 section 8 stages NLE task suites after traversal and the survival
skills: Scout and Eat explore the Dungeons of Doom level by level, Gold adds
routing to visible gold, and Oracle finds the Oracle. This note records the
first wave, the explore-dungeon objective with Scout and Eat, under policy
`hierarchical-task-progression-v1` and the unchanged knowledge bundle
`staircase-reviewed-v3`.

## What changed

- **Contracts.** `ExploreDungeonLeg(max_level)` (JSON
  `{"kind": "explore_dungeon", "max_level": N}`, 1-32, Dungeons of Doom only)
  and `ExploreLevelGoal(level)` (token `explore_level:<dnum>:<dlevel>`, no
  staircase target) are strict value types. `NetHackScout-v0` with
  `nle-task-actions` and `NetHackEat-v0` with `nle-hunger-actions` accept
  exactly one explore leg; any other task, profile, or leg combination is
  rejected.
- **Planner.** The shallowest required level that exploration has not yet
  exhausted is the target: `explore_level` on it, main stairs toward it
  otherwise, and the recorded link out of a branch dungeon. A level skipped by a
  trap door is revisited by climbing. `LevelMemory.explored` is set when a level
  is first found exhausted and, unlike `exhausted`, survives later knowledge
  growth, so walking to `>` does not reopen an explored level.
- **Markers and confirmation.** The step whose decision newly finds a level
  exhausted records `selection.exhausted_level`. When that completes the
  current leg, the step is a deterministic `WAIT` confirmation, so the final
  required level ends `objective_complete` on the next observation without a
  model consultation. A decision discarded by a pause or model failure
  restores the level's exhaustion marks (a test fails without the restore: the
  retried step lost its marker). The model is offered only `explore_level` for
  an explore goal (`decision.model_selectable_skills`); stair-goal prompts are
  byte-for-byte unchanged.
- **Replay audit.** `replay.ExplorationReplay` rebuilds the coordinator's
  dungeon memory from a stored run. `derive_action_record` re-derives each
  executed action's memory record from its recorded action, source, and intent;
  the objective planner (including branch re-arms) and stuck-consultation
  re-arms are replayed in the coordinator's order. A marker is confirmed only if
  the shared exploration skill reports `search_exhausted` on the decided-on
  observation at the level's current knowledge. Only confirmed markers complete
  an explore leg; any other marker is an integrity problem.
- **Metrics and thresholds.** Episodes record `explored_cells` (the sum over
  levels of the most non-blank glyphs seen live, NLE Scout's public count) and
  `worst_hunger_state`. Cases may declare typed metric thresholds; a case with
  at least one threshold may set `min_successes: 0`. Earlier schema-3 reports
  lack the new fields and still render byte for byte.
- **Regression suites.** `staircase-v3` and `traversal-v2` repeat the cases,
  seeds, caps, and thresholds of `staircase-v2` and `traversal-v1` under the new
  policy; the older suites stay pinned and are refused by this checkout.
- **UI.** The goal field renders `explore_level:<dnum>:<dlevel>`, and a step's
  decision details show `Exhausted: level (d, l)` when a marker is recorded.

## Development smoke before probes

All runs in this section used the explicit scripted development model on
development-only seeds.

- The replay reproduced the coordinator exactly: on Scout seeds 11-13 and Eat
  seeds 11-15 (2,000-step cap) every one of the 11,837 committed memory records
  matched its re-derived record and every marker (five) was confirmed.
- The first level's exhaustion took 1,234-1,764 steps on the Eat seeds that
  reached it; Scout seeds 11-13 died at 959-1,030 steps before exhausting their
  first level.
- Scripted `NetHackStaircase-v0` runs on seeds 1-10 (1,000-step cap) still end
  `task_success` at exactly the recorded step counts 217, 44, 222, 47, 147, 151,
  286, 222, 102, and 430, and record no marker.
- A Scout `explore_dungeon(1)` search over development seeds 20-57 found seed
  53 completing at step 322 through the `WAIT` confirmation; it is the
  permanent coordinator and evaluator test.
- Browser: the managed Chromium daemon was unavailable, so headless Windows
  Edge was driven over CDP by a throwaway PowerShell script against a scripted
  service running the seed 53 Scout `explore_dungeon(1)` run. The run
  information showed Goal `explore_level:0:1` and Outcome `objective_complete`,
  and the expanded final event (#323, `MiscDirection.WAIT`) showed the
  confirmation rationale and `Exhausted: level (0, 1)`
  (`C:\Temp\explore-ui-smoke.png`).

## Held-out probes and fixed thresholds

The probes ran the exact planned cases with the scripted development model into
throwaway reports, on seed ranges no committed suite uses. Nothing was tuned
after them; they fixed only the suite thresholds.

| Probe | Seed | End (steps) | Levels explored (marker step) | Max depth | Explored cells | Return | Death |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- |
| Scout, `explore_dungeon(3)` | 800 | death (982) | DL1 (126) | 2 | 964 | 963.94 | killed by a goblin |
| | 801 | death (1,007) | none | 1 | 625 | 625.00 | killed by a kobold |
| | 802 | death (923) | DL1 (922) | 1 | 320 | 320.00 | killed by a kobold zombie |
| | 803 | death (1,032) | none | 1 | 557 | 557.00 | died of starvation |
| | 804 | death (1,012) | none | 1 | 554 | 554.00 | killed by a grid bug |
| Eat, `explore_dungeon(5)` | 820 | death (1,748) | none | 1 | 669 | 793.97 | killed by a jackal |
| | 821 | death (1,691) | DL1 (1,511) | 2 | 753 | 793.97 | killed by a newt |
| | 822 | death (1,740) | DL1 (586) | 2 | 1,060 | 793.96 | killed by a fox |
| | 823 | death (1,707) | none | 1 | 583 | 793.94 | killed by a bat |
| | 824 | truncated (2,000) | DL1 (245) | 1 | 462 | 1,587.98 | alive |

No probe completed its objective. Every Scout probe reached Fainting; every
Eat probe ate one known ration at Hungry (seed 824 ate two) and four later
died while Fainting. Every audit was clean: no invalid action, gate rejection,
or unconfirmed marker. The Scout reward is almost exactly the explored-cell
count, and each Eat ration was worth about 800.

**Observed failure class.** ADR 0004 defines a level as exhausted when
exploration reports `search_exhausted`, which happens only after its bounded
hidden-passage search of every wall and dead end facing dense unexplored rock.
That search outlasted the hunger horizon: Scout, whose `nle-task-actions`
profile cannot eat, starves or faints near 1,000 steps, and Eat's one ration
extends that to about 1,700. Seed 824 also shows the cost after exhaustion: its
first level had no known `>`, so its remaining 1,755 steps were 173 stuck
consultations and re-armed searches. The definition was deliberately kept; the
evidence motivates a future bounded search-budget or exploration skill under a
new policy, which is not implemented.

**Thresholds.** Scout and Eat have no NLE success state, and the probes never
completed the objective, so both suites are ADR 0004 section 8 baselines:
`min_successes: 0` with metric thresholds fixed before their first episode.

- `scout-v1` (seeds 900-904, `explore_dungeon(3)`, cap 2,000): median
  `explored_cells` and median Scout return each at least 350, the probe median
  557 times 0.7 rounded down to a multiple of 50. Deaths and depth have no
  bound because every probe died and only one left level 1.
- `eat-v1` (seeds 920-924, `explore_dungeon(5)`, cap 2,000): median Eat return
  at least 700 (the median episode eats a ration), median `explored_cells` at
  least 450 (669 times 0.7, rounded down), and at most one starvation death
  (the probes had none).

## Committed real-model runs

After `nethack-agent doctor` passed (Ollama 0.34.4, `gemma4-nethack:latest`),
each committed suite ran exactly once with the local model through loopback
Ollama (`num_ctx` 8,192). Every report is complete, with zero invalid actions,
gate rejections, integrity failures, decision failures, and model fallbacks.

| Suite | Report | Result | Episodes/steps | Model decisions (p50) |
| --- | --- | --- | --- | --- |
| `staircase-v3` | `staircase-v3-20260928T091404Z` | PASS, 10/10 including seed 6 | 10 / 1,868 | 10 (1,220 ms) |
| `traversal-v2` | `traversal-v2-20260928T091446Z` | FAIL: 3/5, 3/5, 1/5 (Mines needs 2/5) | 15 / 9,354 | 24 (1,185 ms) |
| `scout-v1` | `scout-v1-20260928T091827Z` | PASS on metric gates, 0/5 objectives | 5 / 4,941 | 5 (1,109 ms) |
| `eat-v1` | `eat-v1-20260928T092011Z` | PASS on metric gates, 0/5 objectives | 5 / 8,340 | 5 (970 ms) |

- `staircase-v3` repeated the milestone trajectories: 1,868 steps, as in the
  accepted milestone suite.
- `traversal-v2` reproduced `traversal-v1`'s case counts (3/5, 3/5, 1/5), so
  entering the Mines again missed its fixed 2/5 threshold. The failure stays a
  failure; seeds 701 and 702 died or were truncated on levels 1-2 while
  Fainting in every case.
- `scout-v1`: explored cells 550, 575, 358, 463, 524 (median 524 against at
  least 350) and the same Scout return median 524; every episode died on level
  1 between 899 and 1,048 steps (two by starvation, three killed while
  Fainting) without exhausting it.
- `eat-v1`: Eat returns 394.95, 793.99, 793.96, 793.96, 793.91 (median 793.96
  against at least 700), explored cells 524, 553, 848, 1,033, 1,564 (median
  848 against at least 450), and no starvation death. Each episode ate one
  verified ration; seed 924 exhausted levels 1 and 2 (steps 430 and 1,134) and
  reached depth 3, and all five later died while Fainting.

The baselines pass because they are gated on the probe-derived metrics, not on
objective completion; the exhaustion-cost failure class above is unchanged.

## Verification

- `uv run pytest -q`: 431 passed. Ruff check and format check passed; `node
  --check` passed on every browser module; the pinned MkDocs strict build,
  `git diff --check`, and `verify network --timeout 20 --json` (nine loopback
  destinations, proxy bypass verified) passed.
- Every committed report, including the immutable `staircase-v1`,
  `staircase-v2`, and `traversal-v1` reports, re-renders from its JSON
  byte for byte, and every report file is mode 0644.
