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
