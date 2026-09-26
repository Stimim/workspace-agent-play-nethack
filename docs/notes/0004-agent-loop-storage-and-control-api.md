# 0004: Agent loop, storage, and control API

Date: 2026-09-26

## Scope

This slice connects the NLE adapter to a local model and exposes runs through a
loopback service:

- `observation.ObservationProjector` copies each ephemeral NLE observation into
  immutable, JSON-serializable state with map deltas, glyph IDs (`glyph_rows`
  and cell glyphs), and prompt flags (`single_character_choice`, `text_input`,
  `wait_for_space`).
- `decision` defines the structured decision schema, validation, run states,
  and outcomes. `ollama.OllamaClient` (moved out of the CLI) and
  `model.OllamaDecisionModel` request schema-constrained output with one
  repair retry. `network` holds the shared loopback URL check.
- `coordinator.AgentCoordinator` runs the lifecycle state machine and the
  deterministic action gate.
- `storage.RunStore` persists run records and ordered JSON events in SQLite.
- `run_manager.RunManager`, `api.create_app`, `control_client.ControlClient`,
  and the `serve` and `run` CLI commands provide the control surface.

The coordinator is flat: one model decision per NLE action. Hierarchical goals
and skills remain open, as do headless scenario commands that launch the
service and wait for state transitions.

## Decisions

- The model must list the selected action among its candidates with the
  highest score, so the persisted trace cannot contradict the choice.
- Model inference happens outside the coordinator lock. Pause or stop during
  inference discards the pending decision instead of blocking control calls.
- The service holds one active run per process. Run control state is in
  memory; SQLite is the durable record.
- Run creation (`POST /api/runs`) accepts only `seed`, `max_episode_steps`, and
  `auto_start` with strict types; environment, model, policy, and knowledge
  versions remain service-fixed rather than configurable per request.
- Run stop is idempotent; calling stop on an already stopped run reports the
  final state without duplicating stop events.
- Reported `latency_ms` metrics use a hybrid measurement: Ollama server
  `total_duration` when available, falling back to client wall-clock elapsed
  time on transport or pre-response failure.
- Event retrieval endpoints support pagination with `limit` on HTTP and
  WebSocket routes, and HTTP responses report `next_after` and `has_more`.
- The WebSocket stream performs bounded history replay and live event
  streaming, offloads database queries asynchronously to worker threads, and
  actively monitors client disconnects.
- FastAPI lifespan management ensures `RunManager` and database resources are
  closed gracefully on server shutdown.
- Coordinator advances use an explicit in-flight revision; pause, resume, and
  stop invalidate pending inference without holding the coordinator lock across
  model work. Run-state changes and matching events commit atomically with
  expected-state guards.
- Each NLE adapter writes to a unique episode directory. Loopback HTTP clients
  pin `localhost` to `127.0.0.1`, retain literal IPv6 support, and bypass
  environment proxies.

## Verification (historical original slice)

- `uv run pytest -q`: 16 tests passed, covering projection, decision
  validation and repair, coordinator pause-on-failure and step cap, SQLite
  reopen and ordering, and API run control with ttyrec finalization.
- `uv run ruff check` and `uv run ruff format --check` passed.
- `smoke agent` against `gemma4-nethack:latest` (Ollama 0.34.4, model not
  preloaded): one decision, action `MiscDirection.WAIT`, 831 prompt tokens,
  257 output tokens, about 21 s.
- `serve` plus `run start`, `status`, `pause` (409 while paused), `stop`,
  `events`, and `status` for an unknown ID (404) against a temporary data
  directory; stop finalized the ttyrec.
- A throwaway script with a scripted model exercised auto-start, pause,
  resume, and a WebSocket stream that delivered live step events and closed
  after truncation at the step cap.

## Verification (2026-09-27 hardening)

- `uv run ruff format --check`: 23 files already formatted.
- `uv run ruff check`: all checks passed.
- `uv run pytest -q`: 59 tests passed with one upstream Starlette/AnyIO
  deprecation warning.
- A live FastAPI `TestClient` smoke with real NLE and a scripted model exercised
  create, a real step, one-event HTTP cursor pages, idle WebSocket disconnect,
  stop, empty post-stop replay, lifespan shutdown, and ttyrec finalization
  without contacting Ollama.

## Known gaps

- Event payloads are untyped JSON; event kinds are strings.
- Runs left `running` or `paused` in SQLite by a stopped service are not
  reconciled on restart.
- Run creation does not allow per-request overrides of task environment, model,
  character, or knowledge cards; those remain service-level configurations.
