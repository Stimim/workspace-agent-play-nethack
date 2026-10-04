# Documentation index

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md): current system boundaries, invariants, and milestone contract.
- [`../TODO_LIST.md`](../TODO_LIST.md): prioritized product work and acceptance criteria.
- [`development.md`](development.md): reproducible developer setup and checks.
- [`decisions/`](decisions/): durable architecture decision records, including [ADR 0001](decisions/0001-initial-product-and-runtime.md) (initial product and runtime), [ADR 0002](decisions/0002-deterministic-skill-arbiter.md) (deterministic skill arbiter), [ADR 0003](decisions/0003-typed-contract-construction.md) (typed contract construction rather than a runtime JSON Schema engine), [ADR 0004](decisions/0004-traversal-goals-and-task-progression.md) (typed traversal goals, stair identity, and staged NLE task progression), and the proposed [ADR 0005](decisions/0005-early-survival-and-seed-evaluation.md) (milestone 2: early survival and representative-plus-fresh seed evaluation).
  [Proposed ADR 0006](decisions/0006-unified-goal-suites.md) supersedes active
  environment/profile coupling and heterogeneous regression evaluation while
  preserving historical suites and reports.
- [`notes/`](notes/): chronological development history and lessons; the latest task-progression evidence (explore-dungeon objectives, Scout and Eat suites) is in [note 0017](notes/0017-scout-and-eat-task-suites.md), survival-policy evidence and bounds in [note 0016](notes/0016-evidence-gated-survival-skills.md), the sticky agent-column viewport fit in [note 0018](notes/0018-agent-column-viewport-fit.md), the representative-seed catalog and used-seed ledger in [note 0020](notes/0020-representative-seed-catalog.md), fresh-sample suite schema and paired baselines in [note 0022](notes/0022-suite-schema-3-fresh-samples.md), and earlier product decisions and evidence.
- Milestone-2 unified-survival remediation: the rejected first goal-aware
  branch-gate comparison is retained in [note 0037](notes/0037-goal-aware-branch-gate-probes.md);
  the qualified frontier-preserving change and its complete paired results
  are in [note 0038](notes/0038-branch-exit-frontier-preserving-probes.md).
  The subsequent hidden-passage/boulder-detour candidate was rejected for
  losing five established development successes despite qualifying aggregate
  held-out results ([note 0039](notes/0039-hidden-passage-detour-probes.md)).
- [`external/`](external/): instructions for large external source material that is not committed.
- [`../_agents/`](../_agents/): repository-specific coding-agent procedures and tools.
- [`../nethack-agent/knowledge/`](../nethack-agent/knowledge/): reviewed knowledge made available to the local playing agent.

When behavior or architecture changes, update the relevant canonical document and add a note describing evidence and lessons. Do not use chronological notes as a substitute for correcting stale current documentation.
