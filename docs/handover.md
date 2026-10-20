# Handover

Status and working notes for the next coding agent (for example Claude Code,
`claude.exe`). Read this after `AGENTS.md`, `README.md`, `ARCHITECTURE.md` and
`TODO_LIST.md`. Facts here were current at commit `4acf4d0` (2026-10-20);
`TODO_LIST.md` and the notes stay authoritative when they disagree.

## 1. Where the project stands

- **Shipped policy:** `hierarchical-survival-hp-prayer-burden-look-ration-v1`
  (commit `22d0a5f`, note 0051), knowledge `survival-reviewed-v2`. Later
  commits changed tooling and docs only.
- **Milestones:** 1 accepted; 2 evaluated, acceptance failed (notes 0036, 0046);
  **3 in progress** (ADR 0007): enter the Minetown temple, and stand next to the
  peaceful Oracle, in two separate suites.
- **Current numbers** (scripted development model):

  | Suite | Objectives | Deaths | Weak-or-worse deaths |
  | --- | --- | --- | --- |
  | minetown-regression-v2 (67) | 19 | 42 | 20 |
  | oracle-regression-v2 (67) | 9 | 53 | 19 |
  | unified-d5-regression-v5 (67) | 54 | 5 | 0 |
  | Minetown fresh 605-634 (30) | 9 | 19 | 5 |
  | Oracle fresh 605-634 (30) | 6 | 24 | 8 |

- **What the last four rule attempts showed:** every survival-only or
  escape-only rule moves deaths around instead of adding objectives.
  - 0052 slime-mold food: REJECTED. More food, but stalls still burn it.
  - 0053 ranged clearing of floating eyes and gas spores: paused. The hero
    has one dagger, so it gets one shot.
  - 0054 stall budget: unqualified. Leaves stalls, then dies deeper, often
    hungry.
  - 0057 Elbereth disengage: REJECTED. Fewer deaths, but objectives fell and
    resting caused more Weak-or-worse deaths.
- **Root cause:** the death analysis (note 0056, Phase 3 section; raw data in
  `~/nethack-evidence/0055-death-analysis/`). Deeper levels kill a weak hero
  (median XL 3-5, AC 6) that keeps fighting at low HP with prayer on cooldown.
  Long single-level stalls consume the food. Rest and stall reduction appear
  to need each other.

## 2. Decisions waiting for the project owner

1. **Next gameplay step.** A combined candidate (0057 resting + 0054 stall
   budget, qualified as one unit) needs a recorded ADR 0007 exception to "one
   rule per qualification". The alternatives are the optional gate amendment
   (`TODO_LIST.md` order item 3) or a different roadmap item.
2. **Commit provenance for Claude Code.** AGENTS.md rule 9 requires
   `_agents/skills/omp-commit/scripts/omp_commit.py`. It finds the conversation
   UUID from a running OMP client and refuses to commit without one. It cannot
   work from Claude Code as written. The owner must choose a replacement rule,
   for example extending the script to a Claude Code session identity, or
   committing manually. Until then, do not invent a trailer and do not bypass
   the script's checks (ruff, plus the commit guard that requires a staged
   qualification note or a `Qualification-Exempt:` trailer for
   `nethack-agent/src/` changes).
3. **Optional cleanups:** fix Markdown list formatting in 18 older docs (ADR
   0004, notes 0044/0049/0050, ...); trim README "Project status" history.

## 3. Work in flight (not in `main`)

Candidate code lives in git worktrees outside the repository. **It is
uncommitted**, so it is not backed up anywhere. Commit or push these branches
before deleting directories or reinstalling the machine.

| Worktree | Branch (base `22d0a5f`) | State | Record |
| --- | --- | --- | --- |
| `~/nethack-evidence/0057/candidate` | `rule-0057-elbereth-disengage` | rejected, frozen | note 0057 |
| `~/nethack-evidence/0054/candidate` | `rule-0054-no-progress-budget` | unqualified; two blocking bugs fixed | `~/nethack-evidence/0054/STATUS.md` |
| `~/nethack-evidence/0053/candidate` | `rule-0053-ranged-clearance` | paused (needs ammunition) | note 0056, `implementation-report.json` |
| `~/nethack-evidence/0052/candidate` | `qualify-0052-slime-mold` | rejected | note 0052 |
| `~/nethack-evidence/0052/baseline` | detached at `22d0a5f` | shipped baseline with its own `.venv` | reused by 0057 |

In the main checkout: `docs/notes/evidence/0055/` and a one-line edit to note
0056 are uncommitted output of the death-analysis evidence task. Verify them
against that task's report before committing.
`docs/feedback-2026-10-18-1138.md` is the owner's file; never edit, stage or
delete it.

0054 open items: staircase seed 1 gives up search early; T=200 versus T=400;
catalog entries 1 and 701 changed from death to truncated; ADR 0004's
"cleared on level entry" list is stale.

## 4. How work is done here

