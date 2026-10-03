# 0035: Descend D5 Cap Probes

Date: 2026-10-04

## Rule
To determine the max_episode_steps and min_success_rate for the new descend-d5-v1 suite, we run held-out probes with the following parameters:
- **Seeds:** 1360-1379 (registered as development probes)
- **Model:** scripted
- **Policy:** final policy (`hierarchical-survival-exit-v1` with `survival-reviewed-v2` bundle)
- **Environment:** `NetHackScore-v0`
- **Action Profile:** `nle-survival-actions`
- **Objective:** `reach_level(0, 5)`
- **Cap:** 5000

We record the step at which each episode ends.

**Cap calculation:**
The `max_episode_steps` will be the smallest of {3000, 4000, 5000} that keeps at least 90% of the objective completions seen at 5000.

**Rate calculation:**
The `min_success_rate` starts at 0.5 (the ADR floor). We raise it to the largest multiple of 0.05 that is at most (the probe success rate at the chosen cap minus 0.15), never going below 0.5.

## Results
| Seed | Outcome | Step |
|---|---|---|
| 1360 | objective_complete | 773 |
| 1361 | objective_complete | 591 |
| 1362 | death | 483 |
| 1363 | objective_complete | 366 |
| 1364 | objective_complete | 471 |
| 1365 | objective_complete | 645 |
| 1366 | truncated | 5000 |
| 1367 | objective_complete | 310 |
| 1368 | truncated | 5000 |
| 1369 | objective_complete | 1263 |
| 1370 | objective_complete | 477 |
| 1371 | objective_complete | 747 |
| 1372 | truncated | 5000 |
| 1373 | objective_complete | 1329 |
| 1374 | death | 1240 |
| 1375 | objective_complete | 418 |
| 1376 | death | 2650 |
| 1377 | objective_complete | 1615 |
| 1378 | objective_complete | 271 |
| 1379 | death | 3829 |

- **Total completions at 5000 cap:** 13
- **Longest completion:** 1615 steps (seed 1377)
- **Completions at 3000 cap:** 13 (100% of 5000-cap completions)
- **Chosen Cap:** 3000
- **Probe success rate at 3000 cap:** 13/20 = 0.65
- **Chosen Rate:** max multiple of 0.05 <= (0.65 - 0.15) = 0.50. Flooring at 0.5 means `min_success_rate = 0.5`.
