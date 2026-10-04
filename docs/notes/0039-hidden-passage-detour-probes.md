# 0039: Hidden-passage and boulder-detour probes

**Decision: REJECT.** The 30-seed aggregate qualifies, but the 67-seed
development run loses five established successes. No product change ships.

## Preregistration (before any episode)

Baseline HEAD is `9e56dd70f85cefca3a9c889931799f0661bfdcaf` (note 0038's
shipped goal-aware branch-exit fix). The user moved task/suite unification to
a separate branch; this candidate does not edit TaskSpec validation or suite
JSON files. The historical 67-seed external development setup stays fixed.

- **Qualification:** the next 30 unused development integers, **1440–1469**.
  `used_seeds(evaluation/)` returned 430 used seeds and verified this range
  unused before registration. Register it in the ledger before either arm.
  These seeds are never fresh acceptance seeds.
- **Setup:** actual coordinator, scripted development model, lawful dwarven
  Valkyrie, `NetHackScore-v0`, `nle-survival-actions`, `reach_level(0,5)`, cap
  3000, `survival-reviewed-v2`, `hierarchical-survival-exit-v1`. Use separate
  immutable baseline and candidate worktrees/data/report directories under
  `/tmp/hidden-detour-{baseline,candidate}/`.
- **Candidate:** retain bounded search budgets and current density/distance
  scoring. Add blank orthogonal continuations opposite known passages to
  corridor search candidates, even at bends or fanned ends; search outward
  from visited doorless doorways as already done from open doors. Exclude
  displayed boulders from concealed-passage targets: explore hidden detours,
  never push or route through boulders. Continue an existing search before
  approaching a monster-blocked frontier; real reachable frontiers still
  take precedence. Do not alter melee, HP recovery, prayer, hunger, door-kick
  safety, knowledge cards, TaskSpec, or historical suite contracts.
- **Freeze:** finish implementation and behavior tests, record the candidate
  patch SHA-256, then run episodes. Never mutate an arm mid-suite, redraw or
  replace failed seeds, or rerun failed runs. Disclose all preflight failures.
- **Development gate:** run the same 67 seeds once; compare with retained HEAD
  results from note 0038: 52 objectives, eight deaths, one hunger death, seven
  truncations. Objectives cannot fall, and no previous success may become a
  failure unless explicitly justified here. Report every changed outcome.
  Targets are 5, 701, 1368, 1372, 1379, and 703 if its blocker shares this cause.
- **Qualification gate:** ship only if candidate objectives are not lower,
  deaths and hunger deaths are not higher, all records are complete, and
  invalid actions, gate rejections, and integrity problems are zero on all
  30 seeds. Hunger death means starvation or last-live hunger Weak or worse
  (NLE >= 3), not terminal zeroed statistics or historical worst hunger.
  Harness display thresholds are not the shipment rule.
- **Decision:** ship or reject the frozen candidate according to those gates.
  A shipped fix gets behavioral regressions, architecture/development updates,
  this retained comparison, and the repository provenance commit procedure.
  Scripted results are not real-model milestone acceptance.

## Diagnosis and failing-before behavior

Replay of retained public observations on the six target seeds identifies
missing candidate geometry rather than a need to push boulders:

- 5: the boulder-free native diagnostic route uses hidden continuation (30,7)
  beside known corridor (29,7). Its west/northwest/south exits make the old
  pairwise-adjacent dead-end test false, so that continuation has zero searches.
- 701: visited doorless doorway (44,4) faces hidden corridor (45,4), but the
  old doorway branch searches wall glyphs only; the outward blank has zero
  searches. The further native route includes a secret door and locked gate.
- 1368: corridor (66,13) has a three-cell north fan. Its hidden south
  continuation (66,14) has zero searches because the fan is not an old dead end.
- 1372: the boulder-free route needs hidden continuation (64,7) beside corridor
  (63,7); a west fan again defeats the old dead-end predicate.
- 1379: late public decisions oscillate between approaching a monster-blocked
  frontier (8,12) and routing away to committed search (7,16), spending no
  searches at that destination. Continuing a reachable commitment removes
  this particular interruption without displacing actual reachable frontiers.
- 703: a displayed, unsafe-to-melee gas spore blocks the tiny current reachable
  component. This candidate does not authorize attacking it. Measure whether
  newly eligible search geometry exposes a detour; do not assume it succeeds.

Native terrain is diagnostic only and is never an input to policy decisions.
Public memory reconstructs zero coverage on the missing targets. The previous
boulder-free diagnostic paths for 5 and 1372 contain hidden passages, so their
existing ability to route around *known* boulders was not the missing feature.

Five meaningful regression cases fail before the product repair: doorless
outward search, bend continuation, fanned-end continuation, exclusion of a
known boulder from hidden search, and commitment ahead of blocked frontiers.
The original open-door case passes. The first bend fixture was too simple
and passed; it was corrected to the observed three-direction geometry before
implementation. The first blocked-frontier fixture lacked remembered terrain
under its monster and passed; adding the previously visible corridor makes
it reproduce the failure. All six final cases pass after the repair.

