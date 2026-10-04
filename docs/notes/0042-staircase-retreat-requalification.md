# 0042: Requalification of the fixed staircase-retreat/RecoverySkill candidate

## Preregistration (frozen before any episode)

Note 0041 rejected `/tmp/fix3-candidate.patch` (the full `RecoverySkill`
threat-disengagement/rest feature, including the original "retain goal
stairs during escape" change) for a systemic defect: `health_action_error`'s
search/wait-adjacency gate fired on every skill's wait/search action, not
only `RecoverySkill`'s own, hard-rejecting legitimate in-flight
`EXPLORE_LEVEL` hidden-passage searches whenever a monster wandered
adjacent (seeds 703, 1370, 1376, 1377, 1379 dev; 64, 78 fresh).

**Fix applied** (`/tmp/fix3-candidate-v2.patch`, a superset of v1): split
`health_action_error`'s search/wait check in two:
1. Gas-spore blast-radius proximity (`gas_spore_distance <= 2`) stays
   universal across every skill — standing or searching beside a known gas
   spore is never correct regardless of which skill is acting.
2. The hostile-adjacency idle check (`_attackers`) is now scoped to
   `selection.skill is Skill.RECOVERY` only — other skills' legitimate
   in-flight searches/waits are no longer hard-rejected merely because a
   monster wandered adjacent.

The single `health_action_error` function remains the only implementation,
called identically by the runtime gate (`coordinator.py` `ActionGate`,
lines ~212/1129) and the evaluator audit (`evaluation.py` `_action_is_valid`
line ~2341), so both paths share the fix by construction, not by
duplication.

An existing test, `test_threat_action_gate_and_audit_agree_on_actual_attack_or_move`,
had pinned the disproven over-broad behavior (asserted `Skill.EXPLORE_LEVEL`
`Command.SEARCH`/`MiscDirection.WAIT` beside a jackal must be rejected). Its
two jackal-adjacency cases are corrected to `accepted=True`; its gas-spore
proximity cases are untouched (still `accepted=False`, now universal). A new
regression test, `test_non_recovery_search_beside_a_hostile_is_not_gate_rejected`,
directly reproduces the seed-64/78 shape (an `EXPLORE_LEVEL` search beside a
hostile must be accepted) and confirms `RecoverySkill`'s own rest is still
blocked by the same adjacency under the same conditions.

Full patch review against the original fix-3 brief confirmed every other
requirement already present and evidence-justified, unchanged from note
0041's content: the 3.6.7 `major_hit_point_trouble` prayer predicate with
unchanged `PRAYER_FIRST_SAFE_TURN`/repeat-wait timeout tracking; the
floating-eye no-melee and gas-spore blast-radius movement rules (universal,
unaffected by the defect); retreat-or-known-stairs disengagement; the
bounded `REST_ACTION_LIMIT`-budgeted rest when hurt and no threat is
visible; and the `survival-reviewed-v3` cards (`threat-recovery-v3`,
`prayer-recovery-v3`, `stairs-recovery-v3`, `exploration-recovery-v3`), all
hash-verified against `manifest.survival-reviewed-v3.json` and already
covered by `test_reviewed_v3_prayer_and_rest_cases_agree_with_behavior`.
Nothing in the patch was found unjustified by evidence; nothing else was
removed.

**Methodology** (unchanged from note 0040/0041's protocol):
1. Run the 67-seed historical development set
   (`evaluation/unified-d5-regression-v2.json`, pinning
   `survival-reviewed-v3`) against the fixed candidate tree; compare against
   HEAD's qualified development result (52 objectives, 8 deaths, 1 hunger
   death, zero invalid actions/gate rejections).
2. Run a fresh 30-seed comparison between HEAD (`survival-reviewed-v2`) and
   the fixed candidate (`survival-reviewed-v3`) on seeds **91-120** — the
   next unused range in `evaluation/seed-ledger.json` after note 0041
   consumed 61-90. Seeds 61-90 are not reused.
3. Every suite runs as a long-lived background job with an explicit
   timeout large enough that no suite is cut short by tooling. If any run
   is cut short regardless, that sample is disclosed as spoiled and a new,
   not-yet-used seed range is drawn; a cut-short sample is never selectively
   resumed or partially counted.
4. Causally diagnose every lost success and new death.

**Acceptance** (note 0040/0041 bar, unchanged): fresh/dev objectives not
lower and deaths not higher than HEAD; zero starvation deaths; zero deaths
ending Weak or worse; zero invalid actions, gate rejections, or integrity
problems.

**Ship path**: if accepted, commit the fixed patch plus
`evaluation/unified-d5-regression-v2.json`, the `survival-reviewed-v3`
manifest and cards, tests, and docs together with this note's results. If
rejected, this note records the rejection only; no code ships.

## Iteration log: two further defects found and fixed before the final run

The `/tmp/fix3-candidate-v2.patch` candidate described above was run on the
preregistered dev set and on fresh seeds 91-120 (first attempt, spoiled by
an unrelated tooling 300-second background-job execution cap; re-run on
121-150, completed). The 121-150 run revealed a **second** defect: the
universal gas-spore proximity half of the split check correctly fired, but
`ExploreLevelSkill`'s search-spot selection (`_search`/`evaluate` in
`skills.py`) had no awareness of gas-spore blast radius and would commit to
a spot inside it, which the gate then hard-rejected (fresh seeds 127, 132,
144, 146; dev seeds unchanged at 703/1370/1376/1377/1379). Fixed by making
`_search`'s `evaluate` proactively exclude candidate spots within
`gas_spore_distance <= 2`, with a new regression test,
`test_search_never_selects_a_spot_within_a_gas_spores_blast_radius`.

