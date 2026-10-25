# 0061: Explore-before-search qualification (milestone 3A, rule 1)

## Preregistration: frozen before any qualification arm

Freeze date: 2026-10-26. No qualification result is recorded in this
section. The candidate is **unqualified and unshipped**. External evidence
(suites, preflight, manifests, launch scripts) lives under
`~/nethack-evidence/0061q/`.

### One rule

Milestone 3A Phase 3, first rule (ADR 0008). Note 0060 found that searching
a level that lacks the target took 58% of baseline stall turns.

- **Target ranges:** the Mines branch range (Dlvl 2-4) for
  `enter_dungeon(2)` and the Minetown leg; the Oracle range (Dlvl 5-9) for
  `find_oracle`; Mines levels 3-4 for the Minetown temple.
- **Order:** in each range the planner explores every range level's frontier
  before searching any range level for hidden passages. A range level whose
  frontier ran out counts as visited, and the hero moves on by the main
  staircase. Once every range level is explored, the nearest range level not
  yet exhausted is searched. The existing branch re-arm and the all-exhausted
  fallbacks are unchanged.
- **Branch range order:** identified branch staircase; two `>` known;
  unexplored frontier; not exhausted; re-armed once.
- **State:** `LevelMemory.frontier_explored` is sticky like `explored`. The
  planner sets it only while the level is current, from
  `skills.frontier_exhausted`: no frontier even past monsters, and no known
  locked door beside unexplored space. The coordinator and
  `ExplorationReplay` plan on the same observations, so they agree, and
  cells seen on the way out never withdraw it.
- **Out of scope:** no change to search, navigation, combat, food or
  prayer. `reach_level` tasks (the D5 suite) never use the changed paths.

### Development history: not qualification evidence

One development pass on the regression suites (commit `c7541b2`,
`~/nethack-evidence/0061/dev1-*`; log `~/nethack-evidence/0061/DEV.md`).
Values are baseline -> candidate, objectives / deaths / Weak-or-worse /
starvation:

| Suite (67) | O / D / W / S | Stalled runs |
| --- | --- | --- |
| Minetown | 19/42/20/1 -> 24/39/10/1 | 48 -> 26 |
| Oracle | 9/53/19/0 -> 13/49/7/0 | 40 -> 25 |
| D5 | 54/5/0/0 -> 54/5/0/0 | 11 -> 11 |

All gates passed in development. Every development loss was traced:

- Minetown 1528054415 lost to the secret-passage class: the branch was
  hidden on Dlvl 2, and Dlvl 3's main `>` needed four secret cells.
- 9, 6 and 1364 searched Dlvl 4 first, once every range level was explored.
- 1375 was blinded in a shop and walked into the unseen shopkeeper. Smoke
  Minetown 701, the same blindness hazard with a priest, is not a
  publicly-peaceful attack.
- The rest are deeper combat deaths.

These runs used historical seeds and are not qualification evidence.

### Identity and pins

- **Baseline:** `~/nethack-evidence/0052/baseline`, detached at
  `22d0a5f74569277b4e030aa9a7d9427b7ecda7d9`, policy
  `hierarchical-survival-hp-prayer-burden-look-ration-v1`.
- **Candidate:** `~/nethack-evidence/0061/candidate`, branch
  `rule-0061-explore-before-search` at `4f3c6f4`. That is `c7541b2` (the
  rule) plus the ledger reservation, on `main` `e1a232b`. Its gameplay code
  differs from `22d0a5f` only by this rule: the later product commits change
  only the UI, run speed and storage.
- **Candidate policy (qualification only):**
  `hierarchical-survival-hp-prayer-burden-look-ration-explore-first-qual-v1`.
- **Knowledge:** both arms load `survival-reviewed-v2`, unchanged.
- **Preflight:** all seven descriptors passed no-episode `load_suite` and
  `require_suite_configuration` in their own worktree
  (`preflight-candidate.json`, `preflight-baseline.json`).
- **Paired cases:** all five paired `cases` objects are equal, so seeds,
  tasks, caps and per-case criteria match (`cases-equality.json`).
- **Tests:** ruff clean; `pytest -q` 749 passed.

### Frozen sample and execution contract

