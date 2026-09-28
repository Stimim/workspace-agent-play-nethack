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
