# 0041: Causal qualification of the "retain goal stairs during escape" candidate — REJECTED

## Background

Commit `634dc52` ("Retain deterministic goal stairs during public-state
escapes") was pushed to `main` without any dev-set or fresh-sample
qualification run, violating the protocol in note 0040. It was reverted by
`4e254e1`. This note preregisters, runs, and causally reviews that candidate
properly, per note 0040's protocol, before any ship decision.

**Scope correction**: investigation found the committed diff was not a small
delta on an existing qualified disengagement feature. `RecoverySkill`,
`health_action_error`, `rest_allowed`, `needs_disengagement`, and the entire
`recovery.py`/`health.py` module did not exist at the last qualified commit
(`c8620f7`, note 0040). They were new, never-qualified work from this
session. The "goal-stair retention" change was one more rule layered on top
of that already-unqualified feature. The candidate evaluated below is
therefore the whole new threat-disengagement/rest-budget feature (including
the goal-stair fix), not an isolated one-line change, because that is the
actual, atomic, never-shipped unit of behavior.

## Preregistration (frozen before any episode)

**Candidate**: HEAD (`4e254e1`, no `RecoverySkill`/threat-disengagement
feature) plus the reverted `634dc52` diff reapplied from
`/tmp/fix3-candidate.patch`, pinning knowledge bundle `survival-reviewed-v3`.

**Methodology**:
1. Run the 67-seed historical development set
   (`evaluation/unified-d5-regression-v2.json`, a copy of immutable `v1` with
   `survival-reviewed-v3` pinned) with the candidate; compare against HEAD's
   known `survival-reviewed-v2` development result (52 objectives, 8 deaths,
   1 hunger death, zero invalid actions/gate rejections, per note 0040).
2. Run a fresh 30-seed comparison (seeds 61-90, the next unused range in
   `evaluation/seed-ledger.json`) between HEAD (`survival-reviewed-v2`) and
   candidate (`survival-reviewed-v3`).
3. Causally diagnose every lost success, new death, and new gate rejection.

**Acceptance**: fresh/dev objectives not lower and deaths not higher than
HEAD; zero starvation deaths; zero deaths ending Weak or worse; zero invalid
actions, gate rejections, or integrity problems (note 0040 section 3).

## Results

### Dev set (67 seeds, scripted model, `--development-scripted-model`)

| | HEAD (retained baseline, note 0040) | Candidate (`unified-d5-regression-v2`, this run) |
|---|---|---|
| Objectives | 52/67 | 50/67 |
| Deaths | 8 | 6 reported as death + **5 gate rejections** |
| Hunger deaths | 1 | not reached (run disqualified below) |
| Invalid actions / gate rejections | 0 | **5** |

Report: `/tmp/candidate-dev/reports/unified-d5-regression-v2-development-20261004T053353Z.json`.

Per-seed candidate outcomes that differ from a clean HEAD-comparable run:
seeds **703, 1370, 1376, 1377, 1379** all end `paused_after_gate_rejection`
with the identical error `"search/wait must not idle beside an attacking
hostile or gas spore"`. Seeds 703 and 1379 were previously-qualified
*deaths* in the HEAD baseline (note 0040's documented pre-existing
search/combat failure class); the candidate now turns them into **invalid
actions** instead of clean deaths — strictly worse, not a neutral
reclassification.

Two previously-run seeds (1368, 1372) that note 0040 reports as having been
remediated to `objective_complete` remain `objective_complete` here; this is
consistent with the earlier qualified fix, not new candidate behavior.

### Fresh sample (seeds 61-90, `staircase-retreat-fresh-v2`/`v3`)

HEAD: 28/30 objectives, 1 death (seed 79), 1 truncation (seed 70).
Report: `/tmp/head-fresh/reports/staircase-retreat-fresh-v2-development-20261004T052607Z.json`.

Candidate: run repeatedly hit an unrelated 300-second background-job
execution cap in this environment before finishing all 30 seeds (last
completed seed: 78 of 30 attempted, three attempts, `/tmp/candidate-fresh*`).
The completed 19/30 seeds already reproduce the dev-set failure class
independently: seeds **64** and **78**, both clean `objective_complete`
successes under HEAD, now end `stopped` under the candidate with the exact
same error, `"search/wait must not idle beside an attacking hostile or gas
spore"` (`/tmp/candidate-fresh3/runs.sqlite3`, `runs` table). No candidate
run on any sample completed without this new failure mode. The fresh run was
not completed to 30/30 because the result is already conclusive and further
scripted-model runtime would not change the decision below.

## Causal diagnosis

All 7 observed candidate-only failures (5 dev, 2 fresh so far) share one
root cause and error string. `health_action_error`'s search/wait-adjacency
gate (`recovery.py`, the new module) is a global rule applied to every
`Command.SEARCH`/`MiscDirection.WAIT` action regardless of which skill chose
it. It did not exist before this session. It is not scoped to
`Skill.RECOVERY`: it fires whenever the actually-selected action is a
wait/search and a hostile is adjacent at execution time, including a
legitimate multi-turn `EXPLORE_LEVEL` hidden-passage search that has no
awareness of, or exemption from, this rule. When a monster wanders adjacent
mid-search — ordinary, expected NetHack behavior — the coordinator now
hard-rejects the in-flight action instead of letting `EXPLORE_LEVEL`
continue or redirect, turning what was previously a clean outcome (success
or a known combat/search death) into an unrecoverable gate rejection. This
is a genuine, systemic defect in the new feature, not a pre-existing failure
class surfacing differently and not scripted-model noise: it is reproduced
identically across 5 distinct dev seeds and 2 distinct fresh seeds, always
with the same message, always on a wait/search action that a non-Recovery
skill selected while a hostile was or became adjacent.

## Decision: REJECT

The candidate fails the preregistered acceptance bar categorically (zero
gate rejections required; 5 observed in dev, 2 more observed in a partial
fresh run) and also loses development objectives (52 to 50) while
transmuting two previously-clean deaths into worse integrity failures. `main`
remains at `4e254e1` (no `RecoverySkill`/threat-disengagement feature). The
candidate diff is preserved only as `/tmp/fix3-candidate.patch` (not
committed, not shipped). No later policy may reintroduce this behavior
without first fixing the search/wait-adjacency gate to exempt or correctly
interoperate with non-Recovery skills' in-flight searches, and re-running
this same qualification protocol on a fresh, unused seed sample.
