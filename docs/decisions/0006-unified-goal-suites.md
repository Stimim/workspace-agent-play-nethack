# ADR 0006: Unified location-goal evaluation suites

- Status: proposed
- Date: 2026-10-04
- Supersedes: ADR 0004's environment/action-profile coupling for evaluation and ADR 0005's heterogeneous regression acceptance. Their committed suites and reports remain immutable historical evidence.

## Context

The agent's durable purpose is to reach places in the dungeon. Staircase, traversal, Scout, Eat, and D5 suites have measured different NLE tasks and action profiles even though they exercise one explorer policy with the same skills: eating, praying, safe-corpse eating, fighting, exploring, and kicking. That split withholds survival behavior on Scout and Eat, conflates task reward with navigation, and makes regressions incomparable. Development now has one setup that runs all historical seeds on `NetHackScore-v0`, `nle-survival-actions`, and `reach_level(0,5)`; the retained original baseline is 50/67 successes, seven deaths, one hunger death, and ten truncations (note 0038). The frontier-preserving candidate is 52/67, with eight deaths and one hunger death; this is development evidence, not real-model milestone acceptance.

## Decision

1. **One policy and skills.** Every evaluation task is a location goal executed by the same coordinator and full survival action profile. Use `NetHackScore-v0` with `nle-survival-actions` unless the goal requires a task-specific NLE environment. Action profile is a policy capability, not a task restriction. Keep old profile values readable so existing policy-pinned suites, stored TaskSpecs, and reports continue to validate and render byte-identically; new evaluation suites do not restrict the policy to those profiles.
2. **Staircase is a sub-goal.** `NetHackStaircase-v0` ends successfully as soon as NLE detects the hero on its first qualifying downstairs, and does not permit the episode to continue toward D5. Standing on any downstairs is therefore a sub-goal of reaching D5, not a distinct objective whose environment should constrain the policy. Keep the old Staircase suite as immutable evidence; express new location evaluation on Score.
3. **Historical development regression.** `evaluation/unified-d5-regression-v1.json` runs the same Score/survival/reach-D5 setup on the 67 unique seeds from staircase 1-10, traversal 700-704, Scout 900-904, Eat 920-924, catalog-only 53 and 824, the 20 fresh seeds from the committed `descend-d5-v1` report, and note 0035 probes 1360-1379. Deduplicate overlaps. The aspirational development target is **67/67**; the suite is a tracking suite, not a commit gate. Its per-case display success floor is the loader's minimum of one, not a shipment criterion; global invalid actions, gate rejections, and incomplete records remain unacceptable.
   The active runner is `unified-d5-regression-v2.json`, preserving exactly those 67 seeds and setup while pinning `survival-reviewed-v3`; committed v1 remains immutable.
4. **Next milestone's fresh acceptance.** A new acceptance suite must draw fresh seeds against the used-seed ledger, declare its success-rate threshold before running, and explicitly require zero starvation deaths and zero deaths whose last live hunger state is Weak or worse (`hunger_at_death <= Hungry`). These fresh-draw gates, not the 67 historical cases, decide the next milestone. Do not relabel or replace old suites, reports, or policy evidence.
5. **Same active capabilities.** Remove artificial TaskSpec restrictions coupling Scout/Eat/other supported environments to a profile. Keep objective/environment validity rules and real engine success semantics intact. Older `nle-task-actions` and `nle-hunger-actions` TaskSpecs remain valid because historical artifacts depend on their exact action tables; allowing them is compatibility, not an active evaluation recommendation.

## Consequences

- Active evaluation measures whether the same survival-capable explorer reaches places across a broad, paired development history.
- Historical suites and reports retain their original tasks, profiles, thresholds, and interpretation; they are not retroactively scored as unified-policy results.
- The 67-seed score is a diagnostic target and cannot block commits. The small fresh-draw acceptance suite carries predeclared objective and hunger-death gates for milestone decisions.
- Task-specific environments remain available only where their engine semantics are required; currently Staircase's early terminal success is exactly why it is not suitable for a D5 objective.
