# 0058: Branch-stair identity diagnosis

**Decision: NO RULE** (2026-10-21). The Phase 2 item "fix downward
branch-stair identity" is closed without a candidate. In the shipped
baseline, taking the Gnomish Mines `>` while the goal is main-dungeon
descent costs 2 turns per affected run and no objectives. Diagnosis only:
no product code changed, no evaluation ran, and no seeds were consumed.

## Evidence

Source: the shipped baseline Oracle regression arm (`0052-base-or-reg`,
`oracle-regression-v2`, 67 seeds, commit `22d0a5f`, scripted development
model), read from its report and `runs.sqlite3` step events. The per-run
record and scripts are in [evidence/0058/](evidence/0058/).

- 26 of 67 runs took the Mines `>`, the same 26 that note 0050 classed as
  branch confusion. Branch level: Dlvl 2 in 7 runs, Dlvl 3 in 11, Dlvl 4 in 8.
- Each run entered the Mines once, observed one step on Mines level 1, and
  climbed straight back. From the last step on the branch level to the first
  step back on it took exactly 2 steps and 2 turns in every run (52 in all).
- No run died in the Mines. 25 of 26 then descended the main `>` to the next
  Dlvl; seed 703 died on Dlvl 3, after returning, to a gas spore's
  explosion.
- Outcomes of the 26: 4 objectives, 1 truncated, 21 deaths on main Dlvl
  3-7, 8 of them at Fainting.

## Why no rule

Recovery already works: `_leave_branch` (`planner.py`) climbs the recorded
arrival link at once, and the used `>` then counts as a branch staircase,
so `candidate_tier` refuses it for the main target. Existing tests cover
both steps (`test_planner.py::test_a_wrong_dungeon_is_left_by_the_recorded_branch_link`,
`::test_two_downstairs_are_probed_and_elimination_finds_the_branch`).

No public information could tell the staircases apart earlier. In every
run no other `>` was displayed when the hero descended. NetHack 3.6.7 has
one downstairs glyph, and the overview records a branch only after it is
used (`recbranch_mapseen` from `goto_level`, `do.c:1422`,
`dungeon.c:2009-2036`).

The cost in these runs is the later deaths on main levels, which belong to
the Phase 3 survival and Phase 4 food work, not to branch identity. The
opposite direction (Minetown runs that descend the main dungeon) was not
analysed and remains under the Mines cave-navigation and branch-identity
item.
