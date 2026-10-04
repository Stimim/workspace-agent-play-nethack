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

## Completed paired qualification: REJECT 3b

All four arms completed without tooling cutoff or replacement episodes.
The candidate is rejected and its five product/test files restored exactly
to the shipped 3a snapshot. No corrected hazard candidate or further combat
rule is attempted. The frozen rejected implementation is retained at
`/tmp/3b-hazard-candidate.patch`; all public events and native ttyrecs remain
in the corresponding data directories.

| Set | Objectives baseline→candidate | Deaths | Truncated | Stopped | Gate rejections |
| --- | --- | --- | --- | --- | --- |
| Unified development, 67 seeds | 54→55 | 5→3 | 8→5 | 0→4 | 0→4 |
| Fresh 271-300, 30 seeds | 23→21 | 5→4 | 2→2 | 0→3 | 0→3 |

Both arms have zero invalid actions and integrity failures, and complete
records. Fresh hunger deaths are 0→0. The fresh objective gate fails,
as does the zero-gate-rejections gate on both sets. Apparent death reductions
include episodes stopped by the gate, not survival wins.

| Fresh seeds (all 30) | Baseline | Candidate |
| --- | --- | --- |
| 271, 273, 275, 278-283, 285, 287-290, 292-295, 298-300 | objective_complete | objective_complete |
| 272, 274, 276, 296 | death | death |
| 277, 286 | objective_complete | stopped |
| 284 | death | stopped |
| 291, 297 | truncated | truncated |

### Trace-causal table

Every lost success and every gate stop was reconstructed from both arms'
stored public events. There are no new deaths on either set. All seven
stops report `must not idle or search adjacent to a displayed gas spore`.
Replaying each candidate's complete recorded steps found no marker errors;
the final public memory had zero unoccupied passable neighboring cells
allowed by the frozen hazard/movement rules, and the avoidance helper
returned no action. This is class (i), a defect/limitation of the changed
hazard rule, not class (ii) divergence reaching an existing failure.
The unexecuted rejected proposal's source is not recorded or claimed.

| Seed/set | Paired outcome | First different executed action, public hazard | Final stopped state |
| --- | --- | --- | --- |
| 4/dev, lost success | objective_complete→stopped | Step309: N→W; spore(63,14) | Step310, hero(62,16), spore(62,15), D3, turn315, HP11 |
| 277/fresh, lost success | objective_complete→stopped | Step889: E→S; spore(40,3) | Step942, hero(34,10), spore(35,10), D4, turn955, HP38 |
| 286/fresh, lost success | objective_complete→stopped | Step360: NE→NW; spore(28,10) | Step422, hero(14,5), spore(15,5), D4, turn427, HP18 |
| 703/dev | death→stopped | Step172: SEARCH→E; spore(16,7) | Step182, hero(20,8), spore(19,8), D3, turn189, HP18 |
| 1528054415/dev | truncated→stopped | Step277: W→SE; spore(34,14) | Step337, hero(41,14), spore(40,14), D3, turn336, HP17 |
| 1376/dev | death→stopped | Step285: E→W; spore(64,9) | Step317, hero(55,7), spore(56,7), D4, turn311, HP13 |
| 284/fresh | death→stopped | Step945: SW→N; spore(28,7) | Step969, hero(28,5), spore(28,6), D2, turn967, HP32 |

Development gains 1379 and 1887524929 are truncated→objective_complete;
all other outcome changes appear above. These gains do not override the
fresh loss and safety gates.

Reports:
- `/tmp/3b-base-dev/reports/unified-d5-regression-v2-development-20261004T092820Z.json`
- `/tmp/3b-cand-dev/reports/unified-d5-regression-v2-development-20261004T092838Z.json`
- `/tmp/3b-base-fresh/reports/hazard-3b-fresh-271-300-development-20261004T092827Z.json`
- `/tmp/3b-cand-fresh/reports/hazard-3b-fresh-271-300-development-20261004T092849Z.json`

Complete paired rows: `/tmp/3b-{dev,fresh}-comparison.json`.
Causal reconstructions: `/tmp/3b-dev-stopped-traces.json` and
`/tmp/3b-fresh-traces.json`. Seeds 271-300 are consumed and never reused.
This is scripted development qualification, not real-model milestone evidence.
Final product remains shipped low-HP prayer only; stop after 3a/3b as requested.

Final restored prayer-only checkout: 607 tests pass with three dependency
deprecation warnings; Ruff check and format check pass. Restoration content
was hash-matched to the immutable shipped baseline before writing. The
completed baseline dev/fresh arms above exercise this exact product behavior.
