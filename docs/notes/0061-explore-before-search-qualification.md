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
