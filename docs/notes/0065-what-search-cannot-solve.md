# 0065: What hidden-passage search cannot solve

## Decision

**Diagnosis complete; search ranking is not the next rule** (2026-10-26, ADR
0008 Phase 3). Notes 0063 and 0064 planned search ranking next. Measured on
the 46 stalled stays of [note 0062](0062-remaining-stall-mechanisms.md),
however, a hidden passage the search fails to find blocks only 8% of stall
turns. In most stays the search has nothing left to find: the route is
blocked by something search cannot open, and the hero keeps re-searching its
last candidate stand. The largest classes are:

1. **A monster on the route** (43%): molds, floating eyes and gas spores
   the policy will not melee.
2. **Mines levels** (21%): mostly the Minetown temple task.
3. **A locked or closed door** (11%).

Choosing the next rule from these is an owner decision, recorded in
`docs/handover.md`. No product code changed and no seeds were consumed.

## Method

- **Source:** the shipped baseline regression arms
  (`~/nethack-evidence/0062/base-{mt,or}-reg`, commit `9783a7e`), read-only.
  Step indices match note 0062's records, which came from the 0061 candidate
  arms with identical outcomes: the hero positions agree at the probed steps.
- **Search profile** ([search_profile.py](evidence/0065/scripts/search_profile.py)):
  `LevelMemory` was rebuilt from stored events with `ExplorationReplay`. At
  every hidden-passage search in each stay, the script recorded the search
  round, how many stands still scored as candidates, and whether the hero
  stood next to the true hidden cell from note 0062. Blocker waits, which are
  also sent as search actions, are excluded by their rationale.
- **Stand ranks** ([rank_probe.py](evidence/0065/scripts/rank_probe.py)): at
  the first search, the stall step and mid-stay, every reachable stand was
  scored the way `skills._search` scores it. The script reports the rank of
  the stands next to the true hidden cell.
- **Final cause** ([causes.py](evidence/0065/scripts/causes.py)): each stay
  takes the first matching group:
  - a Mines level;
  - a monster: 300 or more blocker waits, or a peaceful monster on the true
    route at the stall or end step;
  - a locked or closed door on the true route;
  - no target on this level;
  - a hidden cell on the route;
  - anything else.

  One stay was moved by hand after tracing: in Minetown 1377 a floating eye
  shuts the hero in (see below).
- **Prayers** ([prayers.py](evidence/0065/scripts/prayers.py)): every prayer
  in the Minetown and Oracle arms, with the messages that follow it.

## Findings

### The search runs out of candidates (68,496 searches)

| Searches made | Count | Share |
| --- | --- | --- |
| At round 10 or later (each stand already searched 100+ times) | 37,947 | 55% |
| With a single candidate stand left | 23,758 | 35% |
| Next to the true hidden cell | 162 | 0.2% |

Six stays each searched one stand between 720 and 8,084 times. Minetown 1374
searched (42,15) 8,084 times and Minetown 1377 searched (19,12) 5,888 times.
With Luck 0, a search finds an adjacent hidden door or corridor with chance
1/7 (`rnl(7)`, `dosearch0` in NetHack 3.6.7 `detect.c`). After 30 misses
the chance that a hidden cell is still there is about 1%, so these searches
were almost certainly wasted.

### Final causes (182,764 turns in 46 stays)

| Cause | Stays | Turns | Share | Searches | Blocker waits |
| --- | --- | --- | --- | --- | --- |
| Monster on the route | 10 | 78,912 | 43% | 28,616 | 20,946 |
| Mines level (Minetown temple task) | 11 | 38,187 | 21% | 21,543 | 42 |
| Locked or closed door | 4 | 19,773 | 11% | 4,221 | 1 |
| Target not on this level | 11 | 16,934 | 9% | 5,321 | 41 |
| Hidden passage not found | 4 | 15,038 | 8% | 2,403 | 0 |
| Route open, or other | 6 | 13,920 | 8% | 6,392 | 78 |

