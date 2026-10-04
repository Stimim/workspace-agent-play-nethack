# NetHack Agent

Local-first research and engineering project whose north star is an autonomous
NetHack ascension. Online coding agents may develop and debug the software; the
playing agent uses local models and must remain offline.

## Repository map

```text
.
├── AGENTS.md          # instructions for coding agents
├── ARCHITECTURE.md    # current system design and invariants
├── TODO_LIST.md       # prioritized product work and acceptance gates
├── docs/
│   ├── decisions/     # durable architecture decision records
│   ├── notes/         # chronological development history and lessons
│   └── external/      # acquisition notes for uncommitted source material
├── _agents/           # skills, tools, and model recipes for online coding agents
└── nethack-agent/     # local player application and runtime knowledge
```

The top level stays small. New top-level directories must represent a domain
that could plausibly become its own repository or submodule.

## Bootstrap

Prerequisites: Python 3.12, `uv`, CMake 3.28+, Ollama, and the local
`gemma4-nethack:latest` model.

```bash
cd nethack-agent
uv sync --locked
uv run nethack-agent doctor
```

`doctor` performs a real NLE reset/step and a short local Ollama generation.
See [`docs/development.md`](docs/development.md) for configuration and isolated
checks.

## Project status

Developer bootstrap, the deterministic NLE adapter, observation projection,
hierarchical coordinator, reviewed local knowledge cards, typed SQLite event
contracts, local control surface, headless scenario orchestration, and
executable network-boundary verification are implemented. Each run executes a
typed task spec (NLE task, action profile, and objective legs). An objective
planner turns the legs into typed goals: stand on, or traverse, a staircase of
a direction with a main or branch identity
([ADR 0004](docs/decisions/0004-traversal-goals-and-task-progression.md)).
Deterministic staircase-navigation and exploration skills serve the goals over
dungeon memory that keeps each visited level. `staircase_navigation` routes to
a remembered reachable staircase matching the goal and waits on it or uses
it, first fighting a safe adjacent hostile. `explore_level` walks to
unexplored space, opens or kicks doors, fights adjacent hostiles, and searches
for hidden passages. On bounded `nle-hunger-actions` runs, the hunger skill
eats an exactly recognized inventory ration only at Hungry or worse. On
`nle-survival-actions`, deterministic prayer handles eligible Weak hunger
after a conservative timeout, and a separate skill routes at most five
steps to a verified fresh allow-listed corpse at Not Hungry or worse.
`EAT`, `PRAY`, prompt-only keys, and their exact confirmation answers are
permit-gated away from model fallbacks. A deterministic arbiter switches
between traversal and survival skills; the local model is consulted at the
start, when exploration is stuck, and for unhandled prompts. The staircase
task never changes level. Runs expose the current goal and skill, stream
typed events through the loopback service and CLI, and keep bounded scenarios
and network verification reproducible.

The first product milestone requires this hierarchy to succeed on at least 6
of 10 fixed `NetHackStaircase-v0` seeds, including seed 6, while recording
SQLite events and ttyrecs and streaming the decision trace to a local web UI.
With the local `gemma4-nethack:latest` model, the committed suite
(`nethack-agent/evaluation/staircase-v1.json`) passed its acceptance gate with
10/10 task successes and complete records
(`nethack-agent/evaluation/reports/staircase-v1-20260926T211301Z.md`), and the
dependency-free browser UI is served by the same loopback service, so milestone
1 is accepted. A deterministic arbiter picks skills; the model is consulted at
the start, on stuck exploration, and for unhandled prompts
([ADR 0002](docs/decisions/0002-deterministic-skill-arbiter.md)). The exact
acceptance contract and boundaries are in [`ARCHITECTURE.md`](ARCHITECTURE.md);
work is tracked in [`TODO_LIST.md`](TODO_LIST.md).

Since acceptance, the browser UI has gained a redesigned agent column with
Events, Messages, Tools, and Verbose tabs, explicit ability labels, inventory
BUC evidence cues, pet highlighting, `0`/`X` boulder and ghost symbols, and map
annotations for each step's recorded frontier or other destination, attack
target, and planned path. The reviewed knowledge bundle (`staircase-reviewed-v2`)
now makes `autoopen` explicit and documents covered and branch stairs from NLE
and local-wiki evidence. The committed suite with this bundle and the local
model again passed 10/10 with trajectories identical to the accepted run
(`nethack-agent/evaluation/reports/staircase-v1-20260927T065500Z.md`;
[note 0013](docs/notes/0013-review-feedback-resolutions.md)).

Milestone A of the traversal roadmap
([note 0015](docs/notes/0015-typed-traversal-goals.md)) replaced the fixed goal
with typed traversal goals, per-level dungeon memory with stair identities,
permit-gated level changes, and the `staircase-reviewed-v3` bundle. Its
committed schema-2 `staircase-v2` and `traversal-v1` suites and reports remain
immutably pinned to policy `hierarchical-traversal-v1`.

