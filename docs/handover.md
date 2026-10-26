# Handover

Status and working notes for the next coding agent (for example Claude Code,
`claude.exe`). Read this after `AGENTS.md`, `README.md`, `ARCHITECTURE.md` and
`TODO_LIST.md`. Facts here were current on 2026-10-26 (notes 0063 and 0064
recorded); `TODO_LIST.md` and the notes stay authoritative when they
disagree.

## 1. Where the project stands

- **Shipped policy:**
  `hierarchical-survival-hp-prayer-burden-look-ration-explore-first-v1` (note
  0061, explore-before-search), knowledge `survival-reviewed-v2`. Its
  baseline was `22d0a5f` (note 0051).
- **Milestones:** 1 accepted; 2 evaluated, acceptance failed (notes 0036, 0046);
  3 (ADR 0007: enter the Minetown temple, and stand next to the peaceful
  Oracle, in two separate suites) **paused** for **3A in progress** (ADR 0008,
  2026-10-25): reach the next staircase without single-level stalls over
  1,000 turns.
- **Current numbers** (scripted development model):

  | Suite | Objectives | Deaths | Weak-or-worse deaths |
  | --- | --- | --- | --- |
  | minetown-regression-v3 (67) | 24 | 39 | 10 |
  | oracle-regression-v3 (67) | 13 | 49 | 7 |
  | unified-d5-regression-v6 (67) | 54 | 5 | 0 |
  | Minetown fresh 635-664 (30) | 13 | 15 | 0 |
  | Oracle fresh 635-664 (30) | 8 | 21 | 5 |

  Stalled runs (one level stay over 1,000 turns): 26 / 25 / 11 of 67 and
  12 / 10 of 30 fresh. ADR 0008 asks for at most 10 / 10 / 11 and 4 / 4.

- **0061 explore-before-search: QUALIFIED and shipped.** This is the first
  rule to add objectives on both targets. It works because it cuts stalls.
  Its lost successes defer a shallow level whose target is behind a secret
  passage and then search the nearest range level without a bound. That is
  the next rule's class.
- **0063 search-spot ping-pong and 0064 sessile blockers: both NOT
  QUALIFIED** in development (notes 0063, 0064; no fresh seeds spent). Each
  removed its waste of turns (spot switches down about 70%; blocker waits
  from thousands to a few dozen), but stalled runs did not fall. The freed
  turns became searches that do not find the exit, and Minetown
  Weak-or-worse or starvation deaths rose. The bottleneck is where the hero
  searches.
- **What the earlier rule attempts showed:** every survival-only or
  escape-only rule moves deaths around instead of adding objectives.
  - 0052 slime-mold food: REJECTED. More food, but stalls still burn it.
  - 0053 ranged clearing of floating eyes and gas spores: paused. The hero
    has one dagger, so it gets one shot.
  - 0054 stall budget: unqualified. Leaves stalls, then dies deeper, often
    hungry.
  - 0057 Elbereth disengage: REJECTED. Fewer deaths, but objectives fell and
    resting caused more Weak-or-worse deaths.
  - 0059 rest + stall budget combined: NOT QUALIFIED after three development
    passes (note 0059). Pass 3 passed Minetown (19 objectives, 37 deaths) and
    Oracle (14, 50) but failed D5 (53, 6, 3 Weak-or-worse). No fresh seeds
    spent.
- **Root cause:** the death analysis (note 0056, Phase 3 section; raw data in
  `~/nethack-evidence/0055-death-analysis/`). Deeper levels kill a weak hero
  (median XL 3-5, AC 6) that keeps fighting at low HP with prayer on cooldown.
  Long single-level stalls consume the food. Rest and stall reduction appear
  to need each other.

## 2. Decisions waiting for the project owner

1. **Next gameplay step: decided** (owner, 2026-10-25). Milestone 3A
   (ADR 0008): Phase 1 diagnosis done (note 0060). The first Phase 3 rule,
   explore-before-search, is shipped (note 0061; seeds 635-664 consumed).
   Note 0062 diagnosed what remains. Rules 0063 (search-spot ping-pong)
   and 0064 (never waiting on sessile blockers) were NOT QUALIFIED in
   development (notes 0063, 0064). Next: search ranking, starting from a
   re-measure of note 0062's route classes. The baseline arms at the
   shipped commit are in `~/nethack-evidence/0062/base-*-reg` (worktree
   `~/nethack-evidence/0062/baseline`). Candidate 0059 was recorded NOT
   QUALIFIED (note 0059). Fresh seeds 665-694 are the next unused range; check with
   `used_seeds` first.
2. **Verification process: decided** (ADR 0008 §4, Phase 2): stall
   diagnostics (`stalls.py`, done) and long-cap Minetown/Oracle stall seeds in
   the representative-seed catalog. A noise margin for the paired gates
   remains open.
