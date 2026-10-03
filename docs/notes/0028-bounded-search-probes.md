# 0028: Bounded-search probes and a rejected budget decision

Date: 2026-10-03

## Scope and decision

Milestone 2 item 9 remains **not complete**. No budget was selected and no
bounded-search policy was shipped: all three pre-registered candidates failed
the no-increase-in-starvation-deaths rule. The only product commit from this
work is the budget-independent corpse recording fix `d43cc64`, documented in
[note 0027](0027-safe-fresh-corpse-eating.md). Policy version stays unchanged.

All episodes here used the actual coordinator and `ScriptedDevelopmentModel`,
`NetHackScore-v0`, `nle-survival-actions`, `reach_level(0,5)`, and cap 3000.
They are development evidence, never real-model acceptance runs. Seeds
1170–1209 are excluded through the used-seed ledger. Explicit seed fields and
inclusive ledger ranges were checked for prior use, together with all
`evaluation/*.json` files. No acceptance suite or threshold was changed.

## Item-8 baseline, seeds 1170–1189

The first probe used isolated HEAD `802b23b`. Its three corpse-gate errors
(1170, 1177, 1185) were retained; those seeds were rerun at `a30b300` after
that independent fix. The other seventeen outcomes matched the corrected
baseline smoke. The table below uses the corrected measurements for those
three seeds and the original measured trajectories for the other seventeen.
`D` is Dungeons of Doom, `M` is Mines; search counts follow chronological
level visits, including revisits. Depth includes the final live objective
observation; visits count the level on which each executed action was chosen.
Hungry means the first live hunger index ≥2, in game turns. Meals count
observed finished corpse meals, not attempted EATs. Worst hunger ignores
zeroed terminal statistics.

| Seed | Outcome | Depth | Death cause | Steps | SEARCH | SEARCH by visit | PRAY / meals | First Hungry turn | Worst hunger |
| ---: | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | --- |
| 1170 | death | 3 | killed by a gecko | 1001 | 20 | D1:0; D2:0; D3:20 | 0 / 0 | 751 | Fainting |
| 1171 | objective_complete | 5 | — | 1647 | 377 | D1:0; D2:377; D3:0; M1:0; D3:0; D4:0 | 1 / 0 | 744 | Weak |
| 1172 | truncated | 3 | — | 3000 | 1021 | D1:30; D2:91; D3:900 | 2 / 3 | 735 | Fainting |
| 1173 | objective_complete | 5 | — | 329 | 11 | D1:0; D2:0; D3:11; D4:0 | 0 / 1 | — | Not Hungry |
| 1174 | death | 2 | killed by a jackal | 1184 | 0 | D1:0; D2:0 | 0 / 1 | 946 | Fainting |
| 1175 | objective_complete | 5 | — | 246 | 0 | D1:0; D2:0; D3:0; M1:0; D3:0; D4:0 | 0 / 0 | — | Not Hungry |
| 1176 | truncated | 2 | — | 3000 | 1337 | D1:2; D2:1335 | 2 / 0 | 738 | Fainting |
| 1177 | objective_complete | 5 | — | 765 | 11 | D1:0; D2:5; D3:0; D4:6 | 0 / 3 | — | Not Hungry |
| 1178 | objective_complete | 5 | — | 380 | 0 | D1:0; D2:0; M1:0; D2:0; D3:0; D4:0 | 0 / 2 | — | Not Hungry |
| 1179 | objective_complete | 5 | — | 199 | 0 | D1:0; D2:0; D3:0; D4:0 | 0 / 0 | — | Not Hungry |
| 1180 | truncated | 3 | — | 3000 | 1185 | D1:0; D2:0; M1:0; D2:0; D3:1185 | 2 / 4 | 936 | Weak |
| 1181 | truncated | 4 | — | 3000 | 1652 | D1:248; D2:0; D3:7; M1:0; D3:0; D4:1397 | 2 / 1 | 726 | Fainting |
| 1182 | objective_complete | 5 | — | 383 | 0 | D1:0; D2:0; D3:0; D4:0 | 0 / 0 | — | Not Hungry |
| 1183 | objective_complete | 5 | — | 522 | 0 | D1:0; D2:0; D3:0; D4:0 | 0 / 0 | — | Not Hungry |
| 1184 | objective_complete | 5 | — | 1516 | 410 | D1:410; D2:0; D3:0; D4:0 | 0 / 2 | 748 | Hungry |
| 1185 | objective_complete | 5 | — | 1704 | 446 | D1:0; D2:0; D3:446; D4:0 | 0 / 4 | 808 | Hungry |
| 1186 | death | 4 | killed by a kobold zombie | 978 | 24 | D1:4; D2:0; D3:0; D4:0; M1:0; D4:20 | 0 / 1 | 760 | Fainting |
| 1187 | objective_complete | 5 | — | 365 | 0 | D1:0; D2:0; D3:0; D4:0 | 0 / 0 | — | Not Hungry |
| 1188 | objective_complete | 5 | — | 298 | 12 | D1:12; D2:0; D3:0; D4:0 | 0 / 0 | — | Not Hungry |
| 1189 | objective_complete | 5 | — | 1516 | 426 | D1:0; D2:0; D3:426; D4:0 | 0 / 0 | 741 | Hungry |

