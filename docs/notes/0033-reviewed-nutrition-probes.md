# 0033: Reviewed nutrition probes

## Preregistration (frozen before any episode)

Baseline HEAD is `6645966932fea6e123eea2b885d63458600bff4b`. Freeze this
section; append implementation, audit, results, verification and decision without
changing these rules. No episode preceded this preregistration.

- **Seeds:** the next 30 unused integers starting at 1300. `used_seeds(evaluation/)`
  validated 290 previously used seeds across the ledger, catalog and suites.
  Exact sample **1300–1329 inclusive**, all unused; register before any arm.
  These become development seeds, never fresh milestone acceptance seeds.
- **Setup:** actual `AgentCoordinator` and `ScriptedDevelopmentModel`,
  `NetHackScore-v0`, `nle-survival-actions`, objective `reach_level(0,5)`,
  cap 3000, unchanged from note 0032. Separate immutable source snapshots,
  data and report directories for every arm. No local real-model acceptance
  claim is made by these scripted probes.
- **Arms:** A = immutable HEAD `6645966`; B = the approved nutrition package;
  C = the same nutrition package plus the four frozen note-0032 corrections
  in `/tmp/item32-exit-candidate.patch`, SHA-256
  `3cfd536af5de50755aee91e3b62db7b3ae78e1b94b962e9b0e29cf92d17e21f6`.
  Rebase of that delta may only resolve conflicts, not change its behavior.
  Freeze B and C before their episodes. No candidate mutation during a suite.
- **Nutrition package:** recognize held partly eaten and other identified
  ration description variants; collect reviewed identified non-shop floor
  food when unburdened and cheaply reachable, otherwise eat it from the floor
  when Hungry with exact confirmation; preserve a tracked fresh safe-corpse
  arrival through blank underfoot feedback, using EAT and exact confirmation;
  make only lichen exempt from ordinary freshness/kill provenance, including
  pet-moved lichen identified by the exact prompt; expand reviewed fresh
  corpses to garter snake, hobbit, goblin, iguana and shrieker, plus
  jackal/fox/coyote only without public lycanthropy evidence and without
  polymorph. Preserve non-shop, species, race and pet exclusions. Add the
  explicitly selected `survival-reviewed-v2` bundle; v1 stays byte-identical.
- **Unchanged:** prayer interval and safety predicate, `POLICY_VERSION`,
  `item10-suites` branch and its files. No subagents. User changes stay
  unstaged; use `git add -p` for authored TODO/development hunks.
- **Qualification:** compare each candidate with A on all 30 seeds, including
  errors. Objectives **not lower**, total deaths **not higher**, hunger deaths
  **not higher**, and zero invalid actions, gate rejections and integrity
  problems. Hunger death means starvation or last live hunger Weak or worse
  (NLE >= 3), never zeroed terminal fields. Never replace a failed run.
- **Selection:** ship C if it qualifies; otherwise B if it qualifies; otherwise
  ship nothing. Development reruns cannot change this rule.
- **Development only:** rerun 1275, 1299, 1265 and 1218 under B and C, report
  separately, do not gate selection on reused seeds.
- **If something ships:** record the audit, three fresh-arm tables, development
  results and decision here; update architecture/development, ADR 0005's card
  and bundle mention, and item 8/9 TODO sub-bullets linking 0032/0033. Require
  full pytest, ruff, `git diff --check`, strict MkDocs from a clean staged
  export, and staircase seeds 1–10 at cap 1000 (10/10). Commit through
  `omp_commit.py` as `Recover missed food and widen reviewed corpses`, adding
  `and keep exit discovery behind frontiers` if C ships.
- **If neither qualifies:** restore candidate product/tests/cards/docs to A
  while preserving user changes; commit this note and the seed ledger only
  as `Record nutrition probes` through `omp_commit.py`.

## Pre-implementation audit

The read-only note-0032 nutrition audit found four Fainting deaths, excluding
truncations 1276 (NotHungry) and 1280 (Hungry). It matched 10,417 original native
steps and exercised ten manual meal/prayer interventions followed by recorded
command tails, not adaptive-policy qualification. Full evidence is retained in
`/tmp/item32-nutrition-diagnosis.json`.

