# 0063: Search-spot commitment (ping-pong), development

## Decision

**NOT QUALIFIED; not preregistered** (2026-10-26, ADR 0008 Phase 3). Rule
0063 stops the search skill from switching its committed spot back and forth
([note 0062](0062-remaining-stall-mechanisms.md)). Each of its three
development passes failed at least one §4.1 gate. Pass 2 was the best: it
cut spot switches in stalled stays by about 70% and passed Oracle and D5, but
Minetown starvation deaths rose from 1 to 2. In no pass did the number of
stalled runs fall. The turns the rule saves go into more searching that does
not find the exit. The development budget is spent, so no fresh seeds were
spent and nothing was merged. The code is on branch
`rule-0063-search-spot-commitment`, one commit per pass (`b69f4eb`,
`2781989`, `6a210f5`; worktree `~/nethack-evidence/0063/candidate`).

## Method

- **Base:** the shipped commit `9783a7e`, with the regression arms of note
  0062 (`~/nethack-evidence/0062/base-{mt,or,d5}-reg`). The branch starts at
  `e9dde72`, which adds only documentation.
- **Suites:** `minetown-regression-v3`, `oracle-regression-v3` and
  `unified-d5-regression-v6`, relabelled `*-spot-commit-dev-0063` outside the
  repository. Seeds, tasks and step caps are unchanged. Policy label
  `hierarchical-survival-hp-prayer-burden-look-ration-explore-first-spotcommit-qual`;
  the planned `...-spot-commit-qual-v1` exceeds the suite contract's
  80-character limit.
- **Runs:** 67 seeds per suite, the scripted development model, 2 workers
  per arm, compared with `compare.py` and `stalls.py`. Pass 1 skipped D5
  because Minetown had already failed.
- **Diagnosis:** `LevelMemory` was rebuilt from stored step events with
  `ExplorationReplay`, read-only
  ([scripts](evidence/0063/scripts/)).
- **Provenance:** a worker agent ran the passes and saved each pass's patch
  at launch. The host hung during the pass-3 D5 arm, which was rerun from
  scratch; the partial arm is set aside as `aborted-dev3-d5`. The
  orchestrator re-checked the gates against the reports, the switch counts
  against the databases, and traced pass 3 itself.

## Root cause

In Minetown 1369 (Dlvl 2) a yellow mold at (11,17) stood on the route to the
committed spot (17,8). `route_tree` treats a displayed monster the policy
will not attack as a wall, so the spot looked unreachable and the skill
picked (44,11). On the way there a red mold blocked that route, and the skill
picked (17,8) again. Monsters are known only while displayed, so once a mold
was out of view the dropped spot looked reachable again. Map knowledge did
not change for over 5,000 steps.

Across the 11 stays of note 0062, almost every switch came from a displayed
monster cutting off the route, mostly molds, floating eyes and, in
1528054415, a shopkeeper. Minetown 1376 and Oracle 904 instead alternate
between stair navigation and search around a mold: rule 0064's mechanism.

## The passes

| Pass | Commit | What cuts search cells off |
| --- | --- | --- |
| 1 | `b69f4eb` | Any displayed monster the policy will not attack |
| 2 | `2781989` | A never-melee monster of base speed 3 or less: molds, jellies, floating eye, gas spore, the Oracle |
| 3 | `6a210f5` | Speed 0 only: molds, blue and spotted jellies, the Oracle |

While such a monster blocks the committed spot, every cell reachable only
through it is recorded, and the search skill skips those cells until map
knowledge changes.

## Results

Objectives / deaths / truncations, Weak-or-worse deaths, starvation deaths.
Invalid actions, gate rejections and integrity failures were zero in every
arm.

| Suite | Baseline `9783a7e` | Pass 1 | Pass 2 | Pass 3 |
| --- | --- | --- | --- | --- |
| Minetown | 24/39/4, 10, 1 | 25/37/5, **13**, 1 | 25/36/6, 10, **2** | 24/39/4, **12**, **2** |
| Oracle | 13/49/5, 7, 0 | 15/47/5, 5, 0 | 13/48/6, 4, 0 | 13/49/5, 6, 0 |
| D5 | 54/5/8, 0, 0 | not run | 55/5/7, 0, 0 | **53**/5/9, 0, 0 |

Bold marks a failed gate.

| Measure (Minetown / Oracle) | Baseline | Pass 1 | Pass 2 | Pass 3 |
| --- | --- | --- | --- | --- |
| Stalled runs | 26 / 25 | 25 / 25 | 26 / 26 | 26 / 25 |
| Spot switches in stalled stays | 1,261 / 1,338 | 352 / 372 | 334 / 418 | 590 / 731 |
| Search steps in stalled stays | 50,343 / 37,778 | 53,811 / 48,382 | 59,545 / 54,146 | 52,504 / 38,933 |

D5 stalled runs were 11, then 10 in pass 2 and 11 in pass 3. In pass 3 the
shopkeeper switches of 1528054415 came back.

### What each pass found

- **Pass 1:** peacefuls and other moving monsters cut off whole levels.
  - Minetown 2, a lost success: at step 1386 an adjacent hobbit cut off
    347 cells. In the Minetown task an undescribed monster is not
    attackable.
  - Minetown 2105401147, 1, 703 and 704 (new Weak-or-worse), Minetown 1374
    and Oracle 924 (new deaths): first cuts by a shopkeeper, gnome or
    hobbit.
- **Pass 2:** speed-1 and speed-3 monsters do move.
  - Minetown 2, a lost success: a floating eye cut off 374 cells, then
    moved away. The cut outlasted it, and the run was truncated after
    11,419 turns on Dlvl 3.
  - Minetown 6, new Weak-or-worse: floating-eye cuts of 371 and 440 cells.
  - Minetown 1, new starvation: a correct brown-mold cut changed the
    search order. On Dlvl 3 the run then made 1,842 searches and 1,627
    waits for a gas spore and a floating eye: rule 0064's mechanism.
  - D5 10, a lost success: a correct yellow-mold cut hid a 5-cell pocket
    that held the baseline's next spot, and the exit was not found.
- **Pass 3:** every remaining change is a correct speed-0 cut followed by a
  different search order.
  - Minetown 1, new starvation and Weak-or-worse: a brown-mold cut at
    step 3170, diverging at step 3341.
  - Minetown 9, new Weak-or-worse: a brown-mold cut at step 1517, diverging
    at step 1612; killed by a fox while fainting at turn 2,895.
  - Minetown 1369: still dies fainting on Dlvl 2, at turn 5,913 instead of
    10,667.
  - D5 10: lost its success through the same cut as in pass 2.

## Evidence

Per-seed records for each pass, the paired comparisons, stall diagnostics
and analysis scripts are in [evidence/0063/](evidence/0063/). Raw arms, the
development log (`DEV.md`) and the per-pass patches are in
`~/nethack-evidence/0063/`.

## Lessons

- Fixing the walk between search spots did not find more exits. Minetown
  1369, the clearest ping-pong case, still starves on the same level. The
  saved turns become search steps (Oracle pass 2: 37,778 to 54,146) at
  stands that do not hide the exit. The next rule must change where the hero
  searches, not how it gets there.
- A monster that is not displayed is not known. Any rule that remembers
  blockers must forget the ones that move; only speed-0 monsters are safe to
  remember ([note 0064](0064-sessile-blockers-development.md)).
- In the Minetown task an undescribed monster counts as peaceful, so
  monster-based rules must not treat it as a lasting obstacle.
