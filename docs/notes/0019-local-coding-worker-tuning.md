# 0019: Local coding worker tuning

Date: 2026-09-29

## Scope

Developer tooling only. This changes the local Ollama models behind OMP's
`fast` and `good` coding-worker tiers. It does not change the NetHack playing
model, gameplay policy, runtime network boundary, or evaluation configuration.

## Starting point and diagnosis

OMP session `01a0e866-fedd-7191-a297-d4c3ddf86027` created
`omp-coder:latest` from `qwen3.5:9b` (9.7B Q4_K_M) with `num_ctx` 32,768. It
routed Vibe `fast` and `good` to it with thinking `off` and `high`, capped
Ollama at one in-flight request, and set `task.maxConcurrency` to 2. In the
[note 0018](0018-agent-column-viewport-fit.md) task, those workers produced
broken edits and false completion claims.

Their session files show two harness causes:

- **Compaction loop.** Worker prompts start at about 8-9k tokens. OMP reserves
  `max(16384, 15% of window)`, so a 32,768-token window compacts at 16,384.
  The four workers compacted 1, 18, 24, and 27 times (handoff and soft). Their
  records say compaction "freed too little context to make progress": the
  model kept replacing its own history with self-written summaries.
- **Edit format.** The default `hashline` edit tool needs a copied four-hex
  snapshot tag and exact line anchors. Every tool error in the baseline rerun
  below was a failed hashline `edit`.

## Benchmark

Each run used a fresh detached worktree and a fresh `omp -p` process. That
process reads the persistent settings plus a `--config` overlay, so it needs no
`/restart`. Tasks:

- **L1, specified edits:** the four exact [note 0018](0018-agent-column-viewport-fit.md)
  edits, starting before the fix. Scored against the committed diff.
- **L2, open-ended fix:** only the bug report and constraints. Scored with
  headless Edge over CDP: `innerHeight - agent-column.bottom` at 1920x1080 on
  load and with the error banner shown. The correct value is 10.72 px in
  both; the unfixed page measures -34.28 and -67.28.
- **L3, spec to code:** implement `normalize_loopback_http_url` from a written
  specification after its body was removed. Scored by
  `tests/test_network.py` and 22 hidden inputs compared with the original
  implementation's return values, messages, and exception chaining.

"Replace" means the `edit.modelVariants: {omp-coder: replace}` overlay.
"+reserve" also set `compaction.reserveTokens: 8192`. All runs used thinking
`high` unless marked `off`.

| Run | Model, window | Settings | Min | Requests | Compactions | Tool errors | Result |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| L1 | qwen3.5:9b, 32k | defaults | 26.4 | 63 | 5 | 10 | Broken: dropped an import and `syncAgentPanel()`, no resize listener |
| L1 | qwen3.5:9b, 64k | defaults | 30.9 | 68 | 0 | 16 | Broken: lost indentation, missing function and listener |
| L1 | qwen3.5:9b, 32k | replace+reserve | 7.6 | 19 | 0 | 4 | Correct; function placed one function later |
| L1 | qwen3.5:9b, 64k | replace+reserve | 9.5 | 26 | 0 | 0 | Correct; same placement difference |
| L1 | qwen3.5:9b, 64k, off | replace+reserve | 36.5 | 56 | 0 | 0 | Exact; 77 reads, mostly repeated |
| L1 | gpt-oss:20b, 64k | apply_patch+reserve | 26.9 | 78 | 0 | 22 | Exact; called nonexistent `search`/`open` tools |
| L1 | gemma4:26b, 64k | replace | 22.0 | 32 | 0 | 1 | Exact |
| L2 | qwen3.5:9b, 64k | replace+reserve | 8.4 | 10 | 0 | 1 | Stopped after announcing a plan; no edit |
| L2 | qwen3.5:9b, 64k | replace+reserve | 14.8 | 42 | 0 | 4 | Wrong: -10.5 / -43.5 px |
| L2 | gpt-oss:20b, 64k | apply_patch+reserve | 11.5 | 25 | 0 | 2 | Wrong: removed the height; column shrank to 337 px |
| L2 | gemma4:26b, 32k | replace+reserve | 47.3 | 56 | 2 | 4 | Correct: 10.72 / 10.72 px; resize hook placed in tooltip code |
| L2 | gemma4:26b, 64k | replace | 33.6 | 21 | 0 | 1 | Tracks header and banner, but gap is 0.22 px (subtracted 0.75rem, not 1.5rem) |
| L3 | qwen3.5:9b, 64k | replace | 17.2 | 35 | 0 | 7 | Visible tests pass; hidden 15/22 (crashes without a port, drops exception chaining) |
| L3 | gemma4:26b, 64k | replace | 10.0 | 17 | 0 | 4 | Visible tests pass; hidden 20/22 (wrong message for non-loopback IPs) |