| Seed | First Hungry / final Weak / first Fainting | Last live turn / cause | Missed nutrition and existing-contract defects |
| ---: | --- | --- | --- |
| 1275 | 936 / 2138 / 2197 | 2276 / kobold lord | Rotten interrupted ration leaves 134 held nutrition rejected as partly eaten; non-shop floor ration at D4 (51,12), underfoot 2062, gives 800. Finishing partial ration only delayed failure; floor meal removed Fainting over the recorded tail. |
| 1299 | 1134 / 2885 / 2944 | 3246 / jackal | Preserved pet-moved lichen at D2 (69,4) gives 200, but age/provenance gate rejects it. Eating it removed Fainting but the command-tail branch died to an orcish dagger: nutrition is not a survival guarantee. |
| 1265 | 730 / 2450 / 2509 | 2606 / jackal | Fresh rejected jackal/jackal/coyote/hobbit/goblin offer nominal 1050; a coyote meal removed Fainting over its command tail. Floor tripe is not conservative safe food. |
| 1218 | 751 / 2558 / 2615 | 2956 / orc zombie | Rotten interrupted ration leaves 134; blank underfoot feedback loses fresh lichen meal 2375 (200); reviewed rejected fresh species offer 600 before Fainting, pear/garlic another 90. Partial ration or tracked lichen meal removed Fainting over recorded tails. |

No persistent corpse-meal WAIT latch was present. Actual native prayer timers
were already zero at second Weak, but conservative public-policy intervals
blocked repeat prayer. A second prayer drew a 1350-turn timer in one diagnostic
branch; this package does **not** shorten intervals or expose private timers.
Earlier main descent had no observed main-goal exit when Hungry. Corrected
1299 and HEAD reached the same final game turn; an additional early lichen
shifted the prayer phase, so its death is not simply extra exploration time.

Local wiki page/revision evidence is retained in
`/tmp/item32-nutrition-wiki.json`; updated cards must explicitly distinguish
lichen's nonrotting exception, canid lycanthropy restrictions, ordinary fresh
corpse hazards, and safe identified food from tripe/eggs/tins or undead garlic.

## Implementation

`food.py` parses reviewed identified-comestible description variants
(including `partly eaten`) and public floor/look-here text for the expanded
comestible list (rations, cram/K/C-rations, lembas, fruit, garlic, wolfsbane),
and public lycanthropy evidence (`You feel feverish`, a were-bite message).
`menus.py` parses NLE's native pickup menu from `tty_chars` (no structured
field exists). `foraging.py` adds `FoodSkill` and the shared
`food_action_error` predicate: collect an identified non-shop comestible
within a bounded five-step route while unburdened (`Command.PICKUP`,
confirmed against the exact menu text), else eat it from the floor only at
Hungry or worse with an exact offer match. `tasks.py` adds `Command.PICKUP`
and `ActionRole.FOOD_PICKUP` to `nle-survival-actions` (60 actions), forbidden
to routine or fallback selection. `corpse.py` widens `ALLOWED_CORPSES`,
removes lichen's 19-turn cap, and adds `eligible_lichen` for a pet-moved
corpse identified only by its exact text at a new cell, without kill-turn
provenance. `coordinator.py` and `evaluation.py` share every new predicate
between live execution and replay audit. `safe-corpses-v2.md` and
`nutrition-foraging.md` (bundle `survival-reviewed-v2`) cite the reviewed
NetHackWiki pages for the widened list, lichen's nonrotting property,
canid-lycanthropy cannibalism, ration/fruit nutrition values, and the
undead-garlic interaction; `survival-reviewed-v1` and its cards stay
byte-identical.

## Audit: a stale same-cell kill record

