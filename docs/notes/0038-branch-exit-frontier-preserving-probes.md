# 0038: Frontier-preserving branch-exit probes

## Preregistration (frozen before any episode)

Baseline HEAD remains `7455cef9fbccae9d259b1b4da10c6685837e6029`.
The note-0037 candidate failed qualification and is not shipped. Its worktree,
reports, sample, and frozen patch remain unchanged. This is a new candidate
on a new sample, not a mutation or rerun of the failed comparison.

- **Qualification sample:** the next 30 unused development integers after
  note 0037: **1410–1439 inclusive**. Check against `used_seeds(evaluation/)`
  and register before either arm. These are never fresh acceptance seeds.
- **Setup:** actual coordinator and scripted development model, lawful dwarven
  Valkyrie, `NetHackScore-v0`, `nle-survival-actions`, `reach_level(0,5)`, cap
  3000, `survival-reviewed-v2`, existing `hierarchical-survival-exit-v1` pin.
  Separate immutable trees and data/report directories for both arms under
  `/tmp/branch-exit-frontier-{baseline,candidate}/`.
- **Arms:** A = immutable baseline HEAD; B = goal-compatible downstairs guard
  for locked-gate forcing and object-covered exit discovery, with one narrower
  precedence rule than rejected note 0037. When some downstairs are known but
  all are incompatible with the current goal, ordinary reachable frontiers
  remain first; object-covered checks become a fallback before hidden search.
  When no downstairs are known, keep the existing object-covered-first order.
  Compatible downstairs, targetless/upstairs goals, shop/closed-inventory,
  dungeon, HP, hunger, retry, and direction-confirmation safeguards retain
  their existing behavior. Reuse `candidate_tier` and the same predicate in
  selection, runtime gating, and evaluator audit. No search scoring, boulder,
  combat, nutrition, prayer, card, task/profile, or suite-contract changes.
- **Freeze:** finish product changes and scoped behavior tests; freeze the
  candidate patch and record SHA-256 before any candidate episode. Do not
  mutate either evaluated tree during its suite. Retain all errors/failures.
- **Development:** run all 67 inventoried historical seeds once with the same
  setup. Compare with the retained original HEAD result: 50 objectives, seven
  deaths, one hunger death, ten truncations. No lower objective count and no
  previous objective success lost unless explicitly justified in this note.
  Also disclose differences from rejected note 0037 (56 objectives), without
  treating its unshipped behavior as the HEAD baseline. The diagnosed four
  cases remain 1, 703, 1366, and 2105401147; do not assume they all improve.
- **Qualification:** ship only if B's objectives are not lower, deaths are not
  higher, hunger deaths are not higher than A on all 30 seeds, and invalid
  actions, gate rejections, and integrity problems are zero. Require complete
  records. Hunger death means starvation or last-live hunger Weak or worse
  (NLE >= 3), never terminal zeroed stats or historical worst hunger. Report
  every seed, including errors; harness display thresholds are not this rule.
- **No replacement:** never rerun/replace a failed run, redraw seeds, or mutate
  the candidate mid-suite. Disclose harness preflight failures. A failure is
  retained and cannot support shipment. A shipped change gets behavior tests,
  architecture/development documentation, notes, and an `omp_commit.py` commit.

No episode for this candidate preceded this preregistration.

## Candidate freeze

Before registration, `used_seeds(evaluation/)` reported 400 used seeds and
confirmed 1410–1439 were the next unused development integers. The frozen
candidate patch `/tmp/branch-exit-frontier-candidate.patch` has SHA-256
`2d2c39b92dcdfe777ad21b6da98dac6a3314483f145e119321b726699a259a0b`.
It is applied to detached baseline HEAD in
`/tmp/branch-exit-frontier-candidate`. Product and tests are frozen before
either candidate suite starts.

The covered-cell proposal was extracted unchanged into `_check_covered_exit`
so default and branch-fallback paths share one implementation. The branch-only
fallback cannot divert an already reachable frontier. Twenty focused branch
compatibility, covered-cell precedence, and existing gate-safety tests passed.
The original branch cases failed before the goal-aware change in note 0037.
The note-0037 test cleanup is included here: no exact trajectory/count
re-pinning, and an isolated same-cell lichen permit regression retains the
nutrition bug's behavioral protection. No harness preflight failure occurred.

## Complete development results

The 67-seed set improves **50/67 → 52/67**, and **no previous objective
success becomes a failure**. Every episode and replay audit is complete,
with zero invalid actions, gate rejections, integrity problems, or failed
model decisions. The only outcome-class changes against HEAD are:

| Seed | HEAD | Candidate | Candidate steps / hunger |
| ---: | --- | --- | --- |
| 1 | truncated | objective_complete | 1524 / alive |
| 1366 | truncated | objective_complete | 978 / alive |
| 2105401147 | truncated | death: wererat | 661 / Not Hungry |

Seed 1371 remains successful but changes from 747 to 888 steps. Every other
seed has the same outcome and step count as HEAD, including seed 703's
gas-spore wait at the 3000-step cap. The four diagnosed seeds are not silently
counted as four fixes: **two now complete, one remains truncated, and one
previous truncation becomes a non-hunger combat death**. The latter's route
now forces a door (KICK at step 544) rather than remaining in hidden search;
it then dies while attacking a wererat and its summoned rats. This satisfies
the user's development rule (higher successes and no lost success), but the
development death increase is explicitly retained for the subsequent
HP/threat-aware recovery work, not presented as a survival improvement.