- **Seeds:** 635-664 inclusive, reserved in the candidate ledger
  (`4f3c6f4`) before either fresh arm. `used_seeds` showed no overlap. Both
  targets share the sample, and pairs are compared only within one target.
- **No changes after launch:** no redraw, replacement, rerun of failures or
  mid-suite change.
- **Not acceptance:** this is scripted development qualification, not
  held-out or milestone acceptance.
- **Runtime:** the scripted development model, `nle-survival-actions`, and a
  lawful dwarven Valkyrie. Caps are 10,000 action steps for Minetown and
  Oracle and 3,000 for D5.
- **Reused reports:** the three 0052 baseline regression reports (same base,
  suites and caps).
- **Order:** wave 1 is the five candidate arms (`launch-wave1.sh`). Wave 2,
  the two baseline fresh arms (`launch-wave2.sh`), refuses to start unless
  every wave-1 arm finished with exit code 0, not stopped.
- **How arms run:** both scripts run `sha256sum --check frozen.sha256`
  first. Each arm uses two workers under `nice -n 15 ionice -c 3`, through
  the detached runner (state `~/nethack-evidence/0061q/state`), with at most
  five arms at once and no tool deadline.

| Run | Wave | Suite (under `~/nethack-evidence/0061q/suites/`) |
| --- | --- | --- |
| `0061q-cand-mt-reg` | 1 | `candidate/minetown-regression-v2-explore-first-qualification-0061.json` |
| `0061q-cand-or-reg` | 1 | `candidate/oracle-regression-v2-explore-first-qualification-0061.json` |
| `0061q-cand-d5-reg` | 1 | `candidate/unified-d5-regression-v5-explore-first-qualification-0061.json` |
| `0061q-cand-mt-fresh` | 1 | `candidate/minetown-fresh-v4.json` |
| `0061q-cand-or-fresh` | 1 | `candidate/oracle-fresh-v4.json` |
| `0061q-base-mt-fresh` | 2 | `baseline/minetown-fresh-v4-baseline-0061.json` |
| `0061q-base-or-fresh` | 2 | `baseline/oracle-fresh-v4-baseline-0061.json` |
| `0052-base-{mt,or,d5}-reg` | reuse | `~/nethack-evidence/0052/0052-base-*-reg/reports/` |

### Gates

For **each** of the five paired sets:

- objectives not lower;
- deaths not higher;
- last-live Weak-or-worse deaths and starvation deaths not higher;
- complete comparable records, with zero invalid actions, gate rejections
  and integrity failures.

Evidence of hunger, conduct or detector state that is missing counts as
unknown, not zero. `compare.py` computes the gates; `stalls.py` reports the
ADR 0008 stall metric, which is a primary claim and not a gate here.

Trace every lost success and new death, and distinguish a changed-rule defect
from trajectory divergence into an existing failure. No unexplained loss, and
no loss from a defect in the changed rule, may ship. A behavior change after
launch spoils the sample.

### Frozen SHA-256

Every file the candidate changed since `e1a232b`, relative to the candidate
worktree. The digests of this note, the suites, the preflight records and the
launch scripts are frozen externally in `~/nethack-evidence/0061q/frozen.sha256`.

| Candidate file | SHA-256 |
| --- | --- |
| `ARCHITECTURE.md` | `b04c2cf2ae31d8c1fca03e00fcc0b87500f1b0afef07377fb2d7afc410674fdc` |
| `nethack-agent/evaluation/seed-ledger.json` | `2595afa8fa4eeb3721a51815316cbb150cb9cf7ae27ef24e0640f09fe36ab78e` |
| `nethack-agent/src/nethack_agent/navigation.py` | `6e4323d3db923592ee65d67ca1843a568363e6b2ad6734e910830c3df6ab6877` |
| `nethack-agent/src/nethack_agent/planner.py` | `51557c1cc7254a43219f4f6b3ce7607b48cc264e8a7f7c4bf3af504449306450` |
| `nethack-agent/src/nethack_agent/run_manager.py` | `73c3a75aadd43c6495d0dfe9808c0d04ef35cb8b1b47c55c27d4fd818de7201c` |
| `nethack-agent/src/nethack_agent/skills.py` | `8ef0a924d5a3f0a35e35cff43f608088a4f9234f480dd2588c872b8d16b110c4` |
| `nethack-agent/tests/test_planner.py` | `7cf586cb7f6950e7b983c074fbeb310f9d228adafe43022ed3f9799d4cf6455b` |
| `nethack-agent/tests/test_targets.py` | `0dacef0873a537fdd7868f16d16b77d0f43953d64686a1f9edc5ec44796fdaa8` |

