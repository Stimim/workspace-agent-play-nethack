# Development

## Prerequisites

- Linux (the initial workstation is WSL2)
- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- CMake 3.28 or newer (required if NLE must build from source)
- Ollama reachable on loopback
- local model `gemma4-nethack:latest`

The selected model is about 9.6 GB while the current GPU has 8 GB VRAM. Ollama may partially offload it to system memory; startup and generation can therefore be slower than a fully resident model.

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

`smoke agent` resets seed 6, asks the configured model for one structured
decision, executes it through the coordinator's action gate, and finalizes the
ttyrec. It reports the chosen action, goal, token counts, and latency.

Configuration is environment-based:

```bash
export NETHACK_AGENT_OLLAMA_URL=http://127.0.0.1:11434
export NETHACK_AGENT_MODEL=gemma4-nethack:latest
export NETHACK_AGENT_OLLAMA_TIMEOUT_SECONDS=180
```

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

## Quality checks

```bash
cd nethack-agent
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Tests use real NLE environments with scripted models; they do not need Ollama.
Behavioral changes also require a smoke run of the changed path: `smoke agent`
covers one real model decision.

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

## NetHackWiki source material

The XML dump is intentionally ignored because it is about 188 MB uncompressed. See `external/nethack-wiki-xml-dump/README.md` for acquisition and licensing, then use the coding-agent skill:

```bash
python ../_agents/skills/nethack-wiki/scripts/wiki_dump.py search "stair"
python ../_agents/skills/nethack-wiki/scripts/wiki_dump.py page "Stairs"
```

Do not put the raw dump into a model prompt. Extract a relevant page, verify the supported NetHack version and source, then write a concise cited card under `nethack-agent/knowledge/`.

## Dependency policy

`pyproject.toml` declares direct requirements; `uv.lock` is the reproducible full resolution. NLE is consumed as a package from the maintained `NetHack-LE/nle` project. Do not add a fork or submodule until a concrete engine change requires it.
