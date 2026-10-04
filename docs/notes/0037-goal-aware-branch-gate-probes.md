# 0037: Goal-aware branch-gate probes

## Preregistration (frozen before any episode)

Baseline HEAD: `7455cef9fbccae9d259b1b4da10c6685837e6029`.
This section is frozen. Append implementation, outcomes, verification, and
shipment decision without changing the sample, candidate scope, or rules.

- **Qualification sample:** the next 30 unused development integers after
  note 0035's sample: **1380–1409 inclusive**. Before registration,
  `used_seeds(Path("evaluation"))` returned 370 used seeds; none of these 30
  was present. Register the sample in the seed ledger before either arm.
  These are development probes, never fresh acceptance seeds.
- **Setup, both arms:** actual `AgentCoordinator`, scripted development model,
  lawful dwarven Valkyrie, `NetHackScore-v0`, `nle-survival-actions`, objective
  `reach_level(0,5)`, cap 3000, bundle `survival-reviewed-v2`. Keep the current
  policy pin `hierarchical-survival-exit-v1` during this behavior comparison;
  unification and its new policy/suite infrastructure are a subsequent change.
  Use separate immutable source worktrees and data/report directories under
  `/tmp/branch-gate-{baseline,candidate}/`.
- **Arms:** A = immutable baseline HEAD above; B = exactly the goal-aware
  branch-gate change. While seeking the main downstairs, a remembered Mines
  branch downstairs must not suppress guarded locked-gate forcing or checking
  unvisited object-covered exit terrain. Reuse the existing staircase
  compatibility predicate. Preserve behavior when the compatible downstairs
  is known, the exploration goal has no stair target, or the goal is upstairs.
  Selection, execution gate, and evaluator must use the same goal-aware
  predicate. Preserve main-dungeon, shop, closed-inventory, HP, hunger, and
  retry safeguards. No search scoring, boulder handling, combat, nutrition,
  prayer interval, knowledge-card, task/profile, or suite-contract changes.
- **Candidate freeze:** complete product changes and scoped behavior tests,
  then freeze B in an isolated tree and record its patch SHA-256 before its
  first development or qualification episode. Do not mutate B during either
  suite. Retain every report and episode, including failures and errors.
- **Development set:** all **67** unique historical seeds from the unified
  diagnosis, including fixed suites, catalog, descend-d5-v1 baseline/fresh
  report, and note 0035. Same unified setup. Compare with the retained HEAD
  diagnosis (50 objectives, seven deaths, ten truncations). A change must not
  reduce objectives or change any previous success to failure unless the note
  explicitly justifies that regression. Report all changed seeds. The four
  diagnosed branch-gate cases are 1, 703, 1366, and 2105401147; their improvement
  is measured, not presumed or used to replace the qualification sample.
- **Qualification rule:** ship only if B has objectives **not lower**, deaths
  **not higher**, and hunger deaths **not higher** than A on all 30 seeds,
  including errors, and **zero invalid actions, gate rejections, and integrity
  problems**. Hunger death means starvation or last-live hunger Weak or worse
  (NLE index >= 3); do not use zeroed terminal statistics or historical worst
  hunger. Require complete records. Display-only harness success thresholds
  do not replace this paired rule.
- **No replacement:** never rerun or replace a failed run, redraw a seed, or
  mutate the candidate mid-suite. Disclose any harness preflight failure.
  Qualification failure means no product shipment; retain its evidence and
  record the decision. Shipping requires behavior tests, architecture and
  development documentation, this note, and the repository commit procedure.

No episode for this fix was executed before this preregistration.

## Candidate freeze and behavior reproduction

The frozen candidate patch is `/tmp/branch-gate-candidate.patch`, SHA-256
`10536428052b610c1a47fb4d5c7212ae029f31908db3a6bcb027d019dfa3c59e`.
It was applied to detached baseline `7455cef` at
`/tmp/branch-gate-candidate` before any candidate episode.

`navigation.downstairs_known` reuses `candidate_tier` with the exploration
target; `locked_door_kick_error`, covered-cell exploration, and the shared
runtime/evaluator kick audit use it. Unknown main probes still count as
compatible; established Mines branches do not. Targetless and upstairs
exploration retain their previous downstairs guard. All other gate protections
are unchanged.

The two new behavioral regressions failed on baseline (main-goal branch-gate
forcing and object-covered exit checks). After the change, the five new
parameterized cases and existing gate safety/direction/injury cases passed:
19 passed. An initial test-fixture constructor omitted `StairTarget`'s required
`dungeon_number`; that fixture-only error was corrected before the actual
failing-before behavior run and candidate freeze. No evaluation harness
preflight failure occurred before these episodes.

