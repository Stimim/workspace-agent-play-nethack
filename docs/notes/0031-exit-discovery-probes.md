# 0031: Exit discovery probes

## Preregistration (frozen before any new episode)

Baseline HEAD is `a84bac7`. This section is frozen; append diagnosis, results,
verification, and decision later without changing these rules.

- **Seeds:** the next 30 unused integers starting at 1240. Before registration,
  `used_seeds(evaluation/)` returned 230 used seeds after reading the seed ledger,
  representative catalog, and committed evaluation suites. None in 1240–1269
  was used: exact sample **1240–1269 inclusive**. Register all 30 in the ledger
  before either arm starts. These become development seeds, not fresh acceptance
  seeds.
- **Setup:** actual `AgentCoordinator`, `ScriptedDevelopmentModel`,
  `NetHackScore-v0`, `nle-survival-actions`, objective `reach_level(0,5)`,
  cap 3000, matching note 0030. Separate artifact directories per arm and seed.
- **Arms:** immutable HEAD before implementation (`a84bac7`) versus exit
  discovery changes: guarded forcing of known locked main-dungeon route gates,
  open-door outward search stands, and visiting object-covered unexplored
  terrain. No SEARCH cap, POLICY_VERSION change, prayer/corpse changes, or
  unrelated behavior. Rank-4 corridor reprioritization is omitted unless the
  development rerun leaves seed 1237 unsolved and a small fix suffices; if used,
  freeze the complete candidate before its fresh arm, and disclose it.
- **Qualification:** ship only if candidate objective successes are **strictly
  greater** than baseline, total deaths **not higher**, hunger deaths **not
  higher**, and **zero invalid actions, gate rejections, integrity problems**.
  Count all 30 seeds, including errors; never silently replace a run.
  Hunger deaths mean starvation or death whose last live hunger is Weak or
  worse (NLE index >= 3), not zeroed terminal stats or historical worst hunger.
- **Development evidence only:** rerun the previously failed legacy seeds
  1212, 1215, 1216, 1218, 1221, 1224, 1227, 1228, 1231, 1232, 1233, 1236,
  1237, 1239 with candidate code; report separately, not as qualification data.
- **Decision:** if qualification fails, commit only this note and the ledger
  as `Record exit-discovery probes`. If it passes, ship implementation,
  behavior tests, architecture/development/ADR updates and checked item 9 as
  `Kick locked gates and widen exit discovery`, following the requested full
  verification and scripted staircase seeds 1–10 at cap 1000 (10/10 required).

No new episode was run before writing this preregistration. User-unrelated
changes remain unstaged; TODO_LIST.md and docs/development.md are selectively
staged. There are no other editors or subagents.

## Native-memory diagnosis (non-committed development evidence)

The preceding investigation used normal, non-wizard NLE 1.3.0 at `a05d52e`,
not a changed policy. It replayed every recorded legacy action and matched
all projected before/after observations, normalizing only proper names:
**39,256 unique actions, 78,512 comparisons, 249 visible-downstairs checks**,
including successful control 1213 (269 actions, 19 stair checks).

Each NLE instance has its own memfd-copied libnethack. Locate its inode in
`/proc/self/maps`, acquire the already-loaded copy with `RTLD_NOLOAD`, and read
exported `u`, `level`, `dnstair`, `sstairs`, `ftrap` via ctypes without writes
or game-state entrypoints. Close that extra handle before closing NLE, so a
recycled descriptor does not retain an old library. Matching release source:
NetHack-LE/nle v1.3.0, commit `70cb9b5260d05b38ee1ee1b0228d5f6f8ca54655`.
Compiler/header measurements established `rm` size 8, `typ` offset 4,
`seenv` offset 5, flags byte 6 low five bits, locations `[80][21]` x-major,
objects offset 13440, `u.uz` offset 10, and `stairway` size 5. Cross-check
native hero coordinates/level and visible downstairs against public observations.
All coordinates below use NLE x = native x minus one.

