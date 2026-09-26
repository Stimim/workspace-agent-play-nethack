# Development

## Prerequisites

- Linux (the initial workstation is WSL2)
- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- CMake 3.28 or newer (required if NLE must build from source)
- Ollama reachable on loopback
- local model `gemma4-nethack:latest`

The selected model is about 9.6 GB on disk while the current GPU has 8 GB VRAM. Its Modelfile default context of 131,072 tokens made Ollama place it 64% on the CPU. Requests therefore set `num_ctx` explicitly (default 8,192), and at that size `ollama ps` reports 3.2 GB, 100% GPU.

## Bootstrap

```bash
cd nethack-agent
uv sync --locked
uv run nethack-agent doctor
```

`doctor` performs real checks: it creates and steps a deterministic NLE Staircase environment, queries Ollama, verifies the configured model, and requests a short local generation. It exits nonzero if either path fails.

Run one check in isolation:

```bash
uv run nethack-agent smoke nle
uv run nethack-agent smoke ollama
uv run nethack-agent smoke agent
```

`smoke agent` resets seed 6, asks the configured model for a typed goal and
skill, lets the deterministic arbiter act (navigation or exploration) or
requests one fallback action, executes it through the action gate, and
finalizes the ttyrec. It reports action-selection source, action, goal, skill,
aggregate token counts, and latency.

### Local control service

```bash
uv run nethack-agent serve --data-dir data
```

`serve` defaults to host `127.0.0.1` and port `8000`; override them with
`--host` and `--port`. It accepts only loopback hosts. It stores `runs.sqlite3`
and per-run artifacts under the data directory (`nethack-agent/data/` is
ignored by Git).
From another shell:

```bash
uv run nethack-agent run start --seed 6 --max-steps 200   # paused after reset
uv run nethack-agent run step RUN_ID                      # one hierarchical action
uv run nethack-agent run resume RUN_ID                    # run on a worker thread
uv run nethack-agent run pause RUN_ID
uv run nethack-agent run status RUN_ID
uv run nethack-agent run events RUN_ID --after -1
uv run nethack-agent run stop RUN_ID
```

`run start --auto` resumes immediately. Commands print the JSON API response
and exit nonzero on HTTP or connection errors. The service allows one active
run per process; runs cannot be controlled after a service restart. The API
and WebSocket endpoints are listed in `ARCHITECTURE.md`.

### Browser UI

While `serve` is running, open <http://127.0.0.1:8000/> (or the chosen loopback
host and port). The page is served by the control service itself; it needs no
build step, extra dependency, or network access. Use the header to start a run
(seed, max steps, auto start) or attach to an existing run id, then pause,
resume, single-step, or stop it. `#run=RUN_ID` in the URL reattaches after a
reload. Starting while another run is active shows the service's 409 detail;
stop the active run first. Runs from before a service restart are shown
read-only.

For a no-Ollama UI check, serve with the scripted development model on a
scratch data directory:

```bash
uv run nethack-agent serve --development-scripted-model \
  --data-dir /tmp/nethack-ui --port 8010
```

Assets live in `src/nethack_agent/ui/` and are listed in the `_UI_ASSETS`
allowlist in `api.py`; add any new file there. The Content-Security-Policy
permits only same-origin scripts, styles, images, and connections, so do not
add inline scripts, inline `style`/`on*` attributes, or external URLs, and
insert model or game text with `textContent`. `tests/test_ui.py` enforces the
headers, the served module graph, and these asset rules.

### Owned headless scenarios

The existing `run` command is client-only. To launch and own a child service
for exactly one scenario, choose either bounded steps:

```bash
uv run nethack-agent scenario run \
  --seed 6 --max-steps 200 --steps 10 \
  --data-dir data/scenarios --port 8010 --timeout 300 --json
```

or autonomous execution with `--auto` in place of `--steps N`. The command
accepts only loopback hosts, waits for service health and run-state changes with
a finite monotonic deadline, follows every event cursor page, stops an active
run, and terminates and reaps its child on success, failure, timeout, or
`Ctrl+C`.

Normal scenarios use local Ollama. For deterministic development and CI only,
add `--development-scripted-model`; this explicit no-Ollama model is never a
production fallback and its runs are not valid evaluation episodes.

Behaviorally verify the gameplay network boundary with:

```bash
uv run nethack-agent verify network --timeout 20 --json
```

This command runs a real NLE step through the HTTP service with the explicit
scripted development model. It sets proxy variables to a non-loopback sentinel,
records actual socket destinations, blocks any non-loopback attempt, and
requires observed loopback traffic. It does not contact Ollama.

Configuration is environment-based:

```bash
export NETHACK_AGENT_OLLAMA_URL=http://127.0.0.1:11434
export NETHACK_AGENT_MODEL=gemma4-nethack:latest
export NETHACK_AGENT_OLLAMA_TIMEOUT_SECONDS=180
export NETHACK_AGENT_OLLAMA_NUM_CTX=8192
export NETHACK_AGENT_API_URL=http://127.0.0.1:8000       # run commands
export NETHACK_AGENT_API_TIMEOUT_SECONDS=300             # run commands
```

`NETHACK_AGENT_OLLAMA_NUM_CTX` must be a positive decimal integer (at most
1,048,576). Every generation sends it as Ollama's `num_ctx`, and every run
records it as `ollama_num_ctx`. If Ollama reports a prompt that leaves fewer
than the requested output tokens of headroom in that window, the client raises
`OllamaContextLimitError`: Ollama may have silently truncated the prompt. That
counts as a failed decision attempt under the one-repair policy. Changing the
value changes the evaluated configuration, so it must stay fixed for a suite.

### Ollama installation or version mismatch

