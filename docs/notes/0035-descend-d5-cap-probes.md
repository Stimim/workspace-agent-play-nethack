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

## Execution Notes
The rule defining the thresholds and conditions above was fixed and written to this document before any probes were executed.

The probe run was executed over two stages due to a `bash` timeout after seed 1368 (which hit the 5,000 step cap). The run was immediately resumed from seed 1369 onwards using an identical continuation suite. Every seed (1360-1379) was executed exactly once; no episode encountered an error or required a rerun.

## Catalog Changes
During the milestone 2 policy integration, a catalog check revealed that two historically failing seeds now successfully complete their objectives under `hierarchical-survival-exit-v1`. They were promoted in `representative-seeds.json` from `known_failure` to `must_pass`:

- **`descend-d3-stair-defense-2`** (seed 2): Expected `known_failure/death`, observed `objective_complete`.
- **`descend-d3-hidden-downstairs-702`** (seed 702): Expected `known_failure/truncated`, observed `objective_complete`.

Check evidence:
```text
IMPROVED descend-d3-stair-defense-2 seed 2: expected known_failure/death, observed objective_complete; known failure now succeeds; update the catalog
IMPROVED descend-d3-hidden-downstairs-702 seed 702: expected known_failure/truncated, observed objective_complete; known failure now succeeds; update the catalog
```

## Probe Artifacts
The final, correct temporary JSON suite used to run the probes (rendered here for seeds 1369-1379; 1360-1368 followed an identical structure):
```json
{
  "schema_version": 3,
  "suite_id": "temp-d5-probes-2",
  "character": "val-dwa-law",
  "policy_version": "hierarchical-survival-exit-v1",
  "knowledge_bundle_id": "survival-reviewed-v2",
  "seed_selection": "none",
  "step_cap_rationale": "5000",
  "cases": [
    {
      "case_id": "probe-1369",
      "seeds": [1369],
      "task": {
        "environment": "NetHackScore-v0",
        "action_profile": "nle-survival-actions",
        "objective": { "legs": [ { "kind": "reach_level", "level": { "dungeon_number": 0, "dungeon_level": 5 } } ] }
      },
      "max_episode_steps": 5000,
      "acceptance": { "min_successes": 1, "required_success_seeds": [] }
    },
    ...
  ],
  "acceptance": {
    "max_invalid_actions": 0,
    "max_gate_rejections": 0,
    "require_complete_records": false
  }
}
```

The command used to execute the suite:
```bash
uv run nethack-agent eval run --suite evaluation/temp-d5-probes-2.json --development-scripted-model --data-dir /tmp/item10-temp-probes
```