- **Monster on the route:** Minetown 1528054415, 1376, 1374, 1377 and 9;
  Oracle 1379, 924, 701, 904 and 6. The hero either waits for the monster
  or, with rule 0064, searches elsewhere. Neither gets it past.
  - Minetown 1374: the hidden corridor cell was found at step 5,770, but a
    floating eye still blocked the corridor beyond it.
  - Minetown 1377: the hero found a hidden door at (19,13) and stepped
    through into a one-cell dead end. A floating eye then sat in that
    doorway, and the hero searched the dead end 5,888 times
    ([map_at.py](evidence/0065/scripts/map_at.py), step 4,629).
  - Minetown 1528054415 also has a target gap: its hidden cell is beside a
    straight corridor, which `_search_targets` never targets.
- **Mines level:** Minetown 643863903, 1703050900, 1195605202, 5, 703,
  1367, 1009099699, 1354866613, 901, 1003301977 and 1365. The temple door is
  locked, the temple is unreachable, or the level has no temple. ADR 0007
  forbids kicking doors in Minetown.
- **Locked or closed door:** Oracle 5, 1370 and 1377 (Dlvl 1), and
  Minetown and Oracle 1. The native-truth route crosses a locked door.
  - The kick rule refuses at Weak or worse hunger and needs unexplored
    space beyond the door; these stays spend much of their time Weak or
    Fainting. Whether each door was known to be locked was not traced.
  - Oracle 5: the hero found the door while in a form with no hands ("You
    can't open anything -- you have no hands!") and never tried it again.
    It then waited 7,779 steps on the scripted model's fallback.
- **Hidden passage not found:** Minetown 1369, 10, 701 and Oracle 1375. In
  1369 the best-ranked stand, (49,12), already targets the hidden cell, but
  molds cut the route to it (note 0063). In 10 and 1375 a stand next to the
  hidden cell was searched 10 times without success. It was then skipped
  until every other candidate on the level had been searched as often:
  41 to 126 stands.

### Prayers do not explain the failed searches

Praying too soon costs 3 Luck (`pray.c`), and with Luck −2 to −4, `rnl(7)`
returns 0 about once in 266 calls instead of once in 7. That would make
searching about 38 times slower. But of 192 prayers in the two arms, 187
fixed the trouble and only one came too soon (Minetown 1376: "You feel
foolish!") ([prayers.json](evidence/0065/prayers.json)). Two stays, Minetown
and Oracle 1 and Oracle 1377, did search next to their hidden cell 31 and 38
times before finding it. At 1/7 per search that happens about 1% of the
time, so Luck below −1 from another source cannot be excluded. Luck is not
in the observation.

## Candidate next rules

| Rule | Class it attacks | Stall turns | What it needs |
| --- | --- | --- | --- |
| Get past a sessile monster at range | Monster on the route | 43% | A source of throwable items or ammunition (TODO Phase 2; candidate 0053 is paused) |
| Kick a locked door to a known but unreachable region, and retry doors after a no-hands failure | Locked or closed door | 11% | The ADR 0007 conduct gates; main dungeon only |
| Leave a level after its search is exhausted, when the target may be elsewhere | Target not on this level, and some of the rest | 9% or more | A bound such as 30 misses per stand, kept clear of the 0054 failure |
| Search ranking (soft per-stand decay instead of rounds; corridor-side targets) | Hidden passage not found | 8% | Nothing new |
| Minetown temple access | Mines level | 21% | A milestone 3 objective decision (locked temple door) |

## Evidence

[evidence/0065/](evidence/0065/): the per-stay search profile, stand ranks,
final causes, prayer outcomes and scripts.

## Lessons

- The search measure has to separate searching from waiting. Blocker waits
  are sent as search actions, and the first profile counted 85,490
  "searches" instead of 68,496.
- A stand searched far beyond the 1% miss bound is a sign that the blocker is
  not a hidden passage.
- Two stays with the same seed and level are not always the same stay
  (Minetown and Oracle 701). Deduplicate stays by length as well.
- A native-truth route class names the first barrier on the fewest-blocker
  route, not what stops the hero. Minetown 1377 classed as a locked door,
  but the hero was shut in by a floating eye. Check the agent's own map.
