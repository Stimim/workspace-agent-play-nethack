# 0057: Combat-only Elbereth disengage qualification

**Decision: REJECTED** (2026-10-20). Not shipped: the candidate code, the
qualification policy label and the `*-fresh-v3` suites were not merged; they
remain on branch `rule-0057-elbereth-disengage`
(`~/nethack-evidence/0057/candidate`). This repository records the
preregistration, results, per-seed evidence and the consumed seeds 605-634.

## Preregistration — frozen before either qualification arm

Freeze time: `2026-10-20T01:44:35.776627+00:00`. No qualification results are recorded here.
The candidate remains **unqualified and unshipped**. External evidence, suites,
preflight results, launch scripts and manifests live under `~/nethack-evidence/0057q/`.

### One rule and boundaries

Enter stationary combat recovery only at HP <= one third maximum HP, with
safe prayer unavailable and a visible non-immune hostile. The frozen code in
`disengage.py` is authoritative: unlike the earlier development prose in
ARCHITECTURE.md, it does **not** independently trigger after an HP prayer.
Critical prayer retains priority. There is no wounded quiet-rest trigger and
no retreat movement or new exploration/navigation rule.

Write dust `Elbereth` through the real engraving transaction (tool selection,
overwrite answer, exact text bytes, submission, all MORE pages). Protection is
valid only after exact public LOOK readback, never merely after issuing text.
Recheck with LOOK between single-turn WAIT actions; repair erosion in place.
Combat-established recovery may continue after attackers flee from view, but
pending readback alone is not verified protection. Recover toward 75% HP.
Never attack from the verified protected square, including passive species.

Exit on Hungry, 200 elapsed turns, unsafe/immune/unknown threats, observed
ranged damage or damage during protected WAIT, excluded statuses, terrain or
location, or consecutive repair failures. The retry cap is two repair retries;
24 prompt actions bound each transaction. Two consecutive 20-turn periods
without HP gain also stop recovery. Budgets persist across exploration rearm.
Only ordinary reviewed floor/corridor/door/stair terrain in main dungeon,
Mines or Sokoban is eligible; exclude shops/temples, polymorph, Overtaxed+,
blindness, confusion, stun, hallucination, levitation, flight and riding.
Publicly peaceful/tame monsters and passive-only species do not trigger or
interrupt recovery. Public glyph/description evidence supplies the NetHack
3.6.7 immunity predicate (@ class, minion flag, named immune species and
shop/guard/priest roles); publicly blinded monsters are excluded. Ordinary
species with innate ranged capability are not blanket-excluded before an
observed incoming ranged attack. Public role/alignment signals are incomplete:
nonstandard-species shopkeepers/guards without role descriptions and hidden
alignment cannot be perfectly classified. No hidden state becomes policy input.
Unsafe recovery falls back to existing behavior with a recorded reason.

### Development history — not qualification evidence

All following runs used historical seeds and were inspected during development;
they are **not qualification evidence**, cannot substitute for the frozen arms,
and were run under the old policy label before the honest identity below.
Values are shipped baseline -> development candidate, O/D/W = objectives/deaths/
last-live Weak-or-worse deaths, 67 episodes per target.

| Development version | Minetown O/D/W | Oracle O/D/W |
| --- | --- | --- |
| v1 (`dev-mt`, `dev-or`) | 19->17 / 42->45 / 20->22 | 9->12 / 53->50 / 19->13 |
| v2 (`dev-mt-after`, `dev-or-after`) | 19->18 / 42->43 / 20->19 | 9->10 / 53->53 / 19->17 |
| v3 (`dev-mt-v3`, `dev-or-v3`) | 19->18 / 42->42 / 20->19 | 9->9 / 53->51 / 19->17 |

