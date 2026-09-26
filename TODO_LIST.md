# Roadmap

This file tracks product work. Completed work and reasoning belong in `docs/notes/`; durable choices belong in `docs/decisions/` and `ARCHITECTURE.md`.

## Now: milestone 1 — Staircase agent

Acceptance: the fixed local policy succeeds on at least 6 of 10 committed deterministic `NetHackStaircase-v0` seeds, including seed 6, with no invalid NLE actions and complete SQLite plus ttyrec replay data.

- [ ] Define typed observation, decision, action, run-state, and event contracts.
- [x] Implement the NLE adapter with lawful dwarven Valkyrie, deterministic seeds, ttyrec capture, and explicit legal actions.
- [x] Build observation projection for map, player statistics, messages, prompts, and inventory.
- [ ] Build the hierarchical coordinator and deterministic action gate.
- [x] Add structured Ollama output, one repair retry, then pause-on-failure behavior.
- [ ] Curate the first local-model knowledge cards from cited NetHackWiki pages.
- [ ] Add SQLite run/event storage and artifact layout.
- [ ] Add the loopback HTTP control/status API and WebSocket event stream; make start, pause, step, stop, and observation usable by both coding-agent tools and the browser.
- [ ] Add headless scenario commands that launch the service, submit validated run configurations, wait for state transitions, and stop runs gracefully.
- [ ] Add the dependency-light browser UI: map, status, inventory, structured decisions, and start/pause/step/stop controls.
- [ ] Commit the 10-seed evaluation suite, including seed 6, and report per-seed outcomes and latency.
- [ ] Verify gameplay performs no non-loopback network requests.

## Next: robust dungeon play

- [ ] Analyze milestone failures and update deterministic skills or reviewed knowledge; do not let evaluation runs mutate themselves.
- [ ] Add replay comparison and aggregate run diagnostics.
- [ ] Add bounded navigation, combat-risk, hunger, inventory, and prompt-handling skills as evidence requires.
- [ ] Evaluate whether Laya improves routine action ranking enough to justify another model runtime.
- [ ] Progress through NLE tasks that exercise exploration, gold, food, and the Oracle.

### Development tooling
- [x] Add the `omp-commit` skill: derive the active conversation UUID from
  unambiguous live OMP evidence, normalize its Git trailer, and run format/lint
  checks before allowing a commit.
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
