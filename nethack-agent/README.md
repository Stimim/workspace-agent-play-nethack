# NetHack agent

This Python application domain contains the deterministic NLE adapter, observation projector, flat coordinator with a deterministic action gate, structured Ollama decision model, SQLite run/event store, and a loopback HTTP/WebSocket control service with a CLI client. Hierarchical skills, knowledge cards, the web UI, and the evaluation suite are milestone work tracked in [`../TODO_LIST.md`](../TODO_LIST.md).

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

Run control through the local service:

```bash
uv run nethack-agent serve --data-dir data   # http://127.0.0.1:8000
```

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
