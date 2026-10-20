# 0056: Roadmap consolidation

Date: 2026-10-19

The full pre-consolidation `TODO_LIST.md` is in git history at the commit before this change. This note preserves roadmap-only facts and diagnosis removed from the active checklist; it does not claim new qualification or rerun any evaluation. Fixed-string `git grep -F` checks against notes, ADRs, README, architecture and development docs located the existing evidence linked below; unmatched details are retained here.

## Milestone 1 and milestone 2

Milestone 1 delivered typed observation, decision, action, run-state and event contracts. Its implementation and acceptance history remain in notes [0003](0003-deterministic-nle-adapter.md), [0004](0004-agent-loop-storage-and-control-api.md), [0005](0005-reviewed-knowledge-cards.md), [0006](0006-staircase-evaluation-suite.md), [0007](0007-exploration-policy-and-staircase-acceptance.md), and [ADR 0001](../decisions/0001-initial-product-and-runtime.md). Milestone 2's original acceptance and remediation results remain in [0036](0036-milestone-2-real-model-evaluation.md), [0038](0038-branch-exit-frontier-preserving-probes.md), [0040](0040-causal-hidden-detour-qualification.md), [0043](0043-single-rule-prayer-qualification.md), [0044](0044-single-rule-hazard-qualification.md), [0045](0045-three-single-rule-qualification.md), and [0046](0046-descend-d5-v2-real-model-acceptance.md).

The old roadmap explicitly moved the D5 retry into milestone 3: the Oracle target on Dlvl 5-9 subsumes reaching D5. Exit-discovery stalls, combat without prayer, ranged rule 3 and the prayer interval remain milestone-3 work rather than a separate retry. The paused rule-3 code was withdrawn from `main` at `086f61e`.

## Milestone 3 — order of work and Phase 0 tooling

- The 2026-10-06 order was parallel evaluation/evidence records, hunger live-lock/food reserve, branch staircase identity/stall breaker, then the rest. On 2026-10-18, after the hunger fix shipped, user feedback moved step-history maps and speed limiting ahead of food reserve to accelerate diagnosis. The 2026-10-19 order supersedes both: disengage/rest, then requalify stall budget 0054, then an optional ADR 0007 gate amendment; tooling may run alongside.
- The completed `omp_commit.py` guard refuses staged `nethack-agent/src` changes unless a staged note records a qualification decision or the commit message carries the documented exemption trailer.
- Parallel evaluation of `unified-d5-regression-v4` measured **1,449 s sequential versus 395 s at 10 workers**, with identical per-seed results and action sequences on **67/67 seeds**. CPU contention and SQLite connection churn limited speedup. Thread-safe RunStore connection reuse remains open.
- Detached suite runs have a completion marker so a tool deadline does not cut them short. Whole-process-group stopping was open at consolidation. It shipped on 2026-10-19 as `detached_eval.py [--state-dir DIR] stop NAME [--timeout S] [--force]`, with PID-identity checks and whole-process-group signals ([skill](../../_agents/skills/detached-eval/SKILL.md)).
- Evidence-record tooling is `_agents/skills/evidence-record/`; note 0050's compact per-seed records were backfilled under `docs/notes/evidence/0050/`, with raw data at `~/nethack-evidence/0050/`. The record includes case, seed, outcome, steps, turns, death cause, hunger, deepest level, failure class, plus commit, suite, model and command.
- Completed step-history selection uses each stored step's full observation, not reconstruction. Attachment loads only the last 50 events and the list retains 300, so earlier steps of long runs are not selectable. Current behavior is documented in [development](../development.md#browser-ui).
- Completed `resume` speed limiting is per run, live-changeable via API, CLI and browser, and uses interruptible waits. It defaults to unlimited; pacing is in-memory only and does not alter gameplay events.

## Milestone 3 — Phase 1 objectives

[0050](0050-phase1-objectives-baselines-detector-audit.md) records shipped objective/planner/conduct support, detector audits and baselines. Oracle recognition currently requires seeing the Oracle herself; centaur statues, fountains, sounds and Sokoban up-branch avoidance remain open (the up-branch occurs on the level below the Oracle, Dlvl 6-10).