`ollama --version` must not report different client and server versions.
Mismatched binaries can answer metadata requests but fail to start a model
runner. `doctor` detects this before waiting for generation.

If the client and server differ, or the service reports a missing runner binary,
repair the installation using the
[official Linux instructions](https://docs.ollama.com/linux), then restart the
system service:

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl daemon-reload
sudo systemctl restart ollama
ollama --version
```

Review installation scripts before running them. If Ollama was launched another
way, restart it through that installation's service manager. Then rerun
`uv run nethack-agent doctor`.

The Ollama URL must resolve to a loopback hostname or address. Gameplay must remain offline; online services are permitted only for development work performed outside an episode.

## Evaluation suite

The committed milestone suite is `nethack-agent/evaluation/staircase-v1.json`
(seeds 1–10, 1,000-step cap). Confirm Ollama first, then run the whole suite
against the configured local model:

```bash
cd nethack-agent
uv run nethack-agent doctor
uv run nethack-agent eval run \
  --suite evaluation/staircase-v1.json \
  --data-dir data/evaluations/staircase-v1-explore \
  --report-dir evaluation/reports
```

Use a fresh data directory per policy version: the strict event reader does not
accept step events recorded before the current selection contract.

Progress lines go to stderr every `--progress-interval` seconds (default 30).
Each invocation reserves a new `<suite>-<UTC timestamp>.json` and `.md` pair in
the report directory (default `DATA_DIR/reports`), rewrites that pair (mode
0644) after each seed, and never replaces an earlier report. `--json` prints the
final report and its paths. The command exits 0 when the report is written,
including when acceptance fails; read `acceptance.passed` and
`acceptance.milestone_accepted`. It exits 1 for configuration or Ollama
readiness errors and 130 after `Ctrl+C`, which stops the active run and records
an `interrupted` report.

If an interrupted (or crashed, still `running`) suite will not be finished, for
example because the policy changed, finalize its report instead of deleting it:

```bash
uv run nethack-agent eval abort \
  --report evaluation/reports/<suite>-<timestamp>.json \
  --reason "policy replaced before completion"
```

This keeps every recorded result verbatim, sets status `aborted` with the
reason, re-renders the Markdown from the JSON, and exits 1 for any other status.

`--seeds 6,1,2,3,4,5,7,8,9,10` changes only execution order. A subset such as
`--seeds 6` writes a `partial` report that cannot pass acceptance. For a fast,
Ollama-free harness check, add `--development-scripted-model`; those reports are
marked `development_scripted` and never count as milestone evidence. The
scripted model always selects `explore_level` and waits as its fallback action,
so it exercises the deterministic policy exactly as a real run does until the
model is consulted. Changing seeds, the step cap, or acceptance requires a new
suite file and `suite_id`, not an edit after results are known.

## Quality checks

```bash
cd nethack-agent
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Tests use real NLE environments with scripted models and FastAPI's test client;
they do not need Ollama. Behavioral changes also require a smoke run of the
changed path: `smoke agent` covers one real model decision, `serve` plus `run`
cover independently managed control, `scenario run` covers child ownership and
cleanup, and `verify network` proves the socket boundary with actual traffic.

## Documentation preview

From the repository root, launch the local Markdown viewer with:

```bash
uvx \
  --from mkdocs==1.6.1 \
  --with pymdown-extensions==12.1 \
  --with mkdocs-mermaid2-plugin==1.2.3 \
  mkdocs serve --config-file docs/mkdocs.yml --dev-addr 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/>. The server watches the repository and rebuilds
after Markdown changes. It renders task-list checkboxes and Mermaid diagrams.
Stop it with `Ctrl+C`. The first launch downloads the pinned viewer packages
through `uvx`; Mermaid's browser library is loaded from `unpkg.com`.

The control service also defaults to port 8000; pass `--port` to one of them
when running both.

## NetHackWiki source material

The XML dump is intentionally ignored because it is about 188 MB uncompressed. See `docs/external/nethack-wiki-xml-dump/README.md` for acquisition and licensing, then use the coding-agent skill from the repository root:

```bash
uv run python _agents/skills/nethack-wiki/scripts/wiki_dump.py search "stair"
uv run python _agents/skills/nethack-wiki/scripts/wiki_dump.py page "Stairs"
```

From `nethack-agent/`, run `uv run python ../_agents/skills/nethack-wiki/scripts/wiki_dump.py ...`.

Do not put the raw dump into a model prompt. Extract a relevant page, verify the supported NetHack version and source, then write a concise cited card under `nethack-agent/knowledge/`.

### Reviewed runtime knowledge

`nethack-agent/knowledge/manifest.json` allowlists cards in prompt order and
pins each card's SHA-256. After a reviewed card edit, recompute its hash, update
the manifest, and bump `bundle_id` for a semantic card-set change:

```bash
cd nethack-agent
sha256sum knowledge/staircase-goal.md
uv run pytest -q tests/test_knowledge.py
uv run python -c 'from nethack_agent.knowledge import load_default_knowledge_bundle as l; b=l(); print(b.version, b.character_count, b.estimated_tokens)'
```

The service loads and validates the bundle once at startup, then records its
content-derived version on every run. Ollama skill and fallback-action prompts
include only its bounded facts and non-goals. Card metadata, the raw dump, and
unlisted files are not injected. See `nethack-agent/knowledge/README.md` for the
card schema, sources, and CC BY-SA 3.0 attribution.

## Dependency policy

`pyproject.toml` declares direct requirements; `uv.lock` is the reproducible full resolution. NLE is consumed as a package from the maintained `NetHack-LE/nle` project. Do not add a fork or submodule until a concrete engine change requires it.
