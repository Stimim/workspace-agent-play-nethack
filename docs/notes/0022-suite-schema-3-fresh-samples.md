# 0022: Suite schema 3, fresh samples, and paired baselines

Date: 2026-10-01

## Implementation

Milestone 2 work item 3 implements the suite-schema-3 evaluation contract from
[ADR 0005](../decisions/0005-early-survival-and-seed-evaluation.md), without
creating the production `descend-d5-v1` suite or running the real model.

A schema-3 suite may combine fixed cases, baseline entries selected from the
strict representative-seed catalog, and a `fresh_sample` count, inclusive
range, task, cap, minimum success rate, and metric thresholds. Each catalog
entry keeps its recorded task, seed, step cap, outcome expectation, and
provenance. The catalog policy pin is checked before evaluation and its digest
is checked after evaluation. Suite/schema and draw provenance use strict typed
construction.

Fresh draws use a seeded PRNG without replacement, excluding all
`used_seeds()` values and the draws of prior schema-4 reports in the suite's
normal report directory or the selected report directory. Before the first
episode, the report contains the draw seed, range, sorted excluded-seed
snapshot, and ordered sampled seeds. That snapshot permits exact replay after
the used-seed ledger grows. A second invocation with the same draw seed does
*not* repeat already reported fresh seeds. A baseline's `must_pass` failure
fails baseline acceptance; changed `known_failure` outcomes are reported.
Fresh acceptance checks success rate and optional metrics independently, with
a 95% Wilson interval. Suite-wide integrity remains an independent gate.
`--compare-report` requires an earlier schema-4 report of the same suite digest
and renders paired baseline outcome and objective-success changes in JSON,
Markdown, and the plain CLI. Historical suites 1-2 and committed report files
remain untouched and render byte-for-byte.

## Scripted-model smoke (not milestone evidence)

The temporary fixture `/tmp/nethack-suite3-smoke-20261001/small-fresh-fixture.json`
used the existing catalog's `staircase-anchor-6` as baseline (its unchanged
catalog cap), two fresh `NetHackStaircase-v0` seeds at a four-step cap, range
`[1000000, 2147483647]`, and a 50% fresh success-rate gate. A copy of the
catalog and ledger lived beside the fixture. From `nethack-agent/`:

```bash
uv run nethack-agent eval run \
  --suite /tmp/nethack-suite3-smoke-20261001/small-fresh-fixture.json \
  --data-dir /tmp/nethack-suite3-smoke-20261001/data \
  --development-scripted-model --draw-seed 29
```

Observed: baseline seed 6 `task_success` in 151 steps; fresh seeds
`[1178076704, 164457879]` both `truncated` at four steps. Report
`small-fresh-fixture-development-20261001T144934Z.json` recorded draw seed
29 and zero exclusions. Its CLI summary (report path omitted here) ended:

```text
FAIL evaluation small-fresh-fixture (complete): 1/3 task successes
  - fresh sample success rate 0.000000 is below required 0.500000
  - development scripted model runs are never valid milestone evidence
  baseline: PASS
  fresh sample: FAIL (0/2)
```

```bash
uv run nethack-agent eval run \
  --suite /tmp/nethack-suite3-smoke-20261001/small-fresh-fixture.json \
  --data-dir /tmp/nethack-suite3-smoke-20261001/data \
  --development-scripted-model --draw-seed 29 \
  --compare-report /tmp/nethack-suite3-smoke-20261001/data/reports/small-fresh-fixture-development-20261001T144934Z.json
```

Observed: baseline seed 6 again `task_success` in 151 steps; fresh seeds
`[1178076706, 164457880]` both `truncated` at four steps. Report
`small-fresh-fixture-development-20261001T144954Z.json` recorded the two
previously drawn seeds as exclusions, baseline PASS, fresh FAIL (0/2), Wilson
95% interval `[0.0, 0.65762]`, and this paired CLI output:

```text
  paired baseline diff:
    staircase-anchor-6 seed 6: task_success (yes) -> task_success (yes); unchanged
```

These short scripted runs exercise NLE, SQLite/ttyrec replay, report persistence,
separate acceptance, reproducible exclusion, and paired comparison; the failed
fresh gate is expected from the four-step fixture and is not milestone evidence.
