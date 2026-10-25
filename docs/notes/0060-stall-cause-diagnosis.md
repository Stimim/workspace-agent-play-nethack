# 0060: Milestone 3A stall-cause diagnosis

## Decision

**Diagnosis complete; first rule chosen** (2026-10-25, ADR 0008 Phase 1).
The largest stall cause is the planner, not hidden exits. It makes the hero
search a level for a target that is not there: the Mines branch staircase,
the Oracle, or a Mines temple. That class takes 58% of the stall turns. The
first Phase 3 rule addresses it. No product code changed, no evaluation ran,
and no seeds were consumed. The stall definition of ADR 0008 §2 stands
unchanged.

## Method

- **Source:** the shipped baseline regression arms (`0052-base-{mt,or,d5}-reg`,
  commit `22d0a5f`, scripted development model, 67 seeds each), read-only.
- **Stays:** every contiguous stay on one level longer than 1,000 game turns
  (ADR 0008 §2). There are 125 stays in 99 runs: Minetown 67, Oracle 47,
  D5 11.
- **Snapshot:** each run was replayed with the native-truth skill
  (diagnosis only), and the true map captured at the first step 1,000 turns
  into each stay.
- **Target:** the cell the hero's goal at that step was seeking:
  - the main or branch downstairs, from the goal's stair target;
  - the temple room's centre, for temple and altar goals;
  - the Oracle, on the Oracle special level.
- **Classes:**
  - *Wrong target:* no such target on this level.
  - *Open route:* `analysis.analyze` found a barrier-free route. It is
    *seen* when the target cell was already on the hero's map.
  - *Barrier:* the classes every minimal route must cross (secret door or
    corridor, locked or closed door, boulder, peaceful monster).
- **Excluded:** one run (Minetown seed 1363) failed replay. NetHack writes
  `<name>'` rather than `<name>'s` for a shopkeeper whose name ends in "s",
  and the skill's shopkeeper-name normalization does not cover that. That
  leaves 124 classified stays.

Per-stay records: [evidence/0060/stalled-stays.json](evidence/0060/stalled-stays.json).
Scripts: [evidence/0060/scripts/](evidence/0060/scripts/).

## Results

| Cause | Stays | Runs | Turns past the 1,000th |
| --- | --- | --- | --- |
| Target not on this level | 82 | 69 | 172,161 (58%) |
| Exit needs a secret door or corridor | 22 | 21 | 72,387 (25%) |
| Target seen, open route, not taken | 12 | 12 | 22,303 (8%) |
| Open route, target never seen | 5 | 5 | 13,167 (4%) |
| Locked door | 2 | 2 | 9,876 (3%) |
| Peaceful monster in the way | 1 | 1 | 4,761 (2%) |

58 of the 98 classified stalled runs stalled only in wrong-target stays.

### Target not on this level (82 stays)

- **Mines branch, 49 stays (Minetown suite):** main Dlvl 2 (37), 3 (11) and
  4 (1). None of these levels has a down branch staircase, and the main `>`
  was already on the hero's map in 45 of them.
- **Oracle, 27 stays (Oracle suite):** Dlvl 5 (23) and 6 (4), none on the
  Oracle level. The main `>` was on the map in 25.
- **Mines temple, 6 stays:** Mines levels 3 and 4 that are not Minetown, with
  an `enter_temple` (5) or `occupy_altar` (1) goal.
- **Cost:** median stay 2,051 turns. Outcomes of these runs: 60 deaths, 13
  objectives, 9 truncations.

**Mechanism.**
- `ObjectivePlanner._enter_branch` treats a branch-range level as open until
  it is `exhausted`. `FindOracleLeg` keeps `ApproachOracleGoal` on Dlvl 5-9,
  and `EnterMinetownTempleLeg` keeps `EnterTempleGoal` on Mines level 3,
  until the level is `explored`. On Mines level 4 without an identified
  town it keeps `EnterTempleGoal` with no exit condition at all.
- Both flags are set only by `DungeonMemory.mark_exhausted`, when exploration
  reports `search_exhausted`: every frontier visited *and* every hidden-passage
  search candidate spent.
- So the hero searches each range level for hidden passages before it has
  seen the next range level, where the target is usually in plain sight.

### Exit needs a secret passage (22 stays)

- All 22 target a downstairs (21 main, 1 branch).
- Median 877 searches on the level. In only 10 of 22 stays did any search
  stand next to a secret cell on the true shortest route to the main
  downstairs.

### Target seen and reachable but not taken (12 stays)

Mostly levels with long `staircase_navigation` or repeated
`search_exhausted` stretches (Minetown 904, Oracle 3, 700). This class needs a
per-run trace before any rule.

## Consequence for Phase 3

1. **First rule: explore before searching in a target range.**
   - In the branch range (Dlvl 2-4), the Oracle range (Dlvl 5-9) and on
     Mines levels 3-4, a level whose frontier is exhausted counts as visited:
     the hero takes the known main staircase onward.
   - Hidden-passage search of a range level happens only after every range
     level has been frontier-explored without finding the target.
   - It changes the planner, so it needs a shared predicate across planner,
     coordinator, replay and evaluator, and consumer tests that fail without
     it.
2. **Then:** secret-passage search targeting (25%) and the seen-but-not-taken
   traces (8%).
3. **Tool gap:** fix native-truth replay normalization of possessive
   shopkeeper names ending in "s".
