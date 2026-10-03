# 0036: Milestone 2 real-model evaluation

Date: 2026-10-04

## Configuration and preflight

The committed suites at `2b76177` ran once each, serially, in this order:
`staircase-v4`, `traversal-v3`, `scout-v2`, `eat-v2`, `descend-d5-v1`.
Policy `hierarchical-survival-exit-v1`, bundle `survival-reviewed-v2`, model
`gemma4-nethack:latest`, Ollama 0.34.4, NLE 1.3.0, lawful dwarven Valkyrie,
and `num_ctx` 8192 stayed fixed. Gameplay used loopback Ollama only.
No suite, episode, or failed decision was manually retried or replaced; no
harness invocation crashed. All reports are complete. Data remains ignored
under `nethack-agent/data/evaluations/`.

Preflight from `nethack-agent/`: `uv run nethack-agent doctor`, then
`ollama ps` and `nvidia-smi`. Doctor reported:

```text
OK   ollama: Ollama 0.34.4; model gemma4-nethack:latest; local generation completed (2 output tokens)
```

`ollama ps`:

```text
NAME                     ID              SIZE      PROCESSOR    CONTEXT    UNTIL
 gemma4-nethack:latest    abaff763e771    3.2 GB    100% GPU     8192       4 minutes from now
```

`nvidia-smi` reported NVIDIA-SMI 615.71.08, KMD 616.92, CUDA UMD 13.4,
RTX 4070 Laptop GPU, 5710 MiB / 8188 MiB, 2% utilization, and:

```text
|  No running processes found                                                             |
```

WSL's process display did not expose the Ollama runner; `ollama ps` showed
only the playing model loaded, not a coding model.

## Commands and draw

Each command ran from `nethack-agent/`, without a scripted-model flag:

```bash
uv run nethack-agent eval run --suite evaluation/staircase-v4.json --data-dir data/evaluations/staircase-v4 --report-dir evaluation/reports
uv run nethack-agent eval run --suite evaluation/traversal-v3.json --data-dir data/evaluations/traversal-v3 --report-dir evaluation/reports
uv run nethack-agent eval run --suite evaluation/scout-v2.json --data-dir data/evaluations/scout-v2 --report-dir evaluation/reports
uv run nethack-agent eval run --suite evaluation/eat-v2.json --data-dir data/evaluations/eat-v2 --report-dir evaluation/reports
uv run nethack-agent eval run --suite evaluation/descend-d5-v1.json --data-dir data/evaluations/descend-d5-v1 --report-dir evaluation/reports
```

No `--draw-seed` was supplied. The documented default selected draw seed
`2304745538` with `secrets.randbits(32)` before any episode and persisted its
provenance in the report. The ordered fresh seeds are:

```text
1259450733, 643863903, 1703050900, 1354866613, 1063911084,
279714031, 1807224773, 799362204, 2065672237, 1887524929,
1077361413, 1195605202, 1009099699, 1528054415, 2105401147,
2014004543, 1003301977, 296200318, 2094095407, 1840248764
```

The inclusive range was `[1000000, 2147483647]`; its excluded-seed snapshot
was empty because all previously used seeds lay outside that range. The
committed schema-4 report in `evaluation/reports/` makes these fresh seeds
excluded by future draws automatically (note 0022); a duplicate ledger entry
is unnecessary. Reports retain the original draw snapshot after later draws.

## Results

Reports are JSON plus rendered Markdown in
`nethack-agent/evaluation/reports/`, with the stems below. Episode wall time
is the report aggregate; invocation wall time includes setup and auditing.

| Suite | Successes | Fixed gates and observed values | Result | Model decisions | Latency p50/p95/max (ms) | Episode / invocation wall (s) |
| --- | --- | --- | --- | ---: | --- | --- |
| staircase-v4 | 10/10, including 6 | 10 required | PASS | 11 | 1136.033 / 2260.188 / 2260.188 | 59.959 / 66.82 |
| traversal-v3 | 4/5 descend, 4/5 round-trip, 1/5 Mines | At least 3/5, 3/5, 2/5 respectively | FAIL (Mines) | 18 | 1132.526 / 1427.151 / 1427.151 | 163.944 / 184.18 |
| scout-v2 | 0/5 objectives | Median explored cells 523 >= 350; median return 523 >= 350 | PASS (metrics) | 5 | 1125.487 / 1200.319 / 1200.319 | 87.588 / 104.98 |
| eat-v2 | 0/5 objectives | Median return 793.97 >= 700; explored cells 902 >= 450; starvation deaths 2 > 1 | FAIL (starvation) | 9 | 1047.056 / 1285.195 / 1285.195 | 180.923 / 211.43 |
| descend-d5-v1 | 6/8 baseline, 18/20 fresh | All six must-pass entries passed; fresh 90% >= 50% | PASS | 43 | 1188.599 / 1431.830 / 1592.359 | 411.413 / 470.24 |

