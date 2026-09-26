# NetHack Agent

Local-first research and engineering project whose north star is an autonomous
NetHack ascension. Online coding agents may develop and debug the software; the
playing agent uses local models and must remain offline.

## Repository map

```text
.
├── AGENTS.md          # instructions for coding agents
├── ARCHITECTURE.md    # current system design and invariants
├── TODO_LIST.md       # prioritized product work and acceptance gates
├── docs/
│   ├── decisions/     # durable architecture decision records
│   ├── notes/         # chronological development history and lessons
│   └── external/      # acquisition notes for uncommitted source material
├── _agents/           # skills and tools for online coding agents
└── nethack-agent/     # local player application and runtime knowledge
```

The top level stays small. New top-level directories must represent a domain
that could plausibly become its own repository or submodule.

## Bootstrap

Prerequisites: Python 3.12, `uv`, CMake 3.28+, Ollama, and the local
`gemma4-nethack:latest` model.

```bash
cd nethack-agent
uv sync --locked
uv run nethack-agent doctor
```

`doctor` performs a real NLE reset/step and a short local Ollama generation.
See [`docs/development.md`](docs/development.md) for configuration and isolated
checks.

## Project status

Developer bootstrap and the deterministic NLE adapter are implemented. The
adapter fixes the Staircase character and RNG inputs, exposes public typed
observations and legal actions, rejects invalid actions, tracks lifecycle, and
finalizes a ttyrec for every episode.

The first product milestone is a hierarchical local agent that succeeds on at
least 6 of 10 fixed `NetHackStaircase-v0` seeds, including seed 6, while
recording SQLite events and ttyrecs and streaming a structured decision trace
to a local web UI. The observation projector, a structured Ollama decision
model, a flat coordinator with a deterministic action gate, and SQLite run
storage are implemented; hierarchical goals, the control API, and UI are not
implemented yet. Their exact acceptance contract
and boundaries are in [`ARCHITECTURE.md`](ARCHITECTURE.md); work is tracked in
[`TODO_LIST.md`](TODO_LIST.md).

## Documentation

Start with [`docs/README.md`](docs/README.md). Architecture documents describe
the current design, decision records explain why, and notes preserve the
development timeline without becoming stale sources of truth.