Exercising the candidate against real seeds before committing to the 90-run
sweep surfaced a correctness defect, not merely a qualification outcome: a
single gate rejection, `EAT requires the observed fresh corpse under the
hero`, paused seed 1300 at turn 1600. A sewer rat was later killed on exactly
the cell of an earlier untracked lichen sighting. `CorpseSkill` correctly
selected the lichen actually displayed there, but `_hunger_permit`'s
re-validation branched on whether *any* same-cell kill record existed before
checking the evidence's own kill-turn, so the unrelated sewer-rat record
shadowed the valid lichen and the live gate rejected a correct EAT. The same
defect existed in the evaluator's replay audit. Both call sites now dispatch
on `evidence.kill_turn is None` first, matching the pattern the route-step
auditor already used. A permanent regression test
(`test_real_seed_1300_eats_untracked_lichen_shadowed_by_a_later_same_cell_kill`)
reproduces the exact scenario on the real seed. This fix applied to arms B
and C before any reported episode below; no seed's recorded outcome used the
defective code.

## Fresh three-arm comparison

All three arms ran the frozen setup on seeds 1300-1329: actual
`AgentCoordinator` and `ScriptedDevelopmentModel`, `NetHackScore-v0`,
`nle-survival-actions`, `reach_level(0,5)`, cap 3000, separate immutable
source snapshots (`git worktree` at `6645966` for A; the candidate copied
into isolated trees for B and C, with the frozen patch applied only to C) and
separate data/report directories. Hunger death means starvation or last live
hunger Weak or worse.

### Arm A: immutable HEAD `6645966`

Report: `/tmp/item33-arm-a-run/reports/nutrition-probes-development-20261003T194909Z.json`.

**24/30 objectives, 2 deaths, 0 hunger deaths, 4 truncations**; 31,623 steps;
zero invalid/gate/integrity problems.

| Seed | Outcome | Steps | Death cause (hunger at death) |
| ---: | --- | ---: | --- |
| 1300 | truncated | 3000 | — |
| 1301–1309 | objective_complete (9/9) | 429–1534 | — |
| 1310 | death | 734 | killed by a fox (not_hungry) |
| 1311 | objective_complete | 389 | — |
| 1312 | death | 1351 | killed by a giant bat (not_hungry) |
| 1313–1320 | objective_complete (8/8) | 397–989 | — |
| 1321 | truncated | 3000 | — |
| 1322–1326 | objective_complete (5/5) | 424–1180 | — |
| 1327 | truncated | 3000 | — |
| 1328 | objective_complete | 463 | — |
| 1329 | truncated | 3000 | — |

### Arm B: reviewed nutrition package

Report: `/tmp/item33-arm-b-run2/reports/nutrition-probes-development-20261003T201531Z.json`.

**24/30 objectives, 0 deaths, 0 hunger deaths, 6 truncations**; 37,624 steps;
zero invalid/gate/integrity problems.

| Seed | Outcome | Steps | Death cause (hunger at death) |
| ---: | --- | ---: | --- |
| 1300 | truncated | 3000 | — |
| 1301 | objective_complete | 496 | — |
| 1302 | truncated | 3000 | — |
| 1303–1305 | objective_complete (3/3) | 717–1443 | — |
| 1306 | truncated | 3000 | — |
| 1307–1320 | objective_complete (14/14) | 391–2632 | — |
| 1321 | truncated | 3000 | — |
| 1322–1326 | objective_complete (5/5) | 354–1506 | — |
| 1327 | truncated | 3000 | — |
| 1328 | objective_complete | 462 | — |
| 1329 | truncated | 3000 | — |

### Arm C: nutrition package plus the frozen note-0032 corrections

Report: `/tmp/item33-arm-c-run2/reports/nutrition-probes-development-20261003T201534Z.json`.

**20/30 objectives, 4 deaths, 1 hunger death, 6 truncations**; 36,918 steps;
zero invalid/gate/integrity problems.