Read the complete native map at entry and end. For five deaths, exact static
post-terminal map/u/stair reads match last-live values; dynamic objects,
monsters, and traps are explicitly last-live because `freedynamicdata` frees
their lists before NLE returns. A first unsafe heap read segfaulted; corrected
captures skip that read. No hole/trapdoor appears in safely read collections.

Route analysis minimizes movement steps or blocked cells then steps, with
secret, locked, closed, boulder, and non-pet peaceful-monster categories
individually held blocked. It excludes solid/water/lava terrain and forbids
diagonal passage through intact doors, including secret doors: the low three
SDOOR flag bits are wall mode, not broken/open state, and native conversion
makes an unlocked secret door closed. This is geometry, not combat simulation.

| Seed | Dlvl | Main downstairs | Primary obstruction / alternate route | Shortest / fewest-blocker steps | SEARCH on final level |
| --- | ---: | --- | --- | ---: | ---: |
| 1212 | 3 | (31,14) | Known lock (45,4) | 23 / 23 | 2171 |
| 1215 | 4 | (67,8) | SCORR (59,17) outside visited open door (58,17), then SDOOR (59,6) | 24 / 24 | 1007 |
| 1216 | 3 | (56,11) | Known lock (17,8), then SDOORs (29,13), (34,15) | 50 / 50 | 2050 |
| 1218 | 3 | (62,12) | Known lock (3,10); cheapest route SDOOR (65,10); shortest instead SCORR (51,7), locked SDOOR (60,15) | 76 / 81 | 1602 |
| 1221 | 4 | (72,9) | Observed, unvisited chest-covered downstairs; unlocked route 43 steps | 41 / 43 | 1567 |
| 1224 | 2 | (75,8) | Known lock (48,15); shorter alternative boulder (54,8), SCORR (59,8) | 95 / 99 | 988 |
| 1227 | 2 | (8,18) | Known lock (12,6), then SDOOR (10,7) | 67 / 67 | 1108 |
| 1228 | 3 | (54,14) | Known lock (63,11); closed door (64,2) is avoidable | 30 / 40 | 1282 |
| 1231 | 1 | (42,3) | SCORR (14,5) outside visited open door (13,5), then SDOOR (38,3) | 47 / 47 | 2035 |
| 1232 | 2 | (22,4) | Known lock (9,8) | 18 / 18 | 1888 |
| 1233 | 3 | (6,13) | Known lock (15,8), then SDOOR (6,12) | 30 / 30 | 70 |
| 1236 | 4 | (3,17) | Known lock (57,12); boulder (49,9) is avoidable | 60 / 64 | 1660 |
| 1237 | 2 | (62,6) | Known lock (59,6); 29-step alternative SDOOR (48,12) | 23 / 23 | 1260 |
| 1239 | 3 | (7,7) | Known lock (13,8) | 32 / 32 | 598 |

Class totals: **11 known locked gates**, **2 excluded open-door search stands**,
**1 object-covered downstairs never visited**. All eleven gate cases used zero
KICK commands on the final level. Nine locks remain mandatory with other
barriers relaxed; 1224 and 1237 have alternatives. There are no primary
water/lava/peaceful-NPC cutsets. No further hidden/boulder blocker remains on
the minimal route after forcing the gate for 1212, 1224, 1228, 1232, 1236,
1237, 1239; four other locked-gate cases still require secret discovery.

Relevant hidden cells received zero adjacent SEARCH (Chebyshev distance <=1)
except 1237's alternative (48,12): **10/1260 = 0.79%**. That stand is an
eligible corridor end, not filtered by MIN_SEARCH_SCORE. Replaying exact
recorded coverage at budget 50 gives its adjusted score 146 (density 166,
distance 10), versus the committed room-wall stand's 81. Commitment can
suppress a better corridor candidate; this is rank 4, not the dominant cause.
Most other hidden cells remain unreachable behind the first gate.

