# 0062: Remaining stall mechanisms after explore-before-search

## Decision

**Diagnosis complete; next two rules chosen** (2026-10-26, ADR 0008 Phase 3).
After note 0061 shipped, most remaining stall steps go to three mechanisms
inside hidden-passage search, not to choosing the wrong level:

1. **Search-spot ping-pong** (rule 0063, first). The search skill switches
   its committed spot back and forth before reaching either spot.
2. **Waiting for a monster that never moves** (rule 0064, second). The
   policy waits for molds, floating eyes or gas spores that block the only
   known route.
3. **Search ranking**: searches never reach the cell that hides the exit.
   This is re-measured after rules 0063 and 0064, because ping-pong inflates
   it.

No product code changed and no seeds were consumed.

## Method

- **Source:** the candidate regression arms of note 0061
  (`~/nethack-evidence/0061q/cand-{mt,or}-reg`), read-only. The shipped
  commit `9783a7e` reproduces them outcome for outcome
  (`~/nethack-evidence/0062/ship-vs-cand.json`: no transitions in any of the
  three suites). D5 has no stalls beyond those of note 0060.
- **Stays:** the longest level stay of every run whose longest stay exceeds
  1,000 game turns (ADR 0008 §2): Minetown 26, Oracle 25. That is 46
  distinct stays, 182,764 turns, because five seeds have identical stays in
  both suites.
- **Snapshots:** each stay was replayed with the native-truth skill (diagnosis
  only), with the true map at three points: the stay's first search, its
  stall step (1,000 turns in) and its last step. All 51 replays succeeded.
- **Route classes:** taken at the stall step, from `analysis.analyze` toward
  the goal's actual target (note 0060's goal cells):
  - the hidden cells on the fewest-blocker route;
  - the number of the stay's searches made next to the first of those cells;
  - whether a stand next to it was on the hero's map.
- **Mechanisms:** each step of the stay was counted by its recorded rationale:
  - searching;
  - walking to a search spot, and how often that spot changed without being
    reached;
  - waiting for a blocking monster;
  - everything else.

Per-stay records:
[evidence/0062/stalled-stays.json](evidence/0062/stalled-stays.json).
Scripts: [evidence/0062/scripts/](evidence/0062/scripts/).

## Findings

### Mechanisms (169,063 steps in 46 stays)

| Mechanism | Steps | Share |
| --- | --- | --- |
| Search | 68,496 | 41% |
| Walk to a search spot | 42,408 | 25% |
| Wait for a blocking monster | 21,108 | 12% |
| Approach a route a monster blocks | 2,754 | 2% |
| Other (explore, fight, look, eat, pray) | 34,297 | 20% |

**Search-spot ping-pong.** 11 stays change their search-spot target at
least 20 times without reaching it: Minetown 1, 5, 9, 701, 1369, 1376,
1528054415 and 1703050900; Oracle 5, 902 and 904. In Minetown 1369 (Dlvl 2,
10,619 turns) the hero made 7,873 travel steps and 987 searches. Its target
alternates between (43,11) and (17,8) every 12 steps, always switching at
the same cell, so it reaches neither. The skill's own invariant says
a chosen spot stays committed until spent or unreachable, so this is a
defect. The cause is not yet confirmed: route reachability may depend on the
hero's position, for example a boulder that can be pushed from one side
only.

**Waiting for monsters that never move.** In seven stays the policy waited
at least 200 times for a "peaceful or unsafe to melee" blocker to move:

| Seed | Waits | Blocker |
| --- | --- | --- |
| 1376 | 6,084 | green mold |
| 1379 | 4,595 | floating eye, gas spore |
| 701 | 4,050 | yellow mold |
| 6 | 3,414 | floating eye |
| 9 | 1,813 | floating eye |
| 924 | 599 | red mold |
| 904 | 358 | green mold |

Molds never move, and floating eyes and gas spores barely move. In Minetown
1376 the main `>` was seen, 11 steps away, behind a green mold in a
one-wide corridor, and the hero waited from turn 4,178 to the step cap.
Ranged clearance (candidate 0053) is paused for lack of ammunition. Rule 0064
instead stops waiting: it treats a sessile, unsafe-to-melee blocker as
impassable, so the hero routes around it, searches elsewhere or leaves the
level.

### Route classes at the stall step (46 stays)

| Class | Stays | Turns | Share |
| --- | --- | --- | --- |
| Hidden cell on the route; a stand beside it is known, but fewer than 30 searches were made there | 7 | 45,303 | 25% |
| Route open and seen (includes monster-blocked corridors) | 7 | 27,515 | 15% |
| Searched next to the hidden cell 30+ times | 3 | 17,446 | 10% |
| Route open through unseen cells | 4 | 16,121 | 9% |
| Oracle not on this level | 8 | 15,620 | 9% |
| Other barrier (locked door, boulder) | 3 | 12,705 | 7% |
| Mines branch not on this level | 6 | 11,754 | 6% |
| Hidden cell with no known stand beside it | 1 | 10,926 | 6% |
| Temple: locked door; no temple; unreachable; up stairs; altar | 7 | 25,374 | 14% |

The analysis ignores monsters, so the monster-blocked stays (1376, 904, 700)
count as "open and seen". The "wrong level" classes (Oracle or branch not on
this level, 15% together) are what is left of note 0060's largest class.
These stays did not hold up on a level that lacks the target; they searched
there under a range goal on the way through. Many end once the `>` is found.

## Lessons

- A class from the end-of-stay map can mislead. A hidden passage found late
  in the stay looks like an open route, so classify at the stall step.
- The route analysis ignores monsters. Read the waits in the step rationales
  as well.