The evidence-gated combat and hunger changes in
[note 0016](docs/notes/0016-evidence-gated-survival-skills.md) are policy
`hierarchical-survival-v1`, retaining `staircase-reviewed-v3`. Policy
`hierarchical-task-progression-v1` (same bundle) added the
`explore_dungeon` objective for `NetHackScout-v0` and `NetHackEat-v0`,
evaluator-replayed exhaustion markers, and typed metric thresholds, with the
`staircase-v3` and `traversal-v2` regression suites. Policy
`hierarchical-task-specialists-v1` added deterministic gold navigation on
`NetHackGold-v0`. Policy `hierarchical-survival-hp-prayer-v1` pinned
`survival-reviewed-v2` and development runner `unified-d5-regression-v2`.
Its low-HP prayer rule qualified on development 52→54/67 and fresh
25→29/30, without retreat/rest/disengagement ([note 0043](docs/notes/0043-single-rule-prayer-qualification.md)).
Hazard-only 3b was rejected: fresh objectives 23→21/30 and seven
gas-spore trapped-state gate stops; its code was removed and prayer alone
remained shipped ([note 0044](docs/notes/0044-single-rule-hazard-qualification.md)).
Policy `hierarchical-survival-hp-prayer-burden-v1` pinned
`survival-reviewed-v2` and development runner `unified-d5-regression-v3`. It
adds observed-load-refusal recovery: drop surplus food/items (keeping one
ration, the wielded weapon, and worn equipment) until Burdened or better,
deferring to combat defense and never during an active unrelated prompt.
Two real defects found and fixed during qualification (an EAT/inventory-letter
key collision, and burden preempting combat defense) are documented, not
shipped unfixed; the qualified candidate matched baseline on every one of 97
combined development and fresh episodes with zero invalid actions, gate
rejections, or integrity failures ([note 0045](docs/notes/0045-three-single-rule-qualification.md)).
The current policy, `hierarchical-survival-hp-prayer-burden-look-v1`, pins
`survival-reviewed-v2` and development runner `unified-d5-regression-v4`. It
adds bounded look-here discovery: when an arrival message is an ambiguous
"several/many objects" pile, press the native look command once and preserve
its multi-page screen (previously silently auto-dismissed) to recognize a
covered staircase, reusing the existing terrain-correction logic unchanged.
Fresh seeds matched baseline exactly (18/30 both); the one development-set
change traced to the feature firing is a gain, not a loss (a starvation
death on seed 5 became a truncation once LOOK kept exploration moving); zero
invalid actions, gate rejections, or integrity failures on either set.
The checkout refuses
older policy-pinned suites before creating an episode; they must not be
relabeled or rerun as later-policy evidence. The task-progression policy's
single real-model runs:
`staircase-v3` passed 10/10, `traversal-v2` again missed its Mines threshold
(1/5), and the `scout-v1` and `eat-v1` baselines passed their metric gates with
no completed objective, because exhaustive search outlasts the hunger horizon
([note 0017](docs/notes/0017-scout-and-eat-task-suites.md)).

Milestone 2's design ([ADR 0005](docs/decisions/0005-early-survival-and-seed-evaluation.md))
is accepted as implemented and evaluated. Its first real-model `descend-d5-v1`
report passed (18/20 fresh objectives, no fresh hunger deaths, no must-pass
baseline regression), and `staircase-v4` and `scout-v2` passed. **Full milestone
acceptance failed:** `traversal-v3` entered the Mines only 1/5 (2/5 required),
and `eat-v2` had two starvation deaths (at most one allowed). Failed reports
are retained; acceptance remediation is next, not a rerun or retuning of
these suites ([note 0036](docs/notes/0036-milestone-2-real-model-evaluation.md),
[`TODO_LIST.md`](TODO_LIST.md)).

The first unified-survival remediation makes exit discovery goal-aware:
remembered Mines branch stairs no longer suppress guarded forcing of a main
exit gate or covered-cell checks. Reachable frontiers keep precedence when
only incompatible stairs are known. Its scripted development set improves
50/67 to 52/67 without losing an existing success; a frozen new 30-seed
comparison improves 24/30 to 27/30 with deaths unchanged. This is qualified
development evidence, not milestone acceptance. The earlier candidate that
increased qualification deaths was rejected and retained
([0037](docs/notes/0037-goal-aware-branch-gate-probes.md),
[0038](docs/notes/0038-branch-exit-frontier-preserving-probes.md)).

Under [ADR 0006](docs/decisions/0006-unified-goal-suites.md) (accepted), the
frozen policy `hierarchical-survival-hp-prayer-burden-look-v1` ran the
fresh-draw acceptance suite `descend-d5-v2` once with the real model:
16/20 reached Dlvl 5 (0.65 required) with zero invalid actions or gate
rejections, but one hero died while Fainting after a 2,700-turn stall on a
level whose main downstairs it never found. **Milestone 2 acceptance failed
again**, on the zero Weak-or-worse death gate
([0046](docs/notes/0046-descend-d5-v2-real-model-acceptance.md)). The
scripted 67-seed development set stands at 54/67.

## Documentation

Start with [`docs/README.md`](docs/README.md). Architecture documents describe
the current design, decision records explain why, and notes preserve the
development timeline without becoming stale sources of truth.
