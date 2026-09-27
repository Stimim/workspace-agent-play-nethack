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

- [ ] Analyze milestone failures and update deterministic skills or reviewed knowledge; do not let evaluation runs mutate themselves.
- [ ] Add replay comparison and aggregate run diagnostics.
- [ ] Add bounded navigation, combat-risk, hunger, inventory, and prompt-handling skills as evidence requires.
- [ ] Evaluate whether Laya improves routine action ranking enough to justify another model runtime.
- [ ] Survey the [Janelia FlyEM male CNS connectome](https://www.janelia.org/project-team/flyem/male-cns-connectome) and define a bounded, evidence-driven comparison of any connectome-inspired planning or action-ranking approach against current baselines; this is research, not a production commitment.
- [ ] Replace the fixed downstairs-only milestone goal with typed traversal goals that can select upstairs, downstairs, and a branch-specific staircase identity; extend memory, intents, and evaluation cases before allowing level changes.
- [ ] Evaluate model-owned high-level choices when benchmarks expose real trade-offs: descend versus gain resources/levels, pray or use another recovery, and prioritize dangerous visible threats.
- [ ] Progress through NLE tasks that exercise exploration, gold, food, and the Oracle.

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