Corrected outcomes: **13/20 objective completions, four truncations, three
deaths**, with 6,932 SEARCH actions. The four long searches remain the dominant
cost. The deaths on 1170/1174/1186 reached Fainting with only 20/0/24 SEARCH
respectively: a search-action cap cannot address every hunger failure.

## Why nominally bounded search runs indefinitely

The legacy quota is ten searches **per neighbouring target cell per round**,
not ten searches per level. Coverage persists across visits and is **not**
cleared on rearm. Rearm instead raises the quota to
`10 * (search_round + 1)` and clears suspected navigation failures and abandoned
search goals. Thus already-covered barren rock becomes eligible again forever.

Spots are room cells next to straight walls or corridor dead ends next to
unknown cells. Dead ends have no priority tier. Scores sum radius-four blank
cell densities for every target, double-counting overlapping regions, require
raw score ≥20, and subtract twice the BFS distance. A committed spot remains
until spent or unreachable. Unknown rock need not contain any hidden passage.

When exploration exhausts a round, the coordinator marks the level exhausted,
but a reach-level planner still needs the unknown downstairs. A stuck model
choice of `explore_level` rearms search; the scripted model always chooses it.
A consultation can recur after twenty steps. Knowledge growth may clear the
current exhausted marker, while the persistent `explored` flag remains set.
For example, 1176 marked D2 exhausted twice yet searched it 1,335 times;
1180 marked D3 twice yet searched 1,185 times; 1181 marked D4 twice yet searched
1,397 times. These are observed trajectories, not claims about hidden layouts.
Wizard mode changed level generation at reset, so no corresponding true-layout
map was available and none was used for scoring or tuning.

## Pre-registered experiment and selection rule

The fixed candidate set was **300, 450, 600** executed `Command.SEARCH` actions
per persistent level key per episode, including model fallbacks. Allowance
never reset on revisit, rearm, branch rearm, or new knowledge. Travel, WAIT,
prompt answers, and kicks did not consume it. The frozen experimental ordering
ranked corridor dead ends first; within tiers it maximised unique never-observed
blank cells in the union of radius-four target regions, minus twice BFS distance,
then tied by distance, row, column. Dead ends with nonempty targets remained
eligible below the wall score cutoff of twenty. Search commitment and per-cell
round coverage remained in place within the hard cap.