| Seed | Outcome | Steps | Death cause (hunger at death) |
| ---: | --- | ---: | --- |
| 1300 | truncated | 3000 | — |
| 1301–1302 | objective_complete (2/2) | 390–796 | — |
| 1303 | death | 955 | killed by a bat (not_hungry) |
| 1304–1308 | objective_complete (5/5) | 477–813 | — |
| 1309 | truncated | 3000 | — |
| 1310–1311 | objective_complete (2/2) | 481–1566 | — |
| 1312 | truncated | 3000 | — |
| 1313 | objective_complete | 620 | — |
| 1314 | truncated | 3000 | — |
| 1315–1320 | objective_complete (6/6) | 173–1331 | — |
| 1321 | truncated | 3000 | — |
| 1322 | death | 1254 | killed by a gnome (not_hungry) |
| 1323 | death | 402 | killed by a bat (not_hungry) |
| 1324–1326 | objective_complete (3/3) | 342–1122 | — |
| 1327 | death | 2315 | killed by a hobgoblin (**fainting**) |
| 1328 | objective_complete | 1096 | — |
| 1329 | truncated | 3000 | — |

## Separate development reruns (not a shipment gate)

Reruns of 1218, 1265, 1275 and 1299 under B and C, same score/survival/
reach-D5/cap-3000 setup, zero invalid/gate/integrity problems in every run.

| Seed | B outcome / steps | C outcome / steps |
| ---: | --- | --- |
| 1218 | objective_complete / 1464 | objective_complete / 1235 |
| 1265 | objective_complete / 2399 | death (killed by a giant bat, not_hungry) / 2534 |
| 1275 | objective_complete / 394 | objective_complete / 1315 |
| 1299 | truncated / 3000 | truncated / 3000 |

B turns all four reviewed Fainting deaths from the pre-implementation audit
into completions or truncations with no death at all. C also avoids every
Fainting death on these four seeds, but 1265 now dies to combat (a giant bat)
instead, matching the audit's own caveat that recovered nutrition is not a
survival guarantee. Reused seeds; not a qualification gate.

## Frozen-rule decision: ship B

| Criterion | A (baseline) | B | C |
| --- | ---: | ---: | ---: |
| Objectives not lower | 24 | 24 — Pass | 20 — **Fail** |
| Total deaths not higher | 2 | 0 — Pass | 4 — **Fail** |
| Hunger deaths not higher | 0 | 0 — Pass | 1 — **Fail** |
| Invalid / gate / integrity | 0/0/0 | 0/0/0 — Pass | 0/0/0 — Pass |

C fails three of the frozen criteria: fewer objectives (20 vs 24), more total
deaths (4 vs 2), and a new hunger death (seed 1327, Fainting) absent from both
A and B. This reproduces note 0032's own unqualified result: pairing the
frontier-first exit-discovery correction with the nutrition package does not
rescue it. **B qualifies**: equal objectives, every death eliminated (2→0),
no hunger deaths, and zero invalid actions, gate rejections, or integrity
problems across all 30 seeds including the fixed gate-rejection bug above.
Per the frozen selection rule, **B ships**; the note-0032 correction is not
part of this delivery.

## Verification

Full pytest: **587 passed** (adds the seed-1300 regression test), zero
warnings beyond pre-existing deprecations. `ruff check .` and
`ruff format --check .` pass on 53 files after mechanical autofix/format.
`git diff --check` on the staged candidate reports no whitespace errors.
Strict MkDocs build from a `git checkout-index` export of exactly the staged
tree succeeds with no warnings. Actual scripted staircase regression (current
policy, temporary suite reusing `staircase-v1`/`-v2` seeds 1-10, cap 1000):
**10/10** objectives, zero invalid actions, gate rejections, or integrity
problems. Report:
`/tmp/item33-staircase-regression/reports/staircase-dev-regression-development-20261003T203700Z.json`.

`survival-reviewed-v1` reloads byte-identical (same version hash and 5,917
characters / 1,480 tokens as before this work); `survival-reviewed-v2` loads
at 5,985 characters / 1,497 estimated tokens, under the 6,000/1,500 bound.
`POLICY_VERSION`, the default `staircase-reviewed-v3` bundle, and every
published evaluation suite are unchanged. The unmerged `item10-suites`
worktree and its files were not touched. No subagents were used for this
work.
