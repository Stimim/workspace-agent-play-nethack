# 0050: Phase 1 objectives, baselines, and detector audit

Redo of the Phase 1 change reverted in [note 0049](0049-phase1-audit.md). The
product commit is `Reapply Phase 1 objectives with audit fixes` on branch
`phase1-redo`, rebased onto the native-truth fixes. This is scripted
development evidence (`scripted-development` model, `survival-reviewed-v2`,
policy `hierarchical-survival-hp-prayer-burden-look-v1`), not real-model
acceptance.

## Decision

**Qualified; ship.** The `enter_minetown_temple` and `find_oracle` legs, their
public detectors (`targets.py`), Oracle-attack conduct (`conduct.py`), and the
`minetown-regression-v1` and `oracle-regression-v1` development suites ship.

- Existing objectives are unchanged: `unified-d5-regression-v4` at this code
  matches the pre-Phase-1 report `20261004T135521Z` on all 67 seeds, by both
  outcome and step count. Product source on `main` was identical to that
  report's commit `5536c7d`.
- Measured against native truth, the new detectors made no false claim and
  missed no success: 19/19 Minetown and 9/9 Oracle claims are true, and every
  native success was claimed.
- Not done, and still open in `TODO_LIST.md`: the ADR 0007 §4.2 held-out cap
  probes (both suites use a provisional 10,000-step cap), and recognizing the
  Oracle level from statues, fountains or sounds, plus Sokoban avoidance. The
  planner recognizes the Oracle level only when it sees her.

## Changes from the reverted commit

- `conduct.attack_evidence` maps both `CompassDirection.*` and
  `CompassDirectionLonger.*` moves into a monster. A `Command.FIGHT` prefix
  removes the pet-swap exemption for the next move. Applied before each step
  and again during evaluator replay.
- `_corpse_route_error` accepts a route to an untracked lichen corpse even
  when an earlier, consumed kill shared its cell. This was the false invalid
  action on Minetown seed 703. Both fixes have regression tests.

## Baselines (67 seeds each, cap 10,000)

| Suite | Success | Deaths | Weak/Fainting at death | Truncated | Invalid / gate / integrity | Peaceful / Oracle attacks |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `minetown-regression-v1` | 19 | 42 (1 starvation) | 20 | 6 | 0 / 0 / 0 | 0 / 0 |
| `oracle-regression-v1` | 9 | 52 | 19 | 6 | 0 / 0 / 0 | 0 / 0 |

Reports `minetown-regression-v1-development-20261005T122330Z` and
`oracle-regression-v1-development-20261005T122330Z` are development data and
are not committed. Death causes are spread out; the most frequent are giant
rat (4) and rothe (3) for Minetown, and giant ant (5) and pony (4) for Oracle.
Hunger is the largest single class: 39 of the 94 deaths came at Weak or
Fainting.

## Detector audit

`_agents/skills/native-truth/detector_audit.py` replays every run with full
observation checks. It rebuilds the evaluator's detector state and reads
native truth on every step on an audited level: Mines levels for Minetown,
main-dungeon Dlvl 5-9 for the Oracle. Native success means the hero's
`rm.roomno` names a current TEMPLE room and the hero is not in its doorway
(Orcish Town: on the ALTAR), or a live peaceful Oracle is adjacent.

| Target | True positive | False positive | False negative | True negative | Replay failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Minetown | 19 | 0 | 0 | 48 | 0 |
| Oracle | 9 | 0 | 0 | 58 | 0 |

- **Claim timing:** 16 Minetown claims land on the first native success step.
  Three are late: seed 922 by 1 step, seed 9 by 3, and seed 921 by 40. Oracle
  claims all land on the first adjacent step.
- **Town identity** on audited Mines levels: 26 Minetown levels identified, 1
  missed (seed 1009099699, Orcish Town), and 102 filler levels with no false
  identification.
- **Variants reached** (source-derived candidates): minetn-1 ×3, -2 ×6, -3 ×3,
  -4 ×1, -5 ×4, -6 ×7, -7 ×3, at depths 5-7. One temple entry (seed 3) had no
  temple message; altar-room occupancy still claimed it on the entry step.
- **Orcish Town completion is unexercised.** No run stood on its altar, so its
  unaligned-altar detector has no measured true positive.
- **Near misses:** 8 runs reached Minetown and 4 reached the Oracle level
  without success. All 12 died there; 4 Minetown deaths came at Weak or
  Fainting.

## Failure classification

**Branch confusion.** 26 Oracle runs entered the Gnomish Mines. In every case
the planner's goal was `traverse_stairs(main, down)` on Dlvl 2-4, and the hero
took the Mines branch staircase. With both `>` unidentified, the planner cannot
distinguish them. 4 of those runs later succeeded. On the Minetown side, 26
runs never entered the Mines: 20 died first and 6 were truncated.

**Stalls (12 truncated runs).** Each was replayed with `replay.py` at the first
step on its final level and at the end. Every final level was main Dlvl 2-5
with no Mines branch staircase, so the true goal was the main downstairs. The
last 1,000 steps of each run show what the agent was doing.

| Suite, seed | Level | `>` seen | True blocker at end | SEARCH on level | Last 1,000 steps |
| --- | --- | --- | --- | ---: | --- |
| Minetown 1362 | D2 | yes | none | 2,503 | hunger `EAT`/`ESC` loop |
| Oracle 6 | D5 | yes | none | 3,124 | hunger `EAT`/`ESC` loop |
| Minetown 824 | D3 | yes | peaceful monster in route | 7,090 | `SEARCH` under stair navigation |
| Minetown 1376 | D2 | yes | none | 8,345 | `SEARCH` under stair navigation |
| Minetown 1840248764 | D2 | yes | none | 5,535 | exploration `SEARCH` |
| Minetown 799362204 | D3 | yes | none | 1,909 | exploration moves/`SEARCH` |
| Oracle 924 | D4 | no | none | 1,319 | exploration `SEARCH` |
| Minetown 1368 | D3 | no | none (secret door found earlier) | 6,992 | exploration `SEARCH` toward branch |
| Oracle 1374 | D3 | no | peaceful monster in route | 8,755 | exploration `SEARCH` |
| Oracle 1379 | D3 | no | secret passage + peaceful monster | 9,047, 0 next to the secret | exploration `SEARCH` |
| Oracle 1528054415 | D3 | no | secret passage + peaceful monster | 7,998, 0 next to the secret | exploration `SEARCH` |
| Oracle 5 | D4 | no | locked door or boulder | 740 | `WAIT` loop |

Two are defects rather than hard levels. The hunger skill alternates `EAT`
and `ESC` 500 times each, and stair navigation searches in place with the
main `>` known and a native route open (seed 1376) or blocked only by a
peaceful monster (seed 824).

## Native-truth tooling changes

- Replay normalization now also masks the quoted price of containers.
  `get_cost_of_shop_item` adds `contained_cost()` of the contents
  (`shk.c:2025`), and unidentified glass is priced from `ubirthday`
  (`shk.c:2085`). Without this, Minetown seeds failed replay at a large box
  quoted 3662 vs 5912 and 2508 vs 308 zorkmids.
- `replay.py` exposes `load_run`, `replay_environment` and `replay_step` so
  `detector_audit.py` uses the same replay checks.

## Evidence

Development databases are `/tmp/redo-{mt,or,d5}/runs.sqlite3` (not committed).
Reports, audit JSON and stall replays were copied outside `/tmp` for this
session only. The suites, seeds, code and this note reproduce them.
