# ADR 0008: Milestone 3A, find the way down

- Status: accepted (project owner, 2026-10-25)
- Date: 2026-10-25
- Refines: [ADR 0007](0007-mines-minetown-and-oracle.md); milestone 3 pauses
  until this milestone is accepted

## Context

Milestone 3 is far from acceptance: the shipped policy reaches the Minetown
temple in 19 of 67 regression runs and the Oracle in 9. Four survival and
stall rules failed qualification (notes 0052, 0054, 0057, 0059). Each one
moved deaths around without adding objectives.

Most of the game time goes to single-level stalls. Measured from the stored
step events of the shipped baseline arms (`22d0a5f`, the 0052 regression
arms) and of candidate 0059's last pass (`afc3282`), using the read-only
script `docs/notes/evidence/0059/scripts/stalls.py`:

| Suite (67 runs) | Runs with a level over 1,000 turns | Turns past the 500th on one level |
| --- | --- | --- |
| Minetown, baseline | 48 | 72% |
| Oracle, baseline | 40 | 66% |
| D5, baseline | 11 | 32% |
| Minetown, 0059 pass 3 | 47 | 76% |
| Oracle, 0059 pass 3 | 40 | 60% |

The stalls consume food, which shows up as Weak-or-worse deaths deeper
down (note 0056, Phase 3). The 0054 stall budget did not shorten them,
because its no-progress clock restarts on any newly observed cell
(note 0059). The causes of the stalls are not yet classified.

## Decision

### 1. Goal

On main-dungeon Dlvl 1-9 and Gnomish Mines levels 1-4, the hero finds and
reaches a goal-compatible staircase without long single-level stalls. The
character, suites, objectives and conduct rules are those of ADR 0007.

### 2. Stall metric

A **stalled run** has at least one contiguous stay on one level (same
`depth` and `dungeon_number`, from its first to its last step event) longer
than 1,000 game turns. Time spent fighting or resting on that level counts.
The 1,000-turn threshold and this definition may be refined once, after the
Phase 1 diagnosis and before any qualification run. Any refinement is
recorded here.

### 3. Acceptance

With one frozen policy:

1. **Regression suites:** at most 10 stalled runs of 67 in each of
   `minetown-regression-v2` and `oracle-regression-v2`, and no more than the
   baseline's 11 in `unified-d5-regression-v5`.
2. **Fresh sample:** at most 4 stalled runs of 30 per target, on one frozen
   30-seed fresh sample per target drawn from unused seeds.
3. **Paired outcome gates:** ADR 0007 §4.1's gates against the shipped
   baseline, unchanged. Objectives not lower; deaths, Weak-or-worse deaths and
   starvation deaths not higher; zero invalid actions, gate rejections and
   integrity failures. Fewer stalls must not be bought with more deaths.

Each product rule still qualifies separately under ADR 0007 §4.1 and the
note 0040 protocol. A rule's primary claim is fewer stalled runs; the outcome
gates are its non-inferiority checks.

### 4. Phases

1. **Diagnose (no seeds spent).** With the native-truth skill, classify every
   stalled level in the baseline arms by cause. Classes include:
   - an exit hidden behind a secret door or corridor;
   - an exit seen but not routed to;
   - a locked door or a boulder in the way;
   - a search that wastes turns (for example the cross-level walking in
     0059);
   - a trapdoor-only or otherwise unusual exit;
   - fighting or waiting.
2. **Verification.**
   - `compare.py` reports stall diagnostics per arm and changed seed: the
     longest level stay, stalled runs, arrive-then-leave events and
     model-fallback waits.
   - The representative-seed catalog gains long-cap Minetown and Oracle
     stall seeds.
3. **Rules.** One rule per cause class, largest class first, each qualified
   separately.
4. **Acceptance.** The criteria in §3.

### 5. Not decided here

- A noise margin for the paired gates (TODO_LIST "optional ADR 0007 gate
  amendment") stays open for the owner.
- After acceptance, milestone 3 resumes. Resting (0057) is expected to be
  re-tried on top of the reduced stalls.