Non-committed evidence: `/tmp/item9-native-truth/{seed}/truth.json`, five
`death-end.json` files, `classification-inputs-final.json`, and the original
read-only tapes `/tmp/item9-postfix-0-data/{seed}/trace.json`. They contain
entry/end true terrain, door flags, branch stairs, safe heap collections,
routes, hidden-cell eligibility, distances, and search positions. Exact
temporary scripts were supplied inline and deleted after the investigation.

## Implementation rationale and episode setup

The Dlvl-1-only restriction was introduced by `a02c757` with exploration:
avoid angering shopkeepers (shops below Dlvl 1) and town watch (Minetown).
The new predicate preserves those protections using known shop/shopkeeper
evidence, closed-inventory messages, and refusal outside dungeon 0.
Engravings are not a separate exposed public observation; the adapter exposes
messages, so `"Closed for inventory"` is learned from the message, including
look-here engraving text when NLE emits it, and remembered at adjacent doors.

The minimum kick health is 10 HP: matching native `src/dokick.c` Ouch damage
is `rnd(CON > 15 ? 3 : 5)`, at most 5, so this requires two worst-case damage
units before attempting a kick; rechecking after an injury prevents another
kick below that floor. Weak-or-worse hunger is refused; hunger survival rules
remain higher priority. Eight direction-confirmed kicks per door are the
existing lifetime bound. WHAMM, opened/shattered, Ouch, and other messages
are retained as observed outcomes in level memory and original step records.

Both arms use the actual typed evaluator and coordinator, with separate data
and report directories under `/tmp/item9-exit-{baseline,candidate}/`.
An initial external suite preflight rejected `min_successes: 0` before any
episode; its display-only threshold was corrected to 1. The frozen paired
qualification rule above, not that display threshold, decides shipment.

### Candidate freeze

Development reruns completed before the fresh candidate arm: 12/14 objectives,
including seed 1237 in 554 steps. **Rank 4 is omitted:** changes 1–3 solved
1237 without changing corridor scoring or search commitment.

Before the fresh candidate arm, the complete code/test delta was captured as
`/tmp/item9-exit-candidate.patch`, SHA-256
`25fd2b602eee5663a7cdf92349374025c6a30ea8823f9fc4ac7f2268f05fbf3d`.
After the development episodes, the gate was clarified to distinguish a wait
or attack while routing to a gate from an actual pending kick-direction answer,
and KICK was removed from model fallback offers. The fresh arm includes those
guards. They do not change any already-approved development action: all 14
episodes had zero rejected/invalid actions. Final verification also covers the
pending-direction guard. No behavior is changed during the fresh arm.

### Shop-message contract correction: original probe retained

The first candidate's 30 episodes completed with 23 objectives, 4 deaths,
0 hunger deaths, and zero recorded invalid/gate/integrity problems. It is
**not the shipment candidate**: correctness review found that a generic
`"welcome to "` cue also classified the native XP message
`"Welcome to experience level 2."` as a shop. A new behavior regression failed
before correction and passed afterwards. Native `shk.c` identifies shop
greetings by `Welcome[ again] to <possessive owner> <shop>`; the correction
uses that form, not an XP greeting, while retaining known-shopkeeper evidence.
This is a contract bug correction, not a threshold/weight/performance retune.

The original full report is retained at
`/tmp/item9-exit-candidate/reports/exit-discovery-candidate-development-20261003T122119Z.json`;
its episodes and the first development rerun are not erased or silently
replaced. Re-evaluate the corrected implementation on the **same preregistered
30 seeds and unchanged setup/rule**, and repeat the 14 development seeds
separately. Disclose both candidate runs. Only the corrected comparison can
support shipment; the display-only evaluator acceptance remains irrelevant.
No seed, qualification threshold, arm setup, or frozen preregistration text
is changed. Rank 4 remains omitted.

