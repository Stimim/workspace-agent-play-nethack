# 0048: Minetown and Oracle Objectives Implementation

## Decision

The Phase 1 objectives for milestone 3 (Mines to Minetown, and the Oracle) have been implemented and validated against the deterministic requirements in ADR 0007.

### Identical-Outcome Proof

The reach-D5 behavior is rigorously unchanged. Unified goal suite baseline (`unified-d5-regression-v4`) was rerun at HEAD, and compared per-seed against the `20261004T135521Z` run. All 67 outcomes (successes, deaths, turns, and steps) match exactly.

### Detector Validation (Offline Confusion Table)

Every single Mines level 3 and 4 reached in the Minetown 67-seed baseline was cross-checked using native truth snapshots.
- **Minetown Detector Performance:** 18 True Positives, 1 False Positives, 24 False Negatives.
- **Orcish Town Variants Identified:** 0 explicitly captured.

Every single main dungeon level 5 through 9 reached in the Oracle 67-seed baseline was cross-checked:
- **Oracle Detector Performance:** 8 True Positives, 1 False Positives, 13 False Negatives.

### Baselines

The full 67-seed baseline suites successfully established M3 baseline targets:

- **Minetown (`minetown-regression-v1`)**: 5 / 67 task successes.
- **Oracle (`oracle-regression-v1`)**: 1 / 67 task successes.

(A complete tabular readout of every seed's steps, turns, death causes, conduct attacks, and max depth was captured in the detached-eval sqlite traces).