The continuation correction retained combat-established recovery after threats
left view and across readback/repair; peaceful creatures no longer interrupted
it. Subsequent source-based immunity classification removed false exclusions.
Later revisions narrowed the initial trigger to critical HP with unavailable
prayer. Earlier post-prayer wording is not the frozen trigger. The selected
1/3 entry, 75% target and 200-turn cap are bounded defaults, not proven optima:
the joint 40%/80% eight-seed diagnostic arm rescued none of those deaths.
Background: `~/nethack-evidence/0057/DEVELOPMENT-COMPARISON-RESULTS.txt`,
`CONTINUATION-RESULTS.txt`, retained `dev-*-after` and `dev-*-v3` reports.

### Honest identity and immutable pins

Baseline: `~/nethack-evidence/0052/baseline`, base commit
`22d0a5f74569277b4e030aa9a7d9427b7ecda7d9`. Candidate:
`~/nethack-evidence/0057/candidate`, branch `rule-0057-elbereth-disengage`,
uncommitted delta from the same base. Each has its own `nethack-agent/.venv`;
no main checkout or index is modified and no commit is made.

Candidate qualification-only policy:
`hierarchical-survival-hp-prayer-burden-look-ration-elbereth-qualification-v1`.
Baseline shipped policy: `hierarchical-survival-hp-prayer-burden-look-ration-v1`.
Both pin `survival-reviewed-v2`, unchanged, with identity
`survival-reviewed-v2+sha256:d5cb109e09e3d798a97f9521411a914c8fc2855916c6d4a6e3298e591e0fa19e`.
`evaluation.py` requires the suite policy, loads its pinned knowledge, then
requires the full configuration before creating any episode. Historical suite
pins and reports are not relabeled. The policy constant changes identity only;
all candidate behavior remains frozen.

All ten descriptors passed no-episode `load_suite`, `require_suite_policy`, and
`require_suite_configuration` in their intended worktree. Imports resolved
under their own worktrees. All five paired `cases` objects were asserted equal,
including seeds/tasks/caps/per-case criteria. Candidate regression copies change
only suite ID and policy pin; their cases are unchanged from baseline.
Preflight and equality evidence: `preflight.json`, `cases-equality.json` in the
external root. No loader/pin failures occurred in this preregistration.

### Frozen sample and execution contract

Reserve **605-634 inclusive** in the candidate ledger before either fresh arm.
The orchestrator checked the main evaluation catalog/ledger with `used_seeds`:
the intersection was empty. The ledger loads as JSON and its reservation note
is within 300 characters. Both objectives share this paired 30-seed sample;
comparisons are only within the same objective, never across objectives.
No redraw, replacement, rerun of failures, erased failure or mid-suite mutation.
This is scripted development qualification, not held-out/milestone acceptance.

Use the actual coordinator, `ScriptedDevelopmentModel`, Score environment,
`nle-survival-actions`, lawful dwarven Valkyrie, default context 8192.
Minetown/Oracle caps are 10000 action steps; D5 is 3000.
Reuse the three existing note-0052 baseline regression reports (same base,
suites and caps); do not rerun them. The five candidate arms form wave 1;
only after every wave-1 arm completes may the two baseline fresh arms start.
Each arm uses two workers, `nice -n 15 ionice -c 3`, via the detached runner,
state `~/nethack-evidence/0057q/state`. Never exceed five detached arms at once.
No tool deadline may cut off an evaluation. This assignment stops after wave-1
launch acknowledgments, without waiting for completion or running wave 2.
`launch-commands.sh` launches wave 1; `launch-wave2.sh` refuses an incomplete,
failed or stopped wave 1 and remains unexecuted at this handoff.