Corrected pre-episode delta: `/tmp/item9-exit-candidate-corrected.patch`,
SHA-256 `f81cebbf2569e931823144c43a0912885b58864d0145b576030547e4f9f8db4c`.
All 18 focused behavior tests pass, including the XP/non-shop distinction
and shared runtime/evaluator gate agreement.

## Paired comparison results

Both arms used the frozen 30 seeds, cap 3000, actual `AgentCoordinator` and
`ScriptedDevelopmentModel`, `NetHackScore-v0`, `nle-survival-actions`, and
`reach_level(0,5)`. All reported records are complete and unchanged-input.
These are **development probes**, not milestone or real-model acceptance.

| Arm | Objectives | Deaths | Hunger deaths | Truncated | Steps | SEARCH | Invalid / gate / integrity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Baseline `a84bac7` | 19/30 | 5 | 2 | 6 | 39,885 | 10,714 | 0 / 0 / 0 |
| Corrected candidate | 23/30 | 4 | 0 | 3 | 25,697 | 3,289 | 0 / 0 / 0 |

**Qualifies under the unchanged rule:** 23 > 19 objectives, 4 ≤ 5 deaths,
0 ≤ 2 hunger deaths, and zero invalid actions, gate rejections, or integrity
problems. No threshold or acceptance adjustment is made.

### Baseline, immutable HEAD `a84bac7`

Report:
`/tmp/item9-exit-baseline/reports/exit-discovery-baseline-development-20261003T115829Z.json`

| Seed | Outcome | Steps | SEARCH | Hunger/death cause | Invalid / gate / integrity |
| ---: | --- | ---: | ---: | --- | --- |
| 1240 | objective_complete | 942 | 83 | — | 0 / 0 / 0 |
| 1241 | death | 2775 | 1509 | fainting: killed by a grid bug | 0 / 0 / 0 |
| 1242 | objective_complete | 661 | 121 | — | 0 / 0 / 0 |
| 1243 | objective_complete | 1676 | 485 | — | 0 / 0 / 0 |
| 1244 | objective_complete | 410 | 22 | — | 0 / 0 / 0 |
| 1245 | objective_complete | 760 | 15 | — | 0 / 0 / 0 |
| 1246 | objective_complete | 745 | 4 | — | 0 / 0 / 0 |
| 1247 | death | 144 | 0 | not_hungry: killed by a boulder | 0 / 0 / 0 |
| 1248 | objective_complete | 676 | 46 | — | 0 / 0 / 0 |
| 1249 | objective_complete | 547 | 1 | — | 0 / 0 / 0 |
| 1250 | objective_complete | 1083 | 204 | — | 0 / 0 / 0 |
| 1251 | truncated | 3000 | 36 | — | 0 / 0 / 0 |
| 1252 | objective_complete | 410 | 0 | — | 0 / 0 / 0 |
| 1253 | truncated | 3000 | 1238 | — | 0 / 0 / 0 |
| 1254 | objective_complete | 479 | 0 | — | 0 / 0 / 0 |
| 1255 | objective_complete | 802 | 27 | — | 0 / 0 / 0 |
| 1256 | objective_complete | 790 | 93 | — | 0 / 0 / 0 |
| 1257 | death | 1234 | 442 | not_hungry: killed by a sewer rat | 0 / 0 / 0 |
| 1258 | truncated | 3000 | 1000 | — | 0 / 0 / 0 |
| 1259 | objective_complete | 586 | 89 | — | 0 / 0 / 0 |
| 1260 | objective_complete | 103 | 0 | — | 0 / 0 / 0 |
| 1261 | objective_complete | 806 | 0 | — | 0 / 0 / 0 |
| 1262 | death | 763 | 0 | not_hungry: killed by a giant bat | 0 / 0 / 0 |
| 1263 | objective_complete | 1853 | 801 | — | 0 / 0 / 0 |
| 1264 | objective_complete | 994 | 12 | — | 0 / 0 / 0 |
| 1265 | truncated | 3000 | 1359 | — | 0 / 0 / 0 |
| 1266 | objective_complete | 462 | 0 | — | 0 / 0 / 0 |
| 1267 | death | 2184 | 227 | fainting: killed by a giant rat | 0 / 0 / 0 |
| 1268 | truncated | 3000 | 1430 | — | 0 / 0 / 0 |
| 1269 | truncated | 3000 | 1470 | — | 0 / 0 / 0 |