3. **Commit provenance for Claude Code: decided.** Claude Code commits by
   itself (owner decision, 2026-10-20) with
   `_agents/skills/omp-commit/scripts/omp_commit.py claude-commit
   --message-file FILE`. It runs the guard and checks and adds one
   `Claude-Session: <id>` trailer beside `Co-Authored-By:`, so `claude
   --resume <id>` reopens the conversation (AGENTS.md rule 9,
   `_agents/skills/omp-commit/SKILL.md`). `omp_commit.py commit` refuses to
   run inside Claude Code: outside OMP it falls back to the single live OMP
   session. That is why commit `5892159` (the 0055 evidence record) carries
   the OMP orchestrator's `OMP-Conversation` trailer; it was actually made by
   Claude Code session `ebfd92cf-38da-48d2-b9b3-fb2d860347f9`.
4. **Optional cleanups:** fix Markdown list formatting in 18 older docs (ADR
   0004, notes 0044/0049/0050, ...); trim README "Project status" history.

## 3. Work in flight (not in `main`)

Candidate code lives in git worktrees outside the repository. Each branch is
committed with a `Qualification-Exempt` trailer. The older candidate
branches were pushed to `origin` on 2026-10-25; the 0063 and 0064 branches
are not pushed yet.

The baseline for the next qualifications is `~/nethack-evidence/0062/baseline`,
detached at `9783a7e`, with regression arms on `*-regression-v3` and
`unified-d5-regression-v6` in `~/nethack-evidence/0062/base-*-reg`. They
reproduce the 0061 candidate outcome for outcome. The 0052 baseline reports
describe the old policy.

| Worktree | Branch (base `22d0a5f`) | State | Record |
| --- | --- | --- | --- |
| `~/nethack-evidence/0064/candidate` | `rule-0064-sessile-blockers` (base `e9dde72`, `8480bb1`) | NOT QUALIFIED after 1 development pass; may be re-measured on top of search ranking | note 0064 |
| `~/nethack-evidence/0063/candidate` | `rule-0063-search-spot-commitment` (base `e9dde72`; passes `b69f4eb`, `2781989`, `6a210f5`) | NOT QUALIFIED after 3 development passes | note 0063, `~/nethack-evidence/0063/DEV.md` |
| `~/nethack-evidence/0061/candidate` | `rule-0061-explore-before-search` (base `e1a232b`) | QUALIFIED; shipped to `main` as one commit with the shipped label | note 0061, `~/nethack-evidence/0061q/` |
| `~/nethack-evidence/0057/candidate` | `rule-0057-elbereth-disengage` | rejected, frozen | note 0057 |
| `~/nethack-evidence/0059-rest-stall/candidate` | `rule-0059-rest-plus-stall-budget` (0054 + 0057, then fixes to `afc3282`) | NOT QUALIFIED after 3 development passes | note 0059, `~/nethack-evidence/0059-rest-stall/DEV.md` |
| `~/nethack-evidence/0054/candidate` | `rule-0054-no-progress-budget` | rejected with 0059; its later bug fixes live on the 0059 branch | `~/nethack-evidence/0054/STATUS.md`, note 0059 |
| `~/nethack-evidence/0053/candidate` | `rule-0053-ranged-clearance` | paused (needs ammunition) | note 0056, `implementation-report.json` |
| `~/nethack-evidence/0052/candidate` | `qualify-0052-slime-mold` | rejected | note 0052 |
| `~/nethack-evidence/0052/baseline` | detached at `22d0a5f` | shipped baseline with its own `.venv` | reused by 0057 |

The death-analysis evidence record is committed (`5892159`,
`docs/notes/evidence/0055/`). Its recount gave 18 of 21 mid-fight prayers
healing the hero, not the 17 first reported; note 0056 is corrected.
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
   actions, gate rejections and integrity failures.
   `_agents/skills/evidence-record/compare.py` computes these per pair and
   lists every changed seed. Trace every lost success and new death. A
   behavior change after launch spoils the sample.
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
# ADR 0008 stall and loop diagnostics from paired run databases (read-only)
uv run --project nethack-agent python3 _agents/skills/evidence-record/stalls.py \
  --pair NAME BASE_DIR/runs.sqlite3 CAND_DIR/runs.sqlite3 --output OUT.json
# compact per-seed record for a report
uv run --project nethack-agent python3 _agents/skills/evidence-record/record.py REPORT.json \
  --commit SHA --command "CMD" --output docs/notes/evidence/NNNN/NAME.json
# paired ADR 0007 gates and changed seeds; repeat --pair for each set
uv run --project nethack-agent python3 _agents/skills/evidence-record/compare.py \
  --pair NAME BASE_REPORT.json CAND_REPORT.json --base-commit SHA \
  --output docs/notes/evidence/NNNN/paired-comparison.json
# checks (from nethack-agent/)
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

### Limits and known pitfalls

- **Host:** about 15 GB RAM and 20 cores. 10 arms of 2 workers each, plus an
  idle analysis kernel holding 2.2 GB, pushed it into swap. Run at most 5 arms
  at once with 2 workers each. Close SQLite connections and reset Python
  kernels after analysis. Each step event is about 22 KiB, so a 67-seed arm
  is a database of 2-4 GB; `~/nethack-evidence` holds roughly 100 GB.
- **`/tmp` is a RAM-backed tmpfs (7.8 GB)** on this host, so files there use
  memory. Keep evaluation data, databases and detached state under
  `~/nethack-evidence/`, never in `/tmp` or a session scratchpad. The host
  hung on 2026-10-26 with about 15 GB in use (cause unconfirmed; earlyoom is
  now installed).
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
