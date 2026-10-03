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

### OMP local coding model

Every local OMP role uses the Ollama model `omp-coder:latest`; this is
developer tooling, separate from the playing agent's `gemma4-nethack:latest`.
Its recipe derives from `gemma4:26b` (26B-A4B MoE) with `num_ctx` 65,536:

```bash
ollama create omp-coder:latest --file _agents/models/omp-coder/Modelfile
omp models refresh   # OMP caches Ollama discovery
```

Current global OMP routing:

```yaml
modelRoles:
  default: anthropic/claude-opus-5-5
  fast_worker: openai-codex/gpt-6-luna:auto
  good_worker: openai-codex/gpt-6-sol:auto
  smol: ollama/omp-coder:latest:off
  tiny: ollama/omp-coder:latest:off
  commit: ollama/omp-coder:latest:off
task:
  agentModelOverrides: {sonic: "@fast_worker", task: "@good_worker"}
  maxConcurrency: 2
providers:
  maxInFlightRequests: {ollama: 1}
edit:
  modelVariants: {omp-coder: replace}
disabledProviders: [google-antigravity]
```

Vibe `fast`/`good` and the `sonic`/`task` subagents use the OpenAI worker
roles; only `smol`, `tiny`, and `commit` use the local model. The
`omp-coder` `replace` edit variant therefore applies to those local roles.
The legacy `retry.fallbackChains` entries for Gemini, `smol`, and `tiny` still
point to `omp-coder-smol:latest`
(`_agents/models/omp-coder-smol/Modelfile`, gemma4:e4b at 8,192 tokens); keep
that tag until those chains are removed.

On the RTX 4070 Laptop GPU (8 GB), gemma4 keeps attention and shared weights on
the GPU (about 5 GB) and its expert weights in RAM (14.3 GB). It generates
about 17 tokens per second and reads prompts at about 190 tokens per second.
Ollama runs one active conversation per loaded model, but saves displaced
conversations in an 8 GiB RAM prompt cache and restores them. Interleaved
requests can therefore resume without re-reading; the server log reports a
65,536-token cache limit. The playing model cannot stay loaded alongside it.

A running OMP session keeps the settings and model catalog it started with, so
run `/restart` after changing them. Without a restart, a fresh process from a
checkout or a `git worktree` of it picks up the current configuration:

```bash
omp -p --model ollama/omp-coder:latest --thinking high "<task>"
```

Add `--mode json --session-dir DIR` to keep a transcript. Check every worker
result yourself (diff, tests, browser); worker reports are not evidence. The
benchmarks and decisions are in
[note 0019](notes/0019-local-coding-worker-tuning.md).

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

Without `--task`, a run executes the staircase task. `run start --task FILE`
and `scenario run --task FILE` instead send the strict `TaskSpec` JSON object
in `FILE` ([ADR 0004](decisions/0004-traversal-goals-and-task-progression.md)):

```json
{
  "environment": "NetHackScore-v0",
  "action_profile": "nle-task-actions",
  "objective": {
    "legs": [
      {"kind": "reach_level", "level": {"dungeon_number": 0, "dungeon_level": 3}}
    ]
  }
}
```

`environment` is the NLE task id and `action_profile` names the code-defined
action tuple handed to NLE (only `nle-task-actions`, NLE's `TASK_ACTIONS`,
exists). `NetHackStaircase-v0` accepts only its single
`stand_on_stairs(down, any)` leg; `NetHackScore-v0` accepts any 1-8 legs of
`stand_on_stairs`, `reach_level`, and `enter_dungeon`. Scout, Gold, Eat, and
Oracle are rejected until their objectives exist. Unknown or duplicate keys
and invalid values fail before the service is contacted. The run record
stores the spec in `runs.task` and returns it as `run.task`; runs stored
before tasks existed return `null`. The coordinator's objective planner turns
the legs into typed goals; on `NetHackScore-v0` a completed last leg ends the
run with outcome `objective_complete`, while `NetHackStaircase-v0` still ends
on NLE's own success. For example, from `nethack-agent/`, with the JSON above
in `/tmp/descend.json`:

```bash
uv run nethack-agent scenario run --seed 4 --max-steps 600 --auto \
  --task /tmp/descend.json --development-scripted-model \
  --data-dir /tmp/nethack-traversal --port 8011 --timeout 300 --json
```

Seed 4 first probes the Gnomish Mines `>` on dungeon level 2, climbs back by
the recorded branch link, and reaches (0, 3) through the main `>` identified by
elimination. Each stair use is a `MiscDirection.DOWN` or `UP` step whose
intent names the staircase identity and level.

