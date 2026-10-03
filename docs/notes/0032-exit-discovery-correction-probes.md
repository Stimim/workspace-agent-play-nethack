# 0032: Exit-discovery correction probes

## Preregistration (frozen before any new episode)

Baseline HEAD is `1c2688a`. Freeze this section; append findings, results,
verification and decision without changing these rules.

- **Seeds:** the next 30 unused integers starting at 1270. Before registration,
  `used_seeds(evaluation/)` validated 260 used seeds across the ledger, catalog
  and committed suites. Exact sample **1270–1299 inclusive**, all unused.
  Register before either arm starts. These become development seeds, never
  fresh acceptance seeds.
- **Setup:** actual `AgentCoordinator` and `ScriptedDevelopmentModel`,
  `NetHackScore-v0`, `nle-survival-actions`, `reach_level(0,5)`, cap 3000,
  unchanged from note 0031. Separate data/report directories per arm.
- **Arms:** immutable HEAD `1c2688a` versus the four approved corrections:
  covered-object visits only as fallback immediately before hidden SEARCH;
  bound every goal participating in a detected route cycle; exclude known
  shop rooms from covered-object probing; invalidate cached peaceful glyphs
  only on unambiguous public adjacent-monster attacks on the hero.
  Freeze candidate before its fresh arm. No guard gold/follow changes, SEARCH
  cap, combat tactics changes, or POLICY_VERSION change. Do not touch the
  unmerged `item10-suites` branch or its suite files.
- **Qualification:** all 30 seeds count, including errors. Ship only if objective
  successes are **not lower**, total deaths **not higher**, hunger deaths **not
  higher**, and zero invalid actions, gate rejections and integrity problems.
  Hunger death means starvation or death with last live hunger Weak or worse
  (NLE >= 3), not zeroed terminal fields. Never silently replace a run.
- **Development only:** rerun 1240, 1253, 1259, 1265 and 1218 with corrected
  code; report separately and do not gate shipment on these reused seeds.
- **Decision:** if it fails, commit note and ledger only as
  `Record exit-discovery correction probes`. If it qualifies, ship code/tests,
  architecture/development documentation and item 9 sub-bullet linking this
  note; require full pytest, ruff check/format, diff whitespace checks, strict
  MkDocs from a clean staged export and scripted staircase seeds 1–10 at cap
  1000 (10/10), then commit via `omp_commit.py` as
  `Keep exit discovery behind frontiers and out of shops`.

No new episode preceded this preregistration. No subagents are used. Existing
user edits stay unstaged; TODO_LIST.md and docs/development.md use `git add -p`.

## Review findings and candidate freeze

Read-only review of note 0031's retained decisions found:

| Seed | Finding | Causal assessment |
| --- | --- | --- |
| 1253 | Open-door SEARCH at 923 exposes a passage; frontier step 924 relocates to a gold room; covered visits 925–927 collect gold. Vault guard demands, warns, attacks; peaceful glyph stays cached. No KICK. | New exposure; pre-existing guard/peacefulness handling. Teleport-trap mechanism inferred from relocation, not named by public messages. |
| 1259 | Known shop greeting 638; object probe 643 reveals a large mimic disguised as a scroll, HP 11→4. No KICK or disguised-door opening. | Direct new merchandise-probing exposure. |
| 1265 | Previously declined hobbit attack caches species glyph; waits 822–829 under explicit hobbit hits, HP 28→10, then dies Satiated. | Pre-existing peacefulness defect exposed on changed route, not hunger or kick damage. |
| 1218 | Covered target alternates between displayed object and red mold; covered/frontier routing ping-pongs and cycle handling abandons only frontier goals. Werejackal/jackals finish combat. | New routing exposure; combat policy itself pre-existing. |
| 1240 | Candidate finds exit door at 1692, but 1693 chooses remote shop object despite adjacent reachable exit frontier. Later floating-eye waits dominate: 931 waits plus 251 actual hidden searches. | Object-priority regression plus pre-existing repeated waits; not a SEARCH-cap diagnosis. |

Corrections preserve the existing frontier and guarded-kick flow. Covered-cell
selection runs immediately before hidden SEARCH and excludes known shop cells.
The cycle window now remembers each routed goal and abandons all participating
goals, clearing a participating committed search goal. Public adjacent attack
messages invalidate cached peaceful glyphs; attacks on another creature, hero
attacks, and nonadjacent messages do not. Intrinsic never-melee species remain
protected. Guard gold/follow behavior is unchanged.

Nine positive regression cases fail on immutable `1c2688a`, then all 87 skill
tests pass on the corrected implementation, including existing gate/evaluator
agreement and the covered-cell fallback test. Three narrow negative attack
cases also pass. No gate predicate/API is changed.

Frozen pre-episode code/test delta: `/tmp/item32-exit-candidate.patch`, SHA-256
`3cfd536af5de50755aee91e3b62db7b3ae78e1b94b962e9b0e29cf92d17e21f6`.
No runtime behavior changes during either fresh arm. Temporary evaluator suites
retain display-only `min_successes: 1`; only the frozen comparison rule decides
shipment.

