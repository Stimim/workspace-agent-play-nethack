# NetHack agent

This Python application domain contains the deterministic NLE adapter, observation projector, flat coordinator with a deterministic action gate, and structured Ollama decision model, plus real NLE and Ollama diagnostics. Hierarchical skills, knowledge cards, persistence, the control API, the web UI, and the evaluation suite are milestone work tracked in [`../TODO_LIST.md`](../TODO_LIST.md).

```bash
uv sync --locked
uv run nethack-agent doctor
```

Individual checks:

```bash
uv run nethack-agent smoke nle
uv run nethack-agent smoke ollama
uv run nethack-agent smoke agent   # one real model decision and NLE step
```

Regression tests use real NLE environments and scripted models; they do not require Ollama:

```bash
uv run pytest -q
```

Defaults:

- environment: `NetHackStaircase-v0`;
- character: lawful dwarven Valkyrie (`val-dwa-law`);
- model: `gemma4-nethack:latest`;
- Ollama: `http://127.0.0.1:11434`.

See [`../docs/development.md`](../docs/development.md) for prerequisites and configuration.
