# Documentation index

- [`../ARCHITECTURE.md`](../ARCHITECTURE.md): current system boundaries, invariants, and milestone contract.
- [`handover.md`](handover.md): current status, decisions awaiting the owner, uncommitted candidate branches, and operating limits for the next coding agent.
- [`../TODO_LIST.md`](../TODO_LIST.md): prioritized product work and acceptance criteria.
- [`development.md`](development.md): reproducible developer setup and checks.
- [`decisions/`](decisions/): durable architecture decision records, including [ADR 0001](decisions/0001-initial-product-and-runtime.md) (initial product and runtime), [ADR 0002](decisions/0002-deterministic-skill-arbiter.md) (deterministic skill arbiter), [ADR 0003](decisions/0003-typed-contract-construction.md) (typed contract construction rather than a runtime JSON Schema engine), [ADR 0004](decisions/0004-traversal-goals-and-task-progression.md) (typed traversal goals, stair identity, and staged NLE task progression), the proposed [ADR 0005](decisions/0005-early-survival-and-seed-evaluation.md) (milestone 2: early survival and representative-plus-fresh seed evaluation), [ADR 0007](decisions/0007-mines-minetown-and-oracle.md) (milestone 3: Minetown temple and Oracle) and [ADR 0008](decisions/0008-find-the-way-down.md) (milestone 3A: find the way down without long stalls).
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
  [Note 0040](notes/0040-causal-hidden-detour-qualification.md) records the
  revised aggregate-and-causal protocol, diagnoses every required loss, and
  ships that exact retained candidate without replacing its original reports.
- Milestone 3 Phase 1: the reverted first attempt and its audit are in
  [note 0049](notes/0049-phase1-audit.md). The shipped objectives, baselines,
  native-truth detector audit, and ground-truth failure classification are
  in [note 0050](notes/0050-phase1-objectives-baselines-detector-audit.md).
- Milestone 3 Phase 4: the qualified hunger-skill ration live-lock fix,
  policy `hierarchical-survival-hp-prayer-burden-look-ration-v1`, and its
  per-seed evidence are in [note 0051](notes/0051-ration-livelock-qualification.md).
- Milestone 3 Phase 4: the rejected canonical slime-mold reserve rule and its consumed fresh sample are recorded in [note 0052](notes/0052-canonical-slime-mold-qualification.md).
- Roadmap consolidation and preserved roadmap-only facts, diagnosis, and deferred-work dispositions: [note 0056](notes/0056-roadmap-consolidation.md).
- Milestone 3 Phase 3: the rejected combat-only Elbereth disengage rule, its development history, consumed fresh sample and per-seed evidence: [note 0057](notes/0057-elbereth-disengage-qualification.md).
- Milestone 3 Phase 2: branch-stair identity diagnosis, closed without a rule (the Mines `>` detour costs 2 turns): [note 0058](notes/0058-branch-stair-identity-diagnosis.md).
- Milestone 3A Phase 3: the qualified and shipped explore-before-search rule, policy `hierarchical-survival-hp-prayer-burden-look-ration-explore-first-v1`, its consumed fresh sample 635-664 and per-seed evidence: [note 0061](notes/0061-explore-before-search-qualification.md).
- Milestone 3 Phases 2-3: combined rest + stall-budget candidate 0059, NOT QUALIFIED after three development passes (D5 regression gates failed; no fresh seeds spent), with per-pass evidence: [note 0059](notes/0059-rest-plus-stall-budget-development.md).
- Milestone 3A Phase 1: native-truth classification of every baseline stall; 58% of stall turns search a level for a target it lacks: [note 0060](notes/0060-stall-cause-diagnosis.md).
- [`external/`](external/): instructions for large external source material that is not committed.
- [`../_agents/`](../_agents/): repository-specific coding-agent procedures and tools.
- [`../nethack-agent/knowledge/`](../nethack-agent/knowledge/): reviewed knowledge made available to the local playing agent.

When behavior or architecture changes, update the relevant canonical document and add a note describing evidence and lessons. Do not use chronological notes as a substitute for correcting stale current documentation.