## Separate development reruns (not a shipment gate)

Report:
`/tmp/item32-exit-development/reports/exit-correction-development-development-20261003T170302Z.json`.
All five reused seeds use the same score/survival/reach-D5/cap-3000 setup.

| Seed | Outcome | Steps | SEARCH | Hunger/death cause | Invalid / gate / integrity |
| ---: | --- | ---: | ---: | --- | --- |
| 1240 | objective_complete | 980 | 43 | — | 0 / 0 / 0 |
| 1253 | truncated | 3000 | 594 | — | 0 / 0 / 0 |
| 1259 | objective_complete | 607 | 102 | — | 0 / 0 / 0 |
| 1265 | death | 2528 | 774 | fainting: killed by a jackal | 0 / 0 / 0 |
| 1218 | death | 2681 | 185 | fainting: killed by an orc zombie | 0 / 0 / 0 |

**2/5 objectives, 2 deaths, 2 hunger deaths, 1 truncation.** Corrected 1240 and
1259 reach the objective instead of the reviewed floating-eye stall/mimic
death. This does not claim all reviewed failures are solved: 1253 truncates,
and 1265/1218 now die Fainting to different enemies. These adverse development
outcomes are retained and reported, not used to change the frozen candidate
or qualification thresholds.

## Candidate verification

Full pytest: **598 passed**, three dependency deprecation warnings. The first
full run found the obsolete seed-9 expectation of death within 600 steps;
corrected behavior truncates instead. Removed that incidental trajectory arm,
not repinned it; the genuine zeroed-terminal/last-live-level success invariant
remains. This is test-only cleanup after candidate freeze, with no runtime
change. Ruff check and whole-project format check pass (50 Python files).

Actual scripted staircase regression, seeds 1–10, cap 1000: **10/10** objectives,
zero invalid actions, gate rejections or integrity problems. Current policy and
default bundle are pinned in the temporary development suite; historical suite
files are unchanged. Report:
`/tmp/item32-exit-staircase/reports/exit-correction-staircase-development-20261003T170745Z.json`.

## Fresh paired comparison

Both arms retain all 30 registered seeds 1270–1299, the frozen score/survival/
reach-D5/cap-3000 setup, complete records and unchanged inputs/configuration.
These development probes are not milestone or real-model acceptance evidence.

### Baseline HEAD `1c2688a`

Report:
`/tmp/item32-exit-baseline/reports/exit-correction-baseline-development-20261003T170302Z.json`.

**20/30 objectives, 6 deaths, 0 hunger deaths, 4 truncations**; 31,524 steps,
6,986 SEARCH actions; zero invalid/gate/integrity problems.

| Seed | Outcome | Steps | SEARCH | Hunger/death cause | Invalid / gate / integrity |
| ---: | --- | ---: | ---: | --- | --- |
| 1270 | objective_complete | 524 | 0 | — | 0 / 0 / 0 |
| 1271 | death | 533 | 0 | not_hungry: killed by a bolt of lightning | 0 / 0 / 0 |
| 1272 | objective_complete | 873 | 46 | — | 0 / 0 / 0 |
| 1273 | objective_complete | 1197 | 45 | — | 0 / 0 / 0 |
| 1274 | death | 18 | 0 | not_hungry: killed by a fox | 0 / 0 / 0 |
| 1275 | objective_complete | 394 | 0 | — | 0 / 0 / 0 |
| 1276 | objective_complete | 1047 | 69 | — | 0 / 0 / 0 |
| 1277 | objective_complete | 919 | 0 | — | 0 / 0 / 0 |
| 1278 | death | 1608 | 82 | hungry: killed by a kitten | 0 / 0 / 0 |
| 1279 | truncated | 3000 | 980 | — | 0 / 0 / 0 |
| 1280 | truncated | 3000 | 1996 | — | 0 / 0 / 0 |
| 1281 | objective_complete | 737 | 0 | — | 0 / 0 / 0 |
| 1282 | objective_complete | 650 | 93 | — | 0 / 0 / 0 |
| 1283 | objective_complete | 452 | 2 | — | 0 / 0 / 0 |
| 1284 | death | 257 | 0 | not_hungry: killed by a boulder | 0 / 0 / 0 |
| 1285 | truncated | 3000 | 628 | — | 0 / 0 / 0 |
| 1286 | death | 252 | 49 | not_hungry: killed by a boulder | 0 / 0 / 0 |
| 1287 | objective_complete | 956 | 12 | — | 0 / 0 / 0 |
| 1288 | objective_complete | 1184 | 241 | — | 0 / 0 / 0 |
| 1289 | objective_complete | 671 | 0 | — | 0 / 0 / 0 |
| 1290 | objective_complete | 767 | 37 | — | 0 / 0 / 0 |
| 1291 | objective_complete | 1273 | 280 | — | 0 / 0 / 0 |
| 1292 | death | 221 | 0 | not_hungry: killed by a boulder | 0 / 0 / 0 |
| 1293 | objective_complete | 468 | 37 | — | 0 / 0 / 0 |
| 1294 | objective_complete | 605 | 0 | — | 0 / 0 / 0 |
| 1295 | objective_complete | 214 | 0 | — | 0 / 0 / 0 |
| 1296 | objective_complete | 1916 | 530 | — | 0 / 0 / 0 |
| 1297 | objective_complete | 582 | 22 | — | 0 / 0 / 0 |
| 1298 | objective_complete | 1206 | 196 | — | 0 / 0 / 0 |
| 1299 | truncated | 3000 | 1641 | — | 0 / 0 / 0 |