Re-run on fresh seeds 151-180 (completed) revealed a **third** defect: the
scripted/real model's fallback path (`AgentCoordinator._fallback_plan`,
used whenever no deterministic skill proposes an action) has no
public-state awareness at all and could still choose a gas-spore-adjacent
`WAIT`/`SEARCH`; the gate correctly rejected it, but rejection stopped the
episode outright instead of trying a different fallback action (dev seed
703 and four seeds sharing its cause, 1370/1376/1377/1379; fresh seed 153).
Fixed by having `_fallback_plan` substitute the first otherwise-allowed
action the same `health_action_error` predicate accepts whenever the
model's chosen fallback action would be rejected, reusing the identical
shared predicate rather than a second copy. All nine previously affected
seeds were individually re-verified gate-clean in isolation
(`--suite` trimmed to one case/seed) before freezing a fourth candidate and
drawing an entirely new, not-yet-used fresh sample (181-210; seeds 91-150
are registered as consumed/superseded in `seed-ledger.json` and not
reused).

Patch `/tmp/fix3-candidate-v3.patch` is the result of all three fixes.

### Complete consumed-sample accounting

| Note / range | Fate and reason |
| --- | --- |
| 0041 / 61-90 | Rejected original candidate; HEAD completed 30/30 episodes, candidate completed 19/30 before tooling cut it short. All seeds reserved for this real-engine sample remain consumed. |
| 0042 / 91-120 | Spoiled first attempt: both arms cut short by the default tooling 300-second timeout. Not resumed or counted for the decision. |
| 0042 / 121-150 | Completed first superseded candidate (hostile-adjacency scoping fix only); revealed gas-spore-unaware search-spot choices. Superseded after changing that rule, not because failures were replaced. |
| 0042 / 151-180 | Completed second superseded candidate (search-spot avoidance added); revealed unsafe model fallback, including seed 153. The ledger commit calls this the “third superseded-candidate seed range”, counting the spoiled 91-120 attempt as well. Superseded after changing fallback selection. |
| 0042 / 181-210 | Completed final candidate with fallback substitution; rejected on objective regression and two remaining gate rejections. |

Every range remains consumed; none is reused as a new frozen sample.

## Final results (patch v3, seeds 181-210, dev set unified-d5-regression-v2)

### Dev set (67 seeds)

| | HEAD (qualified, note 0040) | Candidate v3 |
|---|---|---|
| Objectives | 52/67 | **50/67** |
| Deaths | 8 | 6 |
| Invalid actions / gate rejections | 0 | **0** |

Report: `/tmp/candidate-dev-v4/reports/unified-d5-regression-v2-development-20261004T075254Z.json`.
Zero gate rejections this time, but **objectives are lower than HEAD**
(50 < 52), which alone fails the preregistered acceptance bar. The five
seeds that used to be deaths (703, 1370, 1376, 1377, 1379) are now
`truncated` with 1,300-2,970 model-fallback decisions each (vs. 1-3 for a
normal episode): the fallback-substitution fix stops the gate rejection but
leaves the agent oscillating near the hazard for the full 3,000-step budget
instead of dying or progressing, converting five deaths into five
non-progressing truncations and netting fewer objectives than HEAD even
though no individual seed's classification looks obviously worse in
isolation.

### Fresh sample (seeds 181-210)

| | HEAD | Candidate v3 |
|---|---|---|
| Objectives | 23/30 | **18/30** |
| Gate rejections | 0 | **2** (seeds 190, 210) |

