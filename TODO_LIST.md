# Roadmap

This file tracks product work. Completed work and reasoning belong in `docs/notes/`; durable choices belong in `docs/decisions/` and `ARCHITECTURE.md`.

## Now: milestone 1 — Staircase agent (accepted)

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

## Next: robust dungeon play

Dependency order for the four capability items below: traversal goals, then NLE task suites, then evidence-gated skills, then model-owned choices ([ADR 0004](docs/decisions/0004-traversal-goals-and-task-progression.md)).

- [ ] Analyze milestone failures and update deterministic skills or reviewed knowledge; do not let evaluation runs mutate themselves.
- [ ] Add replay comparison and aggregate run diagnostics.
- [ ] Add bounded navigation, combat-risk, hunger, inventory, and prompt-handling skills as evidence requires.
  - [ ] Combat risk: fight an adjacent hostile before waiting on stairs (baseline seeds 1, 2, 4 died on `>`); retreat/rest rules only after traversal or Scout deaths with HP traces.
  - [ ] Hunger: a new action profile with only the keys eating needs (item letter as a prompt answer, ESC) and eating a known-safe inventory ration when Hungry (seeds 2, 3, 5 starved or fainted with a ration uneaten).
  - [ ] Covered stairs: recognized from look-here messages as part of traversal memory (seed 5).
  - [ ] Prompt handlers ship with the actions that cause them (eat item selection, "eat it?", "pray?"); no generic prompt skill while suites show no unhandled prompts.
  - [ ] Navigation and inventory skills only after a failure class recurs in traversal or task-suite evidence.
- [ ] Evaluate whether Laya improves routine action ranking enough to justify another model runtime.
- [ ] Survey the [Janelia FlyEM male CNS connectome](https://www.janelia.org/project-team/flyem/male-cns-connectome) and define a bounded, evidence-driven comparison of any connectome-inspired planning or action-ranking approach against current baselines; this is research, not a production commitment.
- [ ] Replace the fixed downstairs-only milestone goal with typed traversal goals that can select upstairs, downstairs, and a branch-specific staircase identity; extend memory, intents, and evaluation cases before allowing level changes.
  - [ ] Typed `TaskSpec` (NLE task, action profile, objective legs) selected per run; fix step caps above 5,000 (NLE cap above `TimeLimit`); `runs.task` column.
  - [ ] Typed `Goal` union (`stand_on_stairs`, `traverse_stairs` with direction and main/branch target) replacing the enum; legacy `stand_on_downstairs` reads exactly.
  - [ ] `DungeonMemory` keyed by `(dungeon_number, dungeon_level)`: per-visit versus persistent state, stair links, evidence-backed stair identity, look-here stair messages.
  - [ ] `ObjectivePlanner` and goal-aware staircase navigation and exploration; `objective_complete` outcome.
  - [ ] Traversal permits in `ActionGate` and the same predicate in the evaluator audit; `<` on (0, 1) stays forbidden.
  - [ ] Intents gain `upstairs`, stair identity, and level; UI and legacy readability.
  - [ ] Suite schema 2 pinning policy and knowledge, report schema 3 with traversal metrics, `staircase-v2` regression and `traversal-v1` (descend, round trip, enter Mines); `staircase-v1` stays unchanged and bound to `hierarchical-explore-v1`.
- [ ] Evaluate model-owned high-level choices when benchmarks expose real trade-offs: descend versus gain resources/levels, pray or use another recovery, and prioritize dangerous visible threats.
  - [ ] Only after suites contain a pre-declared number of decision points with two or more applicable goals.
  - [ ] Paired arbiter versus model arms on the same committed seeds (model three times), pre-registered primary metric, bootstrap intervals, latency and token costs; the model owns a decision class only if it wins without more deaths.
- [ ] Progress through NLE tasks that exercise exploration, gold, food, and the Oracle.
  - [ ] `scout-v1` (Scout return, explored cells, depth, deaths), then `gold-v1` (reproduce NLE's `pickup_types:$`), `eat-v1` (after hunger), and `oracle-v1` (NLE success; after traversal, combat risk, and hunger).
  - [ ] Typed episode metrics (gold, score, task return, hunger, HP/XL, death cause) and metric or paired-baseline acceptance fixed before each run.

### Development tooling
- [x] Add the `omp-commit` skill: derive the active conversation UUID from
  unambiguous live OMP evidence, normalize its Git trailer, and run format/lint
  checks before allowing a commit.

- [ ] After `/restart` reloads the persistent OMP settings, rerun one bounded
  `vibe_spawn cli=fast` task and require turn metadata to show
  `ollama/omp-coder-smol:latest` after the real Antigravity quota 429. Fresh
  direct OMP processes already fall back; OMP 18.3.2 did not refresh the
  already-running conversation's worker-launcher snapshot ([0008](docs/notes/0008-omp-local-coding-fallback.md)).

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
- [ ] Keep the sticky agent column inside a 1920x1080 viewport before page scroll; it overflows by about 34 px.
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