| 67-seed arm | Objectives | Deaths | Hunger deaths | Truncated |
| --- | ---: | ---: | ---: | ---: |
| HEAD | 50 | 7 | 1 | 10 |
| Frontier-preserving candidate | 52 | 8 | 1 | 7 |
| Rejected note-0037 candidate, not the baseline | 56 | 6 | 1 | 5 |

Relative to the rejected candidate, 703 and 924 revert to truncations, 1374
reverts to its original bat death, and 2105401147 changes to wererat death.
These are disclosed comparisons, not a claim that the rejected policy was
shipped or that its 56 successes establish the current-success baseline.

## Frozen qualification and shipment decision

| Arm, seeds 1410–1439 | Objectives | Deaths | Hunger deaths | Truncated | Invalid / gate / integrity |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline HEAD | 24/30 | 2 | 0 | 4 | 0 / 0 / 0 |
| Frozen candidate | 27/30 | 2 | 0 | 1 | 0 / 0 / 0 |

**Qualifies; ship the frozen frontier-preserving candidate.** Objectives
27 >= 24, deaths 2 <= 2, hunger deaths 0 <= 0, complete records and zero
invalid/gate/integrity problems satisfy the frozen rule. Seeds 1416, 1423,
and 1428 change from truncations to completions. No qualification success
regresses. Both deaths remain non-hunger deaths: kobold (1419) and cave
spider (1438); seed 1436 remains truncated. No run or failed episode was
replaced, no candidate was mutated during a suite, and no harness preflight
failure occurred. Scripted evidence is not real-model milestone acceptance.

| Seed | Baseline outcome / steps | Candidate outcome / steps |
| ---: | --- | --- |
| 1410 | objective_complete / 168 | objective_complete / 168 |
| 1411 | objective_complete / 852 | objective_complete / 852 |
| 1412 | objective_complete / 507 | objective_complete / 507 |
| 1413 | objective_complete / 801 | objective_complete / 801 |
| 1414 | objective_complete / 921 | objective_complete / 921 |
| 1415 | objective_complete / 941 | objective_complete / 941 |
| 1416 | truncated / 3000 | objective_complete / 573 |
| 1417 | objective_complete / 219 | objective_complete / 219 |
| 1418 | objective_complete / 812 | objective_complete / 812 |
| 1419 | death / 394 | death / 394 |
| 1420 | objective_complete / 717 | objective_complete / 1689 |
| 1421 | objective_complete / 319 | objective_complete / 319 |
| 1422 | objective_complete / 690 | objective_complete / 690 |
| 1423 | truncated / 3000 | objective_complete / 742 |
| 1424 | objective_complete / 520 | objective_complete / 520 |
| 1425 | objective_complete / 996 | objective_complete / 996 |
| 1426 | objective_complete / 390 | objective_complete / 390 |
| 1427 | objective_complete / 617 | objective_complete / 617 |
| 1428 | truncated / 3000 | objective_complete / 674 |
| 1429 | objective_complete / 459 | objective_complete / 459 |
| 1430 | objective_complete / 579 | objective_complete / 579 |
| 1431 | objective_complete / 394 | objective_complete / 394 |
| 1432 | objective_complete / 442 | objective_complete / 442 |
| 1433 | objective_complete / 1599 | objective_complete / 1599 |
| 1434 | objective_complete / 544 | objective_complete / 544 |
| 1435 | objective_complete / 433 | objective_complete / 433 |
| 1436 | truncated / 3000 | truncated / 3000 |
| 1437 | objective_complete / 685 | objective_complete / 685 |
| 1438 | death / 748 | death / 819 |
| 1439 | objective_complete / 538 | objective_complete / 538 |

## Reproduction and verification

Commands use `uv run nethack-agent eval run --development-scripted-model`,
with `/tmp/branch-exit-frontier-qualification.json` for the two 30-seed arms
and `/tmp/unified-baseline-suite.json` for the 67-seed candidate development
run. Source trees, data, ttyrecs, and complete JSON/Markdown reports remain
under their separate `/tmp` roots:

- Baseline: `/tmp/branch-exit-frontier-baseline/reports/branch-exit-frontier-qualification-development-development-20261004T020526Z.json`.
- Candidate qualification: `/tmp/branch-exit-frontier-candidate/qualification-reports/branch-exit-frontier-qualification-development-development-20261004T020750Z.json`.
- Candidate development: `/tmp/branch-exit-frontier-candidate/development-reports/unified-baseline-development-development-20261004T020745Z.json`.
- Original development baseline: `/tmp/unified-baseline-reports/unified-baseline-development-development-20261004T005517Z.json`.

The candidate product code stayed frozen. The complete pytest run after
replacing trajectory-dependent assertions passed **595 tests**, with three
dependency deprecation warnings (66.07 seconds). Twenty focused compatibility,
covered-cell precedence, gate-safety, direction, and injury cases passed.
The actual coordinator suites exercise the shipped exit-discovery path and
the evaluator replays its permits, not merely unit-test wiring.

Pinned MkDocs 1.6.1, pymdown-extensions 12.1, and mermaid2-plugin 1.2.3
also built the staged documentation tree successfully with `--strict`.
The provenance commit helper's first lint check found an unused
`EnterDungeonLeg` import left by deleting the incidental trajectory test.
It was removed after every suite had completed; no product code, episode,
or candidate suite was changed or rerun.

The historical suites and reports are unchanged. The current policy pin and
knowledge bundle remain unchanged for this development-only fix; the next
user-directed infrastructure change versions the unified policy and suite.
Final `descend-d5-v2` real-model acceptance remains a later step.
