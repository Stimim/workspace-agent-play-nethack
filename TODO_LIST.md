# Roadmap

This file tracks product work. Completed work and reasoning belong in `docs/notes/`; durable choices belong in `docs/decisions/` and `ARCHITECTURE.md`.

## Done: milestone 1 — Staircase agent (accepted)

Acceptance: the fixed local policy succeeds on at least 6 of 10 committed deterministic `NetHackStaircase-v0` seeds, including seed 6, with no invalid NLE actions and complete SQLite plus ttyrec replay data.

- [x] Define typed observation, decision, action, run-state, and event contracts.
- [x] Implement the NLE adapter with lawful dwarven Valkyrie, deterministic seeds, ttyrec capture, and explicit legal actions.
- [x] Build observation projection for map, player statistics, messages, prompts, and inventory.
- [x] Build the hierarchical coordinator and deterministic action gate.
- [x] Add structured Ollama output, one repair retry, then pause-on-failure behavior.
- [x] Curate the first local-model knowledge cards from cited NetHackWiki pages.
- [x] Add SQLite run/event storage and artifact layout.
- [x] Add the loopback HTTP control/status API and WebSocket event stream; make start, pause, step, stop, and observation usable by both coding-agent tools and the browser.
- [x] Add headless scenario commands that launch the service, submit validated run configurations, wait for state transitions, and stop runs gracefully.
- [x] Add the dependency-light browser UI: map, status, inventory, structured decisions, and start/pause/step/stop controls.
- [x] Commit the 10-seed evaluation suite, including seed 6, with an `eval run` harness that audits SQLite and ttyrec integrity.
- [x] Report per-seed outcomes and latency for the complete suite with the local model.
- [x] Meet the milestone acceptance gate on the complete suite.
- [x] Verify gameplay performs no non-loopback network requests.

## Done: milestone 2 — Survive the early dungeon (evaluated; acceptance failed)

Goal: reach Dungeons of Doom level 5 without hunger deaths. Design: [ADR 0005](docs/decisions/0005-early-survival-and-seed-evaluation.md) (accepted as implemented and evaluated). The milestone suite passed 18/20 fresh episodes with no fresh hunger deaths, but the full milestone acceptance failed its traversal and Eat regression gates ([0036](docs/notes/0036-milestone-2-real-model-evaluation.md)).

Acceptance is judged on the first committed real-model run of the milestone suite. A failed run is kept; a retry needs a new policy version and a new seed draw.

- Suite `descend-d5-v1` (suite schema 3): `NetHackScore-v0`, a survival action profile (task actions plus eating, PRAY, and prompt keys accepted only as offered answers), objective `reach_level(0, 5)`, and a step cap fixed from held-out probes (at least 3,000).
- Fresh sample: 20 seeds drawn per run from a declared range, excluding every seed in the used-seed ledger; the report records the draw seed and the drawn seeds before the first episode. Pass: at least 50% reach the objective (probes may only raise this), zero starvation deaths, and zero deaths while Weak or Fainting.
- Baseline: every representative-seed catalog entry for the suite's task runs in the same report. No `must_pass` entry may regress; `known_failure` changes are reported with a paired per-seed diff against the previous report.
- Suite-wide: zero invalid actions and gate rejections, complete records, and every prayer replayed by the evaluator against the gate's predicate.
- Regressions under the new policy: the staircase cases pass 10/10; the traversal cases meet their original thresholds, including `enter-mines` at least 2/5; Scout and Eat thresholds are no worse than `scout-v1` and `eat-v1`.
- Unchanged: `gemma4-nethack:latest`, `num_ctx` 8,192, offline gameplay, and immutable committed suites and reports.

Work, in order:

