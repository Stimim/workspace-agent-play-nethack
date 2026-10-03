# 0030: Post-fix bounded-search probes

## Preregistration (frozen before any episode runs)

Registered 2026-10-03 at post-fix revision `02dbf36`. This section is frozen:
results, diagnostics, and any conflict-resolution evidence belong in later
sections and must not change these rules.

- **Seeds:** the next 30 unused integer seeds starting at 1210, checked with
  `used_seeds(evaluation/)` against the ledger, representative catalog, and
  every `evaluation/*.json`: `eat-v1.json`, `representative-seeds.json`,
  `scout-v1.json`, `seed-ledger.json`, `staircase-v1.json`, `staircase-v2.json`,
  `staircase-v3.json`, `traversal-v1.json`, and `traversal-v2.json`.
  The audit found 200 previously registered seeds and no used seeds in
  1210–1239; the exact sample is **1210–1239 inclusive**, with no skips.
  Register the full range in the ledger as development seeds before running.
- **Setup:** actual `AgentCoordinator` plus `ScriptedDevelopmentModel`,
  `NetHackScore-v0`, `nle-survival-actions`, `reach_level(0,5)`, cap 3000,
  isolated worktree at `02dbf36`. Isolate artifact directories by arm and seed.
- **Arms:** legacy (no cap), and per-level SEARCH caps **300, 450, 600**,
  using the frozen draft `/tmp/item9-bounded-after-d43cc64.patch` rebased onto
  `02dbf36`. The rebase may only resolve conflicts; behavior must not change.
  If it does not apply cleanly, report the conflicts before any episode runs.
- **Qualification:** a cap qualifies only if, compared with legacy on the
  same seeds, **all** hold: (a) total deaths are not higher; (b) hunger deaths
  (starvation, or death while Weak/Fainting) are not higher; (c) objective
  successes are not lower; (d) zero invalid actions, gate rejections, and
  integrity problems.
- **Selection:** among qualifying caps, pick the largest drop in total SEARCH;
  on a tie, pick the larger cap. If none qualifies, ship nothing, record the
  result, and stop.

These are development probes, never future fresh acceptance seeds. No policy
version, prayer timeout, corpse rules, or non-search behavior is part of the
comparison. The user's unrelated main-tree changes must remain unstaged.

## Frozen-draft rebase evidence (before episodes)

The preregistration draft above was written before any episodes; its original
whole-file SHA-256 is
`2f808ef49e118a2b0e52a61c0ef326384730d2969efb50429ab194ddd50bd1b8`.
The original frozen patch SHA-256 is
`09ff423fe2ff2cba8d52103caa0af5604ebacf0be8331ebc4735e8028536ec02`.

An isolated worktree was created at `02dbf36`. Plain `git apply --check` reported
only the `replay.py` hunk around old line 137: its map-free nutrition handling
was already installed by `02dbf36`. This conflict was reported before any
episode. `git apply --3way` then applied all nine files cleanly with no manual
source edits: the identical already-landed nutrition hunk is retained once.
All other frozen behavior is unchanged. The rebased delta is retained at
`/tmp/item9-bounded-after-02dbf36.patch`, SHA-256
`113c4edffb47be9758e58d710b9ad0c2c9bf8dab2cb7ebdc4ff8c8d63fb1c49f`.


## Results and preregistered decision

All **120 episodes** were run before the interruption: 30 seeds per arm, using
actual real-NLE coordinator instances in the isolated rebased worktree. Arm
artifacts are separated at `/tmp/item9-postfix-{0,300,450,600}-data/{seed}/`;
no interrupted/resumed session replaced or reran an episode. All original
results were retained and coverage checked after resumption. The frozen
preregistration and rebased patch hashes still match their recorded values.

**No cap qualifies; ship nothing.** Every cap lowers deaths and hunger deaths,
but every cap has only **14 objective successes versus legacy's 16**, and each
also has one real cap-boundary gate rejection in seed 1215. Thus each fails
both qualification (c) and (d). The SEARCH reduction does not override either
failed condition. The tie-break rule is never reached.

### Totals per arm

