# 0046: descend-d5-v2 real-model acceptance

## Preregistration (frozen before any episode)

Date: 2026-10-05. Milestone 2's acceptance, restated under
[ADR 0006](../decisions/0006-unified-goal-suites.md): the first committed
real-model run of `nethack-agent/evaluation/descend-d5-v2.json` decides it.
A failed run is kept; a retry needs a new policy version and a new draw.

- **Frozen policy:** `hierarchical-survival-hp-prayer-burden-look-v1` at
  `086f61e` (low-HP prayer, burden recovery, look-here stairs; the rule-3
  throw candidate is withdrawn, note 0045). Bundle `survival-reviewed-v2`.
  Model `gemma4-nethack:latest`, `num_ctx` 8192, loopback Ollama only.
- **Task:** `NetHackScore-v0`, `nle-survival-actions`, `reach_level(0,5)`,
  cap 3000, lawful dwarven Valkyrie.
- **Draw:** 20 fresh seeds from `[1000000, 2147483647]` by the documented
  random default (no `--draw-seed`), excluding every used seed.
- **Gates:** success rate at least **0.65**; `starvation_death` sum at most
  0; `hunger_at_death` maximum at most 2 (no death while Weak or worse);
  zero invalid actions and gate rejections; complete records.
- **Threshold derivation:** the frozen note 0035 rule (probe success rate
  minus 0.15, rounded down to a multiple of 0.05, never below 0.5) applied to
  all 120 fresh scripted development episodes run on exactly this policy:
  391-420 (rule-2 candidate) 18/30, and the `5536c7d` baseline arms of
  421-450 26/30, 451-480 27/30 and 481-510 28/30. Pooled 99/120 = 0.825,
  giving 0.65. No historical suite seed is in the acceptance sample; the 67
  historical seeds are tracked by `unified-d5-regression-v4`.
- **Known risk, stated before running:** those 120 episodes contained two
  deaths while Fainting (406 newt, 446 cave spider). At that rate a 20-seed
  draw has roughly a 30% chance of at least one hunger death, which fails
  the gate. The gate is not loosened for that.
- **Single run:** no rerun, retry, or replacement. A tooling cutoff is
  disclosed and spoils the run; it does not license a selective resume.