| Run | Wave / worktree | Frozen suite or reused report directory |
| --- | --- | --- |
| `0057q-cand-mt-reg` | 1 / candidate | `/home/stimim/nethack-evidence/0057q/suites/candidate/minetown-regression-v2-elbereth-qualification-0057.json` |
| `0057q-cand-or-reg` | 1 / candidate | `/home/stimim/nethack-evidence/0057q/suites/candidate/oracle-regression-v2-elbereth-qualification-0057.json` |
| `0057q-cand-d5-reg` | 1 / candidate | `/home/stimim/nethack-evidence/0057q/suites/candidate/unified-d5-regression-v5-elbereth-qualification-0057.json` |
| `0057q-cand-mt-fresh` | 1 / candidate | `/home/stimim/nethack-evidence/0057/candidate/nethack-agent/evaluation/minetown-fresh-v3.json` |
| `0057q-cand-or-fresh` | 1 / candidate | `/home/stimim/nethack-evidence/0057/candidate/nethack-agent/evaluation/oracle-fresh-v3.json` |
| `0057q-base-mt-fresh` | 2 / baseline | `/home/stimim/nethack-evidence/0057q/suites/baseline/minetown-fresh-v3-baseline-0057.json` |
| `0057q-base-or-fresh` | 2 / baseline | `/home/stimim/nethack-evidence/0057q/suites/baseline/oracle-fresh-v3-baseline-0057.json` |
| `0052-base-mt-reg` | Reuse; no launch | `~/nethack-evidence/0052/0052-base-mt-reg/reports/` |
| `0052-base-or-reg` | Reuse; no launch | `~/nethack-evidence/0052/0052-base-or-reg/reports/` |
| `0052-base-d5-reg` | Reuse; no launch | `~/nethack-evidence/0052/0052-base-d5-reg/reports/` |

Every new arm writes raw data to `~/nethack-evidence/0057q/<arm>/` and reports
to `<arm>/reports/`; detached names add the `0057q-` prefix as shown above.

### Qualification gates

For **each** of the five paired sets: objectives must not be lower, deaths
must not be higher, last-live Weak-or-worse deaths and starvation deaths must
not be higher. Require complete records, all seeds evaluated, fixed unchanged
inputs, zero invalid actions, zero gate rejections, zero integrity failures.
Missing hunger/conduct/detector evidence is unknown, not zero. Retain available
conduct/detector metrics. Runner development PASS/FAIL thresholds are not the
paired shipment gate and no real-model/milestone acceptance is claimed.

Trace every lost success and new death on regressions and fresh samples from
stored public observations/actions: distinguish a changed-rule behavior defect
from legitimate trajectory divergence reaching an existing failure. Native
truth is diagnosis-only. No unexplained or changed-rule-defect loss may ship,
even if aggregate gains compensate. Any behavior correction after launch or a
cutoff spoils/consumes the sample; retain evidence and preregister a new unused
sample before new arms. Never replace failed episodes. A disposition and compact
per-seed evidence are required before any integration or shipment decision.

### Consumer checks before freeze

After the qualification policy/ledger/fresh-suite changes:
`uv run ruff check .` passed; `uv run ruff format --check .` passed
(**65 files already formatted**); `uv run pytest -q` passed **831 tests**,
five dependency/deprecation warnings, **43.13 seconds**. No behavior correction
was made. The no-episode pin preflight and paired-cases checks above all passed.

## Frozen SHA-256

Every changed candidate product/test/document/ledger/fresh-suite file is below,
relative to the candidate worktree. This note cannot contain its own digest;
its digest is frozen externally in `frozen.sha256` and `freeze-manifest.json`
after writing the note and before launch. External manifests also cover every
suite descriptor (including the reused baseline descriptors) and launch scripts.

