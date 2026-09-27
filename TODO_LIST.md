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