### Frozen corrected candidate

Report:
`/tmp/item32-exit-candidate/reports/exit-correction-candidate-development-20261003T170302Z.json`.

**23/30 objectives, 4 deaths, 2 hunger deaths, 3 truncations**; 33,592 steps,
6,918 SEARCH actions; zero invalid/gate/integrity problems.

| Seed | Outcome | Steps | SEARCH | Hunger/death cause | Invalid / gate / integrity |
| ---: | --- | ---: | ---: | --- | --- |
| 1270 | objective_complete | 523 | 0 | — | 0 / 0 / 0 |
| 1271 | death | 461 | 0 | not_hungry: killed by a bolt of lightning | 0 / 0 / 0 |
| 1272 | objective_complete | 1523 | 443 | — | 0 / 0 / 0 |
| 1273 | objective_complete | 1125 | 39 | — | 0 / 0 / 0 |
| 1274 | objective_complete | 634 | 0 | — | 0 / 0 / 0 |
| 1275 | death | 2223 | 735 | fainting: killed by a kobold lord | 0 / 0 / 0 |
| 1276 | truncated | 3000 | 494 | — | 0 / 0 / 0 |
| 1277 | objective_complete | 827 | 0 | — | 0 / 0 / 0 |
| 1278 | objective_complete | 1039 | 64 | — | 0 / 0 / 0 |
| 1279 | objective_complete | 900 | 140 | — | 0 / 0 / 0 |
| 1280 | truncated | 3000 | 1664 | — | 0 / 0 / 0 |
| 1281 | objective_complete | 607 | 0 | — | 0 / 0 / 0 |
| 1282 | objective_complete | 468 | 45 | — | 0 / 0 / 0 |
| 1283 | objective_complete | 502 | 8 | — | 0 / 0 / 0 |
| 1284 | objective_complete | 1003 | 3 | — | 0 / 0 / 0 |
| 1285 | truncated | 3000 | 506 | — | 0 / 0 / 0 |
| 1286 | objective_complete | 627 | 49 | — | 0 / 0 / 0 |
| 1287 | objective_complete | 1027 | 5 | — | 0 / 0 / 0 |
| 1288 | objective_complete | 514 | 9 | — | 0 / 0 / 0 |
| 1289 | objective_complete | 387 | 0 | — | 0 / 0 / 0 |
| 1290 | objective_complete | 810 | 34 | — | 0 / 0 / 0 |
| 1291 | objective_complete | 1209 | 220 | — | 0 / 0 / 0 |
| 1292 | objective_complete | 1677 | 430 | — | 0 / 0 / 0 |
| 1293 | death | 688 | 292 | not_hungry: killed by a guard | 0 / 0 / 0 |
| 1294 | objective_complete | 437 | 0 | — | 0 / 0 / 0 |
| 1295 | objective_complete | 201 | 0 | — | 0 / 0 / 0 |
| 1296 | objective_complete | 1020 | 126 | — | 0 / 0 / 0 |
| 1297 | objective_complete | 370 | 0 | — | 0 / 0 / 0 |
| 1298 | objective_complete | 805 | 16 | — | 0 / 0 / 0 |
| 1299 | death | 2985 | 1596 | fainting: killed by a jackal | 0 / 0 / 0 |

## Frozen-rule decision: do not ship

| Criterion | Baseline | Candidate | Result |
| --- | ---: | ---: | --- |
| Objectives not lower | 20 | 23 | Pass |
| Total deaths not higher | 6 | 4 | Pass |
| Hunger deaths not higher | 0 | 2 | **Fail** |
| Invalid / gate / integrity problems | 0 / 0 / 0 | 0 / 0 / 0 | Pass |
| All seeds, complete records, unchanged inputs and fixed configuration | Yes | Yes | Pass |

**Does not qualify.** Seeds 1275 and 1299 die Fainting in the corrected arm,
versus baseline objective completion and truncation respectively. The gains
in objectives and total deaths do not override the frozen hunger-death gate.
No thresholds, seeds, rules or candidate behavior are adjusted; no episode
is replaced. Development outcomes do not participate in this decision.

Commit **only this note and the seed ledger** as
`Record exit-discovery correction probes`. Candidate runtime/tests and the
test-only trajectory cleanup were restored to HEAD; the external frozen patch
and all episode evidence remain for investigation. Architecture, development
documentation and TODO item 9 remain unchanged by this attempt.
`POLICY_VERSION` stays `hierarchical-task-specialists-v1`; the unmerged
`item10-suites` branch and its files are untouched. User-unrelated changes stay
unstaged. Candidate verification above describes the probed implementation,
not an installed or accepted correction.