## Results and rejection

All three invocations completed without harness preflight failures, replaced
episodes, or candidate mutations. The 67-seed development set improved
**50/67 → 56/67**, with no previous objective success lost: seeds **1, 703,
924, 1366, 1374, 2105401147** became objective successes. Deaths fell 7→6;
hunger deaths stayed 1→1; truncations fell 10→5. The four diagnosed branch-gate
cases all completed. Other successful trajectories changed without losing
their objectives; full unchanged reports retain every seed.

| Qualification arm (1380–1409) | Objectives | Deaths | Hunger deaths | Truncated | Invalid / gate / integrity |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline HEAD | 23/30 | 2 | 1 | 5 | 0 / 0 / 0 |
| Frozen candidate | 23/30 | 3 | 1 | 4 | 0 / 0 / 0 |

**Reject; do not ship this candidate.** Its extra death violates the frozen
rule even though objectives are unchanged and development results improved.
Seed 1408 improved from truncation to completion, but **1385 regressed from
completion to homunculus death while Not Hungry**. Its first differing action,
step 392 on D2, diverted from the baseline frontier toward an object-covered
cell after branch recovery. It later repeatedly selected a covered-cell route
while blind/deaf and under unseen melee on D4. This evidence motivates keeping
ordinary reachable frontiers ahead of newly enabled branch-only covered-cell
checks, not mutating or repeating this frozen comparison. All remaining
qualification outcome classes were unchanged.

| Seed | Baseline outcome / steps | Candidate outcome / steps |
| ---: | --- | --- |
| 1380 | truncated / 3000 | truncated / 3000 |
| 1381 | objective_complete / 643 | objective_complete / 643 |
| 1382 | objective_complete / 831 | objective_complete / 895 |
| 1383 | objective_complete / 1531 | objective_complete / 1531 |
| 1384 | objective_complete / 1805 | objective_complete / 1805 |
| 1385 | objective_complete / 1096 | death / 1031 |
| 1386 | death / 311 | death / 311 |
| 1387 | objective_complete / 723 | objective_complete / 723 |
| 1388 | objective_complete / 600 | objective_complete / 541 |
| 1389 | objective_complete / 550 | objective_complete / 550 |
| 1390 | objective_complete / 1152 | objective_complete / 921 |
| 1391 | objective_complete / 625 | objective_complete / 625 |
| 1392 | truncated / 3000 | truncated / 3000 |
| 1393 | objective_complete / 746 | objective_complete / 746 |
| 1394 | objective_complete / 522 | objective_complete / 522 |
| 1395 | objective_complete / 806 | objective_complete / 806 |
| 1396 | death / 2700 | death / 2700 |
| 1397 | truncated / 3000 | truncated / 3000 |
| 1398 | objective_complete / 970 | objective_complete / 970 |
| 1399 | objective_complete / 710 | objective_complete / 710 |
| 1400 | objective_complete / 489 | objective_complete / 489 |
| 1401 | objective_complete / 1159 | objective_complete / 1154 |
| 1402 | objective_complete / 910 | objective_complete / 922 |
| 1403 | objective_complete / 483 | objective_complete / 448 |
| 1404 | truncated / 3000 | truncated / 3000 |
| 1405 | objective_complete / 794 | objective_complete / 794 |
| 1406 | objective_complete / 724 | objective_complete / 724 |
| 1407 | objective_complete / 483 | objective_complete / 483 |
| 1408 | truncated / 3000 | objective_complete / 2239 |
| 1409 | objective_complete / 1167 | objective_complete / 1167 |

Retained reports:

- Baseline: `/tmp/branch-gate-baseline/reports/branch-gate-qualification-development-development-20261004T013255Z.json`.
- Candidate qualification: `/tmp/branch-gate-candidate/qualification-reports/branch-gate-qualification-development-development-20261004T013638Z.json`.
- Candidate development: `/tmp/branch-gate-candidate/development-reports/unified-baseline-development-development-20261004T013631Z.json`.
- Original development baseline: `/tmp/unified-baseline-reports/unified-baseline-development-development-20261004T005517Z.json`.

All records and replay audits were complete; no failed/repaired model decision
or model fallback action occurred. The full test run exposed three
trajectory-dependent assertions (exact Mines traversal sequence/counts and a
long seed-1300 path to an unrelated lichen encounter). The exact-trajectory
assertions were removed rather than re-pinned, and the lichen same-cell
provenance defect now has an isolated permit/gate behavior regression.
These test-only adjustments never changed the frozen candidate worktree.