Every task receives NLE's own option choice plus `autoopen` (Gold's is
`pickup_types:$`). The episode cap is enforced by Gymnasium's `TimeLimit` and
always ends as `truncated`; NLE's own abort is set one step later so it never
fires first, including above NLE's 5,000-step default.

### Browser UI

While `serve` is running, open <http://127.0.0.1:8000/> (or the chosen loopback
host and port). The page is served by the control service itself; it needs no
build step, extra dependency, or network access. The full-width control panel
starts a run (seed, max steps, auto start), attaches to an existing run id, and
pauses, resumes, single-steps, or stops the attached run. `#run=RUN_ID` in the
URL reattaches after a reload. Starting while another run is active shows the
service's 409 detail; stop the active run first. Runs from before a service
restart are shown read-only.

The workspace keeps the run/map/player (50rem) and inventory (30rem) columns at
fixed widths; agent information consumes the remaining width (at least 24rem).
At viewport widths of 1520 CSS px or less, use **Agent info** to open that third
column as an overlay instead of squeezing the map or inventory. The breakpoint
is the 107rem three-column layout (columns, two gaps, and workspace padding) at
the 14 px root font size plus 22 px for a vertical scrollbar; `app.css` and
`NARROW_AGENT_QUERY` in `view.js` must change together. Wider viewports keep the
sticky agent column inside the viewport before page scroll: `syncHeaderOffset`
in `view.js` publishes the control panel's height plus any shown error banner as
`--header-offset` on load, on resize, and when the banner changes, and the
column's height subtracts it. The overlay closes with
its Close button, the dimmed background, or Escape. Its Events, Messages, Tools,
and Verbose tabs support click and arrow-key navigation. Every tab has an
independent auto-scroll checkbox. Messages lists each non-blank game message
(trimmed, repeats kept) with its observation step and event sequence.
Events and evidenced deterministic-execution rows expand on click; the newest
step decision is expanded by default. Tools lists only step events that record
`deterministic_skill` or `deterministic_prompt` as their selection source and
an executed action. Verbose shows game messages and concise trace text, not raw
model responses; each summary previews its first text field. Focus or hover
dotted field and goal/skill labels for their accessible explanations; Escape
dismisses a shown tooltip, and a second Escape closes the narrow overlay.

The map preserves NetHack colors and highlights the player independently. It
uses the observation's explicit `pet_rows` mask to distinguish pets from wild
animals; pet status is never inferred from the displayed character. Runs
recorded before pet evidence existed (such as the milestone 1 suite data)
still attach, with `pet_rows: null` meaning unknown, and show no pet highlight.
The projector uses glyph identity, rather than character matching, to display
boulders as `0` and ghost-class monsters as `X`; stored older rows keep the
characters they were recorded with.

Player state is a compact semantic description-list grid. At the normal 50rem
primary-column width it places three labeled stat cells per row, while
auto-fitting to two or one column if the container is constrained; Conditions
spans the full grid. Every field and focusable field tooltip remains available,
and abilities use the full Strength, Dexterity, Constitution, Intelligence,
Wisdom, and Charisma labels. Each inventory item begins with a visible `[B]`,
`[U]`, `[C]`, or `[?]` marker derived from the typed observation `buc` field,
with a distinct class and focusable tooltip; the panel repeats those markers in
a textual legend. `unknown` means no explicit leading beatitude adjective was
present, including for records written before this evidence field existed.

The map also shows the intent recorded by the step event that carries the
displayed observation: a dashed accent box marks the destination the
deterministic skill works toward (frontier, remembered downstairs/upstairs,
search spot, locked door, displayed gold, or fresh corpse), and a solid
danger-colored box marks the monster it attacks. The player highlight wins
over both boxes, the attack-target box wins over the destination box on the
same cell, and a pet keeps its fill under either box. The legend under the
map explains each highlight, and the expanded step decision in Events shows
the same **Intent** with an explanatory tooltip. Corpse evidence there names
the killed species, kill turn, age, cell, and observable meal result; prompt
answers can carry that typed evidence without a map destination. Model
fallbacks and records before intents existed (such as the milestone 1 suite)
show "none recorded"; the UI never infers targets from action directions or
rationales.

