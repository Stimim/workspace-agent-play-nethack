# 0020: Representative-seed catalog and used-seed ledger

Date: 2026-09-30

## What changed

Milestone 2 work items 1 and 2
([ADR 0005](../decisions/0005-early-survival-and-seed-evaluation.md) sections
2-3):

- `seed_catalog.py` defines the strict catalog (`CatalogEntry`, `SeedCatalog`)
  and ledger (`LedgerEntry`, `SeedLedger`) contracts, the Markdown renderer,
  `used_seeds()`, and the catalog check.
- `nethack-agent eval catalog render` regenerates
  `evaluation/representative-seeds.md`; `nethack-agent eval catalog check`
  runs every entry with the scripted development model through
  `run_evaluation`, one single-seed case per entry, and compares the outcomes
  with the expectations.
- `evaluation/representative-seeds.json` holds 11 entries;
  `evaluation/seed-ledger.json` records the probe and development seeds named
  in ADR 0004 and notes 0007 and 0017.

## Initial expectations

Expectations were set from the first scripted run under policy
`hierarchical-task-specialists-v1`, not assumed:

| Entry | Seed | Outcome | Steps | Notes |
| --- | ---: | --- | ---: | --- |
| `staircase-anchor-6` | 6 | task_success | 151 | |
| `descend-d3-covered-stairs-5` | 5 | objective_complete | 169 | |
| `descend-d3-stair-defense-1` | 1 | death | 941 | killed by a kobold on level 2 while Fainting |
| `descend-d3-stair-defense-2` | 2 | death | 923 | killed by a newt on level 2 while Fainting |
| `descend-d3-stair-defense-4` | 4 | objective_complete | 286 | |
| `descend-d3-hidden-downstairs-701` | 701 | death | 965 | killed by a newt on level 1 while Fainting |
| `descend-d3-hidden-downstairs-702` | 702 | truncated | 1,000 | Fainting on level 2 |
| `enter-mines-4` | 4 | objective_complete | 358 | |
| `enter-mines-7` | 7 | objective_complete | 363 | |
| `scout-explore-d1-53` | 53 | objective_complete | 322 | |
| `eat-stuck-after-exhaustion-824` | 824 | truncated | 2,000 | still Hungry on level 1 |

Seeds 1 and 2 were drafted as `must_pass` from the ADR 0004 baseline, where
the old policy died waiting on the stairs. The current policy survives level 1
but dies while Fainting on level 2, so both are `known_failure` and describe
that behavior. Seven of the eleven entries are `must_pass`.

## Verification

- `uv run nethack-agent eval catalog check --data-dir /tmp/nh-catalog-check`:
  PASS, 11 entries, 0 failed, 0 to update, exit 0.
- `uv run pytest -q`: 477 passed, 3 warnings (21 in
  `tests/test_seed_catalog.py`).
- `uv run ruff check .` and `uv run ruff format --check .` passed.

## Local worker process

The local coding workers (note 0019) could not implement this change: one
session rewrote the module repeatedly and invented a different ledger schema.
The director wrote the code; a worker copied it in chunks of at most 130 lines
through quoted heredocs, and each chunk was read back. Copying introduced about
one error per 100 lines, each fixed with an exact single-match replacement.
Long one-shot copies and hand-made fixes by the worker failed.