Every suite recorded **zero invalid actions, gate rejections, integrity
failures, and failed/repaired model decisions**. No model fallback action was
executed. Prayer, corpse meals, and kicks passed the evaluator's gate/replay
audits. The two known-failure baseline entries remained deaths as expected;
no baseline expectation changed. Fresh Wilson 95% interval:
`[0.698966, 0.972134]`. Fresh starvation deaths: **0**; fresh deaths while
Weak or Fainting: **0**. These ADR conditions were checked explicitly against
recorded death cause and `hunger_at_death`; the frozen suite's fresh block
itself only declares the success-rate gate, not those death metric gates.

Report stems:

- `staircase-v4-20261003T213626Z`
- `traversal-v3-20261003T213738Z`
- `scout-v2-20261003T214051Z`
- `eat-v2-20261003T214242Z`
- `descend-d5-v1-20261003T214621Z`

The first full pytest run exposed a rendering-only mismatch in the new
schema-4 report: its generated Markdown listed `steps_by_skill` in in-memory
insertion order, whereas persisted JSON sorts those keys and re-rendering
lists them alphabetically. The original generated Markdown is preserved at
`/tmp/descend-d5-v1-original-generated.md`. The committed Markdown was
re-rendered from the untouched JSON with `render_report_markdown`; only skill
listing order changes, not counts, outcomes, acceptance, or provenance.
No episode was rerun and no product/harness code was modified.

## Failure analysis

**Traversal, enter-mines (failed case):** seed 700 alone entered the Mines.
Seeds 701-704 died while Fainting: respectively newt on depth 1 (369 SEARCH
steps), gecko on depth 2 (164), grid bug on depth 2 (271), and newt on depth 2
(71). Seed 701 also died identically in the otherwise-passing descend and
round-trip cases. This suite deliberately retains `nle-task-actions`, so
survival eating and prayer are unavailable. It misses the immutable 2/5
Mines gate; a future policy must investigate route/search cost and branch
identity/discovery rather than retuning the observed threshold.

**Eat, explore-d1-d5 (failed case):** all five episodes ended while Fainting.
Seeds 922 and 923 died of starvation, failing the at-most-one starvation gate;
they spent 621 and 580 SEARCH steps and reached depth 2. Seeds 920, 921, and
924 died to a jackal, large kobold, and fox, respectively (SEARCH counts 524,
605, 602). Every episode executed verified inventory eating, but the retained
`nle-hunger-actions` profile lacks prayer/corpse recovery. Adequate returns and
explored-cell medians do not imply survival. Investigate search/nutrition
budgeting on this profile before a new-policy regression evaluation.

**Scout (metric case passed, all objectives failed):** the five deaths are
not hidden by the passing baseline gates. It is still exploration coverage
rather than survival evidence; the task action profile cannot eat or pray.

**Descend fresh sample:** seed `1259450733` died to a werejackal at depth 4,
step 805, while Not Hungry, after three downstairs traversals. This is a
combat-risk failure, not a hunger death. Seed `2105401147` was truncated at
3000 steps after visiting main levels 1-3 and Mines `(2, 1)` (max depth 4),
with 1797 SEARCH steps. It remained alive; skills included 2956 exploration,
21 stair navigation, 12 corpse, 7 hunger, and 4 prayer steps. Investigate
branch recovery/exit discovery and combat risk from these records, without
rerunning these fresh seeds as confirmatory evidence.

The baseline retains seed 1's fox death at depth 2 while Hungry (299 SEARCH
steps) and seed 701's newt death at depth 1 while Fainting (369). Both were
known failures; their unchanged outcomes are not must-pass regressions.

## Verdict and next work

The milestone suite **passed**, including the ADR's fresh hunger-death
conditions checked above and the catalog baseline. Item 10's implementation and single-run
assessment are complete; ADR 0005's design is accepted as implemented and
evaluated. **Milestone 2's full acceptance did not pass:** traversal-v3 and
eat-v2 missed their immutable regression gates. Do not interpret each report's
`milestone_accepted` field as acceptance of the entire five-suite milestone.
Keep all failed reports unchanged. Any confirmatory retry needs a new policy,
new suite ids, and a new fresh draw, never replacement of this first evidence.

Next work: diagnose Mines discovery/search and Eat starvation under their
retained action profiles; investigate the observed branch-recovery and
non-hunger combat failures; only ship fixes that qualify against separate
predeclared development probes. A new evaluation must also encode the ADR's
fresh death gates as explicit metric thresholds rather than relying on this
manual audit.

## Validation

- Full `uv run pytest -q`: 590 passed, three dependency deprecation warnings
  (62.72 seconds), after canonicalizing only the new schema-4 Markdown.
- `uv run ruff check .`: all checks passed; `uv run ruff format --check .`:
  53 files already formatted.
- `git diff --check` and staged diff check passed.
- Strict MkDocs passed from a clean staged-index export, using MkDocs 1.6.1,
  pymdown-extensions 12.1, and mkdocs-mermaid2-plugin 1.2.3 (development guide pins).
- Persisted JSON re-renders to the committed Markdown. A scoped report check
  confirmed all 20 drawn fresh seeds are automatically excluded by the report
  directory and that no fresh death was starvation or Weak/Fainting.