| Arm | Objectives | Deaths | Hunger deaths | STUCK | Truncated | Errors | Steps | SEARCH | SEARCH drop | PRAY | Ration EAT | Invalid | Gate rejections | Integrity problems |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Legacy | 16 | 5 | 4 | 0 | 9 | 0 | 50019 | 20675 | — | 22 | 20 | 0 | 0 | 0 |
| 300 | 14 | 1 | 0 | 14 | 0 | 1 | 23038 | 5213 | 15,462 (74.8%) | 1 | 12 | 0 | 1 | 2 |
| 450 | 14 | 1 | 0 | 14 | 0 | 1 | 28322 | 7836 | 12,839 (62.1%) | 4 | 15 | 0 | 1 | 2 |
| 600 | 14 | 2 | 0 | 13 | 0 | 1 | 32002 | 9989 | 10,686 (51.7%) | 6 | 17 | 0 | 1 | 2 |

The error runs are retained in the 30-seed denominator and SEARCH/step totals;
none is silently converted into STUCK, a death, or a success. Their counts end
at the last executed step before the rejected extra SEARCH. Every recorded
action in all four arms passes action validation (zero invalid actions).
Normal completed runs have no gate/integrity problems; each candidate's error
run has one actual gate rejection and two audit problems at capture time:
`run record has no outcome` and `referenced ttyrec is missing or empty`.
The second is the paused recorder's pre-close capture state: after shutdown,
the three retained ttyrecs are nonempty (31,673 / 34,191 / 36,607 bytes).
These diagnostics do not create another episode or replace the gate failure.

Hunger deaths use starvation in the recorded cause or **last live** Weak/Fainting
hunger (NLE indices 3/4), not worst hunger at some earlier point or zeroed
terminal stats. E.g. cap-600 seed 1211 earlier reached Weak, received prayer,
and died NotHungry; that is not a hunger death. Ration EAT counts initiating
inventory-ration commands, not the item-letter answer. PRAY counts initiating
prayer commands, not confirmation answers.

### Qualification

| Cap | Deaths <= 5 | Hunger deaths <= 4 | Objectives >= 16 | Zero gate/integrity problems | Qualifies |
| --- | --- | --- | --- | --- | --- |
| 300 | yes (1) | yes (0) | **no (14)** | **no** | **no** |
| 450 | yes (1) | yes (0) | **no (14)** | **no** | **no** |
| 600 | yes (2) | yes (0) | **no (14)** | **no** | **no** |

All caps lose legacy successes 1211, 1225, and 1230, while gaining 1237. For
1211, caps 300/450 stop STUCK and cap 600 dies to a gnome zombie. All caps die
to a sewer rat in 1225 and stop STUCK in 1230. There is no successful cap among
the candidates to select.

## Per-seed tables

`objective_complete` means reaching main-dungeon level 5. `stuck` is an explicit
budget-policy stop, not successful exploration or an NLE death. `error` is the
actual gate rejection, not an accepted stop. All arms use the same 3,000-step
cap; steps include prompt-answer actions. Death hunger is the last live
observation before termination.

### Legacy (no cap)

