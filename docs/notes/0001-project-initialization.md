# 0001: Project initialization

Date: 2026-09-26

## Discussion

The repository is both product source and durable project memory. Top-level entries stay limited to orientation and governance documents plus independently extractable domain directories. The first domain is `nethack-agent/`; a future NLE fork may become another top-level directory only if package integration proves insufficient.

Product choices established during scope review:

- autonomous ascension is the ultimate goal;
- the first runnable capability is a local-model `NetHackStaircase-v0` agent;
- the milestone gate is at least 6 successes on 10 fixed seeds, including seed 6;
- fixed beginner-friendly character;
- hierarchical model plus deterministic action gate;
- `gemma4-nethack:latest` through Ollama, with no gameplay network access beyond loopback;
- structured decision trace in a local web UI with start, pause, step, and stop;
- SQLite event history plus NLE ttyrec files;
- one inference repair retry followed by a paused, inspectable error;
- no self-modification during runs or evaluation suites.

## Environment evidence

- Python 3.12.3, uv 0.12.17, and CMake 3.28.3 are installed.
- Ollama server reports 0.23.1 while the client reports 0.34.4; model/API behavior must be tested rather than inferred from the client version.
- Installed models include `gemma4-nethack:latest` (9.6 GB), generic `gemma4` variants, and `gemma4:26b` (17 GB).
- GPU: NVIDIA GeForce RTX 4070 Laptop GPU with 8188 MiB VRAM.
- Maintained NLE 1.3.0 supports Python 3.10–3.13, Gymnasium 1.2.0, NetHack 3.6.7, task environments, and ttyrec output. The maintained repository had commits in April and June 2026.
- The ignored NetHackWiki current-page dump is present at `docs/external/nethack-wiki-xml-dump/nethackwiki_current.xml` and is about 188 MB.

## Decisions and lessons

The original Facebook repository is not the dependency target: it was archived, while the `NetHack-LE` continuation is maintained. A package pin is cheaper and easier to reproduce than a premature source fork.

The wiki dump is useful source material but unsuitable as direct LLM context. Coding agents need streaming extraction tools; playing agents need compact reviewed cards with citations. These are separate knowledge products and must not share an unreviewed generated corpus.

A web UI cannot promise hidden model chain-of-thought. The observable contract is a structured trace: state summary, goal, candidates and scores, chosen action, concise rationale, latency, and token counts.

## Bootstrap deliverable

The initialization creates current architecture and roadmap documents, decision and history records, a pinned Python package, real NLE/Ollama diagnostics, and a streaming wiki-dump inspection skill. The live agent, event store, and UI remain explicitly tracked milestone work rather than empty scaffolds presented as complete.

## Verification

- `uv lock` resolved nine packages and `uv sync --locked` installed NLE 1.3.0.
- Ruff lint and format checks passed.
- The NLE smoke created `NetHackStaircase-v0` with `val-dwa-law`, seed 6,
  deterministic time effects, and a 10-step cap; reset and one action completed
  on a 79×21 map with 23 action indices.
- The wiki tool streamed the local dump, found staircase-related titles, and
  extracted the `Staircase` page.
- The loopback guard rejected `https://example.com`; the isolated NLE smoke
  still ran with that invalid Ollama setting.
- Ollama metadata checks found the configured model, but generation did not
  run. The 0.23.1 server attempted to launch an incompatible runner and timed
  out after 180 seconds. An isolated 0.34.4 server then failed immediately
  because `/usr/local/lib/ollama/llama-server` is missing, proving the upgrade
  is incomplete. Repairing and restarting the system-wide installation requires
  administrator authentication unavailable to the coding session. The
  diagnostic now reports the default endpoint's client/server mismatch before
  attempting generation.
- After Ollama was reinstalled and restarted, the complete `doctor` path passed:
  NLE reset/step and a real `gemma4-nethack:latest` generation through Ollama
  0.34.4. The cold check took 68.45 seconds.