## Candidate freeze

The frozen product/test patch `/tmp/hidden-detour-candidate.patch` has SHA-256
`b1ba89b6c42c7fb77d16d10c68c4e45c2aa1228096a0c8028956f1d347d17a91`.
It is applied to detached HEAD `9e56dd7` in `/tmp/hidden-detour-candidate`;
`/tmp/hidden-detour-baseline` remains unchanged at that HEAD. The external
qualification suite is `/tmp/hidden-detour-qualification.json`; neither
tracked task validation nor tracked suite JSON files changed.

Before any episode, the six focused cases passed and the complete test suite
passed **600 tests**, with three dependency deprecation warnings (57.65s).
Both product and behavioral tests now stay frozen throughout the runs.

## Complete frozen qualification results

| Arm, seeds 1440–1469 | Objectives | Deaths | Hunger deaths | Truncated | Invalid / gate / integrity |
| --- | ---: | ---: | ---: | ---: | --- |
| Baseline HEAD | 17/30 | 7 | 0 | 6 | 0 / 0 / 0 |
| Frozen candidate | 20/30 | 6 | 0 | 4 | 0 / 0 / 0 |

The qualification aggregate passes its frozen comparison rule: 20 >= 17
objectives, 6 <= 7 deaths, 0 <= 0 hunger deaths, and zero invalid actions,
gate rejections, integrity problems, failed/repaired model decisions, or
fallback actions. Every record is complete. Baseline has 859 scripted model
decisions versus 535 for the candidate; neither is real-model acceptance.

The qualification sample **does lose two individual previous successes**:
1446 dies to a wererat, and 1467 dies to a giant bat, both Not Hungry.
The rule preregisters aggregate non-increasing deaths, not per-seed retention
on this new qualification sample; these losses are nevertheless disclosed.
The five improvements are 1445 and 1449 (truncation to objective), plus 1453,
1459 and 1460 (death to objective). The latter baseline deaths were iguana,
iguana and small mimic, respectively, all Not Hungry.

| Seed | HEAD outcome / steps | Frozen candidate outcome / steps |
| ---: | --- | --- |
| 1440 | objective_complete / 708 | objective_complete / 708 |
| 1441 | objective_complete / 1021 | objective_complete / 1188 |
| 1442 | truncated / 3000 | truncated / 3000 |
| 1443 | objective_complete / 786 | objective_complete / 786 |
| 1444 | truncated / 3000 | truncated / 3000 |
| 1445 | truncated / 3000 | objective_complete / 1897 |
| 1446 | objective_complete / 1229 | death / 1293 |
| 1447 | objective_complete / 662 | objective_complete / 662 |
| 1448 | objective_complete / 2873 | objective_complete / 2368 |
| 1449 | truncated / 3000 | objective_complete / 1772 |
| 1450 | truncated / 3000 | truncated / 3000 |
| 1451 | death / 262 | death / 262 |
| 1452 | death / 81 | death / 81 |
| 1453 | death / 2297 | objective_complete / 2140 |
| 1454 | objective_complete / 997 | objective_complete / 1066 |
| 1455 | objective_complete / 1581 | objective_complete / 1794 |
| 1456 | objective_complete / 869 | objective_complete / 869 |
| 1457 | truncated / 3000 | truncated / 3000 |
| 1458 | objective_complete / 296 | objective_complete / 296 |
| 1459 | death / 2578 | objective_complete / 2473 |
| 1460 | death / 2512 | objective_complete / 1786 |
| 1461 | objective_complete / 665 | objective_complete / 665 |
| 1462 | objective_complete / 790 | objective_complete / 855 |
| 1463 | objective_complete / 414 | objective_complete / 414 |
| 1464 | objective_complete / 1036 | objective_complete / 1036 |
| 1465 | death / 689 | death / 689 |
| 1466 | objective_complete / 399 | objective_complete / 399 |
| 1467 | objective_complete / 1456 | death / 1357 |
| 1468 | objective_complete / 843 | objective_complete / 843 |
| 1469 | death / 540 | death / 540 |

Baseline report:
`/tmp/hidden-detour-baseline/qualification-reports/hidden-detour-qualification-development-development-20261004T025340Z.json`.
Candidate report:
`/tmp/hidden-detour-candidate/qualification-reports/hidden-detour-qualification-development-development-20261004T025340Z.json`.
Their SQLite records and ttyrecs remain in each worktree's
`qualification-data/`. No run was replaced or rerun, no evaluated tree was
mutated, and there were no harness preflight failures.

For the two qualification losses, the first action differences are search
choices on D4, not new attack permissions. At step 645, 1446's candidate
heads one step toward search stand (48,11), whereas HEAD heads toward (44,16)
30 steps away; both recorded observations have 27 HP and Not Hungry.
At step 317, 1467's candidate searches at (69,17), whereas HEAD starts a
21-step route to (50,11); both have 18 HP and Not Hungry. Subsequent combat
remains the unchanged policy. These recorded differences do not excuse or
hide the eventual deaths.