At the cap, visible frontiers, existing door handling, survival actions, and
known compatible stairs still ran. With no visible progress action or compatible
staircase, a typed `search_budget_exhausted` marker accompanied the exhaustion
confirmation and the run ended non-success `STUCK`. No second allowance,
upstairs reset, unverified wall kicking, or imaginary trapdoor descent was added.
The prototype persisted only budget and ordering version for replay; absence
selected legacy search. Actual SEARCH actions were independently counted in
replay. The experiment did not claim full map coverage when marking a level
policy-exhausted.

Selection was fixed before seeds 1190–1209 ran: choose the smallest candidate
with at least the legacy baseline's objective completions, no increase in
starvation or deaths while Weak/Fainting, no gate/invalid-action/replay problems,
and at least 25% fewer total SEARCH actions. Existing must-pass catalog entries
and Scout/Eat metric thresholds also had to hold before freezing any winner.
No candidate passed the primary rule, so those later qualification checks were
not run and the rule was not relaxed after seeing the seeds.

## Initial comparison: invalidated by a common item-8 bug

Cells below are `outcome / SEARCH`. The legacy arm used `a30b300`; the candidate
arms used the frozen experimental search behavior. These results are preserved
but were **not used to select a budget**.

| Seed | Legacy | 300 | 450 | 600 |
| ---: | --- | --- | --- | --- |
| 1190 | objective_complete / 18 | death / 1 | death / 1 | death / 1 |
| 1191 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1192 | truncated / 1258 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1193 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1194 | death / 32 | error / 72 | death / 72 | death / 72 |
| 1195 | objective_complete / 10 | objective_complete / 10 | objective_complete / 10 | objective_complete / 10 |
| 1196 | truncated / 1734 | stuck / 365 | stuck / 515 | stuck / 665 |
| 1197 | death / 78 | objective_complete / 89 | objective_complete / 89 | objective_complete / 89 |
| 1198 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1199 | death / 338 | stuck / 330 | stuck / 480 | stuck / 630 |
| 1200 | truncated / 2314 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1201 | objective_complete / 117 | stuck / 300 | objective_complete / 355 | objective_complete / 355 |
| 1202 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1203 | truncated / 1418 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1204 | death / 474 | objective_complete / 153 | objective_complete / 153 | objective_complete / 153 |
| 1205 | truncated / 1462 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1206 | truncated / 1549 | death / 47 | death / 47 | death / 47 |
| 1207 | death / 1659 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1208 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1209 | death / 0 | death / 0 | death / 0 | death / 0 |

The event validator incorrectly classified southeast movement (`n`) with corpse
route evidence as a decline, although the coordinator and evaluator restricted
actual declines to deterministic prompt answers. In the legacy baseline this
failed on 1194 step 311, 1195 step 401, 1196 steps 295/1367, 1197 step 202,
1204 steps 555/631, 1205 steps 2306/2308/2310, and 1209 step 362. Initial
candidate arms each had five episodes with a typed-event failure. The first
300/1194 attempt stopped at that audit error (the shown 72 SEARCH is a preserved
partial count); later audit failures were retained while gameplay continued.
No erroneous run was silently treated as clean.

Fix `d43cc64` shares decline classification and live outcome between coordinator,
event validator, and evaluator. Synthetic and real 1194 regressions failed
before and passed after it; the fix was committed independently. Every arm was
then rerun on the same seeds with the fixed corpse semantics, without changing
ordering, candidates, cap, or selection rule. Reusing these seeds was explicitly
authorised because the fix was budget-independent.

## Corrected four-arm comparison

The legacy arm explicitly used legacy search semantics; candidate arms retained
the same frozen experimental behavior. All eighty episodes completed with no
coordinator errors or typed-event/replay problems. Every exhausted-budget marker
was checked against executed SEARCH counts and the current public level.

