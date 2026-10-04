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

## Disclosure: aborted first launch

The first launch (report stamp `20261004T173647Z`, draw seed `3519210030`)
was started without an explicit tool deadline. It was cancelled seconds in,
while episode 1 of 20 (seed 1187627742) was still running, so no episode
result was observed. Its incomplete report and data are kept outside the
committed report directory at
`nethack-agent/data/evaluations/descend-d5-v2-aborted-20261004T173647Z/`
(ignored by Git). All 20 of its drawn seeds are registered in the used-seed
ledger and never reused. The acceptance run below is a complete new draw
under the unchanged preregistration, launched with no deadline; it is not a
selective resume.

## Disclosure: aborted second launch

The second launch (report stamp `20261004T173934Z`, draw seed
`2937289252`) again ran under the shell tool's
default 300-second deadline, shorter than the ~470-second previous D5 run.
It was cancelled to avoid a mid-run cutoff, but only after episode 1 had
finished: seed 1980000625, `objective_complete` in 366 steps. That was the
only observed result; the cancellation was for a tooling reason and was
not a reaction to an unfavorable outcome. Its report and data are kept at
`nethack-agent/data/evaluations/descend-d5-v2-aborted-20261004T173934Z/`, and all 20 drawn
seeds are registered in the ledger and never reused. The acceptance run is
the third launch, detached from any tool deadline.

## Acceptance run (third launch): FAILED on the hunger gate

Command (from `nethack-agent/`, detached with `setsid nohup`, no deadline):
`uv run nethack-agent eval run --suite evaluation/descend-d5-v2.json --data-dir data/evaluations/descend-d5-v2 --report-dir evaluation/reports`.
Report `evaluation/reports/descend-d5-v2-20261004T174004Z.{json,md}`,
status complete, draw seed `661147380` (documented
random default), 20 fresh seeds automatically excluded from future draws.
Preflight at `086f61e`: `doctor` OK (NLE; Ollama 0.34.4,
`gemma4-nethack:latest`), `ollama ps` showed only `gemma4-nethack:latest`
(3.2 GB, 100% GPU, context 8192), GPU 5696/8188 MiB.

| Gate | Result |
| --- | --- |
| Success rate >= 0.65 | **16/20 = 0.80, pass** |
| `starvation_death` sum <= 0 | 0, pass |
| `hunger_at_death` maximum <= 2 | **4 (Fainting), fail** |
| Invalid actions / gate rejections / complete records | 0 / 0 / complete, pass |

Outcomes: 16 objectives, 2 deaths, 2 truncations; 21,301 steps, 588.6 s
episode wall time. 154 model decisions,
none failed or repaired, latency p50/p95/max
1097/1392/1460 ms;
selection sources: 21,204 deterministic skill, 97 deterministic prompt, 0
model fallback.

| Seed | Outcome | Steps | Death cause | Hunger at death | SEARCH steps |
| ---: | --- | ---: | --- | --- | ---: |
| 1987814290 | objective_complete | 733 | — | — | 1 |
| 1213151840 | objective_complete | 1423 | — | — | 846 |
| 340697573 | objective_complete | 319 | — | — | 0 |
| 1507056209 | objective_complete | 559 | — | — | 0 |
| 337773271 | objective_complete | 608 | — | — | 4 |
| 2059028023 | objective_complete | 1094 | — | — | 72 |
| 178234322 | objective_complete | 280 | — | — | 6 |
| 442930654 | objective_complete | 1476 | — | — | 297 |
| 758990772 | objective_complete | 659 | — | — | 0 |
| 1536412837 | objective_complete | 1348 | — | — | 51 |
| 1420394012 | objective_complete | 819 | — | — | 34 |
| 1768159875 | objective_complete | 420 | — | — | 9 |
| 2005928350 | objective_complete | 164 | — | — | 0 |
| 1034991231 | truncated | 3000 | — | — | 202 |
| 245658383 | objective_complete | 922 | — | — | 0 |
| 249447619 | truncated | 3000 | — | — | 1901 |
| 1036106856 | objective_complete | 392 | — | — | 0 |
| 2064852799 | death | 2816 | killed by a giant bat | fainting | 223 |
| 1624140803 | objective_complete | 830 | — | — | 2 |
| 559341345 | death | 439 | killed by a bolt of fire | not_hungry | 0 |

### Failure analysis

**2064852799 (the gate failure).** The hero reached main Dlvl 3 at turn 74
and spent 2,741 of 2,816 steps there: 1,806 steps routing to frontiers and
846 to search spots. It descended the Gnomish Mines branch once and returned
for the main goal, but never found the main downstairs. Nutrition worked as
designed until it ran out: a ration at turn 734 (interrupted, later finished
at 1465), fox and gecko corpses, and a successful Weak prayer at turn 1900.
Hungry again at 2634 and Weak at 2734, 834 turns after that prayer and
inside the conservative 1,229-turn repeat bound, with no food left; it
fainted at 2792 and a giant bat killed it. Classification: a level-exit
discovery stall that outlasted the food and prayer budget, the same class
as the earlier truncations. True-map ground truth was not taken
[INFERENCE for the precise blocker].

**559341345** died to a bolt of fire on Dlvl 3 while Not Hungry (combat).
**249447619** truncated on Dlvl 2 with 1,901 SEARCH steps (exit-discovery
stall). **1034991231** truncated with deepest level in the Mines.

### Verdict

`descend-d5-v2` **failed** milestone acceptance on its zero
Weak-or-worse death gate; the success-rate gate passed with margin. This
report is retained unchanged. Per ADR 0006, a retry needs a new qualified
policy version and a new draw. The dominant remaining failure class, across
this run and the 67-seed development set, is exit discovery on a level whose
main downstairs is hidden or blocked, which then converts into hunger once
the stall exceeds the food and prayer horizon.

Rendering-only correction, as in note 0036: the generated Markdown listed
`steps_by_skill` in run order, while the persisted JSON sorts those keys. The
committed Markdown was re-rendered from the untouched JSON with
`render_report_markdown`; only the skill order inside 20 table rows changes.
The original generated file is kept at
`/tmp/descend-d5-v2-20261004T174004Z-original-generated.md`.