| Seed | Outcome | Steps | SEARCH | Death cause / last live hunger | PRAY | Ration EAT |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| 1210 | objective_complete | 308 | 9 | — | 0 | 0 |
| 1211 | objective_complete | 1819 | 570 | — | 1 | 1 |
| 1212 | truncated | 3000 | 2171 | — | 1 | 2 |
| 1213 | objective_complete | 269 | 0 | — | 0 | 0 |
| 1214 | objective_complete | 679 | 0 | — | 0 | 0 |
| 1215 | death | 2556 | 1007 | killed by a manes / Fainting | 1 | 1 |
| 1216 | truncated | 3000 | 2050 | — | 2 | 1 |
| 1217 | objective_complete | 826 | 33 | — | 0 | 1 |
| 1218 | truncated | 3000 | 1659 | — | 1 | 2 |
| 1219 | objective_complete | 697 | 0 | — | 0 | 0 |
| 1220 | objective_complete | 483 | 0 | — | 0 | 0 |
| 1221 | truncated | 3000 | 1567 | — | 2 | 1 |
| 1222 | objective_complete | 870 | 65 | — | 0 | 1 |
| 1223 | objective_complete | 549 | 10 | — | 0 | 0 |
| 1224 | truncated | 3000 | 988 | — | 1 | 1 |
| 1225 | objective_complete | 1177 | 39 | — | 0 | 1 |
| 1226 | objective_complete | 358 | 0 | — | 0 | 0 |
| 1227 | death | 2822 | 1108 | killed by a newt / Fainting | 1 | 1 |
| 1228 | truncated | 3000 | 1344 | — | 2 | 1 |
| 1229 | objective_complete | 653 | 0 | — | 0 | 0 |
| 1230 | objective_complete | 562 | 42 | — | 0 | 0 |
| 1231 | death | 2705 | 2035 | died of starvation / Fainting | 2 | 1 |
| 1232 | death | 2892 | 1888 | died of starvation / Fainting | 2 | 1 |
| 1233 | death | 1012 | 70 | killed by a magic missile / NotHungry | 0 | 1 |
| 1234 | objective_complete | 434 | 0 | — | 0 | 0 |
| 1235 | objective_complete | 656 | 123 | — | 0 | 0 |
| 1236 | truncated | 3000 | 1660 | — | 2 | 1 |
| 1237 | truncated | 3000 | 1260 | — | 2 | 1 |
| 1238 | objective_complete | 692 | 53 | — | 0 | 0 |
| 1239 | truncated | 3000 | 924 | — | 2 | 1 |

### Cap 300

| Seed | Outcome | Steps | SEARCH | Death cause / last live hunger | PRAY | Ration EAT |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| 1210 | objective_complete | 308 | 9 | — | 0 | 0 |
| 1211 | stuck | 1175 | 300 | — | 0 | 1 |
| 1212 | stuck | 593 | 300 | — | 0 | 0 |
| 1213 | objective_complete | 269 | 0 | — | 0 | 0 |
| 1214 | objective_complete | 679 | 0 | — | 0 | 0 |
| 1215 | error: cap gate (1215) | 1552 | 300 | — | 0 | 1 |
| 1216 | stuck | 510 | 300 | — | 0 | 0 |
| 1217 | objective_complete | 839 | 63 | — | 0 | 0 |
| 1218 | stuck | 611 | 300 | — | 0 | 0 |
| 1219 | objective_complete | 697 | 0 | — | 0 | 0 |
| 1220 | objective_complete | 483 | 0 | — | 0 | 0 |
| 1221 | stuck | 1029 | 300 | — | 1 | 1 |
| 1222 | objective_complete | 939 | 109 | — | 0 | 1 |
| 1223 | objective_complete | 549 | 10 | — | 0 | 0 |
| 1224 | stuck | 1114 | 300 | — | 0 | 1 |
| 1225 | death | 1138 | 87 | killed by a sewer rat / NotHungry | 0 | 1 |
| 1226 | objective_complete | 358 | 0 | — | 0 | 0 |
| 1227 | stuck | 878 | 300 | — | 0 | 1 |
| 1228 | stuck | 1606 | 509 | — | 0 | 1 |
| 1229 | objective_complete | 653 | 0 | — | 0 | 0 |
| 1230 | stuck | 986 | 300 | — | 0 | 1 |
| 1231 | stuck | 415 | 300 | — | 0 | 0 |
| 1232 | stuck | 588 | 300 | — | 0 | 0 |
| 1233 | stuck | 1111 | 300 | — | 0 | 1 |
| 1234 | objective_complete | 434 | 0 | — | 0 | 0 |
| 1235 | objective_complete | 562 | 62 | — | 0 | 0 |
| 1236 | stuck | 958 | 300 | — | 0 | 1 |
| 1237 | objective_complete | 527 | 36 | — | 0 | 0 |
| 1238 | objective_complete | 689 | 128 | — | 0 | 0 |
| 1239 | stuck | 788 | 300 | — | 0 | 1 |

### Cap 450