When the step followed a route, the map also tints the recorded path: the
cells from the one the hero stepped into to the destination (for a locked
door, the cell beside it), with a faint accent background and dotted
underline. It is the breadth-first route the skill computed and moved along
on that step, not a route rebuilt in the browser. The player, attack-target,
and destination highlights win over the tint, and a pet keeps its fill under
it. The **Show path** checkbox beside the legend hides only the tint; it is on
by default, remembered per browser in `localStorage`
(`nethack-agent.showPath`), and redraws without refetching. The expanded step
decision shows a **Path** row such as `8 steps: (44, 4) to (37, 5)`. Waiting,
searching, kicking, adjacent-hostile defense, prompt answers, model fallbacks,
and events recorded before paths existed (including intents recorded without
a `path`) show "none recorded" and no tint.

For a no-Ollama UI check, serve with the scripted development model on a
scratch data directory:

```bash
uv run nethack-agent serve --development-scripted-model \
  --data-dir /tmp/nethack-ui --port 8010
```

Assets live in `src/nethack_agent/ui/` and are listed in the `_UI_ASSETS`
allowlist in `api.py`; add any new file there. `app.js` is the run controller,
`view.js` owns DOM/panel/tab/focus/tooltip behavior, `event-log.js` owns the
bounded logs, `render.js` owns rendering, and `client.js` owns transport. The
Content-Security-Policy permits only same-origin scripts, styles, images, and
connections, so do not add inline scripts, inline `style`/`on*` attributes, or
external URLs, and insert model or game text with `textContent`.
`tests/test_ui.py` enforces the headers and full served module graph, checks
these asset rules, and executes renderer classification, ability labels,
inventory BUC cues, map highlight precedence, path tint and toggle, and intent
selection behavior with Node.js when Node is available.

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

## Evaluation suites

Suite schema 2 pins the policy version and reviewed knowledge-bundle id and
contains one or more cases. Evaluation loads that exact named bundle from the
repository `nethack-agent/knowledge/` directory and passes it to the in-process
`RunManager`; it does not use the service default for a pinned suite. A missing
or invalid pinned bundle fails before the run store, report, or first episode
is created. Schema-1 suites have no knowledge pin and retain the default bundle.
Each case supplies a strict typed `TaskSpec`, its own seeds and step cap, and
its success threshold. Suite-wide acceptance still requires the configured
limits on invalid actions and gate rejections and, for the committed suites,
complete SQLite and ttyrec records. Policy mismatches are also rejected before
creating run data.

Policy `hierarchical-traversal-v1` and knowledge bundle
`staircase-reviewed-v3` have two committed suites:

- `nethack-agent/evaluation/staircase-v2.json` reruns the milestone staircase
  regression on seeds 1–10 at the established 1,000-step cap. It requires at
  least six successes, including seed 6.
- `nethack-agent/evaluation/traversal-v1.json` uses held-out seeds 700–704 and a
  1,000-step cap for three `NetHackScore-v0` objectives: descend the main
  dungeon to `(0, 3)` (at least 3/5), descend there and return to `(0, 1)` (at
  least 3/5), and enter dungeon 2, the Gnomish Mines (at least 2/5). Those
  thresholds were fixed from separate development-only probes on seeds
  600–604 before any committed-suite episode ran; the suite file records the
  observed probe counts and cap rationale.

The first real-model reports are
`nethack-agent/evaluation/reports/staircase-v2-20260928T013844Z.json` (10/10,
accepted) and
`nethack-agent/evaluation/reports/traversal-v1-20260928T013929Z.json` (complete
but not accepted: 3/5, 3/5, and 1/5 by case). Both have zero invalid actions,
gate rejections, and integrity failures. Preserve the failing traversal report;
do not tune the fixed suite after observing it.

The survival-policy, `hierarchical-task-progression-v1`, and current
`hierarchical-task-specialists-v1` checkouts run the same knowledge bundle but
refuse both schema-2 suites above before creating a data directory because
their policy pin is immutable. Reproduce them only from the recorded
traversal-policy commit, with a fresh data directory. Do not rerun, rewrite, or
relabel their reports as later-policy evidence. Policy
`hierarchical-task-progression-v1` instead has its own regression suites,
`evaluation/staircase-v3.json` and `evaluation/traversal-v2.json`, which repeat
the cases, seeds, caps, and thresholds above under new suite ids; they, and the
`scout-v1` and `eat-v1` baselines, are in turn refused by earlier policies.

Policy `hierarchical-survival-exit-v1` runs its own regression suites, `staircase-v4`, `traversal-v3`, `scout-v2`, and `eat-v2`, plus a schema-3 `descend-d5-v1` suite. To run them with the real model, use `uv run nethack-agent eval run --suite evaluation/<suite>.json --data-dir <dir>`.

