# 0064: Never wait on a sessile blocker, development

## Decision

**NOT QUALIFIED; not preregistered** (2026-10-26, ADR 0008 Phase 3). Rule
0064 makes a sessile monster the policy will not melee impassable instead of
waited on. It removed almost every blocker wait, but its one development pass
failed the Minetown Weak-or-worse gate (10 -> 12). The heroes it frees from
waiting now search a level whose exit they cannot find, live on hunger
prayers and die fainting. That is a search problem, not a defect in this
rule, so retuning it would fit individual seeds. No fresh seeds were spent
and nothing was merged. The code is on branch `rule-0064-sessile-blockers`
(`8480bb1`; worktree `~/nethack-evidence/0064/candidate`). It may be
re-measured on top of a search-ranking rule, as a new candidate.

## Method

- **Base:** the shipped commit `9783a7e`, with the regression arms of note
  0062 (`~/nethack-evidence/0062/base-{mt,or,d5}-reg`). The branch starts at
  `e9dde72`, which adds only documentation.
- **Suites:** `minetown-regression-v3`, `oracle-regression-v3` and
  `unified-d5-regression-v6`, relabelled `*-sessile-dev-0064` outside the
  repository. Seeds, tasks and step caps are unchanged. Policy label
  `hierarchical-survival-hp-prayer-burden-look-ration-explore-first-sessile-qual-v1`.
- **Runs:** 67 seeds per suite, the scripted development model, 2 workers
  per arm, compared with `compare.py` and `stalls.py`. Smoke runs on Minetown
  1376 and 9 and Oracle 701, 6 and 1379 came first. A first pass-1 launch was
  stopped after a few minutes to fix a defect the smoke runs found; it is not
  counted.
- The development pass was run by a worker agent. The orchestrator re-checked
  the reported gates against the reports, the blocker-wait counts against
  the databases, and two traces (Minetown 1370 and 1374).

## The rule

- **Where the waits came from:** `skills._past_monster` waits for a blocker
  that is peaceful or unsafe to melee. It is reached from stair navigation and
  from exploration. Waits are capped at `MONSTER_WAIT_LIMIT = 8` per map
  knowledge value, but monsters moving elsewhere keep changing the knowledge,
  so the cap re-arms until the step cap. Minetown 1376 waited 6,082 times for
  one green mold.
- **Sessile:** base speed (`permonst.mmove`, NetHack 3.6.7) of at most 3;
  the hero's is 12. That covers molds, blue and spotted jellies and the Oracle
  (0), floating eyes (1) and gas spores (3). Only monsters the policy already
  refuses to attack count; anything it fights is unchanged.
- **Change:** `route_tree` treats such a blocker as impassable, even when
  routing through monsters. Skill selection, `frontier_exhausted`, replay and
  the evaluator's route check share that one predicate. There are no new
  actions or attacks.
- **Memory:** in a dark corridor a mold two cells away is not drawn, so the
  route looked open from one cell and blocked from the next, and the hero
  stepped back and forth for about 1,000 steps (smoke run, Minetown 1376). A
  speed-0 blocker is now remembered until its cell is seen without it.

## Results

Objectives / deaths / truncations, Weak-or-worse deaths, starvation deaths.
Invalid actions, gate rejections and integrity failures were zero in every
arm, as were attacks on the Oracle or on peacefuls.

| Suite | Baseline `9783a7e` | Pass 1 | Stalled runs | Gates |
| --- | --- | --- | --- | --- |
| Minetown | 24/39/4, 10, 1 | 24/39/4, 12, 1 | 26 -> 26 | **fail** (Weak-or-worse) |
| Oracle | 13/49/5, 7, 0 | 14/49/4, 7, 0 | 25 -> 20 | pass |
| D5 | 54/5/8, 0, 0 | 56/4/7, 0, 0 | 11 -> 11 | pass |

Blocker waits, counted from step rationales
([scripts/waits.py](evidence/0064/scripts/waits.py)):

| Suite | Baseline | Pass 1 | What remains |
| --- | --- | --- | --- |
| Minetown | 8,214 | 148 | shopkeepers, priests, gnomes, dwarves, hobbits |
| Oracle | 13,441 | 19 | shopkeepers, gnomes, dwarves |
| D5 | 1,285 | 12 | shopkeepers |

The median longest stay fell from 610 to 521 turns on Minetown and from 633
to 551 on Oracle.

### Every lost success and new death

- **Lost successes**, all trajectory divergence that later dies in an
  ordinary fight:
  - Minetown 1370, step 544: the baseline waited on a gas spore; the
    candidate died to a housecat on Dlvl 8.
  - Minetown 2, step 1724: a floating eye ahead; a large mimic on Dlvl 8.
  - Oracle 2094095407, step 1146: a different search spot; a pony on Dlvl 5.
  - Oracle 1365, step 1345: the baseline stepped back and forth beside a
    green mold; a killer bee on Dlvl 6.
- **New deaths from truncation:**
  - Minetown and Oracle 1374 and Minetown 1376 die fainting (new
    Weak-or-worse). They no longer wait; they search a level with no
    reachable exit, on repeated hunger prayers. In 1376 a prayer at turn
    7,101 ended "You feel foolish", and a hobgoblin killed the fainting
    hero. 1374 made about 2,500 searches at one spot.
  - Oracle 924: a soldier ant on Dlvl 7.
- **New Weak-or-worse among deaths:** Minetown 9 (the baseline also died
  there hungry), Oracle 1371 and 701. Removed: Minetown 5, Oracle 1887524929,
  904 and 1.
- **Gains:** Minetown 902 (gas spore) and 704; Oracle 1259450733 (yellow
  mold), 296200318 (gas spore) and 1375; D5 1259450733 and 1887524929.

## Open concerns

- A hero trapped between floating eyes now reports `search_exhausted`
  instead of `monster_blocked` and falls back to the model (Oracle 6: 287
  scripted WAIT fallbacks). A real local model could walk into the eye;
  ActionGate refuses fallback attacks only on the Oracle, centaurs and conduct
  cases. That exposure existed before the rule.
- A remembered mold that dies out of sight stays a wall until the hero is
  next to its cell.

## Evidence

Per-seed records, the paired comparison and stall diagnostics are in
[evidence/0064/](evidence/0064/). Raw arms, the development log (`DEV.md`)
and the patch are in `~/nethack-evidence/0064/`.

## Lessons

- Removing a waste of turns frees those turns for searching. When the search
  cannot find the exit, the hero only starves later; the rule moves deaths
  rather than adding objectives. See [note 0063](0063-search-spot-commitment-development.md)
  for the same result from the ping-pong fix.