| Seed | Outcome | Steps | SEARCH | Death cause / last live hunger | PRAY | Ration EAT |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| 1210 | objective_complete | 308 | 9 | — | 0 | 0 |
| 1211 | stuck | 1463 | 450 | — | 0 | 1 |
| 1212 | stuck | 791 | 450 | — | 0 | 1 |
| 1213 | objective_complete | 269 | 0 | — | 0 | 0 |
| 1214 | objective_complete | 679 | 0 | — | 0 | 0 |
| 1215 | error: cap gate (1215) | 1704 | 450 | — | 1 | 1 |
| 1216 | stuck | 704 | 450 | — | 0 | 0 |
| 1217 | objective_complete | 839 | 63 | — | 0 | 0 |
| 1218 | stuck | 1467 | 823 | — | 0 | 2 |
| 1219 | objective_complete | 697 | 0 | — | 0 | 0 |
| 1220 | objective_complete | 483 | 0 | — | 0 | 0 |
| 1221 | stuck | 1331 | 450 | — | 1 | 1 |
| 1222 | objective_complete | 939 | 109 | — | 0 | 1 |
| 1223 | objective_complete | 549 | 10 | — | 0 | 0 |
| 1224 | stuck | 1503 | 450 | — | 0 | 1 |
| 1225 | death | 1138 | 87 | killed by a sewer rat / NotHungry | 0 | 1 |
| 1226 | objective_complete | 358 | 0 | — | 0 | 0 |
| 1227 | stuck | 1031 | 450 | — | 0 | 1 |
| 1228 | stuck | 1871 | 659 | — | 1 | 1 |
| 1229 | objective_complete | 653 | 0 | — | 0 | 0 |
| 1230 | stuck | 2286 | 450 | — | 1 | 1 |
| 1231 | stuck | 616 | 450 | — | 0 | 0 |
| 1232 | stuck | 806 | 450 | — | 0 | 0 |
| 1233 | stuck | 1347 | 450 | — | 0 | 1 |
| 1234 | objective_complete | 434 | 0 | — | 0 | 0 |
| 1235 | objective_complete | 562 | 62 | — | 0 | 0 |
| 1236 | stuck | 1169 | 450 | — | 0 | 1 |
| 1237 | objective_complete | 527 | 36 | — | 0 | 0 |
| 1238 | objective_complete | 689 | 128 | — | 0 | 0 |
| 1239 | stuck | 1109 | 450 | — | 0 | 1 |

### Cap 600

| Seed | Outcome | Steps | SEARCH | Death cause / last live hunger | PRAY | Ration EAT |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| 1210 | objective_complete | 308 | 9 | — | 0 | 0 |
| 1211 | death | 1657 | 503 | killed by a gnome zombie / NotHungry | 1 | 1 |
| 1212 | stuck | 985 | 600 | — | 0 | 1 |
| 1213 | objective_complete | 269 | 0 | — | 0 | 0 |
| 1214 | objective_complete | 679 | 0 | — | 0 | 0 |
| 1215 | error: cap gate (1215) | 1854 | 600 | — | 1 | 1 |
| 1216 | stuck | 897 | 600 | — | 0 | 0 |
| 1217 | objective_complete | 839 | 63 | — | 0 | 0 |
| 1218 | stuck | 1664 | 973 | — | 0 | 2 |
| 1219 | objective_complete | 697 | 0 | — | 0 | 0 |
| 1220 | objective_complete | 483 | 0 | — | 0 | 0 |
| 1221 | stuck | 1631 | 600 | — | 1 | 1 |
| 1222 | objective_complete | 939 | 109 | — | 0 | 1 |
| 1223 | objective_complete | 549 | 10 | — | 0 | 0 |
| 1224 | stuck | 1953 | 600 | — | 1 | 1 |
| 1225 | death | 1138 | 87 | killed by a sewer rat / NotHungry | 0 | 1 |
| 1226 | objective_complete | 358 | 0 | — | 0 | 0 |
| 1227 | stuck | 1187 | 600 | — | 0 | 1 |
| 1228 | stuck | 2137 | 809 | — | 1 | 1 |
| 1229 | objective_complete | 653 | 0 | — | 0 | 0 |
| 1230 | stuck | 2782 | 600 | — | 1 | 1 |
| 1231 | stuck | 818 | 600 | — | 0 | 1 |
| 1232 | stuck | 1023 | 600 | — | 0 | 1 |
| 1233 | stuck | 1497 | 600 | — | 0 | 1 |
| 1234 | objective_complete | 434 | 0 | — | 0 | 0 |
| 1235 | objective_complete | 562 | 62 | — | 0 | 0 |
| 1236 | stuck | 1384 | 600 | — | 0 | 1 |
| 1237 | objective_complete | 527 | 36 | — | 0 | 0 |
| 1238 | objective_complete | 689 | 128 | — | 0 | 0 |
| 1239 | stuck | 1409 | 600 | — | 0 | 1 |