## Completed qualification results

All seven new arms finished with exit code 0 through the detached runner,
without cutoff, replacement or candidate change. `sha256sum --check
frozen.sha256` passed before both waves. All reports are complete, with zero
invalid actions, gate rejections and integrity failures, and zero
`oracle_attacks` and `peaceful_attacks`, in every arm. The three regression
arms reproduce development pass 1 exactly, seed for seed. That is expected:
the scripted runs are deterministic and the gameplay code is unchanged since
`c7541b2`.

O/D/T = objectives/deaths/truncations; W = last-live Weak-or-worse deaths;
S = starvation deaths.

| Paired set | Baseline O/D/T, W, S | Candidate O/D/T, W, S | Gate |
| --- | --- | --- | --- |
| minetown-regression-v2, 67 | 19/42/6, 20, 1 | 24/39/4, 10, 1 | pass |
| oracle-regression-v2, 67 | 9/53/5, 19, 0 | 13/49/5, 7, 0 | pass |
| unified-d5-regression-v5, 67 | 54/5/8, 0, 0 | 54/5/8, 0, 0 | pass (identical) |
| Minetown fresh 635-664, 30 | 6/18/6, 6, 2 | 13/15/2, 0, 0 | pass |
| Oracle fresh 635-664, 30 | 6/22/2, 6, 1 | 8/21/1, 5, 0 | pass |

ADR 0008 stall metric (`stalls.py`; runs with one level stay over 1,000
turns, and the median longest stay):

| Set | Stalled runs | Median longest stay (turns) |
| --- | --- | --- |
| Minetown regression | 48 -> 26 | 2,051 -> 610 |
| Oracle regression | 40 -> 25 | 1,490 -> 633 |
| D5 regression | 11 -> 11 | 329 -> 329 |
| Minetown fresh | 19 -> 12 | 1,824 -> 616 |
| Oracle fresh | 19 -> 10 | 1,344 -> 488 |

That roughly halves stalls but does not meet ADR 0008 §3. Acceptance needs at
most 10 per regression suite and at most 4 per fresh target, so further
Phase 3 rules are needed.

New stalls: Minetown regression 6, 9, 1364 and 1528054415; Minetown fresh
637, 638, 640, 653 and 663; Oracle fresh 654. Except for 663, a 1,021-turn
stay on Mines level 4, each is an unbounded search of a deeper range level
after a shallower one was deferred, as below.

### Every lost success and new death

No loss shows an implementation defect: the flag, the planner and the replay
agree, and nothing changed outside the range planning. The lost successes
come from the rule's preregistered order. A range level whose target lies
behind a hidden passage is deferred once its visible frontier runs out. The
nearest unexhausted range level is then searched without a budget, so the
hero never returns to the shallower level. That is the next rule's class,
secret-passage search targeting, recorded in development as "9, 6 and 1364
searched Dlvl 4 first".