### Corrected candidate

Report:
`/tmp/item9-exit-candidate-corrected/reports/exit-discovery-candidate-corrected-development-20261003T124210Z.json`

| Seed | Outcome | Steps | SEARCH | Hunger/death cause | Invalid / gate / integrity |
| ---: | --- | ---: | ---: | --- | --- |
| 1240 | truncated | 3000 | 1182 | — | 0 / 0 / 0 |
| 1241 | objective_complete | 310 | 0 | — | 0 / 0 / 0 |
| 1242 | objective_complete | 340 | 2 | — | 0 / 0 / 0 |
| 1243 | objective_complete | 531 | 0 | — | 0 / 0 / 0 |
| 1244 | objective_complete | 526 | 48 | — | 0 / 0 / 0 |
| 1245 | objective_complete | 1066 | 79 | — | 0 / 0 / 0 |
| 1246 | objective_complete | 773 | 48 | — | 0 / 0 / 0 |
| 1247 | death | 57 | 0 | not_hungry: killed by a sewer rat | 0 / 0 / 0 |
| 1248 | objective_complete | 793 | 53 | — | 0 / 0 / 0 |
| 1249 | objective_complete | 915 | 285 | — | 0 / 0 / 0 |
| 1250 | objective_complete | 502 | 0 | — | 0 / 0 / 0 |
| 1251 | truncated | 3000 | 24 | — | 0 / 0 / 0 |
| 1252 | objective_complete | 677 | 1 | — | 0 / 0 / 0 |
| 1253 | death | 963 | 377 | not_hungry: killed by a guard | 0 / 0 / 0 |
| 1254 | objective_complete | 375 | 0 | — | 0 / 0 / 0 |
| 1255 | objective_complete | 586 | 30 | — | 0 / 0 / 0 |
| 1256 | objective_complete | 247 | 0 | — | 0 / 0 / 0 |
| 1257 | objective_complete | 567 | 18 | — | 0 / 0 / 0 |
| 1258 | objective_complete | 997 | 227 | — | 0 / 0 / 0 |
| 1259 | death | 644 | 19 | not_hungry: killed by a large mimic | 0 / 0 / 0 |
| 1260 | objective_complete | 121 | 0 | — | 0 / 0 / 0 |
| 1261 | truncated | 3000 | 652 | — | 0 / 0 / 0 |
| 1262 | objective_complete | 602 | 0 | — | 0 / 0 / 0 |
| 1263 | objective_complete | 633 | 68 | — | 0 / 0 / 0 |
| 1264 | objective_complete | 1388 | 57 | — | 0 / 0 / 0 |
| 1265 | death | 833 | 115 | satiated: killed by a hobbit | 0 / 0 / 0 |
| 1266 | objective_complete | 835 | 0 | — | 0 / 0 / 0 |
| 1267 | objective_complete | 763 | 0 | — | 0 / 0 / 0 |
| 1268 | objective_complete | 334 | 4 | — | 0 / 0 / 0 |
| 1269 | objective_complete | 319 | 0 | — | 0 / 0 / 0 |

The original and corrected fresh candidates have identical per-seed outcome,
steps, SEARCH, death cause, and hunger-at-death values in these tables. The
original report remains separately retained; the XP-shop regression still
required correction even though this sample's metrics did not change.

## Legacy failures: separate development rerun

