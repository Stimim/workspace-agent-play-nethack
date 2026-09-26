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

## Subsequent status

The untyped event payloads and flat one-model-action-per-step loop documented
above were replaced on 2026-09-27 by discriminated event dataclasses and the
hierarchical staircase coordinator. Runs left `running` or `paused` in SQLite
by a stopped service are still not reconciled on restart. Run creation still
keeps task environment, model, character, and knowledge configuration at the
service level rather than accepting per-request overrides.

## Verification (2026-09-27 hierarchy and typed events)

- `uv run pytest -q`: 67 tests passed with one upstream Starlette/AnyIO
  deprecation warning. Coverage includes every event variant and SQLite reopen,
  corrupt-event rejection, observation/action/decision round trips, route and
  prompt behavior, model cadence, action gating, cancellation, API event JSON,
  and current goal/skill status.
- `uv run ruff check .` and `uv run ruff format --check .` passed for 27 files.
- A final real-NLE scripted fallback smoke ran seeds 1, 6, and 10. Seed 1
  truncated at 1,000 steps and seed 6 died at step 943; neither exposed the
  downstairs to the navigation skill. Seed 10 succeeded in 166 steps: the
  model selected goal/skill once, supplied 161 ambiguous fallback actions, then
  deterministic navigation took over for five
  actions (`N`, `E`, `E`, `NE`, `NE`) from step 162 through task success.
  This smoke is trajectory evidence, not the milestone 10-seed evaluation.

## Headless orchestration and network-boundary verification

`ControlClient` now validates health, run-state, and paginated-event response
contracts; iterates complete event histories; and waits with finite monotonic
deadlines. `nethack-agent scenario run` owns a child service for one strict
loopback scenario, drives either auto mode or bounded steps, retrieves all
events, stops an active run, and terminates and reaps its child on every exit
path. The pre-existing `run` commands remain client-only.

`nethack-agent verify network` installs a recording socket guard during a real
HTTP-controlled NLE step. It blocks any non-loopback destination and sets proxy
variables to a non-loopback sentinel, so successful observed control traffic
also proves that the client ignored environment proxies. Both this verifier and
the scenario smoke can select the explicit deterministic
`--development-scripted-model`; normal service execution never falls back to
it.

Verification on 2026-09-27:

- `uv run pytest -q`: 85 tests passed. New coverage includes readiness and state
  deadlines, paused/terminal/stopped/error and malformed-state distinctions,
  complete cursor pagination, bounded and auto scenario execution, interrupt
  cleanup, child stop/termination/reaping, and rejected non-loopback socket
  destinations.
- `uv run ruff check .` and `uv run ruff format --check .` passed for 31 files.
- A real `scenario run --seed 6 --max-steps 3 --steps 1
  --development-scripted-model --json` subprocess produced `run_started`,
  `step`, and `run_stopped`, returned final state `stopped`, finalized a ttyrec,
  and reaped its service child.
- `nethack-agent verify network --timeout 20 --json` performed a real scripted
  NLE step, stopped the run with three events, recorded nine actual HTTP socket
  destinations, and found all nine at literal `127.0.0.1` despite the
  non-loopback proxy sentinel. It did not contact Ollama.
