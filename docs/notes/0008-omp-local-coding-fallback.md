# 0008: OMP local coding fallback

Date: 2026-09-27

## Scope

This change adds a developer-only Ollama fallback for OMP coding subagents. It
does not change the NetHack playing model, gameplay policy, runtime network
boundary, or evaluation configuration.

## Inventory and decision

The workstation has 15 GiB RAM and an NVIDIA GeForce RTX 4070 Laptop GPU with
8,188 MiB VRAM. Ollama 0.34.4 initially had these tags:

- `gemma4:26b` — 25.8B Q4_K_M, 17 GB on disk;
- `gemma4:e4b` / `gemma4:latest` — the same 8.0B Q4_K_M model ID
  `c6eb396dbd59`, 9.6 GB on disk;
- `gemma4-nethack:latest` — an 8.0B gameplay tag, 9.6 GB on disk.

`gemma4:26b` cannot fit in 8 GB VRAM. The generic `gemma4:e4b` has Ollama tool
support and is preferable to coupling coding work to the gameplay-named tag.
`_agents/models/omp-coder-smol/Modelfile` therefore derives
`omp-coder-smol:latest` from `gemma4:e4b`, adds a concise coding system prompt,
and fixes `num_ctx` at 8,192. No model download was needed. The definition
belongs under `_agents/` because it configures the online coding-agent
workflow, not the `nethack-agent/` product runtime.

OMP 18.3.2 reports global model-role storage. The existing primaries remain
unchanged:

- `smol`: `google-antigravity/gemini-3.8-flash:auto`;
- `tiny`: `google/gemini-3.5-flash-lite:auto`.

Before this correction, persistent `retry.fallbackChains` preserved the
default-model chain and added only role-keyed `smol` and `tiny` chains. Real
`vibe_spawn cli=fast` metadata resolves the Antigravity model before launching
the child and has selected `:low`, `:medium`, and `:high`; those attempts
stopped at the quota error without using the role chain.

The corrected global configuration explicitly enables model fallback, leaves
multi-hour reset waiting disabled, and preserves every previous chain. It maps
both roles and both bare Gemini model selectors to
`ollama/omp-coder-smol:latest`. It also maps the supported resolved effort
selectors: Antigravity `:minimal`, `:low`, `:medium`, `:high`, and `:auto`;
Google tiny `:off`, `:minimal`, `:low`, `:medium`, `:high`, and `:auto`.
Gemini stays first because `modelRoles` is unchanged; Ollama appears only in
the ordered fallback chains.

OMP's schema accepts role names and model selectors as keys. Bare
model-oriented keys apply whenever that provider/model is active and inherit
the failing turn's effort. Explicit effort keys additionally cover the
selectors recorded by the worker launcher. `retry.modelFallback` is the
recovery switch. `retry.waitForUsageReset: false` makes an unattended worker
try recovery instead of sleeping until the reported multi-hour reset. OMP
18.3.2 exposes no separate configurable error-class list.

## Verification

The following checks were exercised after moving the model definition and
updating the persistent configuration:

- `ollama create omp-coder-smol:latest --file
  _agents/models/omp-coder-smol/Modelfile` reused the installed Gemma layers
  and wrote the derived manifest successfully. `omp models refresh` retained
  `ollama/omp-coder-smol:latest` in OMP's catalog with an 8,192-token context
  and output limit.
- A direct loopback Ollama chat response reported
  `model=omp-coder-smol:latest` and returned `OLLAMA_DIRECT_OK`. `ollama show`
  reports an 8.0B Q4_K_M model with tool capability and `num_ctx 8192`; after
  generation, `ollama ps` reported 3.2 GB, `100% GPU`, and context 8,192.
- Direct OMP selection emitted assistant metadata
  `provider=ollama, model=omp-coder-smol:latest` and returned `OMP_DIRECT_OK`.
- A fresh bounded OMP process selected the exact exhausted
  `google-antigravity/gemini-3.8-flash:low` primary. Its first assistant record
  contained the real HTTP 429 `RESOURCE_EXHAUSTED` error and reset timestamp;
  the next record reported
  `provider=ollama, model=omp-coder-smol:latest` and returned
  `LOW_SELECTOR_FALLBACK_OK`.
- A bounded `@tiny` run used a dummy test key and a closed loopback HTTP proxy,
  with `NO_PROXY` retaining local Ollama access. It first recorded
  `provider=google, model=gemini-3.5-flash-lite` with an error, then
  `provider=ollama, model=omp-coder-smol:latest` with
  `GOOGLE_TINY_FALLBACK_OK`.
- A direct local OMP coding task in a scratch directory exercised the full
  tool protocol at the configured 8,192-token window: the model called `read`
  on a two-line Python file, called `write` to create a corrected copy, and
  finished with Ollama provider/model metadata. The corrected copy executed
  successfully, and the scratch directory was removed.
- `omp config get modelRoles --json`,
  `omp config get retry.modelFallback --json`,
  `omp config get retry.waitForUsageReset --json`, and
  `omp config get retry.fallbackChains --json` read the persisted values back.

The exact already-running `vibe_spawn cli=fast` path remains an active-session
limitation, not a failure of the persisted configuration. Two bounded smokes
after the external config update still selected the parent session's
`google-antigravity/gemini-3.8-flash:low` snapshot, stopped at the same 429 in
about two seconds, made zero tool calls, and made no Ollama attempt. In the
same interval, fresh direct OMP processes used the exact chain successfully.
OMP loads these settings when the process/session starts; an external
`omp config set` does not refresh this already-running worker launcher.

OMP's supported `/restart` command relaunches it with its original flags and
resumes the current session in place. Run `/restart` (or start a new OMP
conversation) before the next `vibe_spawn cli=fast` proof. Success requires
the resulting turn metadata to identify
`model="ollama/omp-coder-smol:latest"` after the real Antigravity quota
failure; marker text by itself is insufficient evidence.

## Operational limits

- The local model has an intentionally bounded 8,192-token context and lower
  coding capability than the Gemini primaries. The exercised read/write task
  proves bounded tool use, not that large delegated tasks fit.
- OMP caches Ollama discovery. Run `omp models refresh` after every rebuild.
- OMP does not walk a chain when a provider is administratively disabled, and
  authentication/configuration failures are not availability fallbacks.
- Current OMP sessions snapshot retry/fallback settings for their worker
  launcher. Persistent changes apply to fresh processes; `/restart` is
  required before proving `vibe_spawn` from a conversation that was already
  running.
- `FROM gemma4:e4b` is portable but tag-based. The observed source model ID is
  `c6eb396dbd59`; detect an unexpected tag change before rebuilding.
- Ollama remains loopback-only. The coding fallback does not change the
  playing agent or introduce a gameplay network dependency.
