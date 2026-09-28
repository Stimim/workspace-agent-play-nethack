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
├── _agents/           # skills, tools, and model recipes for online coding agents
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

Developer bootstrap, the deterministic NLE adapter, observation projection,
hierarchical coordinator, reviewed local knowledge cards, typed SQLite event
contracts, local control surface, headless scenario orchestration, and
executable network-boundary verification are implemented. Each run executes a
typed task spec (NLE task, action profile, and objective legs). An objective
planner turns the legs into typed goals: stand on, or traverse, a staircase of
a direction with a main or branch identity
([ADR 0004](docs/decisions/0004-traversal-goals-and-task-progression.md)).
Two deterministic skills serve the goals over a dungeon memory that keeps each
visited level: `staircase_navigation` routes to a remembered reachable
staircase matching the goal and waits on it or uses it, and `explore_level`
walks to unexplored space, opens or kicks doors, fights adjacent hostiles, and
searches for hidden passages. A deterministic arbiter switches between them;
the local model is consulted at the start, when exploration is stuck, and for
unhandled prompts. Every action passes through a gate that rejects invalid
indices and any level change (`<` and `>`) without a coordinator traversal
permit, which only a typed traversal goal on a level-changing task can earn.
The staircase task never changes level. Runs expose current goal and skill
and stream discriminated typed events through the loopback HTTP/WebSocket service and CLI client. The
`scenario run` command owns a child service for one bounded run, and
`verify network` records and enforces its runtime socket boundary.

The first product milestone requires this hierarchy to succeed on at least 6
of 10 fixed `NetHackStaircase-v0` seeds, including seed 6, while recording
SQLite events and ttyrecs and streaming the decision trace to a local web UI.
With the local `gemma4-nethack:latest` model, the committed suite
(`nethack-agent/evaluation/staircase-v1.json`) passed its acceptance gate with
10/10 task successes and complete records
(`nethack-agent/evaluation/reports/staircase-v1-20260926T211301Z.md`), and the
dependency-free browser UI is served by the same loopback service, so milestone
1 is accepted. A deterministic arbiter picks skills; the model is consulted at
the start, on stuck exploration, and for unhandled prompts
([ADR 0002](docs/decisions/0002-deterministic-skill-arbiter.md)). The exact
acceptance contract and boundaries are in [`ARCHITECTURE.md`](ARCHITECTURE.md);
work is tracked in [`TODO_LIST.md`](TODO_LIST.md).

Since acceptance, the browser UI has gained a redesigned agent column with
Events, Messages, Tools, and Verbose tabs, explicit ability labels, inventory
BUC evidence cues, pet highlighting, `0`/`X` boulder and ghost symbols, and map
annotations for each step's recorded frontier or other destination, attack
target, and planned path. The reviewed knowledge bundle (`staircase-reviewed-v2`)
now makes `autoopen` explicit and documents covered and branch stairs from NLE
and local-wiki evidence. The committed suite with this bundle and the local
model again passed 10/10 with trajectories identical to the accepted run
(`nethack-agent/evaluation/reports/staircase-v1-20260927T065500Z.md`;
[note 0013](docs/notes/0013-review-feedback-resolutions.md)).

## Documentation

Start with [`docs/README.md`](docs/README.md). Architecture documents describe
the current design, decision records explain why, and notes preserve the
development timeline without becoming stale sources of truth.