Those committed suites continue to pin `staircase-reviewed-v3`; their
historical reports and rendered bytes are unchanged. Other runs through
`serve`/UI and the client-side `run` commands retain the default bundle and
cannot override it.

A case may also declare typed `metric_thresholds` (metric, statistic, and an
`at_least`/`at_most` bound). A case with at least one threshold may set
`min_successes` to 0, which is how Scout and Eat, tasks without an NLE success
state, are gated as baselines. Suites with an `explore_dungeon` objective or
any `exhausted_level` marker are audited by replaying the coordinator's memory
(`replay.ExplorationReplay`); an unconfirmed marker is an integrity failure.

The first task baselines are `evaluation/scout-v1.json` (Scout, seeds 900-904,
`explore_dungeon(3)`) and `evaluation/eat-v1.json` (Eat, seeds 920-924,
`explore_dungeon(5)`), both with a 2,000-step cap, `min_successes: 0`, and
metric thresholds fixed from scripted probes on seeds 800-804 and 820-824
before their first episode; the suites and
[note 0017](notes/0017-scout-and-eat-task-suites.md) record the probe
distributions and threshold rule. Their single real-model reports, and those of
`staircase-v3` (PASS 10/10) and `traversal-v2` (FAIL, enter-mines 1/5), are in
`nethack-agent/evaluation/reports/` with timestamps `20260928T0914*`,
`20260928T091827Z`, and `20260928T092011Z`; do not rerun or retune them.

`evaluation/staircase-v1.json` likewise remains the schema-1 milestone record
bound to policy `hierarchical-explore-v1`. To reproduce that historical suite,
check out commit `3211405` in a separate worktree and use a fresh data
directory: older strict readers cannot read newer typed traversal events, and
mixing policies in one run store defeats per-policy evidence.

### Representative seeds and the used-seed ledger

`nethack-agent/evaluation/representative-seeds.json` is the reviewed catalog of
representative seeds
([ADR 0005](decisions/0005-early-survival-and-seed-evaluation.md) section 2).
Each entry names one seed, its `TaskSpec` and step cap, the behavior it
represents, its provenance, a permanent test when one exists, and its
expectation: `must_pass` or `known_failure`, with the outcome the scripted
development model produced when the expectation was set. The strict JSON is the
source of truth; regenerate the human-readable table after every edit:

```bash
uv run nethack-agent eval catalog render
```

`tests/test_seed_catalog.py` fails when `representative-seeds.md` is stale.
Check every entry against the current checkout with the scripted development
model (about three minutes; never evaluation evidence):

```bash
uv run nethack-agent eval catalog check --data-dir /tmp/nh-catalog-check
```

The command writes a development report with one single-seed case per entry
under `DATA_DIR/reports`, prints one line per entry, and exits nonzero if any
entry fails. An entry fails when its run has an integrity problem, an invalid
action, a gate rejection, or an error, or when a `must_pass` entry does not
succeed with its recorded outcome. A `known_failure` that now succeeds is
reported as `IMPROVED`, and one that ends with a different outcome as
`CHANGED`; both exit zero but mean the catalog must be updated in the same
change as the policy change that caused it, with a note.

`nethack-agent/evaluation/seed-ledger.json` records the seeds that probes and
development runs have used, as sources with explicit seeds or inclusive ranges.
`seed_catalog.used_seeds()` unions it with every committed suite's seeds and the
catalog; fresh seed samples must exclude that set.

### Suite schema 3: baselines and fresh samples

Schema-3 suites can contain ordinary fixed-seed `cases`, a `baseline` with
catalog `entry_ids`, a `fresh_sample`, or a combination. Baseline entries are
resolved from `representative-seeds.json` beside the suite; each retains its
catalog task, seed, cap, and `must_pass`/`known_failure` expectation. The
catalog's policy pin must match the suite, and its content hash is recorded and
checked at the end. For example, a development-only fixture can use:

```json
{
  "schema_version": 3,
  "suite_id": "small-fresh-fixture",
  "character": "val-dwa-law",
  "policy_version": "hierarchical-task-specialists-v1",
  "knowledge_bundle_id": "staircase-reviewed-v3",
  "seed_selection": "Fixture: catalog anchor plus unused sample.",
  "step_cap_rationale": "Four-step fresh runs; catalog baseline keeps its cap.",
  "baseline": {"entry_ids": ["staircase-anchor-6"]},
  "fresh_sample": {
    "case_id": "fresh-staircase",
    "task": {
      "environment": "NetHackStaircase-v0",
      "action_profile": "nle-task-actions",
      "objective": {
        "legs": [
          {"kind": "stand_on_stairs", "target": {
            "direction": "down", "connection": "any", "dungeon_number": null
          }}
        ]
      }
    },
    "max_episode_steps": 4,
    "count": 2,
    "range": [1000000, 2147483647],
    "acceptance": {"min_success_rate": 0.5}
  },
  "acceptance": {
    "max_invalid_actions": 0,
    "max_gate_rejections": 0,
    "require_complete_records": true
  }
}
```

Run with `uv run nethack-agent eval run --suite /tmp/small-fresh-fixture.json
--data-dir /tmp/nh-fresh --development-scripted-model --draw-seed 29`; keep
`representative-seeds.json` and `seed-ledger.json` beside the fixture.
To compare baseline episodes, rerun with
`--compare-report /tmp/nh-fresh/reports/<first-report>.json`. The second draw
excludes the first report's fresh seeds even with the same draw seed. The
previous report must be schema 4 for the same suite *digest*; changing the
fixture requires a new suite id rather than silently comparing different
tasks. Before any episode the JSON and Markdown report pair records the draw
seed, ordered drawn seeds, and the excluded-seed snapshot, so that seed draw
can still be reconstructed after the ledger grows. `--seeds` cannot override
a fresh sample.

Report schema 4 separates catalog baseline acceptance (no `must_pass`
regressions; report `known_failure` improvements/changes), fresh rate plus
optional metric gates and a 95% Wilson interval, and suite-wide integrity.
`--compare-report` adds the paired per-entry baseline outcome/success diff to
both the Markdown report and ordinary CLI output. Fresh samples from distinct
draws must be compared by rates/intervals, not as paired seeds. A scripted
development report is never real-model milestone evidence; the real
`descend-d5-v1` suite and run are later work. Historical report schemas 2-3
continue rendering byte-for-byte
([note 0022](notes/0022-suite-schema-3-fresh-samples.md)).


Progress lines go to stderr every `--progress-interval` seconds (default 30).
Each invocation reserves a new `<suite>-<UTC timestamp>.json` and `.md` pair in
the report directory (default `DATA_DIR/reports`), rewrites that pair (mode
0644) after each seed, and never replaces an earlier report. `--json` prints the
final report and its paths. The command exits 0 when the report is written,
including when acceptance fails; read `acceptance.passed` and
`acceptance.milestone_accepted`. It exits 1 for configuration or Ollama
readiness errors and 130 after `Ctrl+C`, which stops the active run and records
an `interrupted` report.

Report schema 3 groups results by case and records traversal metrics for every
episode: turns, depths and exact levels, stair traversals and probes, objective
legs, return, final character state, hunger states, and an xlog death cause
when available. Episodes evaluated since task progression also record
`explored_cells` and `worst_hunger_state`, and a case with metric thresholds
records each computed value and result. Markdown is rendered from the JSON;
keep both files together. Historical schema-2 reports and schema-3 reports
written before these fields remain renderable, byte for byte, without
rewriting them.

Newly recorded episode metrics additionally contain the all-or-none
`steps_by_skill` (executed selection skill, including prompts and fallbacks),
`search_steps` (executed `Command.SEARCH` actions), `first_hungry_turn` (first
live Hungry-or-worse turn), and `hunger_at_death` (last live hunger before a
death, null for nondeath or no live evidence). Older reports omit all four,
which is different from recording zero SEARCH steps. A `hunger_at_death`
maximum `at_most: 2` gate rejects Weak/Fainting-or-worse deaths, and a required
gate fails for missing evidence; recorded nondeaths count as zero. Report
schema 4 renders a per-case diagnostics table only for uniformly newly
recorded results, not for historical results. See
[note 0023](notes/0023-early-hunger-failure-diagnostics.md) for the read-only
event-log analysis of the 18 failed episodes.

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