| Seed | Legacy | 300 | 450 | 600 |
| ---: | --- | --- | --- | --- |
| 1190 | objective_complete / 18 | death / 1 | death / 1 | death / 1 |
| 1191 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1192 | truncated / 1258 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1193 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1194 | death / 32 | death / 72 | death / 72 | death / 72 |
| 1195 | objective_complete / 10 | objective_complete / 10 | objective_complete / 10 | objective_complete / 10 |
| 1196 | truncated / 1734 | stuck / 365 | stuck / 515 | stuck / 665 |
| 1197 | death / 78 | objective_complete / 89 | objective_complete / 89 | objective_complete / 89 |
| 1198 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1199 | death / 338 | stuck / 330 | stuck / 480 | stuck / 630 |
| 1200 | truncated / 2314 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1201 | objective_complete / 117 | stuck / 300 | objective_complete / 355 | objective_complete / 355 |
| 1202 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1203 | truncated / 1418 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1204 | death / 474 | objective_complete / 153 | objective_complete / 153 | objective_complete / 153 |
| 1205 | truncated / 1462 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1206 | truncated / 1549 | death / 47 | death / 47 | death / 47 |
| 1207 | death / 1659 | stuck / 300 | stuck / 450 | stuck / 600 |
| 1208 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 | objective_complete / 0 |
| 1209 | death / 0 | death / 0 | death / 0 | death / 0 |

| Arm | Complete | STUCK | Death | Truncated | SEARCH | SEARCH saved | Starvation deaths | Weak/Fainting deaths | Audit problems |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Legacy | 8 | 0 | 6 | 6 | 12461 | — | 1 | 5 | 0 |
| 300 | 8 | 8 | 4 | 0 | 2867 | 77.0% | 2 | 4 | 0 |
| 450 | 9 | 7 | 4 | 0 | 3972 | 68.1% | 2 | 4 | 0 |
| 600 | 9 | 7 | 4 | 0 | 5022 | 59.7% | 2 | 4 | 0 |

**No candidate qualifies.** Starvation increased from **one to two** in every
candidate arm. Seed 1209 starved with zero SEARCH in every arm; seed 1206,
which the legacy arm truncated after reaching D4, instead starved on D3 in
all candidate arms after 47 total SEARCH. That additional starvation occurred
below even the smallest cap; increasing the cap among the fixed candidates did
not change it. Candidate ordering also changed 1190 from completion to a
Fainting jackal death with only one SEARCH. Conversely, 1197 and 1204 became
completions; 1201 needed more than 300 SEARCH under the new ordering and
completed with 450/600. These are paired observations, not seed-specific fixes
or a justification for post-hoc threshold changes.

STUCK is never success. It terminates episodes that might otherwise have died
later, so reduced death counts must be read together with STUCK counts (eight
at 300, seven at 450/600), not as unconditional survival improvements. The later
item-10 ≥50% objective-completion gate is unaffected and was not evaluated here.

The rejected experimental product changes were removed from the main tree;
only the separate corpse recording fix is shipped. Item 9 stays unchecked,
architecture and developer instructions remain descriptions of the shipped
legacy search, and no budget/policy-version or acceptance commitment was made.

## Verification and local evidence

For the independent corpse fix: full `uv run pytest -q` passed **561 tests**;
Ruff lint and format checks passed. A direct coordinator smoke recorded actual
seed 1194 step 311, game turn 311, `CompassDirection.SE` toward a sewer-rat
corpse with no decline outcome, accepted by the typed event contract. The
actual real-seed evaluator regressions reported no invalid actions, gate
rejections, or integrity problems.

Probe JSON, full per-step before/after/selection traces, and ttyrecs remain in
`/tmp/item9-baseline-data`, `/tmp/item9-corrected-baseline-data`,
`/tmp/item9-fresh-baseline-data`, `/tmp/item9-candidate-{300,450,600}-data`, and
`/tmp/item9-fixed-candidate-{0,300,450,600}-data`; matching `*-results.json` files
record episode metrics. The frozen rejected draft is retained outside the
repository as `/tmp/item9-bounded-after-d43cc64.patch`, with the corrected probe
harness `/tmp/item9_fixed_candidate.py`. These temporary development artifacts
are not committed suites or acceptance reports.