## Rejected prototype's cap-boundary defect

In seed 1215 at each candidate cap, the last executed SEARCH actions have this
recorded rationale on dungeon level 4:

> Wait in place for the yellow mold blocking the route to the unexplored space
> to move; it is peaceful or unsafe to melee.

These carry a `frontier` intent to (49,15), not a `search_spot` intent. The
frozen `_past_monster` issuer uses **Command.SEARCH as a waiting action**, but
does not check the global per-level SEARCH cap. The coordinator counts those
executed commands and correctly rejects the next one at its hard boundary:
`ActionGateError: persistent level SEARCH budget is exhausted`. Completed
steps are 1,552 / 1,704 / 1,854 and executed SEARCH counts are exactly
300 / 450 / 600. Last recorded game turns are 1558 / 1711 / 1861.

This is a frozen-prototype defect, not the repaired corpse-meal latch. It was
not fixed during or after the preregistered comparison, no run was repeated,
and it is not shipped. Even removing this error from consideration would not
make the observed 14 objective successes meet the required 16.

## Dominant remaining failure class

The post-fix legacy baseline's dominant class is **exit-discovery/navigation
stagnation with prolonged hidden-passage searching**, with eventual nutrition
exhaustion in a subset—not corpse continuation and not a blanket prayer failure.
There are nine 3,000-step truncations and four hunger deaths, against one
non-hunger magic-missile death. Those 13 stagnation/nutrition failures, plus the
one combat death, account for **19,731 of 20,675 SEARCH actions (95.4%)**.
A retained-trace reconstruction distinguishes actual hidden-passage SEARCH,
monster-wait SEARCH, model-fallback WAIT, and corpse WAIT; the failed runs
contain no corpse-continuation WAITs. The final known-downstairs state and
per-failure command breakdown are retained in
`/tmp/item9-postfix-diagnosis.json`.
The final remembered level has **no known downstairs in all 14 failed runs**.
The nine truncations and four hunger deaths together spend 19,661 SEARCH
commands: **19,645 actual hidden-passage searches** and 16 monster-wait
searches. The remaining non-hunger magic-missile death has 70 SEARCH commands
and 359 model-fallback WAITs. This distinguishes the dominant exit-discovery
failure from a defective hunger-priority latch, which has zero WAITs here.

The candidate arms mostly turn long runs into **13–14 STUCK stops**, rather
than discovering the exit: fewer deaths alone do not preserve objective
completion. The lost-success and cap-error evidence above must be addressed
before a differently designed search policy is judged on new seeds. This
comparison does not justify changing prayer timeout, combat, corpse rules, or
any acceptance-suite threshold.

## Evidence and scope

- Frozen preregistration was checked against all nine evaluation JSON files
  before episodes, then 1210–1239 was registered as development-only seeds.
- Real runtime imports were verified inside `/tmp/item9-postfix-02dbf36/`, not
  the main tree. All arms use the same post-fix corpse lifecycle and frozen
  prototype code; legacy explicitly has no search configuration/cap.
- Every step was converted to typed events and the complete run audited by
  `summarize_run`, including action validation and exhaustion replay. All
  resulting failures, including the three seed-1215 errors, are reported above.
- Full results: `/tmp/item9-postfix-all-results.json`; separate arm results:
  `/tmp/item9-postfix-{0,300,450,600}-results.json`; mechanical qualification:
  `/tmp/item9-postfix-decision.json`; complete public traces and ttyrecs are in
  the arm/seed artifact directories.
- Main-tree product code, `POLICY_VERSION`, TODO item 9, architecture, development
  guide, and tests are unchanged by this attempt. Only this note and the ledger
  are committed. The prototype remains isolated and unshipped.