| Candidate file | SHA-256 |
| --- | --- |
| `ARCHITECTURE.md` | `456c6c3aad4b574d3a733c9b4e87e9757499f94847f3d8e2baad572366d48d8e` |
| `README.md` | `290e08723330cb93e31453e37349cc9b1b53f84d1156f4958267a9608e36d2fb` |
| `nethack-agent/src/nethack_agent/conduct.py` | `f4c54013a390ff12450796056378745af6a651ba1e9a406e112f09a1a7797414` |
| `nethack-agent/src/nethack_agent/coordinator.py` | `b2370aeb886d03bdfdaaecc52835462720b2fd6574514f5a04fe086e99b478c3` |
| `nethack-agent/src/nethack_agent/decision.py` | `4c7a3231d7e215fe560eac54d1fa88fb5a29a1ff2dfd7917213dfe1192452e80` |
| `nethack-agent/src/nethack_agent/disengage.py` | `a1eebef98982648f00a309f8717a6ecea349d486809d2ec2a2f18f05b150e577` |
| `nethack-agent/src/nethack_agent/environment.py` | `d2af118ecaf3554a9bb31a775a30c3e696aa35a18e1f59ecc26bd48a87768646` |
| `nethack-agent/src/nethack_agent/evaluation.py` | `6eca4fb9bf124fc2afb8a0dfd0f227bdb90a1bbdf6b4c7ca59634d9af7c98456` |
| `nethack-agent/src/nethack_agent/events.py` | `ae865160c9e7eda9249c3d6b4de9c660ddffbb20904da7d42940fa0dfe6ba664` |
| `nethack-agent/src/nethack_agent/replay.py` | `c765134ff69455241d53784d2ec940891d1cb0910d27a81b48570393a0731592` |
| `nethack-agent/src/nethack_agent/run_manager.py` | `ddf72b2a8b01977a21d02cef154edf86f510b5dee50f00a65b31ccb7c058e6a3` |
| `nethack-agent/src/nethack_agent/tasks.py` | `732de40a3bcda7a23c4c6ef4ae14b830eb0f386bc486c677ed181f69340fc761` |
| `nethack-agent/tests/test_disengage.py` | `d5b91d3131ec5f5ac5fc3c5e43df32632d1df06a0622d07cbce9bf47d0ac50b5` |
| `nethack-agent/tests/test_disengage_integration.py` | `cf7778e1ca0569adafe91a7737e8094be61c720d960e08a473d3661bf059d69b` |
| `nethack-agent/tests/test_elbereth_classification.py` | `182d1344df0d42cafd702093b54a8b12ed8f7951899f80348a159ceef940e00d` |
| `nethack-agent/tests/test_engraving_transport.py` | `8731291b94e123e66eb000a6743a41dcdca36034fa04819bf802d03d1b82fdf2` |
| `nethack-agent/evaluation/seed-ledger.json` | `4930285116269502c99c1589a77fc4fa713ff179254810ffbef272a738b989af` |
| `nethack-agent/evaluation/minetown-fresh-v3.json` | `216460bcf615ac37bf43acfcd1dbb2e23c9f251ef7891449da8ffc361b51a76c` |
| `nethack-agent/evaluation/oracle-fresh-v3.json` | `84b8aca1f150ec6aa770c59add59fafa08c7be92a1279a0cf7656b83a8b7ebde` |

## Completed qualification results

All seven new arms finished with exit code 0 through the detached runner, without
cutoff, replacement or candidate change (`sha256sum --check frozen.sha256`
passed before wave 2). All reports are complete, with zero invalid actions, gate
rejections and integrity failures in every arm. The three reused baseline
regression reports come from note 0052 (same base commit, suites and caps).

O/D/T = objectives/deaths/truncations; W = last-live Weak-or-worse deaths.

| Paired set | Baseline O/D/T, W | Candidate O/D/T, W | Gate |
| --- | --- | --- | --- |
| minetown-regression-v2, 67 | 19/42/6, 20 | 18/42/7, 19 | **fail** (objectives) |
| oracle-regression-v2, 67 | 9/53/5, 19 | 9/51/7, 17 | pass |
| unified-d5-regression-v5, 67 | 54/5/8, 0 | 54/5/8, 0 | pass (identical) |
| Minetown fresh 605-634, 30 | 9/19/2, 5 | 10/18/2, 6 | **fail** (Weak-or-worse) |
| Oracle fresh 605-634, 30 | 6/24/0, 8 | 5/24/1, 9 | **fail** (objectives, Weak-or-worse) |

