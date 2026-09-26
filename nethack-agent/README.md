# NetHack agent

This Python application domain contains the deterministic NLE adapter plus real NLE and Ollama diagnostics. The observation projector, live coordinator, persistence, control API, and web UI are milestone work tracked in [`../TODO_LIST.md`](../TODO_LIST.md).

```bash
uv sync --locked
uv run nethack-agent doctor
```

Individual checks:

```bash
uv run nethack-agent smoke nle
uv run nethack-agent smoke ollama
```

Adapter regression tests use real NLE environments:

```bash
uv run pytest -q
```

Defaults:

- environment: `NetHackStaircase-v0`;
- character: lawful dwarven Valkyrie (`val-dwa-law`);
- model: `gemma4-nethack:latest`;
- Ollama: `http://127.0.0.1:11434`.

See [`../docs/development.md`](../docs/development.md) for prerequisites and configuration.