Direct Ollama throughput with a 13k-token prompt on the RTX 4070 Laptop GPU
(8 GB):

| Model | Window | Placement | Prompt tok/s | Output tok/s |
| --- | ---: | --- | ---: | ---: |
| qwen3.5:9b | 32,768 | 24% CPU / 76% GPU, 7.2 GB | 1487 | 17.9 |
| qwen3.5:9b | 65,536 | 36% CPU / 64% GPU, 8.5 GB | 1092 | 9.7 |
| qwen3.5:9b | 98,304 | 45% CPU / 55% GPU, 9.8 GB | 874 | 7.4 |
| gemma4:26b | 32,768 | 76% CPU / 24% GPU, 19 GB | 197 | 18.1 |
| gemma4:26b | 65,536 | 80% CPU / 20% GPU, 19 GB | 192 | 16.9 |

Larger Qwen 3.5/3.6 MoE and coder models are 17 GB or more at Q4 and exceed
this machine's 8 GB VRAM plus 15 GiB WSL memory once the worker and OS are
counted. `gpt-oss:20b` fit but was slower and less reliable than gemma4, so it
was removed.

## Decision

- The `replace` edit variant is required. With `hashline`, even the 64k
  window failed the fully specified task. All four specified-edit runs with
  `replace`, and the one `apply_patch` run, produced working code.
- Both worker models use `num_ctx` 65,536. There the default reserve puts
  compaction at 49,152 tokens. The thinking-`off` Qwen run peaked at 52,720
  and would have compacted once; every other run stayed under 43k. Setting
  `compaction.reserveTokens: 8192` (threshold 55,705) is therefore optional.
  It affects only windows below about 109k tokens, so cloud models are
  unchanged.
- `good` should use `omp-coder-large:latest` (gemma4:26b). It was the only
  model to solve the open-ended task (one of two runs) and scored best on spec
  to code.
- `fast` should keep `omp-coder:latest` (qwen3.5:9b) with thinking on. It is
  the quickest reliable executor of fully specified edits. Thinking `off`
  produced the same result four times slower, through repeated reads.

Recipes: `_agents/models/omp-coder/Modelfile`,
`_agents/models/omp-coder-large/Modelfile`, and the overlay
`_agents/models/omp-local-worker.yml`. The out-of-repository copy
`~/.omp/ollama/omp-coder.Modelfile` was removed in favor of the versioned
recipe. Both tags are built. `omp-coder:latest` keeps its name, so the
persisted roles already select the 64k Qwen model. A fresh
`omp -p --config _agents/models/omp-local-worker.yml --model
ollama/omp-coder-large:latest` smoke called `read` and returned the recipe's
`65536`; its assistant records named `provider=ollama,
model=omp-coder-large:latest`, and `ollama ps` showed 19 GB at 80% CPU /
20% GPU with context 65,536.

## Settings awaiting approval

The persistent OMP settings could not be changed unattended: the approval
prompt for `compaction.reserveTokens` timed out, and OMP forbids retrying
without the user. These keys are still required:

```yaml
edit:
  modelVariants:
    omp-coder: replace
modelRoles:
  fast_worker: ollama/omp-coder:latest:high
  good_worker: ollama/omp-coder-large:latest:high
```

The two models do not fit in memory together. Alternating `fast` and `good`
requests reloads a model each time (about 30 s, plus reprocessing the prompt
at gemma4's 190 tokens/s), so avoid running both tiers concurrently.

## Lessons

- Diagnose local-model failures from session records before blaming model
  size. Here the harness (compaction threshold and edit format) caused most
  failures.
- Fully specified edits are now reliable. Open-ended design and spec-to-code
  work remain partial even with gemma4:26b. Every result still needs checking
  against tests, hidden cases, or a browser, never against the worker's own
  report.
- Small models sometimes end a turn after announcing a plan. In `omp -p`, that
  ended the run with no edit (the first Qwen L2 run). Vibe workers instead
  receive OMP's idle reminder.
