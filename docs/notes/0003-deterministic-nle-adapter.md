# 0003: Deterministic NLE adapter

Date: 2026-09-26

## Scope

The first implementation slice establishes the game-engine boundary before adding model prompting or orchestration. `nethack_agent.environment.NleEnvironment` now owns `NetHackStaircase-v0` construction, deterministic reset, legal actions, episode lifecycle, and ttyrec output.

## Contracts

- `ScenarioConfig` validates the evaluation seed, positive step cap, and artifact directory.
- The environment and character are fixed to `NetHackStaircase-v0` and lawful dwarven Valkyrie for milestone 1.
- `SeedSet` deterministically expands one suite seed into separate core, display, and level-generation seeds. NLE anti-TAS reseeding is disabled and `fix_moon_phase` is enabled.
- `NleObservation` exposes only requested public NLE arrays. NLE's task-only `internal` observation is not part of the type.
- `LegalAction` records the stable episode action index, underlying NetHack command value, and readable enum name.
- `StepTransition` records reward, termination and truncation, NLE end status, ascension flag, and the one-based step index.
- Invalid action indices and invalid lifecycle transitions are rejected before calling NLE.
- Closing the adapter is idempotent and finalizes the episode ttyrec.

## Observation lifetime

NLE reuses NumPy observation buffers across calls. Copying every raw array in the adapter would impose avoidable allocation and bandwidth costs. The adapter therefore returns zero-copy observations whose documented lifetime ends at the next `step` or `reset`. The upcoming projector must extract compact immutable state before advancing the environment; raw observations must not be retained as event history.

## Regression evidence

Five real-environment tests cover public observations and ttyrec finalization, deterministic initial state for the same suite seed, invalid-action rejection without step advancement, terminal state at the configured step cap, and rejection of reset during a running episode.

Final verification passed: five tests, Ruff lint and format checks, lockfile
consistency, and the CLI's real adapter smoke. The smoke reset and stepped a
79×21 Staircase map with 23 legal action indices, reported all three derived
seeds, and finalized one ttyrec.