`nethack-agent/knowledge/manifest.json` is still the active
`staircase-reviewed-v3` bundle. It allowlists cards in prompt order and pins
each card's SHA-256. The separate
`manifest.survival-reviewed-v1.json` selects reviewed hunger/prayer and
conservative corpse cards without changing the current policy or any suite
pin. `manifest.survival-reviewed-v2.json` keeps `v1` byte-identical and
reuses its `stairs-traversal`, `exploration-map`, and `prayer-hunger` cards,
replacing the fresh-corpse card with `safe-corpses-v2` (widened species,
lichen's nonrotting/pet-moved exemption, conditional jackal/fox/coyote) and
adding `nutrition-foraging` (ration/fruit variants, non-shop floor-food
collection, undead-garlic). The bundle id names its survival scope; explicit
selection requires
`load_knowledge_bundle(Path(\"knowledge\"), bundle_id=\"survival-reviewed-v2\")`.
The selected context is 5,985 characters / 1,497 estimated tokens (`v1` is
5,917 / 1,480); both omit the older `safe-interaction` card to stay below the
existing 6,000 / 1,500 budget. Card edits require updating the selected
manifest's hash and bumping that bundle id for semantic changes (do not
mutate committed-report pins):

```bash
cd nethack-agent
sha256sum knowledge/prayer-hunger.md knowledge/safe-corpses-v2.md knowledge/nutrition-foraging.md
uv run pytest -q tests/test_knowledge.py
uv run python -c 'from pathlib import Path; from nethack_agent.knowledge import load_knowledge_bundle as l; b=l(Path(\"knowledge\"), bundle_id=\"survival-reviewed-v2\"); print(b.version, b.character_count, b.estimated_tokens)'
```

The service loads and validates the bundle once at startup, then records its
content-derived version on every run. Ollama skill and fallback-action prompts
include only its bounded facts and non-goals. Card metadata, the raw dump, and
unlisted files are not injected. See `nethack-agent/knowledge/README.md` for the
card schema, sources, and CC BY-SA 3.0 attribution.

The default remains fixed until a later policy version explicitly adopts the
survival bundle. Source revisions and the corrected <=19-turn corpse age rule
are reviewed in [note 0024](notes/0024-reviewed-survival-knowledge.md).

### Survival action profile and prompt gate (milestone 2, item 6)

Choose `nle-survival-actions` in a `TaskSpec` to keep all 58
`nle-hunger-actions` members, then append `Command.PRAY` and `Command.PICKUP`
(60 indexed actions). The profile preserves ration handling and the existing
task objective. Item 6 defined the roles and gate without a prayer or corpse
issuer; item 7 enabled prayer, item 8 enabled strictly verified fresh-corpse
eating, and note 0033 added the food-pickup role for reviewed non-shop floor
comestibles. The active knowledge bundle, `POLICY_VERSION`, and published
evaluation suites remain unchanged.

In NLE 1.3.0, the exact observed confirmation messages (the space before each
closing quote is part of the raw observation) are:

```text
"Are you sure you want to pray? [yn] (n) "
"There is a lichen corpse here; eat it? [ynq] (n) "
```

Both have a single-character-choice prompt. The floor-corpse string was
captured after killing a seed-10 lichen, moving onto its corpse, then issuing
EAT; the prayer string was captured by issuing PRAY on seed 6 in a direct
NLE-environment test. Those tests bypass the agent gate to inspect NLE, not to
grant the policy permission to answer. The item-7 gate allows PRAY only with
the coordinator's evidence-backed prayer permit, and answers only its exact
pending confirmation with a matching typed prompt permit. Item 8 adds a
separate exact-name fresh-corpse confirmation; all other floor-corpse
confirmations are declined. In the survival profile, the model is not offered
ambiguous `y`/northwest.
An exact eat-item prompt can still offer inventory letter `y`, and ordinary
deterministic northwest movement outside a prompt remains legal. The evaluator
replays the gate predicates against the prior recorded observation, including
the offered item-letter and ration evidence. See
[note 0025](notes/0025-survival-action-profile-and-prayer-gate.md).

### Deterministic Weak-hunger prayer (milestone 2, item 7)

On `nle-survival-actions`, a verified inventory food ration is eaten first;
safe adjacent-hostile defense takes precedence over PRAY to avoid praying for
three helpless turns under attack. With no safe ration, prompt, or observed
altar, `PrayerSkill` may pray at Weak-or-worse hunger from game turn 100:
the nominal initial timeout is 300, and `300 - 100 = 200 < 201`, the major
trouble threshold. Any repeat must wait at least 1,229 game turns after the
previous PRAY, regardless of the previous result. That post-prayer bound
covers only 95% of resets and is not a guarantee about hidden timeout, Luck,
alignment record, or divine anger. No model prompt offers PRAY.