These 14 reused seeds do **not** participate in the fresh paired gate.
Corrected rerun: **12/14 objectives, 2 deaths, 0 hunger deaths**, 10,891 steps,
1,038 SEARCH actions, zero invalid/gate/integrity problems. The original
development rerun also solved 12/14; its XP-shop false positive delayed 1233
(839 steps, 130 SEARCH versus corrected 627 steps, 10 SEARCH).

Reports:
`/tmp/item9-exit-development/reports/exit-discovery-development-development-20261003T121114Z.json`
and
`/tmp/item9-exit-development-corrected/reports/exit-discovery-development-corrected-development-20261003T124210Z.json`.

| Seed | Outcome | Steps | SEARCH | Hunger/death cause | Invalid / gate / integrity |
| ---: | --- | ---: | ---: | --- | --- |
| 1212 | objective_complete | 378 | 0 | — | 0 / 0 / 0 |
| 1215 | objective_complete | 1227 | 285 | — | 0 / 0 / 0 |
| 1216 | objective_complete | 338 | 48 | — | 0 / 0 / 0 |
| 1218 | death | 1631 | 222 | satiated: killed by a werejackal | 0 / 0 / 0 |
| 1221 | objective_complete | 328 | 0 | — | 0 / 0 / 0 |
| 1224 | objective_complete | 995 | 11 | — | 0 / 0 / 0 |
| 1227 | objective_complete | 1164 | 185 | — | 0 / 0 / 0 |
| 1228 | objective_complete | 1049 | 57 | — | 0 / 0 / 0 |
| 1231 | objective_complete | 566 | 71 | — | 0 / 0 / 0 |
| 1232 | objective_complete | 366 | 0 | — | 0 / 0 / 0 |
| 1233 | objective_complete | 627 | 10 | — | 0 / 0 / 0 |
| 1236 | objective_complete | 927 | 92 | — | 0 / 0 / 0 |
| 1237 | objective_complete | 554 | 42 | — | 0 / 0 / 0 |
| 1239 | death | 741 | 15 | not_hungry: killed by a magic missile | 0 / 0 / 0 |

## Shipment and verification

Ship exit discovery, not a per-level SEARCH cap. Item 9 is checked with links
to 0028, 0030, and 0031; ADR 0005 remains proposed. `POLICY_VERSION` stays
`hierarchical-task-specialists-v1`; item 10 owns the next version/milestone.

Full post-fix pytest: **586 passed**, three dependency deprecation warnings.
Ruff check and whole-project format check pass (50 Python files).
Test cleanup removes obsolete seed-specific corpse-route trajectory pins
rather than repinning them, and terminal level retention now asserts the last
live observation instead of a fixed depth. Controlled corpse behavior tests
remain. The ledger entry's overlong descriptive note, caught by full pytest,
was shortened without changing registered seeds or protocol.
No runtime behavior changed after the corrected episodes; subsequent Python
changes are import/format cleanup and these contract-test corrections.

The actual current-policy staircase smoke completed **10/10** objectives for
seeds 1–10, cap 1000, with zero invalid/gate/integrity problems:
`/tmp/item9-exit-staircase/reports/exit-discovery-staircase-development-development-20261003T130023Z.json`.
The historical staircase-v3 suite rejected the current policy before any
episode; a temporary development suite preserved its task, seeds, and cap
while using the unchanged current policy/default bundle. A post-report harness
assertion mistakenly treated the typed report as a dictionary; all episodes
had completed, and checking the persisted JSON confirmed 10/10 and clean
records without rerunning them.

The used-seed catalog validates 260 used seeds, including all 1240–1269.
Both worktree and staged `git diff --check` pass. Strict MkDocs built successfully from `/tmp/item9-exit-staged-export/`, a clean export of the staged index. The local coding-worker material was unrelated and has moved out of the repository (developer tooling). The final note records those observed results; no policy/runtime edits follow.
