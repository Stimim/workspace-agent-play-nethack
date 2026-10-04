# 0044: Hazard-only qualification after low-HP prayer

## Frozen before episodes

Baseline: shipped 3a commit c150446, copied before edits to `/tmp/single-rule-3b-baseline`. Candidate adds only hazard avoidance: never melee a displayed non-pet floating eye, never stand/search in cells adjacent (eight-neighbor distance <=1) to a known displayed gas spore. No blast-distance-two extension, rest, attacker retreat, disengagement, or generic fallback retry is added.

Shared public geometry excludes these cells from normal movement/routing and exploration search targets. A newly adjacent spore triggers one ordinary move to the first terrain-passable unoccupied non-adjacent neighbor obeying movement rules, before routine actions. If none exists, there is no fabricated safe move: existing proposal flow continues and the shared runtime/audit hazard predicate can reject an unsafe move/WAIT/SEARCH. That trapped-state limitation is explicitly part of qualification, not silently suppressed. Floating-eye melee exclusion already existed in deterministic hostile selection; shared route/runtime/audit checks cover remaining action sources. Prompts retain existing handling.

Frozen fresh seeds 271-300 reserved in ledger before either arm; Score/survival/reach-D5/cap3000, scripted development model, survival-reviewed-v2. Both arms also run full 67-seed unified-d5-regression-v2. Note0040 aggregates and trace-causal gates apply: objectives nondecreasing, deaths nonincreasing, fresh hunger deaths nonincreasing; zero invalid/gate/integrity failures, complete records; trace every lost success/new death. No sample replacement or failed-seed replacement episodes. Runs are background jobs with explicit 3600-second timeout. Product frozen after the two targeted hazard-routing tests passed; any behavior fix requires a new sample.

SHA-256:
- navigation.py: `c80d10966e804d79d95f7780b223b16b3731538b6c1d30f61ed4cc887b44a562`
- skills.py: `9ae9ba99c41b6602f88cdc2fc532cbec2d85d098882869bfd91f9ca915f69f05`
- coordinator.py: `ebe46a7c445210d07b20453ba7ffd8f1877c234e3474ce27ce9362d6f4c0f8ac`
- evaluation.py: `1dedac43c6a01c5bf8a44cacfca10b80c13358042f7f7437abec8ed633b085d9`