- [x] Representative-seed catalog: strict `evaluation/representative-seeds.json` rendered to `representative-seeds.md` (seed, task, cap, represented behavior, provenance, `must_pass` or `known_failure`, linked test). Seed it from existing evidence: 6; 5; 1, 2, 4; 4 and 7; 53; 701 and 702; 824. Add a scripted-model catalog check that asserts outcome class and key invariants, not step counts ([0020](docs/notes/0020-representative-seed-catalog.md)).
- [x] Used-seed ledger covering committed suites, probes, development runs, and the catalog.
- [x] Suite schema 3 (a baseline case from the catalog and a `fresh_sample` block) and report changes (draw provenance, separate baseline and fresh-sample acceptance, paired baseline diff). Schemas 1-2 and existing reports stay readable and unchanged ([0022](docs/notes/0022-suite-schema-3-fresh-samples.md)).
- [x] Failure diagnostics: per-episode steps by skill and by search, first Hungry turn, and a `hunger_at_death` metric; a note analyzing the 18 Fainting episodes ([0023](docs/notes/0023-early-hunger-failure-diagnostics.md)).
- [x] Reviewed, cited knowledge cards for prayer and hunger and for safe corpse eating (`survival-reviewed-v1`, not yet active; [note 0024](docs/notes/0024-reviewed-survival-knowledge.md)).
- [x] Survival action profile and gate roles: PRAY, eating, and the prayer and eating confirmations accepted only as offered answers; the evaluator audits them with the same predicate. Item 6 kept PRAY blocked pending the deterministic skill ([note 0025](docs/notes/0025-survival-action-profile-and-prayer-gate.md)).
- [x] Deterministic prayer skill: pray when Weak and the tracked prayer timeout is safe; record the prayer, observed kill-message proxy, and outcome in the intent ([note 0026](docs/notes/0026-deterministic-prayer-and-probe-evidence.md)).
- [x] Corpse eating: eat only fresh, identifiable corpses of observed kills on the five-species reviewed safe list; decline everything else ([note 0027](docs/notes/0027-safe-fresh-corpse-eating.md)).
  - Corrected corpse-meal lifecycle and hunger-death diagnosis ([0029](docs/notes/0029-corpse-meal-lifecycle-and-hunger-death-diagnosis.md)).
  - Recovered missed nutrition and widened reviewed fresh corpses: ration
    description variants, non-shop floor-food collection, lichen's nonrotting
    exemption and pet-moved identification, and garter snake, hobbit, goblin,
    iguana, shrieker, jackal, fox and coyote absent lycanthropy evidence
    ([0033](docs/notes/0033-reviewed-nutrition-probes.md)).
- [x] Exit discovery: kick known locked gates on route, search beyond open doors, check object-covered cells; preserve shop, main-dungeon, HP, hunger, and retry safeguards, and audit kicks with the same predicate.
  - SEARCH caps did not qualify ([0028](docs/notes/0028-bounded-search-probes.md), [0030](docs/notes/0030-post-fix-bounded-search-probes.md)); native diagnosis and qualified exit-discovery comparison: [0031](docs/notes/0031-exit-discovery-probes.md).
  - Frontier-first covered-cell fallback and cycle corrections did not
    qualify paired with the reviewed nutrition package ([0032](docs/notes/0032-exit-discovery-correction-probes.md),
    [0033](docs/notes/0033-reviewed-nutrition-probes.md)).
- [x] New policy version, held-out probes, committed suites, one real-model run, and docs (`ARCHITECTURE.md`, `README.md`, development guide, a note); mark ADR 0005 accepted ([0036](docs/notes/0036-milestone-2-real-model-evaluation.md)).

Out of scope: Oracle navigation and the `gold-v1` and `oracle-v1` suites (milestone 3 candidates), retreat, rest, or HP-based prayer unless probes show HP deaths, and model-owned choices.

## Now: milestone 2 acceptance remediation

- [x] Diagnose every existing milestone-2 seed under one Score/survival/
  reach-D5/cap-3000 setup: 50/67 objectives before remediation.
- [x] Qualify goal-aware branch-gate and covered-exit discovery while preserving
  ordinary reachable frontiers: development 50→52/67 with no previous success
  lost; frozen qualification 24→27/30, deaths 2→2, hunger deaths 0→0
  ([0038](docs/notes/0038-branch-exit-frontier-preserving-probes.md)).
  The first candidate failed its death gate and remains recorded
  ([0037](docs/notes/0037-goal-aware-branch-gate-probes.md)).
- [x] Unify new place-reaching evaluation on one survival policy,
  `NetHackScore-v0`, and `nle-survival-actions`; keep historical suites and
  reports immutable. Add `unified-d5-regression-v1` with 67 unique seeds and a
  non-blocking 67/67 development target ([ADR 0006](docs/decisions/0006-unified-goal-suites.md)).
- [x] Qualify hidden-passage/search/boulder-detour handling under the revised
  causal protocol: retained development 52→52/67, deaths 8→8, fresh 17→20/30,
  deaths 7→6; all required losses are pre-existing failure classes reached
  after trajectory divergence ([0040](docs/notes/0040-causal-hidden-detour-qualification.md)).
- [x] Qualify low-HP prayer alone using the actual 3.6.7 major-trouble predicate
  and unchanged public timeout bounds: dev 52→54/67, deaths 8→5; fresh
  25→29/30, deaths 4→0 ([0043](docs/notes/0043-single-rule-prayer-qualification.md)).
- [ ] Qualify HP/threat-aware recovery: current 703 gas-spore explosion, 1379
  homunculus, 1377 involuntary vault relocation/guard handling, and low-HP melee.
- [ ] Resolve remaining hidden-exit failures 5/701; preserve the retained
  1376 hunger/prayer investigation even though its current run dies earlier
  to a goblin. Reconcile the ADR's prayer interval with code before changing it.