| Set / seed | Baseline -> candidate | Finding |
| --- | --- | --- |
| Minetown fresh 637 | objective -> hobgoblin death | The baseline found the Mines `>` on Dlvl 2 after 7 searches. The candidate deferred Dlvl 2 after 66 turns, explored Dlvl 3-4, then searched Dlvl 4 for 7,700 turns (5,607 searches). Deferral, then unbounded search. |
| Minetown fresh 638 | objective -> pony death | Same: the baseline needed 23 searches on Dlvl 2. The candidate searched Dlvl 4 (570) and then Dlvl 3 (6,381) and never returned to Dlvl 2. |
| Oracle fresh 654 | objective -> lizard death, Fainting | The Oracle's part of Dlvl 6 lay behind a hidden corridor. At a dead-end corridor (57,3) the visible frontier ran out, so Dlvl 6 counted as explored after 28 turns. The hero searched there for the way down, found the corridor, crossed to the `>` and descended. It then searched Dlvl 7 for 1,300 turns (510 searches) and fainted. |
| Minetown fresh 645 | objective -> giant bat death | The candidate passed Dlvl 2-3 quickly (the baseline searched both for 3,800 turns) and was killed on Dlvl 4 at T702. Combat after divergence. |
| Minetown fresh 636, 651 | truncated -> gnome mummy / giant spider death | The baseline stalled on Dlvl 3 and Dlvl 2. The candidate reached Mines levels 6 and 8 and died in combat. |
| Oracle fresh 637 | truncated -> rothe death | The baseline searched Dlvl 5 to the cap. The candidate explored Dlvl 5-8 without searching and died in combat on Dlvl 8. |
| Minetown reg 1528054415 | objective -> truncated | Deferral class: the branch was hidden on Dlvl 2, and Dlvl 3's main `>` needed four secret cells (native truth). |
| Minetown reg 9 | objective -> hill orc death, Hungry | Deferral class: Dlvl 4 searched first (4,118-turn stay with fallback waits). |
| Minetown reg 1375 | objective -> killed by Izchak | Blinded in Izchak's shop, the hero walked into the unseen shopkeeper. A blindness hazard, also seen in smoke Minetown 701; not a conduct incident. |
| Minetown reg 703, 704, 2094095407; Oracle reg 2065672237 | objective -> combat death | Deeper or earlier combat after divergence (kobold mummy, giant bat, wolf, paper golem). |
| Minetown reg 824, 799362204, 1362, 1368 | truncated -> combat death | The baseline stalled to the cap. The candidate went deeper and died in combat. 1368 died Fainting, at Dlvl 7. |

Gains: Minetown regression 11 new objectives; Oracle regression 5; Minetown
fresh 10 (635, 641, 643, 646, 649, 650, 654, 655, 656, 664, including both
starvation deaths removed); Oracle fresh 3 (635, 643, 664).

## Decision

QUALIFIED under the preregistered gates. Every paired set passes:
- objectives not lower;
- deaths not higher;
- Weak-or-worse and starvation deaths not higher;
- complete records with zero invalid actions, gate rejections and integrity
  failures.

Every lost success and new death is traced. None comes from a defect in the
changed rule. The lost successes are the preregistered order deferring a
level whose target hides behind a secret passage, which the next Phase 3 rule
must fix. Seeds 635-664 are consumed.

Shipped as policy
`hierarchical-survival-hp-prayer-burden-look-ration-explore-first-v1` with
knowledge `survival-reviewed-v2`. It pins new immutable
`minetown-regression-v3`, `oracle-regression-v3` and
`unified-d5-regression-v6`, copies that change only `suite_id` and
`policy_version`. ADR 0008's stall bars apply to these copies, since the cases
are the same. The qualification suites `minetown-fresh-v4` and
`oracle-fresh-v4` are committed with their qualification-only label, and the
current policy refuses them, as it does every earlier pinned suite.

## Evidence

Compact per-seed records are in `docs/notes/evidence/0061/`:
- `cand-*` for the candidate arms;
- `base-*` for the two new fresh baselines and the three reused note-0052
  regression baselines;
- `paired-comparison.json` (`compare.py`);
- `stalls.json` (`stalls.py`).

Raw databases, reports, manifests and launch scripts are in
`~/nethack-evidence/0061q/`, the development history in
`~/nethack-evidence/0061/`, and a shipped-tree smoke (Minetown seed 3,
objective) in `~/nethack-evidence/0061q/ship-smoke/`.

## Lessons

- **The first rule to add objectives:**
  - It changes where the hero spends turns, not how it fights. It is the
    first milestone-3 rule to add objectives on both targets.
  - It also lowers Weak-or-worse deaths, because less food goes on stalls.
  - This supports note 0056's view that stall reduction is the lever.
- **Deferral needs bounded search:**
  - Deferring a level until the whole range is explored is right on average.
  - It loses when the target sits behind a secret passage on a shallow level,
    because the search that follows is unbounded and picks the nearest
    level, not the likeliest.
  - The next rule should bound or target search, which is ADR 0008's
    secret-passage class: rotate among unexhausted range levels, and rank
    search stands by dead ends and map gaps.