The coordinator records prayer count and most recent PRAY turn, plus the count
of literal observed `You kill` messages as an **ungated** proxy for hidden
alignment record. A typed intent records the Weak trigger, prayer turn, bound,
proxy count, and first live confirmation outcome. The outcome is `fixed` if
hunger drops below Weak or the stomach-content message appears,
`displeased/punished` for the observed anger or punishment messages, or
`not fixed` when prayer finishes without fixing hunger. Terminal/truncated
confirmations have no live outcome because NLE zeroes terminal statistics.
The evaluator rebuilds the history from events and independently checks each
PRAY and exact `y` response against the gate's predicates.

Real NLE development probes on seeds 1100–1109 fixed hunger on 2/5
SEARCH-only first-Weak prayers with no kills; 1110–1129 fixed it on 11/11
first-Weak prayers reached by the fighting coordinator (9 died before Weak).
Both groups are development evidence, not a success-rate promise or fresh
evaluation seeds. See [note 0026](notes/0026-deterministic-prayer-and-probe-evidence.md)
for per-seed outcomes, turn-50 and immediate-repeat controls, the reviewed
Prayer-page explanation, and the residual uncertainty.

### Fresh-corpse eating (milestone 2, item 8)

`nle-survival-actions` adds a deterministic corpse skill, not another NLE
action. Priority is safe adjacent-hostile defense, eligible Weak prayer,
verified inventory ration at Hungry or worse, then an eligible corpse before
stairs or exploration. A known ration still preempts prayer under its existing
no-ration safety guard. Never start eating while Satiated (NLE hunger 0);
Not Hungry or worse permits use of a fresh corpse before the first Hungry turn.

Lichen, newt, sewer rat, giant rat, gecko, garter snake, hobbit, goblin,
iguana, and shrieker qualify; jackal, fox, and coyote qualify too, only
without public lycanthropy evidence (the "You feel feverish" message or a
were-creature bite) and without polymorph, since eating them while sharing a
werejackal's species is cannibalism ([note 0033](notes/0033-reviewed-nutrition-probes.md)).
The coordinator records an actual `You kill the <name>!` combat observation
and its monster cell, at most 19 game turns old on the current level (lichen
alone is exempt from this cap, since it never rots). It routes only to a
visible corpse on that cell through at most five passable BFS steps. On
arrival, `EAT` needs an exact `You see here a <name> corpse.` clause in the
look-here message (possibly after a door or stair clause), matching the
own-kill identity; an inventory prompt instead of a floor offer is canceled
with ESC. A pet can drag a corpse off its kill cell before the hero arrives;
only lichen may then still be eaten, identified at its new cell by this same
exact text, without any kill-turn or age provenance, since it alone needs
none. Only the immediately following exact
`There is a <name> corpse here; eat it? [ynq] (n) `
prompt for the **same** species receives `y` through
`PromptPermit(y, CORPSE_CONFIRMATION)`. A `partly eaten` corpse uses the same
identity, age, and confirmation checks after an interruption. Other floor
offers are declined.

NLE 1.3.0 runs eating occupations to their end or interruption within one
environment step. No meal-continuation WAIT or persistent meal latch exists,
so eating cannot suppress a later eligible prayer or ration decision. Every
live confirmation records `finished`, `interrupted`, or `ended_unrecognized`;
the last kind means the step ended but its final public message does not prove
completion or interruption (including rotten food or a later unrelated message).
Declines record `declined`; terminal/truncated answers carry no live outcome.
An interrupted corpse remains eligible to resume only while fresh and identified.
See [note 0029](notes/0029-corpse-meal-lifecycle-and-hunger-death-diagnosis.md).
The evaluator rebuilds kill provenance, age, identity, and prompt matching
from event observations rather than accepting the intent on trust.

The historical observation analysis found 54 fresh nearby opportunities worth
5,426 potential nutrition on 25 previously stored episode records at Not Hungry
or worse. Its five-square Chebyshev filter was not proof of a passable route,
unlike the implemented five-action BFS limit. The opportunities
included 35 / 4,284 nutrition before their first Hungry turn. Requiring
Hungry or worse instead yielded only four / 432 nutrition opportunities.
These are **opportunities**, not completed meals or an evaluated survival
success rate. See [note 0027](notes/0027-safe-fresh-corpse-eating.md)
for species counts, source revisions, real-NLE regression, and caveats.

Seed 1131 is the real-NLE scripted-coordinator regression: lichen kill at
turn 3 while Not Hungry; a pet then drags the corpse off its kill cell after
a food-ration pickup, so the hero eats it at its new cell by the untracked
look-here identity alone, completing at turn 14 with Satiated hunger, and
zero invalid evaluator actions or gate rejections. Development seeds
1130-1149 are reserved in the used-seed ledger. Seed 1300 is the companion
regression for a later, different-species kill landing on the exact cell of
an earlier untracked lichen sighting: the stale same-cell kill record must
not shadow the still-valid lichen identity actually displayed there
([note 0033](notes/0033-reviewed-nutrition-probes.md)).

