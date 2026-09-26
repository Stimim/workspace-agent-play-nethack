# NetHack agent

This Python application domain contains the deterministic NLE adapter, immutable observation projector, hierarchical goal/skill coordinator, per-level terrain memory with deterministic staircase-navigation, level-exploration, and prompt skills, action gate, structured Ollama decision model, reviewed and hash-pinned local knowledge bundle, typed SQLite run/event store, loopback HTTP/WebSocket control service with a dependency-free browser UI, headless scenario orchestrator, executable network-boundary verifier, and the committed 10-seed evaluation suite with its `eval run` and `eval abort` harness. Milestone status is tracked in [`../TODO_LIST.md`](../TODO_LIST.md). Knowledge card sources, attribution, and update rules are in [`knowledge/README.md`](knowledge/README.md).

```bash
uv sync --locked
uv run nethack-agent doctor
```

Individual checks:

```bash
uv run nethack-agent smoke nle
uv run nethack-agent smoke ollama
uv run nethack-agent smoke agent   # one hierarchical action with local model
```

Run control through the local service:

```bash
uv run nethack-agent serve --data-dir data   # UI and API: http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000/> for the browser UI: map, player statistics,
inventory, messages, run status, the latest structured decision trace, and
latency/token metrics, with start, attach, pause, resume, step, and stop
controls. It uses the same HTTP API and event WebSocket as the CLI, loads no
external resources, and reattaches from `#run=RUN_ID` after a reload.

From another shell:

```bash
uv run nethack-agent run start --seed 6 --max-steps 200 --auto
uv run nethack-agent run status RUN_ID
uv run nethack-agent run pause RUN_ID
uv run nethack-agent run resume RUN_ID
uv run nethack-agent run step RUN_ID
uv run nethack-agent run events RUN_ID
uv run nethack-agent run stop RUN_ID
```

`run` is a client-only command: it never starts or owns the service. For a
single managed scenario, use `scenario run`; it launches a child service, waits
for health, submits a strict run configuration, drives either auto mode or a
bounded number of steps, retrieves every event page, stops an active run, and
terminates and reaps the service:

```bash
uv run nethack-agent scenario run \
  --seed 6 --max-steps 200 --steps 10 --data-dir data/scenarios \
  --port 8010 --timeout 300 --json
```

Use `--auto` instead of `--steps N` for autonomous execution. Normal scenarios
use the configured local Ollama model. The explicit
`--development-scripted-model` option is available only for deterministic
development and CI checks; it is not a production fallback or valid evaluation
mode.

Run the executable network-boundary check without Ollama:

```bash
uv run nethack-agent verify network --timeout 20 --json
```

It installs a process-wide socket guard, points proxy environment variables at
a non-loopback sentinel, runs a real NLE step through the HTTP control service
with the explicit scripted development model, records actual destinations, and
fails if any connection target is not loopback.

Run the committed milestone suite (`evaluation/staircase-v1.json`) against the
local model and write a new timestamped JSON and Markdown report:

```bash
uv run nethack-agent eval run --suite evaluation/staircase-v1.json \
  --data-dir data/evaluations/staircase-v1-explore --report-dir evaluation/reports
```

`--development-scripted-model` exercises the harness without Ollama; such
reports are never milestone evidence. `eval abort --report <json> --reason
<text>` finalizes an interrupted report that will not be completed. See
[`../docs/development.md`](../docs/development.md#evaluation-suite).

Regression tests use real NLE environments and scripted models; they do not require Ollama:

```bash
uv run pytest -q
```

Defaults:

- environment: `NetHackStaircase-v0`;
- character: lawful dwarven Valkyrie (`val-dwa-law`);
- model: `gemma4-nethack:latest`;
- Ollama: `http://127.0.0.1:11434`;
- control API: `http://127.0.0.1:8000`.

See [`../docs/development.md`](../docs/development.md) for prerequisites and configuration.
