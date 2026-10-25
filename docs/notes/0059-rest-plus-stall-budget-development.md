# 0059: Combined rest + stall-budget candidate, development

## Decision

**NOT QUALIFIED** (2026-10-25, project owner). Candidate 0059, the 0057
disengage-and-rest rule combined with the 0054 no-progress navigation budget
under the [ADR 0007 exception](../decisions/0007-mines-minetown-and-oracle.md#process-decision-2026-10-21-combined-candidate-0059),
failed the §4.1 gates on the D5 regression suite in its third and last
development pass. It was never preregistered: no fresh seeds were consumed
(635-664 stay unused), and nothing was merged. As the exception requires,
both rules are rejected as a unit. The code stays on branch
`rule-0059-rest-plus-stall-budget` (`afc3282`, pushed to `origin`;
worktree `~/nethack-evidence/0059-rest-stall/candidate`).

## Method

- Base: the shipped commit `22d0a5f`. Baseline arms: the 0052 regression arms
  (`~/nethack-evidence/0052/0052-base-{mt,or,d5}-reg`), the same reports as
  [note 0057](0057-elbereth-disengage-qualification.md)'s baseline records.
- Candidate suites: copies of `minetown-regression-v2`, `oracle-regression-v2`
  and `unified-d5-regression-v5` relabelled `*-0059-dev` outside the repository
  (`~/nethack-evidence/0059-rest-stall/suites/dev/`; SHA-256 `41029745…`,
  `762ad2e9…`, `6aafd8d9…`). Seeds, tasks and step caps are unchanged.
- Each pass ran all three suites, 67 seeds each, with the scripted
  development model, 2 workers per arm, via `detached_eval.py`. Every pass was
  compared with `_agents/skills/evidence-record/compare.py`.
- Diagnosis used `runs.sqlite3` step events, read-only, with the scripts in
  [evidence/0059/scripts/](evidence/0059/scripts/).

## Results

Objectives / deaths / Weak-or-worse deaths / starvation deaths; baseline
first. Invalid actions, gate rejections and integrity failures were zero in
every arm of every pass.

| Pass (commit) | Minetown | Oracle | D5 |
| --- | --- | --- | --- |
| baseline `22d0a5f` | 19 / 42 / 20 / 1 | 9 / 53 / 19 / 0 | 54 / 5 / 0 / 0 |
| 1 (`9eb1251`) | 12 / 47 / 31 / 3 | 11 / 51 / 16 / 2 | 49 / 5 / 0 / 0 |
| 2 (`5bc5b70`) | 15 / 48 / 25 / 2 | 13 / 52 / 17 / 1 | 54 / 6 / 0 / 0 |
| 3 (`afc3282`) | **19 / 37 / 19 / 1** pass | **14 / 50 / 17 / 0** pass | 53 / 6 / 3 / 0 fail |

Runs with at least 100 model-fallback (WAIT) steps, Minetown / Oracle / D5:
baseline 4 / 3 / 1; pass 1 34 / 24 / 12; pass 2 10 / 8 / 1; pass 3 15 / 7 / 3.

Per-seed records: `pass{1,2,3}-<suite>.json`; paired gates and every changed
seed: `pass{1,2,3}-paired-comparison.json`, all in
[evidence/0059/](evidence/0059/).

## What each pass found

1. **Pass 1** (`9eb1251`). Two 0054 bugs left the hero waiting for thousands
   of steps:
   - A place-objective re-arm never forgave failed moves. D5 1360: a bear
     trap at turn 5 quarantined every exit, and the budget was exhausted
     from turn 19.
   - The coordinator chose the legacy search round by goal class, while the
     skill chooses it by "no stair target". Minetown temple and altar goals
     (901, 1367) never got another search round.

   Fixed in `7a7d04b` and `5bc5b70`. Smoke runs then showed the evaluator's
   own level memory never re-arming (26 / 10 / 460 invalid actions on 901 /
   2105401147 / 1367), so the evaluator now mirrors the coordinator and
   replay re-arm. Spent stair travel falls back to legacy round search
   instead of waiting.
2. **Pass 2** (`5bc5b70`). Lost Minetown successes (1360, 704, 10, ...)
   spent 2,000-3,500 turns on main Dlvl 2 with no stuck reason. The 0054
   `search_candidate` dropped its commitment on arrival at a stand, so the
   hero crossed the level to a better-ranked stand without searching. The
   cells newly observed on each walk restarted the no-progress clock, so the
   budget never ran out. Arrive-then-leave events: candidate 662 in 43 runs,
   baseline 10 in 7. Fixed in `afc3282`: an arrived stand stays committed
   for one batch.
3. **Pass 3** (`afc3282`). Arrive-then-leave events fell to 15 in 9 runs.
   Minetown and Oracle pass every gate. D5 lost 5 successes:
   - 824, 1009099699, 1195605202 and 1372 truncate at the 3,000-step cap.
     1195605202 spends all 3,000 turns on Dlvl 1 with no stuck reason: about
     1,170 east/west moves against 527 searches. The baseline finishes in
     912 turns.
   - 924 dies Fainting on Dlvl 4 after 625 budget-exhausted waits.

   Candidate D5 also gained 4 successes (1259450733, 1528054415, 1887524929,
   5). Its new deaths, 924, 902 and 1, all at Fainting, are the 3 new
   Weak-or-worse deaths.

## Remaining mechanism

The 0054 ranking puts the least-covered stand anywhere on the level ahead of
distance. After each batch the hero walks across the level to the next
stand. The no-progress clock counts every newly observed cell as progress,
including known floor passed on a new route, so these walks keep restarting
it. On small D5 levels with a hidden exit this costs more turns than the
baseline's density-gated search. A successor needs a distance-aware ranking,
or a clock that knowledge of already-mapped floor does not restart.

## Disposition

- The pass 3 code is the best measured state of the pair: it passes
  Minetown and Oracle with more objectives and fewer deaths. Any successor
  that combines these rules again needs a new owner exception to §4.1, its
  own development passes on the regression suites, and a fresh sample. The
  0059 exception does not carry over.
- Representative-seed catalog: its check passed on the pass 1 commit and
  caught none of the three navigation bugs above, which only the full
  regression passes exposed. All 11 catalog entries are milestone 1-2 tasks
  with short caps. None runs `find_oracle` or `enter_minetown_temple`. This
  is open for the owner's review of the verification process.
