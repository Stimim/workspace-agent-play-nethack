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

### OMP local coding fallback

OMP 18.3.2 keeps the online Gemini Flash models as the primary `smol` and
`tiny` roles. `ollama/omp-coder-smol:latest` is their ordered local fallback;
it is developer tooling, separate from `gemma4-nethack:latest`, and is never
used by the playing agent.

The reproducible model definition lives with the other coding-agent resources:

```text
_agents/models/omp-coder-smol/Modelfile
```

Build or refresh its derived tag from the repository root, then refresh OMP's
cached model catalog:

```bash
ollama create omp-coder-smol:latest \
  --file _agents/models/omp-coder-smol/Modelfile
omp models refresh
```

The definition derives from the installed generic `gemma4:e4b` 8B Q4 model
without downloading another model and fixes `num_ctx` at 8,192. On the
reference RTX 4070 Laptop GPU, a live request reports 3.2 GB and 100% GPU
residency. A larger default context caused the same model family to spill onto
CPU.

OMP caches model discovery. Until `omp models refresh` runs, the valid Ollama
tag can still be rejected as unknown and no fallback chain can advance to it.

The persistent OMP settings are global on the reference workstation
(`omp config path` prints `~/.omp/agent`; `modelRoleStorage` is `global`).
The Gemini primaries remain unchanged:

```yaml
modelRoles:
  smol: google-antigravity/gemini-3.8-flash:auto
  tiny: google/gemini-3.5-flash-lite:auto
retry:
  modelFallback: true
  waitForUsageReset: false
  fallbackChains:
    smol:
      - ollama/omp-coder-smol:latest
    tiny:
      - ollama/omp-coder-smol:latest
    google-antigravity/gemini-3.8-flash:
      - ollama/omp-coder-smol:latest
    google/gemini-3.5-flash-lite:
      - ollama/omp-coder-smol:latest
```

The persisted record also repeats the Antigravity chain for the resolved
`:minimal`, `:low`, `:medium`, `:high`, and configured `:auto` selectors, and
the Google chain for `:off`, `:minimal`, `:low`, `:medium`, `:high`, and
`:auto`. Real `cli=fast` worker metadata has selected Antigravity `:low`,
`:medium`, and `:high`; the explicit keys protect those stable resolved
selectors. The role and bare-model keys remain so ordinary role resolution and
fresh OMP processes do not depend on a particular effort. Preserve unrelated
chains, including the default model's chain, whenever editing this record.

Confirm the persistent values and locally discoverable selector:

```bash
omp config get modelRoles --json
omp config get retry.modelFallback --json
omp config get retry.waitForUsageReset --json
omp config get retry.fallbackChains --json
omp models ollama
```

`retry.modelFallback` is OMP's switch for advancing to configured models.
`waitForUsageReset: false` prevents an unattended worker from sleeping until a
multi-hour quota reset instead of trying its chain. OMP 18.3.2 exposes no
separate user-configurable error-class list. Its built-in recovery recognizes
transport errors and provider HTTP 429 usage exhaustion; authentication and
configuration failures do not become availability fallbacks. Administratively
disabling a primary provider is rejected before chain recovery and is not a
valid fallback test.

To exercise the persisted `tiny` chain without using a real Google credential,
route only cloud HTTP through a closed loopback port while leaving Ollama
reachable:

```bash
env GEMINI_API_KEY=invalid-for-fallback-smoke \
  HTTPS_PROXY=http://127.0.0.1:9 \
  HTTP_PROXY=http://127.0.0.1:9 \
  NO_PROXY=127.0.0.1,localhost \
  timeout 60s omp \
    --model @tiny \
    --no-session \
    --no-tools \
    --thinking off \
    --max-time 45s \
    --mode json \
    -p 'Reply with exactly GOOGLE_TINY_FALLBACK_OK.'
```

Inspect the JSON `message_end` records rather than trusting marker text alone.
The exercised run first recorded the failed
`provider=google, model=gemini-3.5-flash-lite` request, then the successful
`provider=ollama, model=omp-coder-smol:latest` response. On the currently
quota-exhausted Antigravity account, the analogous bounded run with
`--model google-antigravity/gemini-3.8-flash:low` recorded the real
`RESOURCE_EXHAUSTED` HTTP 429 followed by the same Ollama provider/model.

OMP loads settings into a running session. An external `omp config set` updates
the persistent file but does not update the already-running conversation's
`vibe_spawn cli=fast` launcher. In this conversation, two exact fast-worker
smokes still stopped at the `google-antigravity/gemini-3.8-flash:low` 429 with
zero tool calls, while fresh direct OMP processes used the new exact chain.
After changing these settings, run `/restart` in OMP; that supported command
relaunches OMP with its original flags and resumes the current session in
place, loading the persistent configuration. A new OMP conversation also loads
it. Verify the next session with one bounded `vibe_spawn cli=fast` task and
require its turn metadata to name
`model="ollama/omp-coder-smol:latest"` before considering the worker path
proved.

The 8,192-token window is enough for OMP's local tool protocol on bounded work:
an exercised local task used `read` on a two-line Python file, used `write` to
produce a corrected copy, and that copy executed successfully. Large delegated
tasks can still exceed this intentionally small window, and the local 8B model
is less capable than the primary. Keep fallback assignments focused and
concise. Ollama remains bound to loopback, so this fallback introduces no
additional cloud provider.

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
`NARROW_AGENT_QUERY` in `view.js` must change together. The overlay closes with
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
deterministic skill works toward (frontier, remembered downstairs, search spot,
or locked door), and a solid danger-colored box marks the monster it attacks.
The player highlight wins over both boxes, the attack-target box wins over the
destination box on the same cell, and a pet keeps its fill under either box.
The legend under the map explains each highlight, and the expanded step
decision in Events shows the same **Intent** with an explanatory tooltip. Model
fallbacks, prompt answers, and runs recorded before intents existed (such as the
milestone 1 suite data) show "none recorded" and no boxes; the UI never derives
a target from the action direction or rationale.

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
contains one or more cases. Each case supplies a strict typed `TaskSpec`, its
own seeds and step cap, and its success threshold. Suite-wide acceptance still
requires the configured limits on invalid actions and gate rejections and, for
the committed suites, complete SQLite and ttyrec records. A pin mismatch is
rejected before the evaluator creates a run store, report, or episode.

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

The current checkout runs policy `hierarchical-survival-v1` with the same
knowledge bundle. It refuses both schema-2 suites above before creating a data
directory because their policy pin is immutable. Reproduce them only from the
recorded traversal-policy commit, with a fresh data directory. Do not rerun,
rewrite, or relabel their reports as survival-policy evidence. A survival
evaluation requires a new predeclared suite id, seeds, thresholds, and policy
pin.

`evaluation/staircase-v1.json` likewise remains the schema-1 milestone record
bound to policy `hierarchical-explore-v1`. To reproduce that historical suite,
check out commit `3211405` in a separate worktree and use a fresh data
directory: older strict readers cannot read newer typed traversal events, and
mixing policies in one run store defeats per-policy evidence.

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
when available. Markdown is rendered from the JSON; keep both files together.
Historical schema-2 reports remain renderable without rewriting them.

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
sha256sum knowledge/stairs-traversal.md
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
