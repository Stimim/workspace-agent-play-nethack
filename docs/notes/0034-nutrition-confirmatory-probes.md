# 0034: Nutrition confirmatory probes

## Preregistration (frozen before any episode)

Baseline HEAD is `10cb81d`. Freeze this section; append implementation, audit, results, verification and decision without changing these rules. No episode preceded this preregistration.

- **Seeds:** the next 30 unused integers starting at 1330. `used_seeds(evaluation/)` validated 320 previously used seeds across the ledger, catalog and suites. Exact sample **1330–1359 inclusive**, all unused; register before any arm. These become development seeds, never fresh milestone acceptance seeds.
- **Setup:** actual `AgentCoordinator` and `ScriptedDevelopmentModel`, `NetHackScore-v0`, `nle-survival-actions`, objective `reach_level(0,5)`, cap 3000, unchanged from note 0033. Separate immutable source snapshots, data and report directories for every arm. No local real-model acceptance claim is made by these scripted probes.
- **Arms:** A = immutable `6645966` (the note-0032 frozen baseline, before the nutrition package); B = immutable `10cb81d` (the shipped nutrition package, including the same-cell kill-record bug fix). Freeze before episodes. No candidate mutation during a suite.
- **Qualification:** compare B with A on all 30 seeds, including errors. Objectives **not lower**, total deaths **not higher**, hunger deaths **not higher**, and zero invalid actions, gate rejections and integrity problems. Hunger death means starvation or last live hunger Weak or worse (NLE >= 3), never zeroed terminal fields. Never replace a failed run.
- **Selection:** if B fails qualification, revert the nutrition package (preserving the regression test if it applies to A's code; otherwise drop it) and record why. If B passes, it remains shipped.
- **If something ships or reverts:** record the two-arm tables and decision here. Update the seed ledger. Commit through `omp_commit.py` as `Confirm the nutrition package on fresh seeds` (or `Revert the nutrition package` if it fails).

## Fresh two-arm comparison

All two arms ran the frozen setup on seeds 1330-1359: actual
`AgentCoordinator` and `ScriptedDevelopmentModel`, `NetHackScore-v0`,
`nle-survival-actions`, `reach_level(0,5)`, cap 3000, separate immutable
source snapshots (`git worktree` at `6645966` for A; `10cb81d` for B) and
separate data/report directories. Hunger death means starvation or last live
hunger Weak or worse.

### Arm A: immutable `6645966` (frozen baseline)

Report: `/tmp/item34-arm-a-run/reports/nutrition-confirmation-development-20261003T204344Z.json`.

**21/30 objectives, 4 deaths, 0 hunger deaths, 5 truncations**;
zero invalid/gate/integrity problems.

| Seed | Outcome | Steps | Death cause (hunger at death) |
| ---: | --- | ---: | --- |
| 1330 | truncated | 3000 | — |
| 1331 | death | 1799 | killed by a small mimic (not_hungry) |
| 1332 | objective_complete | 525 | — |
| 1333 | truncated | 3000 | — |
| 1334-1343 | objective_complete (10/10) | 260-1594 | — |
| 1344 | death | 1146 | killed by a wand (not_hungry) |
| 1345-1346 | objective_complete (2/2) | 165-1546 | — |
| 1347 | truncated | 3000 | — |
| 1348 | objective_complete | 358 | — |
| 1349 | death | 871 | killed by a boulder (not_hungry) |
| 1350-1351 | objective_complete (2/2) | 390-502 | — |
| 1352 | truncated | 3000 | — |
| 1353-1356 | objective_complete (4/4) | 415-1810 | — |
| 1357 | death | 1610 | killed by a falling rock (not_hungry) |
| 1358 | objective_complete | 536 | — |
| 1359 | truncated | 3000 | — |

### Arm B: immutable `10cb81d` (shipped nutrition package)

Report: `/tmp/item34-arm-b-run/reports/nutrition-confirmation-development-20261003T204344Z.json`.

**21/30 objectives, 2 deaths, 0 hunger deaths, 7 truncations**;
zero invalid/gate/integrity problems.

| Seed | Outcome | Steps | Death cause (hunger at death) |
| ---: | --- | ---: | --- |
| 1330 | death | 1488 | killed by a boulder (not_hungry) |
| 1331-1335 | objective_complete (5/5) | 338-1996 | — |
| 1336-1337 | truncated (2/2) | 3000 | — |
| 1338-1339 | objective_complete (2/2) | 342-998 | — |
| 1340 | truncated | 3000 | — |
| 1341-1342 | objective_complete (2/2) | 280-974 | — |
| 1343 | death | 1756 | killed by a small mimic (not_hungry) |
| 1344-1346 | objective_complete (3/3) | 158-1383 | — |
| 1347-1348 | truncated (2/2) | 3000 | — |
| 1349-1351 | objective_complete (3/3) | 371-554 | — |
| 1352 | truncated | 3000 | — |
| 1353-1358 | objective_complete (6/6) | 344-2454 | — |
| 1359 | truncated | 3000 | — |

## Frozen-rule decision: keep shipped

| Criterion | A (baseline) | B |
| --- | ---: | ---: |
| Objectives not lower | 21 | 21 — Pass |
| Total deaths not higher | 4 | 2 — Pass |
| Hunger deaths not higher | 0 | 0 — Pass |
| Invalid / gate / integrity | 0/0/0 | 0/0/0 — Pass |

B qualifies cleanly on the fresh sample. The nutrition package is confirmed and remains shipped.