Reports: `/tmp/head-fresh-181/reports/fresh-181-210-head-development-20261004T075249Z.json`,
`/tmp/candidate-fresh-181/reports/fresh-181-210-candidate-development-20261004T075252Z.json`.

## Causal table (fresh 181-210, every seed whose outcome differs from HEAD)

| Seed | HEAD | Candidate | Diagnosis |
|---|---|---|---|
| 181 | death | truncated | Same non-success class; oscillates near a hazard to the step cap instead of dying. |
| 186 | objective_complete | truncated (2,541 model decisions) | Fallback-substitution loop: repeatedly offered and accepting a different "safe" action without making progress. |
| 190 | objective_complete | **stopped, gate-rejected** (`movement must not enter or remain in a displayed gas spore's blast radius`) | Rejection action source is **untraced**. [INFERENCE] A deterministic route-planned move may have collided with the new safety gate; the stored error alone does not establish its skill or source. |
| 192 | objective_complete | truncated | Same fallback-loop pattern as 186. |
| 202 | objective_complete | death | **Undiagnosed new death.** No trace-supported causal classification was completed; attributing it to unrelated divergence or disengagement is not justified. |
| 204 | death | truncated (1,429 model decisions) | Both arms fail the objective. [INFERENCE] High fallback counts suggest the same non-progress pattern as 186; HEAD did not complete this seed. |
| 205 | objective_complete | truncated (725 model decisions) | Same fallback-loop pattern as 186. |
| 206 | death | objective_complete | One genuine improvement: the goal-stair-retention behavior from the original fix-3 brief working as intended. |
| 209 | truncated | truncated | Same non-success class both arms. |
| 210 | objective_complete | **stopped, gate-rejected** (`search/wait must not idle beside a gas spore`) | Rejection action source is **untraced**. [INFERENCE] Another deterministic WAIT/SEARCH choice is possible, but neither a deterministic source nor exclusion of model fallback was established. |

## Decision: REJECT

Three real defects in this feature were found and fixed through this
iteration (hostile-adjacency over-scoping, gas-spore-unaware search-spot
selection, gas-spore-unaware model-fallback selection), each confirmed by
reproducing the exact failing seed in isolation before and after its fix.
Despite that, the **fourth** frozen candidate still fails the preregistered
bar on a freshly drawn, never-reused 30-seed sample and on the full dev
set:

- Dev-set objectives (50/67) are lower than HEAD's qualified 52/67.
- Fresh-sample objectives (18/30) are substantially lower than HEAD's
  23/30.
- Two fresh-sample gate rejections remain (seeds 190, 210). Their error
  messages establish movement and search/wait gas-spore safety collisions,
  respectively, but the rejected selections' sources were not traced.
  A fourth independent caller defect is [INFERENCE], not an established
  diagnosis.
- The fallback-substitution fix itself introduces a new failure mode —
  unproductive oscillation loops burning the full step budget — that is
  not an integrity violation but is a real behavioral regression visible
  in both the dev set and the fresh sample.

This is a pattern, not a sequence of unrelated one-off bugs: every
component that can choose a `WAIT`/`SEARCH`/move action needs independent
gas-spore (and, by the same argument, floating-eye) awareness, because the
shared `health_action_error` gate is a *terminal* hard-reject with no
generic retry path, and ad hoc per-caller fixes keep surfacing one caller
at a time under live evaluation rather than closing the class. Shipping
this now would trade the original problem (goal stairs abandoned during an
escape) for a worse one (episodes that silently stop or burn their entire
step budget near ordinary gas spores, which are far more common than the
specific escape scenario fix 3 targeted).

`main` remains unchanged by this note (still at the reverted,
note-0041-qualified state). The final patch is preserved only as
`/tmp/fix3-candidate-v3.patch`, not committed. Shipping this feature needs
either a single, consistently-applied gas-spore/floating-eye-aware routing
primitive used by *every* action source (deterministic skills' route
planning, search-spot selection, and model fallback alike), or a non-fatal
retry path in the coordinator for any gate rejection, plus a fix for the
fallback-substitution oscillation loop — not another narrowly-targeted
per-caller patch. A future attempt should design that primitive first,
then re-run this exact qualification protocol on a fresh, unused seed
range (the next one is 211-240; seeds 61-210 are now registered as
consumed in `seed-ledger.json` across notes 0041 and 0042).

Seeds 181-210 (this final, non-shipped candidate's run) are registered in
`seed-ledger.json` as consumed.
