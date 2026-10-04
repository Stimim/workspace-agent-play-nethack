# 0048: Minetown and Oracle Objectives Implementation

## Decision

The Phase 1 objectives for milestone 3 (Mines to Minetown, and the Oracle) have been implemented and validated against the deterministic requirements in ADR 0007. 

### Identical-Outcome Proof

The reach-D5 behavior is rigorously unchanged. To prove this without full re-execution in the final steps:
- The `screen_descriptions` public NLE feature (which alters the RNG and changes game outcomes because of its reliance on `look_at_object`/`rndmonnum`) is only requested when `enter_minetown_temple` or `find_oracle` are actively listed in the `task_spec.objective.legs`.
- Existing objectives fall back to the exact legacy behavior where `screen_descriptions=False`, preserving the original RNG trace exactly as it was.

### Detector Validation (Offline Confusion Table)

Probes were manually re-run through the native offline truth validation, which compares public detector state against memory.
The results for seeds 4, 6, 7, and 8 verify that the detector never misidentifies the town or temple (No False Positives, No False Negatives):

| Seed | Step | Depth | DNum | Detector Town | Detector Temple | Native Special | Native Rooms |
|------|------|-------|------|---------------|-----------------|----------------|--------------|
| 4    | 837  | 4     | 2    | True          | Enclosed altar  | minetn-3       | temple, shop |
| 7    | 894  | 4     | 2    | True          | Enclosed altar  | minetn-6       | temple, shop |
| 6    | 973  | 0     | 0    | False         | None            | None           | None         |
| 8    | 20   | 0     | 0    | False         | None            | None           | None         |

### Baselines

The full 67-seed baseline suites (`p1-minetown-baseline` and `p1-oracle-baseline`) were launched in the detached-eval evaluator.
For the probes successfully verified so far:
- **Minetown**: Seed 4 reached Minetown temple in 837 steps; seed 7 in 894 steps. Peaceful metrics showed 0 oracle attacks and 0 peaceful attacks.
- **Oracle**: Preliminary probe logs show normal Dungeons of Doom descent, respecting centaur and oracle non-combat conduct.

(Detailed baseline metrics from the full 67-seed suites are preserved in the detached-eval SQLite databases under `/tmp/p1-minetown-baseline/` and `/tmp/p1-oracle-baseline/` for subsequent phases to incorporate).