- [ ] After qualified fixes, run a new fresh-draw milestone suite with declared
  objective-success and explicit zero-starvation/zero-Weak-or-worse death gates.
  Never replace the first real-model reports or relabel historical suites.


## Robust dungeon play (ADR 0004)

Remaining ADR 0004 items. Survival, prayer, corpse eating, bounded search, and failure diagnostics moved to milestone 2.

Dependency order for the four capability items below: traversal goals, then NLE task suites, then evidence-gated skills, then model-owned choices ([ADR 0004](docs/decisions/0004-traversal-goals-and-task-progression.md)).

- [ ] Add replay comparison and aggregate run diagnostics.
- [ ] Add bounded navigation, combat-risk, hunger, inventory, and prompt-handling skills as evidence requires.
  - [x] Combat risk: fight a safe-to-melee adjacent hostile before waiting on or traversing stairs; baseline seeds 1, 2, and 4 supplied the evidence. Retreat, rest, and weapon rules remain evidence-gated.
  - [x] Hunger: `nle-hunger-actions` adds only ESC and deduplicated inventory letters to `TASK_ACTIONS`; eat an exactly recognized inventory ration at Hungry or worse and answer its matching item prompt.
  - [x] Covered stairs: recognized from look-here messages as part of traversal memory (seed 5).
  - [ ] Prompt handlers ship with the actions that cause them:
    - [x] Inventory-ration item selection and conservative decline of unverified floor-food `eat it?` prompts.
    - [x] Exact-name fresh-corpse floor confirmation and conservative decline of every other corpse offer.
  - [ ] Navigation and general inventory skills only after a failure class recurs in traversal or task-suite evidence.