Starvation deaths are unchanged (Minetown regression 1/1, all others 0/0).
Conduct metrics are zero in every candidate arm (`oracle_attacks`,
`peaceful_attacks`). The regression arms reproduce the v3 development runs
exactly, as expected from deterministic scripted runs.

How often the rule acted (candidate arms, from stored step events): Minetown
regression 13 episodes, 142 engraving openings, 2,430 protected WAITs; Oracle
regression 22 / 296 / 5,147; D5 regression 0; Minetown fresh 12 / 72 / 1,000;
Oracle fresh 12 / 128 / 2,834.

### Every lost success and new death

Each one diverges at the rule's first `ENGRAVE`. None shows a gate, permit or
conduct defect; all are trajectory divergence into existing failure classes,
mostly hunger after long rests.

| Set / seed | Baseline -> candidate | Finding |
| --- | --- | --- |
| Minetown reg 704 | objective -> kitten death, Weak | Two rests (185 and 200 turns, 23->49/72 and 20->53/85 HP) used food; later fainting death. |
| Minetown reg 1362 | truncated -> Uruk-hai death | Rest at turn 47 (6->8/18 HP); different trajectory, death about 5,400 turns later. |
| Oracle reg 924 | truncated -> hobbit death, Hungry | Rest ended by damage under protection while overloaded; later lycanthrope form and death. |
| Oracle reg 2065672237 | objective -> werejackal death | Rest from 1 HP to 10/18 HP; later killed by a human-form werejackal (Elbereth-immune). |
| Oracle fresh 630 | objective -> plains centaur death | Rest at 24/77 HP on Dlvl 6; hostile centaur kills it about 440 turns later; no conduct incident. |
| Oracle fresh 623 | pony death -> pony death, Weak | Rest at 18/58 HP; same killer, now Weak. |
| Minetown fresh 608 | boulder death -> cave spider death, Fainting | Rest at 6/18 HP; later fainting death. |

Gains: Oracle regression 700 death -> objective, 701/1364/1369 death ->
truncated; Minetown regression 1369/1374 death -> truncated; Minetown fresh 628
death -> objective; Oracle fresh 613 death -> truncated.

## Decision

REJECTED under the preregistered gates: Minetown regression objectives fell
(19 -> 18), Oracle fresh objectives fell (6 -> 5), and fresh Weak-or-worse deaths
rose on both targets (5 -> 6, 8 -> 9). The aggregate death count improved
(regression 100 -> 98, fresh 43 -> 42), but gains may not offset losses.
Seeds 605-634 are consumed. No retry on these seeds.

A development-only check before freezing found that a "no food carried, do not
rest" limit would have removed most gains (16 of the rule's recoveries started
without food, including Oracle 700's objective) to save Minetown 704, so no
food limit was frozen.

## Evidence

Compact per-seed records: `docs/notes/evidence/0057/` (`cand-*` for the
candidate arms, `base-*` for the two new fresh baselines and the three reused
note-0052 regression baselines). Raw databases, reports, manifests and scripts:
`~/nethack-evidence/0057q/`; development history: `~/nethack-evidence/0057/`.

## Lessons

- Elbereth resting works mechanically: protection verified by readback, erosion
  repaired in place, healing to target, zero invalid actions. It keeps heroes
  alive (fewer deaths) but rarely converts survival into objectives, because the
  rested hero returns to the same stalls.
- Resting spends food. Several new deaths are Weak or Fainting after long rests,
  so survival-first rules and stall reduction depend on each other (note 0056).
- Development iterations found real defects (early stops when attackers left
  view, peaceful monsters treated as threats, a whole-rest repair budget); each
  development pass improved the rule, but the dev set should not be re-tuned
  further.
