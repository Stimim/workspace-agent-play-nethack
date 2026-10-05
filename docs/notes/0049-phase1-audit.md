# Phase 1 Audit

## Decision

The Phase 1 commits (Minetown and Oracle Objectives) have been reverted due to critical defects that make completion claims unreliable and introduce detector false positives.

A code review identified two significant defects:
1. **False Negative in Corpse Route Evaluator**: `_corpse_route_error` falsely invalidates routes to lichen corpses (which have no kill turn) if a previous kill on the same tile was consumed. This caused a valid run to be marked as having an invalid action in `minetown-regression-v1` for seed 703.
2. **False Positive in Conduct Detector**: `CompassDirectionLonger` (multi-step moves like `G`) was omitted from the `MOVE_ACTION_NAMES` checked by `attack_evidence` in `conduct.py`. This means the agent could attack the Oracle without incrementing `oracle_attacks`, causing the peacefulness completion detector to incorrectly claim success even if the Oracle was attacked.

Identical-outcome tests confirmed that `reach-D5` performance remained unchanged with 0 differences across 67 seeds, proving that the underlying survival mechanics didn't regress. However, due to the conduct verification blind spot creating a detector false positive, the commits are reverted.

My fixes for these defects, alongside the original commits, are preserved in `/tmp/phase1-candidate.patch` for a future worker to apply and continue.

### Baselines

I recomputed the deterministic baselines using the fallback model, which returned identical task successes to what the original worker reported in the conversation (but contrary to note 0048):
- **Minetown (`minetown-regression-v1`)**: 19/67 successes.
- **Oracle (`oracle-regression-v1`)**: 9/67 successes.

Note 0048 reported 5/67 and 1/67, respectively, which directly contradicted the committed JSON files.

### Detector Audit

Detector audits timed out while verifying cross-checks with native_truth, but the static analysis confirms the False Positive risk for the Oracle detector.