- [ ] Evaluate whether Laya improves routine action ranking enough to justify another model runtime.
- [ ] Survey the [Janelia FlyEM male CNS connectome](https://www.janelia.org/project-team/flyem/male-cns-connectome) and define a bounded, evidence-driven comparison of any connectome-inspired planning or action-ranking approach against current baselines; this is research, not a production commitment.
- [ ] Replace the fixed downstairs-only milestone goal with typed traversal goals that can select upstairs, downstairs, and a branch-specific staircase identity; extend memory, intents, and evaluation cases before allowing level changes.
  - [x] Typed `TaskSpec` (NLE task, action profile, objective legs) selected per run; fix step caps above 5,000 (NLE cap above `TimeLimit`); `runs.task` column.
  - [x] Typed `Goal` union (`stand_on_stairs`, `traverse_stairs` with direction and main/branch target) replacing the enum; legacy `stand_on_downstairs` reads exactly.
  - [x] `DungeonMemory` keyed by `(dungeon_number, dungeon_level)`: per-visit versus persistent state, stair links, evidence-backed stair identity, look-here stair messages.
  - [x] `ObjectivePlanner` and goal-aware staircase navigation and exploration; `objective_complete` outcome.
  - [x] Traversal permits in `ActionGate` and the same predicate in the evaluator audit; `<` on (0, 1) stays forbidden.
  - [x] Intents gain `upstairs`, stair identity, and level; UI and legacy readability.
  - [x] Policy `hierarchical-traversal-v1`; `eval run` refuses schema-1 `staircase-v1` under any policy but `hierarchical-explore-v1` before any episode.
  - [x] Replace the staircase knowledge card with the direction- and identity-neutral `stairs-traversal` card (bundle `staircase-reviewed-v3`), set policy `hierarchical-traversal-v1`, record stair-pair evidence on intents, and record milestone A in [note 0015](docs/notes/0015-typed-traversal-goals.md) (ADR 0004 step 8).
  - [x] Suite schema 2 pins policy and knowledge; report schema 3 records traversal metrics; immutable `staircase-v2` and `traversal-v1` remain bound to `hierarchical-traversal-v1`.
  - [x] Policy `hierarchical-survival-v1` adds only evidence-gated adjacent stair defense and known-ration hunger handling while retaining bundle `staircase-reviewed-v3` ([note 0016](docs/notes/0016-evidence-gated-survival-skills.md)).
- [ ] Evaluate model-owned high-level choices when benchmarks expose real trade-offs: descend versus gain resources/levels, pray or use another recovery, and prioritize dangerous visible threats.
  - [ ] Only after suites contain a pre-declared number of decision points with two or more applicable goals.
  - [ ] Paired arbiter versus model arms on the same committed seeds (model three times), pre-registered primary metric, bootstrap intervals, latency and token costs; the model owns a decision class only if it wins without more deaths.
- [ ] Progress through NLE tasks that exercise exploration, gold, food, and the Oracle.
  - [x] Policy `hierarchical-task-progression-v1`: `explore_dungeon(max_level)` objectives for Scout and Eat, `explore_level` goals, evaluator-replayed `exhausted_level` markers, and the `staircase-v3`/`traversal-v2` regression suites ([note 0017](docs/notes/0017-scout-and-eat-task-suites.md)).
  - [x] `scout-v1` and `eat-v1` baselines committed and run once with the local model: both passed their probe-derived metric gates with 0/5 objective completions; `staircase-v3` passed and `traversal-v2` failed enter-mines at 1/5 ([note 0017](docs/notes/0017-scout-and-eat-task-suites.md)).
  - [ ] `gold-v1` (route to visible gold under NLE's `pickup_types:$`) and `oracle-v1` (NLE success; exact Oracle glyph, never attacked) with a new policy and its own regression suite ids.
  - [x] Typed episode metrics (gold, score, task return, hunger and worst hunger, explored cells, HP/XL, death cause) and typed metric thresholds fixed before each run; a metric-gated case may require no objective success.
  - [x] Oracle goal and leg contracts: strict `approach_oracle` goal (token `approach_oracle:<dnum>:<dlevel>`) and `find_oracle` leg; `NetHackOracle-v0` is rejected as not supported yet and the planner refuses `find_oracle` objectives (94e3180).
  - [x] Policy `hierarchical-task-specialists-v1`: deterministic gold navigation on `NetHackGold-v0` to the nearest reachable displayed gold under `pickup_types:$`, with `gold` intents audited against the decided-on observation's gold glyph (7c71d7a).
  - [ ] Not started: `gold-v1` and `oracle-v1` suites and Oracle navigation.

### Development tooling
- [x] Add the `omp-commit` skill: derive the active conversation UUID from
  unambiguous live OMP evidence, normalize its Git trailer, and run format/lint
  checks before allowing a commit.
- [x] omp-commit resolves the active conversation from its OMP ancestor process, so commits work while several OMP sessions run.

### Observability and browser UI

Browser tooling for inspecting runs. Evidence, design, and the limitations behind the open items are in notes 0009-0012.

- [x] Redesign the agent column: full-width control panel, fixed map and inventory columns with a narrow-viewport overlay, expandable Events/Tools/Verbose tabs with per-tab auto-scroll, and field tooltips ([0009](docs/notes/0009-ui-agent-information-redesign.md)).
- [x] Add a Messages tab for NetHack's own game messages, which also stay in Verbose ([0009](docs/notes/0009-ui-agent-information-redesign.md)).
- [x] Highlight pets from explicit NLE pet evidence and display boulders as `0` and ghosts as `X`, keeping records without pet evidence readable ([0010](docs/notes/0010-pet-and-map-symbol-rendering.md)).
- [x] Annotate the map with each step's recorded destination and attack target ([0011](docs/notes/0011-map-intent-annotations.md)).
- [x] Draw each step's recorded planned path, with a persistent **Show path** toggle ([0012](docs/notes/0012-planned-path-overlay.md)).
- [x] Visualize a recorded `frontier` destination with the destination box and
  draw its recorded route with the persistent **Show path** toggle
  ([0011](docs/notes/0011-map-intent-annotations.md),
  [0012](docs/notes/0012-planned-path-overlay.md)).
- [x] Split the browser controller into main run control, DOM/panel behavior,
  event-log handling, and rendering modules; show explicit ability labels and
  accessible BUC evidence cues.
- [ ] Make persisted events selectable so choosing an old event redraws that event's historical map, player state, inventory, related observation, recorded intent, and planned path; today the map shows only the latest step's intent and path.
- [ ] Record real tool and script executions for the Tools tab; today it lists only step events whose selection source is `deterministic_skill` or `deterministic_prompt`.
- [ ] Add automated browser tests for layout, overlay, focus, and tooltip behavior, which only recorded browser smokes cover today.
- [x] Keep the sticky agent column inside a 1920x1080 viewport before page scroll ([0018](docs/notes/0018-agent-column-viewport-fit.md)).
- [ ] Mark an intent destination on the hero's own cell; the map leaves it unboxed and only the Events row names it.
- [ ] Show where replanning diverges from a drawn path, and record routes that steps compute but do not follow (waiting for a blocker, staircase defense).

## Later: autonomous ascension

- [ ] Establish staged full-game benchmarks and survival metrics.
- [ ] Design long-horizon planning, branch progression, identification, equipment, resistances, and recovery policies.
- [ ] Build an auditable offline knowledge retrieval pipeline beyond hand-curated cards.
- [ ] Evaluate full `NetHackScore-v0` runs, then define an ascension evaluation suite.

## Explicitly deferred

- Forking or vendoring NLE without a concrete engine-level requirement.
- Cloud inference during gameplay.
- Automatic self-modification or online learning during evaluation.
- Displaying or persisting private chain-of-thought as a product feature.