## Complete development results and rejection

| 67-seed arm | Objectives | Deaths | Hunger deaths | Truncated | Invalid / gate / integrity |
| --- | ---: | ---: | ---: | ---: | --- |
| Current HEAD, retained note-0038 run | 52/67 | 8 | 1 | 7 | 0 / 0 / 0 |
| Frozen hidden-detour candidate | 52/67 | 8 | 0 | 7 | 0 / 0 / 0 |

Every candidate record is complete, with zero failed/repaired model decisions.
There are 416 scripted model decisions (HEAD: 551), 11 model fallback actions
(HEAD: zero), and 63,482 steps (HEAD: 70,244). **Reject despite unchanged
objective/death counts and improved qualification aggregates:** seeds **1,
1369, 1377, 1528054415, and 1887524929** were established successes and now
fail. There is no justified exception to success retention here. In particular,
1377 now dies to a guard; the other four newly fail at the step cap. Five new
objectives merely offset those five lost successes and cannot hide them.

The apparent hunger-death improvement is not a prayer or nutrition fix.
1376 now dies much earlier to a goblin, Not Hungry, at step 367, rather than
the retained HEAD werejackal death with last-live Fainting at step 2650.
That earlier combat death removes its hunger-death classification without
making the seed successful or proving better long-term nutrition.

Every changed outcome class is retained below; unchanged outcomes and all
step differences remain in the complete JSON report.

| Seed | HEAD outcome / steps | Frozen candidate outcome / steps |
| ---: | --- | --- |
| 1 | objective_complete / 1524 | truncated / 3000 |
| 703 | truncated / 3000 | death / 552 |
| 902 | death / 2915 | truncated / 3000 |
| 924 | truncated / 3000 | objective_complete / 695 |
| 1368 | truncated / 3000 | objective_complete / 928 |
| 1369 | objective_complete / 1263 | truncated / 3000 |
| 1372 | truncated / 3000 | objective_complete / 795 |
| 1374 | death / 1240 | objective_complete / 1748 |
| 1377 | objective_complete / 1615 | death / 1891 |
| 1379 | truncated / 3000 | death / 2042 |
| 1528054415 | objective_complete / 1724 | truncated / 3000 |
| 1887524929 | objective_complete / 1444 | truncated / 3000 |
| 2105401147 | death / 661 | objective_complete / 1006 |

Of the requested targets, **1368 and 1372 complete**. Seeds **5 and 701 still
truncate at 3000** despite fewer search steps (candidate 630 and 278).
**703 dies to a gas spore explosion**, Not Hungry; its terminal action and
preceding nine actions are SEARCH, not authorized melee. Its last live public
observation places the hero at (55,3) with 11 HP and a gas spore at (53,3).
The records establish a threat during searching, not which actor triggered
the explosion. **1379 dies to a homunculus**, Not Hungry, at 2042. Neither
death is counted as resolving a hidden-passage failure.

The candidate's geometry changes demonstrably repair isolated blind spots,
but expanding candidates while retaining density/distance scoring is not
qualified as a whole policy. The current search commitment rule also does
not establish threat-aware waiting or recovery. No narrower subset is
silently shipped using this candidate's reports.

Development report:
`/tmp/hidden-detour-candidate/development-reports/unified-baseline-development-development-20261004T025340Z.json`.
Retained current-HEAD development baseline:
`/tmp/branch-exit-frontier-candidate/development-reports/unified-baseline-development-development-20261004T020745Z.json`.
All 67 seeds ran once under the identical external suite
`/tmp/unified-baseline-suite.json`. The candidate worktree, patch, reports,
SQLite records and ttyrecs stay intact for diagnosis; failed seeds were not
rerun, replaced, or redrawn.

## Main-tree disposition

After all three suites completed, the main-tree product and test files were
restored to HEAD's behavior. The frozen rejected patch and its five
failing-before regressions remain in the candidate worktree, not as failing
tests against an unchanged product. Only this rejection record, its
documentation-index link, and the permanently consumed seed-ledger range
are retained in the main tree.
Architecture/development feature descriptions intentionally remain unchanged
because no new feature ships. TaskSpec validation, suite JSON files, policy
pin and knowledge bundle remain untouched, preserving the infrastructure
branch's integration boundary.

Post-rejection verification: the restored skill behavior and consumed
seed-registry tests passed **102 tests** (2.12s). This is not a rerun of any
failed episode or of the frozen comparison. The candidate's 600-test result
and all 127 coordinator episodes remain the evidence for rejecting its
behavior despite passing unit coverage.
The staged documentation export also passed a strict build with pinned
MkDocs 1.6.1, pymdown-extensions 12.1, and mermaid2-plugin 1.2.3.