The proposed replacement for the wall/door/bar Minetown counter is public altar evidence on Mines level 3 or 4 reached through the recorded branch crossing, or a priest's temple greeting. The roadmap's source rationale is NetHack 3.6.7 `mines.des`: every Minetown variant has an altar, filler and Mines' End levels have none. Qualify separately after the shipped hunger fix.

## Milestone 3 — Phase 2 navigation candidates

- Exit diagnosis includes the milestone-2 seeds plus **2064852799** and **249447619**. The generic stall breaker must change strategy when a fixed level turn budget expires with no goal exit, or a never-melee monster blocks the only route (seed 6's floating eye corridor). Options include other known exits, branch detours, broader search or another goal; fix the budget from probes.
- Unqualified branch `rule-0054-no-progress-budget`, evidence `~/nethack-evidence/0054/candidate/STATUS.md`: persistent no-progress budget that model rearm cannot refill, coverage-ranked search rotation and goal-compatible routing after budget exhaustion. Probes escaped stalls, but **5 of 10 seeds changed from truncation to death**; **4 of 7 rerun deaths were Weak or worse**. Before qualification, fix the `stuck_consult_step` crash and replay check rejecting periodic stuck re-consultation; after disengagement, choose T=200 versus T=400 from probes and requalify.
- Ranged gas-spore/floating-eye rule 3 from [0045](0045-three-single-rule-qualification.md) must be rebuilt: its saved `/tmp` patch was lost in a host restart. Partial changes survive in `efe58e3`, `cad9108`, `87f74de` (reverted by the rule-3 disposition). Rebuilt but unqualified branch `rule-0053-ranged-clearance` has evidence at `~/nethack-evidence/0053/candidate`. It was paused before qualification because the hero held exactly one dagger at all **156 blocker visits** in the 0051 runs; **7 probes produced 3 throws and no confirmed kill**. An ammunition source is needed first.

## Milestone 3 — Phase 3 survival diagnosis

The 2026-10-19 analysis covered **148 baseline deaths** plus the unqualified stall-budget candidate. This is diagnosis only; scripts/data are at `~/nethack-evidence/0055-death-analysis/`. Deeper levels expose a weak hero (median XL 3-5, AC 6) still meleeing at low HP while prayer is on cooldown; late stall escapes deliver it there starving.

- **34/95** non-hunger deaths had a last decision at **14-33% HP**; **18/21** mid-fight prayers healed the hero ("You feel much better."), who re-engaged and died **4-34 turns** later (recounted from `evidence/0055/scripts/prayers.py`; first reported as 17/21); **12** entered the fatal fight below **50% HP**.
- **65/75** named killers respect Elbereth. Stair flight alone rarely helps: **30/71** healthy-entry deaths had a faster hostile nearby; **13** had a known upstairs within **10 steps**.
- Proposed rule: below about one-third HP with prayer unavailable, or immediately after prayer with the same attackers present, stop meleeing; engrave Elbereth through a new gated action/text-input contract and rest to about **70-80% HP**. Against Elbereth-ignoring attackers (`@` humans, minotaurs), retreat toward a corridor or known stairs. Without a visible threat, rest before wandering below **50% HP**. Verify 3.6.7 Elbereth source rules before design.
- Healing costs about **170 turns** per heal (`allmain.c:505`); food remains a constraint until stalls stop consuming it.
- Optional ADR 0007 amendment: keep objectives nondecreasing but align the per-rule death gate with milestone acceptance (starvation and Weak-or-worse deaths nonincreasing). This would **not** rescue measured 0054: 4 of its 7 new deaths were Weak or worse.
- Lycanthropy evidence currently only stops jackal/fox/coyote corpse eating; seed 6's cure came from prayer for another reason. Public infection message is “You feel feverish.” NetHack 3.6.7 prayer semantics are confirmed: `src/pray.c:207-208` checks `if (u.ulycn >= LOW_PM) return TROUBLE_LYCANTHROPE;` in the major-trouble block after `critically_low_hp`; `src/pray.c:466-467` handles `case TROUBLE_LYCANTHROPE: you_unwere(TRUE);`. The cure message is “You feel purified.” in `src/were.c`. Vault-guard compliance after involuntary relocation is motivated by seed 1377.
- Compact per-death record (148 baseline and 7 candidate rows, regeneration scripts and commands): [evidence/0055/](evidence/0055/).

## Milestone 3 — Phase 4 food

The qualified ration fix is in [0051](0051-ration-livelock-qualification.md). Its Minetown seed 1362 now stalls on Dlvl 2; Oracle seed 6 needs blindness handling. [0052](0052-canonical-slime-mold-qualification.md) rejected the slime-mold reserve rule; the roadmap attributed hunger deaths to long stalls. Food-reserve work must measure turns per level against the food horizon, collect non-shop floor food while unburdened and eat before long stalls.

## Robust dungeon play (ADR 0004)

The original dependency order was traversal goals → NLE task suites → evidence-gated skills → model-owned choices. Shipped traversal, prompt/hunger skills and Scout/Eat history remain in [0015](0015-typed-traversal-goals.md), [0016](0016-evidence-gated-survival-skills.md), [0017](0017-scout-and-eat-task-suites.md) and [ADR 0004](../decisions/0004-traversal-goals-and-task-progression.md).

- The completed typed episode-metrics item covered gold, score, task return, hunger and worst hunger, explored cells, HP/XL and death cause; typed metric thresholds are fixed before a run, and metric-gated cases may require no objective success. ADR 0004 §7 and note 0017 document the component contracts.
- At `94e3180`, strict `approach_oracle` goal/token `approach_oracle:<dnum>:<dlevel>` and `find_oracle` leg contracts existed, but `NetHackOracle-v0` was unsupported and the planner refused `find_oracle`. This planner restriction is historical, superseded by milestone 3's shipped Oracle planner.
- At `7c71d7a`, `hierarchical-task-specialists-v1` added deterministic `NetHackGold-v0` navigation to the nearest reachable displayed gold under `pickup_types:$`; `gold` intents were audited against the decided-on observation's gold glyph. This was not a completed `gold-v1` suite.
- Close the typed-traversal parent and prompt-handler parent: their listed implementation items shipped. Merge general evidence-gated navigation/combat/hunger/inventory work into active milestone 3 and roadmap A-H; prompts still ship with their causing actions (ADR 0004 §8).
- Close legacy NLE `oracle-v1` suite/navigation work as superseded by milestone 3's Score/survival Oracle objective and acceptance suite (ADR 0006/0007). Defer the separate `gold-v1` benchmark: navigation exists, but unified place-reaching evaluation, not an NLE Gold reward suite, is current scope.
- Defer Laya runtime evaluation and [FlyEM male CNS connectome research](https://www.janelia.org/project-team/flyem/male-cns-connectome): neither is a milestone-3 survival/navigation prerequisite; [0013](0013-review-feedback-resolutions.md) retains the research context. Defer model-owned choices until after milestone 3, per ADR 0007; ADR 0004 §8 retains the minimum multi-goal decision-point count, paired arbiter/model arms (model three times), pre-registered metric, bootstrap intervals, latency/tokens and no-extra-deaths ownership gate.
- Retain replay comparison/aggregate diagnostics under Phase 0 rather than treating the existing replay audits as a completed comparison UI/tool.

## Development tooling and browser UI

`omp-commit` resolves the active conversation from its **OMP ancestor process**, so commits work while several OMP sessions run. [0013](0013-review-feedback-resolutions.md) records the original skill, live-evidence resolution, trailer normalization and pre-commit checks; this ancestor-process detail was only in the roadmap.

The completed controller split assigns main run control, DOM/panel behavior, event logs and rendering to separate modules; full ability labels and accessible BUC evidence cues ship (architecture and development guide). UI notes [0009](0009-ui-agent-information-redesign.md)–[0012](0012-planned-path-overlay.md) and [0018](0018-agent-column-viewport-fit.md) retain completed layout, messages, pet/glyph rendering, destination/attack/path overlays, frontier route reuse and viewport fit.

Close the stale “persisted events selectable” item: shipped Phase 0 history selection covers map, player, inventory, observation and recorded intent/path for retained events. Earlier-event fetching is still limited by the 50/300 bounds above. Real tool/script execution records, automated browser layout/overlay/focus/tooltip tests, own-cell destination boxing and path-divergence/unfollowed-route evidence remain open, now grouped in Phase 0.
