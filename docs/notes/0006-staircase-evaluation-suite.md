# 0006: Staircase evaluation suite and first real-model run

Date: 2026-09-27

## Scope

- `nethack-agent/evaluation/staircase-v1.json` commits the milestone suite:
  - suite seeds 1–10, fixed before any suite episode ran;
  - a 1,000-step episode cap;
  - acceptance: at least 6 `task_success` outcomes with seed 6 among them,
    zero invalid NLE actions, zero action-gate rejections, and complete SQLite
    and ttyrec records.
- The step cap matches the earlier documented trajectory smoke. It bounds a
  real-model suite at 10,000 hierarchical actions.
- `nethack_agent.evaluation` and `nethack-agent eval run` execute the suite,
  audit every run, and write a new timestamped JSON and Markdown report pair.
- `OllamaClient` now sends an explicit `num_ctx`: default 8,192, set with
  `NETHACK_AGENT_OLLAMA_NUM_CTX`. It also rejects generations that could have
  been silently truncated.

## Decisions

- **In-process `RunManager`, not scenario orchestration.** The evaluator calls
  `create_run(auto_start=True)` on one `RunManager` per suite. That is the same
  coordinator, worker loop, gate, store, and ttyrec path the HTTP service uses.
  Over multi-hour runs it avoids port allocation, HTTP request timeouts during
  slow inference, and child-process lifecycle failures. It also reads the
  authoritative SQLite log directly for auditing.
- **The suite never intervenes in an episode.** A run that pauses after a
  decision failure or gate rejection is stopped and scored as recorded; it is
  never resumed.
- **Fixed configuration is checked.** Acceptance fails unless all runs share
  model, policy, knowledge version, NLE version, environment, character, step
  cap, and `ollama_num_ctx`. It also fails if the suite or knowledge files
  change during the run.
- **Seed 6 must be among the successes.** "Including seed 6" in the milestone
  contract is read strictly, as `required_success_seeds: [6]`.
- **Gate rejections are inferred from the event log.** They are `agent_error`
  events in `paused` without a decision-failure trace, because only decision
  failures and gate rejections pause the coordinator.
- **Invalid actions are counted independently.** Every stepped action is
  compared against the recorded legal-action table and the descend ban.
- **Reports are never overwritten.** Each invocation reserves its names with
  exclusive creation, adding `-2`, `-3`, … on collision. It then atomically
  rewrites only its own pair after every seed, so an interrupted run leaves a
  valid partial report.
- **Explicit `num_ctx`.** The first real attempt was started without it. Ollama
  then used the Modelfile's 131,072-token context and placed the model
  64% CPU / 36% GPU. That attempt was stopped after about 20 steps and
  discarded. Its partial report and data are kept outside the committed
  report directory, under the ignored
  `nethack-agent/data/evaluations/invalid-num-ctx-131072/`.
- **Truncation guard.** `num_ctx` is recorded per run (`runs.ollama_num_ctx`)
  and in the report configuration. A reported `prompt_eval_count` plus the
  requested output tokens above `num_ctx` raises `OllamaContextLimitError`.
  That counts as a failed attempt under the one-repair policy, and the
  attempt diagnostics keep its token counts.

## Measurements after capping the context

- `ollama ps`: `gemma4-nethack:latest`, 3.2 GB, 100% GPU, context 8,192. With
  the 131,072 default it had been 9.1 GB, 64%/36% CPU/GPU.
- Warm `smoke agent` on seed 6 (skill selection plus one fallback): 6,693 ms
  total, 2,514 prompt tokens, 369 output tokens.
- In the suite, one fallback decision uses about 1,620 prompt tokens and
  ~220 output tokens. Seed 1's decision latency was p50 6.4 s, p95 9.5 s,
  max 19.1 s, so a truncated seed takes about 1.9 h.

## Suite run (aborted)

- Command, from `nethack-agent/`:
  ```bash
  uv run nethack-agent eval run --suite evaluation/staircase-v1.json \
    --data-dir data/evaluations/staircase-v1 --report-dir evaluation/reports \
    --progress-interval 120
  ```
- Started 2026-09-26T18:11:51Z in the committed seed order 1–10, as persistent
  process `staircase-eval-ctx8192`.
- Report pair, rewritten after every seed:
  `nethack-agent/evaluation/reports/staircase-v1-20260926T181151Z.{json,md}`.

| Seed | Outcome | Steps | Wall s | Model decisions | p50 ms | p95 ms | Max ms | Prompt/output tokens | Skill/prompt/model | Repairs | Gate rej. | Invalid | Integrity |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | --- |
| 1 | truncated | 1000 | 6860.2 | 1001 | 6402 | 9494 | 19139 | 1636689/240582 | 0/0/1000 | 6 | 0 | 0 | ok |
| 2 | stopped (interrupted) | 156 | 1053.1 | 157 | 6673 | 7680 | 8768 | 256244/36691 | 0/0/156 | 0 | 0 | 0 | ok |
| 3–10 | not run (suite aborted) | | | | | | | | | | | | |

Seed 1 never saw a downstairs, so every action was a model fallback. The
actions were:

| Action | Count |
| --- | ---: |
| wait | 615 |
| long-move south | 190 |
| search | 69 |
| eat | 45 |
| north | 37 |
| `MiscDirection.UP` | 35 |
| other moves | 9 |

The hero stayed on dungeon level 1. The ttyrec exists, `ollama_num_ctx` is
8,192, and Ollama is 0.34.4.

**Outcome.** The operator stopped the run with SIGINT at 2026-09-26T20:22Z,
during seed 2 (156 steps, interrupted). `eval abort` finalized the report as
`aborted`, with reason "policy replaced before completion". The recorded
results are unchanged. Note 0007 covers the replacement policy and its passing
suite run.

## Verification

- `uv run pytest -q`: 144 passed. New tests cover:
  - suite validation;
  - nearest-rank percentiles;
  - acceptance: threshold, required seed, gate, invalid-action, integrity,
    configuration, partial, interrupted, and development cases;
  - report aggregation and the non-overwriting writer;
  - real-NLE development-model evaluator runs, with tampered-event and
    missing-ttyrec detection;
  - `num_ctx` validation and the truncation guard, including its failed-attempt
    accounting;
  - migration of an existing SQLite store.
- `uv run ruff check .` and `uv run ruff format --check .` passed.
- `eval run --development-scripted-model --seeds 6,1` and `--seeds 2` smoke
  runs produced audited reports with integrity OK. They are harness evidence
  only.

## Limitations and follow-ups

- The exploration policy is weak. With no visible downstairs, the model mostly
  waits or repeats one direction. `MiscDirection.UP` is allowed by the gate; on
  the level-1 upstairs it would leave the dungeon and end the game. Changing
  the policy requires a new suite run, not a mid-suite edit.
- Latency is dominated by about 220 output tokens per fallback decision
  (candidates plus reasons).
- Ollama at temperature 0 on a GPU is not guaranteed bit-for-bit deterministic
  across runs.
- The truncation guard relies on Ollama's reported `prompt_eval_count`. If a
  cached prompt prefix makes Ollama under-report, the guard cannot detect
  truncation.
- The running process was started before report files were made
  world-readable. `eval abort` rewrote its report pair at mode 0644.