To exercise corpse identity, meal-end outcomes, nutrition priority, and
terminal/truncated replay boundaries:

```bash
uv run pytest -q tests/test_coordinator.py -k 'corpse or seed_1131 or seed_1300'
uv run pytest -q tests/test_evaluation.py -k corpse
```

Seeds 1150–1169 are also excluded as development probes: bounded-search probe
at `a58902a`, coordinator, `reach_level(0,5)`, cap 3000. They are not fresh
acceptance-suite seeds.

### Floor-food foraging and ration variants (milestone 2, items 8/9)

[Note 0033](notes/0033-reviewed-nutrition-probes.md) adds a deterministic
`FoodSkill`, not another NLE action beyond `Command.PICKUP`. A held, partly
eaten identified ration, cram ration, K-ration, C-ration, lembas wafer, or
reviewed fruit/vegetable is still itself; the hunger skill resumes it rather
than treating it as unknown. On the main-dungeon level, an identified
reviewed comestible on a non-shop floor cell within a passable route of at
most five steps is collected with `Command.PICKUP` while unburdened,
confirmed only against the exact native pickup-menu text (`PickupMenu`,
parsed from the public `tty_chars` grid, since NLE exposes no structured
pickup-menu field); otherwise it is eaten from the floor only at Hungry or
worse, confirming only the exact offered item text. The coordinator and the
evaluator share the same `food_action_error` predicate. Garlic nourishes an
ordinary hero normally; an undead hero only vomits from eating one, so the
skill skips garlic while the hero is itself undead (own glyph's public
`M2_UNDEAD` flag).

```bash
uv run pytest -q tests/test_skills.py tests/test_evaluation.py -k food
```

## Dependency policy

`pyproject.toml` declares direct requirements; `uv.lock` is the reproducible full resolution. NLE is consumed as a package from the maintained `NetHack-LE/nle` project. Do not add a fork or submodule until a concrete engine change requires it.

## Exit discovery probes (item 9)

[Note 0031](notes/0031-exit-discovery-probes.md) replaces the unqualified SEARCH
cap work with measured exit-discovery changes. The main-dungeon exploration
skill can force known locked route gates only while downstairs are unknown,
with at least 10 HP, hunger better than Weak, no closed-inventory or known
shop/shopkeeper evidence, and fewer than eight direction-confirmed kicks.
It records observed WHAMM/opened/Ouch outcomes and shares its predicate with
the runtime gate and persisted-run evaluator. Engravings have no separate
public field; only their text when emitted in messages is available. Shop
greetings require the native possessive-owner form, not an XP-level welcome.

Visited open doors can now be search stands for a blank outward extension.
Unvisited walkable object-covered cells are visited while downstairs are
unknown; existing look-here staircase recognition supplies the hidden terrain.
There is no per-level SEARCH cap and no new corridor-priority tier: the
development rerun solved 1237 without rank 4.

Seeds 1240–1269 are registered development seeds, excluded from future fresh
samples. The unchanged preregistered comparison improved objectives 19→23,
deaths 5→4, hunger deaths 2→0, with zero invalid actions, gate rejections,
and integrity problems. The complete per-seed tables, original shop-parser
probe, corrected comparison, and 14-seed development rerun are in note 0031.
This is feature qualification, not milestone/real-model acceptance.
`POLICY_VERSION` remains unchanged; item 10 owns versioning and the next
held-out committed suites.

A frontier-first covered-cell fallback, bounded route-cycle abandonment, shop
exclusion, and adjacent-attack peacefulness invalidation were then probed on
seeds 1270-1299: objectives improved 20→23 and total deaths improved 6→4, but
two seeds died Fainting that had not before, failing the frozen hunger-death
gate; the candidate did not qualify
([note 0032](notes/0032-exit-discovery-correction-probes.md)). Paired with
the reviewed nutrition package on seeds 1300-1329, the same correction still
did not qualify (objectives 20 against the nutrition-only package's 24, and a
hunger death the nutrition-only package avoided); only the nutrition package
shipped ([note 0033](notes/0033-reviewed-nutrition-probes.md)). Runtime and
tests for both unqualified attempts were restored; only their notes and the
seed ledger were committed.