### Qualifying a gameplay rule (note 0040 protocol, ADR 0007 §4.1)

1. **Diagnose from stored evidence first.** Use `runs.sqlite3` step events,
   read-only. Native truth (`_agents/skills/native-truth/`) is for diagnosis
   only, never a policy input.
2. **Build one rule.** Use a worktree from the shipped commit with its own
   `.venv` (`uv sync --locked`). Keep a shared predicate across selection,
   ActionGate, StepPayload validation and evaluator replay. Add consumer tests
   that fail without the fix.
3. **Develop on regression suites only.** Never tune on fresh seeds. Stop
   after about three development passes: more tuning overfits.
4. **Preregister and freeze.** Use an honest qualification-only policy label;
   copy suites outside the repo, never relabelling committed ones. Reserve an
   unused contiguous 30-seed fresh range (check with
   `nethack_agent.seed_catalog.used_seeds`). Write a note with SHA-256 of
   every changed file and the gates, and run `sha256sum --check` before
   launch. Note 0057 is the most recent template.
5. **Run the arms.** Baseline regression reports from the same base commit and
   suites can be reused (0052 baseline arms). Candidate arms first, then
   baseline fresh arms.
6. **Apply the gates.** For every paired set: objectives not lower, deaths not
   higher, Weak-or-worse and starvation deaths not higher; zero invalid
   actions, gate rejections and integrity failures. Trace every lost success
   and new death. A behavior change after launch spoils the sample.
7. **Record the outcome** in the main repo, whether QUALIFIED or REJECTED:
   - the note, with a `## Decision` heading;
   - compact records under `docs/notes/evidence/<note>/`;
   - the consumed seeds in `nethack-agent/evaluation/seed-ledger.json`
     (`note` at most 300 characters);
   - updates to `TODO_LIST.md` and `docs/README.md`.
8. **To ship**, also bump `POLICY_VERSION`, pin new copies of the regression
   suites, and update README and ARCHITECTURE (see note 0051).

### Commands

```bash
# detached evaluation; never let a tool deadline cut a run short
_agents/skills/detached-eval/scripts/detached_eval.py --state-dir DIR start --name RUN \
  --cwd WORKTREE/nethack-agent -- nice -n 15 ionice -c 3 uv run nethack-agent eval run \
  --suite SUITE --data-dir OUT --report-dir OUT/reports --workers 2 --development-scripted-model
_agents/skills/detached-eval/scripts/detached_eval.py --state-dir DIR wait RUN   # or status/list/stop
# compact per-seed record for a report
uv run --project nethack-agent python3 _agents/skills/evidence-record/record.py REPORT.json \
  --commit SHA --command "CMD" --output docs/notes/evidence/NNNN/NAME.json
# checks (from nethack-agent/)
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

### Limits and known pitfalls

- **Host:** about 15 GB RAM and 20 cores. 10 arms of 2 workers each, plus an
  idle analysis kernel holding 2.2 GB, pushed it into swap. Run at most 5 arms
  at once with 2 workers each. Close SQLite connections and reset Python
  kernels after analysis. Each step event is about 22 KiB, so a 67-seed arm
  is a database of about 2 GB; `~/nethack-evidence` holds roughly 100 GB.
- **`/tmp` is cleared by restarts.** A restart killed the first 0051 runs. The
  NetHack 3.6.7 source used for citations is at `/tmp/nethack-3.6.7-src` (the
  `NetHack-3.6.7_Released` GitHub tag), and NLE 1.3.0 source at
  `/tmp/nle-1.3.0`. Download them again if missing. Keep detached state
  directories under `~/nethack-evidence/`.
- **Don't pipe `detached_eval.py wait` into `head`:** the broken pipe kills
  the waiter, though not the run.
- **`eval run --seeds` fails on multi-case suites** with "requested case seeds
  must be unique and nonempty". Make a one-case suite copy instead.
- **Suite files:** they need `acceptance` blocks, and `min_successes` must be
  at least 1. Use the schema of `evaluation/minetown-fresh-v1.json` for
  fresh suites.
- **Flaky test:** `tests/test_detached_eval.py::test_detached_process_survives_starting_parent_exit`
  fails occasionally. Rerun it once before investigating.
- **Verify worker claims.** Workers' reports have contained wrong counts (the
  0051 Weak-or-worse count) and accidental `git checkout` reverts. Check every
  number against the actual report, database or diff before committing
  (AGENTS.md rule 10).

## 5. Tooling and UI available

- **Browser UI and service:** `uv run nethack-agent serve --data-dir data
  [--goal staircase|reach-d5|minetown|oracle|FILE]`. The default goal is
  `oracle`.
  - Click any step in the Events tab to view its map, stats and inventory.
    Only the last 50 events are loaded on attach.
  - Use the speed control, or `run speed RUN_ID X`, to follow a run live.
- **Skills** in `_agents/skills/`: `detached-eval`, `evidence-record`,
  `native-truth`, `nethack-wiki`, `omp-commit`.
