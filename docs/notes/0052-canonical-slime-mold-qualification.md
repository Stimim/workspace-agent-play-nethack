# 0052: Canonical slime-mold food-reserve qualification

## Preregistration — frozen before either arm

Freeze time: `2026-10-18T07:58:36.616275+00:00`. This is an unshipped candidate; **no qualification
results or shipping decision are recorded here**. Raw data, external suite
copies, detached state, launch commands and freeze manifest live under
`~/nethack-evidence/0052/`. Neither the main checkout nor its index is changed.
No commit is authorized in this turn.

### One rule and boundaries

Recognize canonical `slime mold` / `slime molds` through the existing reviewed
food pipeline. `food.py` adds that identity and rejects named/called or
parenthetical suffixes for this newly reviewed fruit only, so a configurable
fruit name cannot masquerade as an annotated canonical name. Existing foods
retain their suffix handling. Matching inventory glyph/class/BUC evidence is
still mandatory. Default-name fruit is collected at the existing bounded
route cost while unburdened, or floor-eaten only at Hungry+ with an exact offer.
No new action, permit, priority, earlier eating, or navigation budget is added.
Corpse, prayer and burden-recovery behavior is unchanged.

The reviewed nutrition card is versioned as `nutrition-foraging-v2.md` in
`survival-reviewed-v3`; previous cards/manifests are unchanged. The source is
[NetHack 3.6.7 objects.c:773-785](https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/objects.c#L773-L785)
(vegetable food, 250 nutrition), plus the local dump's
[Slime mold](https://nethackwiki.com/wiki/Slime_mold) revision
`2026-03-14T02:38:01Z`. The existing loader permits only canonical NetHackWiki
URLs in the structured `sources` array, so the primary GitHub citation is
preserved in the card's review metadata (`uncertainty`) and this note; the
loader/network boundary is not relaxed. `card_version: 1` is the card schema,
not the content revision. The new bundle is 5998 characters within the unchanged
6000-character bound.

### Identity and immutable suites

Baseline worktree: `~/nethack-evidence/0052/baseline`, detached at
`22d0a5f74569277b4e030aa9a7d9427b7ecda7d9`. Candidate worktree:
`~/nethack-evidence/0052/candidate`, branch `qualify-0052-slime-mold` from the same
commit. Both have private `.venv` environments; `coordinator.__file__` and
`food.__file__` resolve beneath their respective worktree's
`nethack-agent/src/nethack_agent/`, never the main checkout.

`evaluation.py` calls `require_suite_policy`, loads the suite's explicitly
pinned bundle, then calls `require_suite_configuration` before creating an
episode. Therefore the candidate has an explicit **qualification-only** policy
identity (the only `run_manager.py` change):
`hierarchical-survival-hp-prayer-burden-look-ration-slime-qualification-v1`. Its bundle is
`survival-reviewed-v3+sha256:e30f2b0c443305d39ec8702f093d9a45a6b867dd875ce0aecebb748fb625d624`.
Baseline retains `hierarchical-survival-hp-prayer-burden-look-ration-v1` and
`survival-reviewed-v2+sha256:d5cb109e09e3d798a97f9521411a914c8fc2855916c6d4a6e3298e591e0fa19e`.

Unlike the source-fingerprint-under-old-policy approach in notes 0033/0045,
this qualification gives changed behavior/knowledge an honest separate identity.
Historical regression definitions and reports are not repinned or relabeled.
Baseline uses original `minetown-regression-v2`, `oracle-regression-v2`, and
`unified-d5-regression-v5`. Candidate regression copies outside the checkout
have `-slime-qualification-0052` suite IDs and the candidate policy/bundle pins.
Baseline fresh copies have `-baseline-0052` IDs; candidate fresh suites are
`minetown-fresh-v2` and `oracle-fresh-v2`, copied from the committed v1 schema.
Paired `cases` objects (seeds, tasks, caps, per-case criteria) were checked equal.
All ten descriptors passed no-episode loader/pin preflight before launch.

### Frozen fresh sample and execution contract

Reserve **541-570 inclusive** in the candidate's global ledger before either
arm. The baseline ledger/catalog/suites reader returned an empty intersection
with this range; the candidate reader includes the complete reservation.
The same frozen sample is paired on both target objectives, not held-out
acceptance. No redraw, replacement, mid-suite mutation, or erased failure.

Run all ten arms with two workers each through the committed
`_agents/skills/detached-eval/scripts/detached_eval.py`. State directory:
`~/nethack-evidence/0052/state`. Commands are frozen in
`~/nethack-evidence/0052/launch-commands.sh`. Each arm has a distinct data/report
directory named after its run. No tool deadline; detached `.done` markers retain
exit code and end time. This turn stops after all launch acknowledgments, without
waiting for suite completion.

Configuration: actual coordinator, `ScriptedDevelopmentModel`, Score environment,
survival action profile, lawful dwarven Valkyrie, default context 8192; Minetown
and Oracle caps 10000 action steps, D5 cap 3000. All regression seeds remain
unchanged. There is no real-model or milestone acceptance claim.

| Detached run | Frozen suite path |
| --- | --- |
| 0052-base-mt-reg | `/home/stimim/nethack-evidence/0052/baseline/nethack-agent/evaluation/minetown-regression-v2.json` |
| 0052-base-or-reg | `/home/stimim/nethack-evidence/0052/baseline/nethack-agent/evaluation/oracle-regression-v2.json` |
| 0052-base-d5-reg | `/home/stimim/nethack-evidence/0052/baseline/nethack-agent/evaluation/unified-d5-regression-v5.json` |
| 0052-base-mt-fresh | `/home/stimim/nethack-evidence/0052/suites/baseline/minetown-fresh-v2-baseline-0052.json` |
| 0052-base-or-fresh | `/home/stimim/nethack-evidence/0052/suites/baseline/oracle-fresh-v2-baseline-0052.json` |
| 0052-cand-mt-reg | `/home/stimim/nethack-evidence/0052/suites/candidate/minetown-regression.json` |
| 0052-cand-or-reg | `/home/stimim/nethack-evidence/0052/suites/candidate/oracle-regression.json` |
| 0052-cand-d5-reg | `/home/stimim/nethack-evidence/0052/suites/candidate/unified-d5-regression.json` |
| 0052-cand-mt-fresh | `/home/stimim/nethack-evidence/0052/candidate/nethack-agent/evaluation/minetown-fresh-v2.json` |
| 0052-cand-or-fresh | `/home/stimim/nethack-evidence/0052/candidate/nethack-agent/evaluation/oracle-fresh-v2.json` |

### Qualification gates

For every paired set: candidate objectives not lower, deaths not higher, and
starvation/last-live Weak-or-worse deaths not higher. All records must be
complete, with zero invalid actions, gate rejections and integrity failures.
Retain and inspect conduct/detector metrics rather than treating missing evidence
as zero. Built-in development success thresholds are not the paired shipment
decision.

Trace every lost success and new death on development and fresh samples from
stored public observations/actions, separating a changed-rule defect from a
pre-existing failure after trajectory divergence. No unexplained or changed-rule
defect loss may ship, even if aggregate gains compensate. Native truth is
diagnosis-only. A behavior correction after launch or a cutoff consumes the
sample; retain all evidence and preregister a new unused sample before new arms.
Do not rerun or replace failures. A disposition and compact per-seed evidence
must precede any integration/shipping decision.

### Consumer checks before freeze

Final candidate checks: `uv run ruff check .`, `uv run ruff format --check .`,
and full `uv run pytest`: **688 passed**, five dependency deprecation warnings,
44.24 seconds. Tests cover canonical singular/plural/partial stacks, alternate
fruit labels and annotated-name masquerades, text/glyph disagreement,
shop/burden/hallucination exclusions through skill, runtime gate and evaluator,
exact pickup-menu choices, and real seed-1365 pickup then native EAT/item-letter
consumption with the initial ration retained. The native meal test isolates its
trigger by replacing public hunger/held-choice evidence; world generation,
pickup, prompt and actual consumption are real NLE, not qualification evidence.

Preflight disclosures (all before any qualification episode): the first full
check had 683 passes and one new-card schema failure (`card_version` was
mistakenly 2). A subsequent pin preflight also rejected a GitHub URL in the
wiki-only structured source list. Both were corrected in the new review/card
metadata, without changing loader policy. Knowledge text was compacted within
the existing bound. An intermediate full run passed 684 tests; canonical
suffix-rejection cases were then added before the final 688-test run. No frozen
qualification episode was replaced and no gameplay failure was erased.

## Frozen SHA-256

Paths below are relative to the candidate worktree. This table includes every
changed product/test/knowledge/ledger/fresh-suite file. The note cannot contain
its own digest; its digest is recorded in the external `freeze-manifest.json`
and `frozen.sha256`, frozen after this note is written and before launch.

| Candidate file | SHA-256 |
| --- | --- |
| `nethack-agent/src/nethack_agent/food.py` | `0aea4332befce1cdb28ee3c370a17db05960a0f5f407adab062c499c2e6e1809` |
| `nethack-agent/src/nethack_agent/run_manager.py` | `3b3cb0f2fb71de8f3678dc34cc0e882d1ebd4297d2c822cef4dad7633c08489a` |
| `nethack-agent/tests/test_skills.py` | `621b9e794dc2366c8b41c602b7da37b67d26edb0b4845f60f587e48499856ea8` |
| `nethack-agent/tests/test_knowledge.py` | `8c32aead75e4ad5e5af95998cc3f49c0019550b7dbbd40fb517160904927e9fc` |
| `nethack-agent/knowledge/nutrition-foraging-v2.md` | `e273f485453d17ccd4c0ba44a2b03dcdfb19b0a77900ca3230f269ce42f16566` |
| `nethack-agent/knowledge/manifest.survival-reviewed-v3.json` | `98878fa866f3007e04a0f7d28155e11e1f449af2e1e336e63ae7635b411de87e` |
| `nethack-agent/evaluation/seed-ledger.json` | `c399d402dd61ce466fe50d13030f1ac9a1a411094a383c877d23cb3c1ef8711b` |
| `nethack-agent/evaluation/minetown-fresh-v2.json` | `acc9dc439d5445a8e46ba081f248b602207ca646f2d9993e59b5740819d25ca0` |
| `nethack-agent/evaluation/oracle-fresh-v2.json` | `287a0cabb3b53a5af31204a9e78dccc12711775e005315afedf591da203ab67f` |

| Baseline/external qualification suite | SHA-256 |
| --- | --- |
| `/home/stimim/nethack-evidence/0052/baseline/nethack-agent/evaluation/minetown-regression-v2.json` | `3e08dfc0da8dbafc60128c1a4a45c0b69eaf9a52903de77aa6059de4525bf864` |
| `/home/stimim/nethack-evidence/0052/baseline/nethack-agent/evaluation/oracle-regression-v2.json` | `8c716bc413d9bf4f2367d7d06744b5374362baa1a9bb5335505ee09a2d739997` |
| `/home/stimim/nethack-evidence/0052/baseline/nethack-agent/evaluation/unified-d5-regression-v5.json` | `c5a87503c5bb2598c7591fba0de71f2ab2444eb61599d630e72f2892a51303cc` |
| `/home/stimim/nethack-evidence/0052/suites/baseline/minetown-fresh-v2-baseline-0052.json` | `c220b9ab60210f5daa66789b098d057dd713e965f55a5c7b10e2c11785db6d8f` |
| `/home/stimim/nethack-evidence/0052/suites/baseline/oracle-fresh-v2-baseline-0052.json` | `d5c46f8b1d83045af36a453da969da77a60648ae0febf42866fd77055fa0cdf2` |
| `/home/stimim/nethack-evidence/0052/suites/candidate/minetown-regression.json` | `b18e823ec3e63984fba476c27ca1f0d2b9e8106cbcc86cbd0f3b78ed517c1ec9` |
| `/home/stimim/nethack-evidence/0052/suites/candidate/oracle-regression.json` | `f3dd14940d4638210ac0f5a54bd0daddaef03153e03897e1f47130115db74545` |
| `/home/stimim/nethack-evidence/0052/suites/candidate/unified-d5-regression.json` | `816b7d7aec11c600916befe97499bde0e1a1832c773c430f9f742e5526a5503a` |

## Completed qualification results

All ten detached arms completed with exit code 0: **522 episodes**, without
cutoff, replacement episodes, or a candidate mutation during evaluation.
Completion was collected with `detached_eval.py wait` and no tool deadline.
Every report records complete records, all seeds evaluated, fixed configuration,
and unchanged inputs. No death lacks last-live hunger evidence.

The three new baseline regression arms match all **201 retained note-0051
candidate episodes** on outcome, action-step count, game turns and hunger at
death. Concurrent light probes were expected CPU noise; wall time is not used
as a policy metric.

Values are baseline → candidate. O/D/T = objectives/deaths/truncations;
I/G/Int = invalid actions/gate rejections/integrity failures.

| Paired set | Baseline O/D/T | Candidate O/D/T | Weak-or-worse deaths | Starvation | I/G/Int, both arms |
| --- | --- | --- | --- | --- | --- |
| Minetown regression, 67 | 19/42/6 | 19/42/6 | 20 → 19 | 1 → 1 | 0/0/0 |
| Oracle regression, 67 | 9/53/5 | 9/54/4 | 19 → 16 | 0 → 0 | 0/0/0 |
| Unified D5 regression, 67 | 54/5/8 | 53/7/7 | 0 → 0 | 0 → 0 | 0/0/0 |
| Minetown fresh 541–570, 30 | 2/24/4 | 2/23/5 | 10 → 11 | 1 → 1 | 0/0/0 |
| Oracle fresh 541–570, 30 | 5/24/1 | 5/24/1 | 4 → 4 | 0 → 0 | 0/0/0 |

Available Oracle/peaceful-attack metrics are zero in both target arms.
Peaceful-kill/conduct fields absent from these frozen reports remain unknown,
not retrospectively zero. This is not a clean-conduct or milestone-acceptance
claim. The development runner's printed PASS/FAIL is not the paired decision.

### How often the rule actually fired

All baseline arms have zero slime FoodEvidence, pickups and meals. Candidate
counts below come from the retained public SQLite events, not proposed actions
alone. Every counted pickup initiation produced a verified inventory gain;
every counted inventory meal answer consumed a visible inventory unit.

| Candidate set | Episodes with slime intent | Native pickups | Acquired inventory units | Completed slime meals |
| --- | --- | --- | --- | --- |
| Minetown regression | 12 | 11 | 15 | 7 |
| Oracle regression | 12 | 13 | 16 | 5 |
| Unified D5 regression | 7 | 7 | 9 | 1 |
| Minetown fresh | 6 | 7 | 8 | 7 |
| Oracle fresh | 2 | 3 | 3 | 1 |
| **Total** | **39** | **41** | **51** | **21** |

There are 38 episodes with a pickup and 17 with a slime meal. The remaining
intent-only episode is Minetown seed 7: a food route decision, without a pickup.
All 21 meals were inventory meals; no floor meal occurred. Inventory gains
include retrieval of previously stolen food, not necessarily 51 distinct
generated fruits. Completed units are not a claim of 250 effective nutrition
each: real rotten-food consequences are retained below.

### Every changed endpoint: causal review

The review covers **26 changed endpoints**: ten changed outcome enums and
sixteen same-outcome changes in death cause/hunger. All have a slime-food intent
at or before the first differing primitive command. First-command indices and
all preceding equal command prefixes were independently checked against
SQLite; first slime intents were independently checked by the all-arm action
scan. No environment or native replay was run.

In the table, F/A = first slime FoodEvidence step / first different action step;
P/M = verified native pickups / completed slime meals. NH = Not Hungry;
Faint = Fainting. Every row is causal category **(ii)**: legitimate trajectory
divergence reaching an existing failure class, or a gain on a changed trajectory.
This is not an exception to any aggregate gate.

| Set / seed | Baseline → candidate endpoint | F/A | P/M | Public causal finding |
| --- | --- | --- | --- | --- |
| MT 10 | Objective → killer bee/NH death | 3611/3611 | 1/1 | Clean one-step collection; much later bee swarm kills after a full healing prayer. |
| MT 53 | Jackal/NH → werejackal/NH death | 3477/3478 | 1/1 | Safe pickup/meal; later repeated melee reaches HP1. Another mold remains held. |
| MT 1374 | Coyote/NH → large mimic/NH death | 60/60 | 1/0 | Real D1 fruit, uneaten; later D2 exploration reveals a hidden shop mimic. |
| MT 1379 | Manes/NH death → objective | 194/195 | 1/0 | Fruit remains uneaten at success: trajectory gain, not demonstrated nutrition rescue. |
| MT 279714031 | Hill orc/Faint death → objective | 420/421 | 1/0 | Safe collection; fruit remains held at success. Different combat/navigation timing. |
| MT 296200318 | Killer bee/Faint → bat/Faint death | 609/611 | 1/2 | Two meals feed temporarily; long gas-spore-blocked search/wait stall exhausts food again. |
| MT 1009099699 | Rothe/Faint → named dog/NH death | 1824/1825 | 1/1 | Meal helps hunger; later crowd/orc-captain/dog combat remains fatal. |
| MT 2094095407 | Objective → rothe/Faint death | 184/184 | 1/2 | Early visible-rat concern checked against legacy proposals; later downstairs-route oscillation exhausts food. |
| OR 6 | Iguana/NH death → truncation | 4775/4775 | 1/1 | Safe collection and meal; survives hunger cycles but remains in Oracle/search stall. |
| OR 824 | Lizard/Faint → gray unicorn/NH death | 738/739 | 2/0 | Reserve stolen/recovered but uneaten; later unicorn combat, repeat prayer locked. |
| OR 904 | Iguana/Faint → hobgoblin/NH death | 1895/1896 | 1/0 | Safe one-step target; later rock-mole/hobgoblin combat. Mold remains held. |
| OR 1362 | Giant ant/NH → invisible bugbear/NH death | 804/805 | 1/0 | Safe collection; later SEARCH continues under unseen hits after healing prayer. |
| OR 1365 | Lizard/Faint → invisible hobgoblin/NH death | 21/23 | 1/1 | Rotten slime briefly confuses; much later unseen-hit/search recovery failure. |
| OR 1374 | Truncation → large mimic/NH death | 60/60 | 1/0 | D1 reserve detour; later D2 exploration discovers hidden mimic, not a food target. |
| OR 1009099699 | Bee-poison/NH → gray unicorn/NH death | 219/220 | 1/1 | Safe meal; later lethal combat burst gives no live major-HP prayer state. |
| OR 1195605202 | Rope golem/NH → gray unicorn/NH death | 2825/2826 | 1/0 | Real two-fruit pickup, uneaten; later exploration combat while prayer is cooling down. |
| OR 1528054415 | Truncation → guard/NH death | 44/44 | 1/0 | Safe D1 food; later uncommanded gold-room displacement and ignored guard demands. |
| OR 2105401147 | Giant bat/Faint → rothe/Faint death | 1508/1511 | 1/1 | Food pursued while stunned; existing status handling is permissive. Later food exhaustion/combat. |
| D5 1374 | Objective → large mimic/NH death | 60/60 | 1/0 | Same later exploration/mimic failure, not knowingly routing toward a displayed mimic. |
| D5 1528054415 | Truncation → guard/NH death | 44/44 | 1/0 | Same inherited gold-room/guard handling failure. |
| MT fresh 549 | Black unicorn/NH → hill orc/NH death | 4328/4330 | 1/0 | Clean collection, uneaten; later melee from HP12 to4, then fatal attack. |
| MT fresh 552 | Mastodon/NH death → truncation | 1248/1248 | 2/2 | Temporarily fed, but repetitive Mines4 searching prevents objective completion. |
| MT fresh 565 | Goblin/Faint → fox/Faint death | 2985/2985 | 1/1 | Iguana was initially unseen; defense kills it before pickup. Later stairs stall/depletion persists. |
| MT fresh 566 | Sewer rat/Faint → giant ant/Faint death | 887/889 | 1/2 | Two molds consumed, second rotten; later prolonged exploration, fainting and ant attacks. |
| MT fresh 568 | Giant bat/NH → giant bat/Faint death | 755/756 | 1/1 | Longer changed trajectory outlasts reserve. This is a fresh hunger-gate regression. |
| OR fresh 558 | Giant ant/Faint → housecat/Faint death | 1007/1007 | 2/1 | Stolen reserve recovered/eaten; later repeated SEARCH while fainting permits lethal bites. |

The detailed public pre-states, both divergent commands, rule events, terminal
live states and justifications for every row are in
[`causal-review.json`](evidence/0052/causal-review.json). Successful/capped
after-observations remain valid live states; only zeroed terminal observations
are excluded. No attribution to an unseen species is invented from a glyph:
the invisible-bugbear/hobgoblin labels above come from recorded death causes.

#### Required losses and newly exposed deaths

- **MT 10:** first food action at step3611/turn3637 is unburdened, HP43/43,
  with no nearby monster. After the meal, later Mines1 bee poison reduces HP
  and a prayer restores HP68; the swarm still kills from last-live HP5/68 at
  turn4698, with a ration remaining. This is not a fruit-poisoning or
  eating-under-attack death.
- **MT 2094095407:** the new move at step185 approaches a visible sewer rat
  and takes one point of damage. This was explicitly investigated rather than
  waved away: on the identical recorded state, unchanged navigation and
  exploration both propose W to `(20,6)`, while food proposes NW to `(20,5)`;
  both cells are ordinary floor adjacent to the rat at `(19,5)`. At step186,
  recorded defense attacks W before the food route can continue. Thus a newly
  introduced adjacency policy is not demonstrated. Both later fruit meals are
  at full HP. The eventual loss follows downstairs-route oscillation and food
  exhaustion: last-live turn6759, HP23/70, Fainting, no food; prayer is not
  eligible until6820. This does not declare the inherited threat approach safe.
- **OR/D5 1374:** fruit was genuinely collected on D1 at step65 and never
  eaten. D2 `explore_level`, not the food skill, later enters the hardware store
  and reveals a previously hidden mimic at turn214, dropping HP18→8. Repeated
  melee dies at turn219 without a live HP≤5 prayer opportunity. Baseline's
  encounter instead reaches HP4 and prays. The record does not support
  describing the initial food route as an approach to a known mimic.
- **OR/D5 1528054415:** food collection on D1 is complete long before ordinary
  exploration jumps from `(31,12)` to `(62,18)` at turn1113. Public messages
  show an isolated gold room, then demands to drop money/follow at turns1142
  and1146. Searching ignores them while retaining784 gold. The final movement
  dies at turn1149, last-live HP23/23 and NH; the reserve remains uneaten.
  Trap internals are unobserved. Ignoring guard demands is an inherited
  failure, not acceptable behavior merely because the initial divergence was
  legitimate.
- **MT fresh 568:** the first pickup differs at step756 with HP18/18 and no
  nearby monster. Fruit is later consumed safely; the much longer trajectory
  runs out of food. Baseline dies at turn1171 while NH; candidate dies at3763
  while Fainting, no food, repeat prayer unavailable until3907. Longer survival
  does not excuse the preregistered Weak-or-worse count increase.

#### Retained safety/design qualifications

Oracle2105401147 starts food routing while publicly stunned after a trapped
door. Its nominal three-step route takes ten actions through pickup. Pure
same-public-state proposal comparison finds unchanged exploration proposes the
same first three movement commands while stunned; no separate status recovery
exists here. No approach damage or displayed threat was observed. The
five-step gate is a **per-proposal geometric route bound**, not a five-action
total detour guarantee.

Rotten slime meals are real: Oracle1365 becomes confused at turn2216 and
recovers by2221, long before its fatal unseen hits; Minetown fresh566 also
reports a rotten meal. These are ordinary spoilage/status consequences under
unchanged reviewed-food eating rules, not false canonical identities. Do not
claim every new meal was effect-free. Passive gas spores/floating eyes near
other meals are retained as visible context, not relabeled active attackers.

Some apparently improved hunger endpoints are not nutrition wins: Oracle824
and904 die NH with their molds uneaten, while the Minetown objective gains
1379/279714031 also retain uneaten molds. Their changed trajectories must not
be counted as proof that fruit nutrition rescued those episodes.

## Evidence and reproducibility

The ten compact per-seed records below were generated with the committed
`_agents/skills/evidence-record/record.py`, preserving actual suite IDs,
policy/bundle identities, run commands, and all 522 episode rows:

- [Baseline Minetown regression](evidence/0052/0052-base-mt-reg-minetown-regression-v2-development-20261018T075922Z.json)
- [Candidate Minetown regression](evidence/0052/0052-cand-mt-reg-minetown-regression-v2-slime-qualification-0052-development-20261018T075922Z.json)
- [Baseline Oracle regression](evidence/0052/0052-base-or-reg-oracle-regression-v2-development-20261018T075922Z.json)
- [Candidate Oracle regression](evidence/0052/0052-cand-or-reg-oracle-regression-v2-slime-qualification-0052-development-20261018T075922Z.json)
- [Baseline D5 regression](evidence/0052/0052-base-d5-reg-unified-d5-regression-v5-development-20261018T075922Z.json)
- [Candidate D5 regression](evidence/0052/0052-cand-d5-reg-unified-d5-regression-v5-slime-qualification-0052-development-20261018T075922Z.json)
- [Baseline fresh Minetown](evidence/0052/0052-base-mt-fresh-minetown-fresh-v2-baseline-0052-development-20261018T075922Z.json)
- [Candidate fresh Minetown](evidence/0052/0052-cand-mt-fresh-minetown-fresh-v2-development-20261018T075922Z.json)
- [Baseline fresh Oracle](evidence/0052/0052-base-or-fresh-oracle-fresh-v2-baseline-0052-development-20261018T075922Z.json)
- [Candidate fresh Oracle](evidence/0052/0052-cand-or-fresh-oracle-fresh-v2-development-20261018T075922Z.json)

Supplemental compact records:
[native rule firings](evidence/0052/rule-firings.json) and
[all changed endpoints](evidence/0052/causal-review.json).
The recorded commit is the parent commit, not a claim that the candidate delta
was committed: reproducing the candidate requires its retained worktree and
the preregistered file hashes/bundle, not a bare checkout of22d0a5f.

Raw reports/SQLite/ttyrecs remain in `~/nethack-evidence/0052/0052-*`.
The external analysis scripts and outputs are retained there:
`analyze-reports.py` / `paired-report-analysis.json`,
`count-slime-actions.py` / `slime-action-counts.json`,
`verify-causal-indices.py` / `causal-index-verification.json`,
`query-terminal-states.py` / `terminal-state-audit.json`, and
`compare-public-proposals.py` / `same-public-state-proposals.json`.
The SQLite action scans select each run's ordered `run_started`/`step` payloads;
terminal queries select the final nonzero-turn observation. Proposal comparison
is a pure calculation on reconstructed public memory, never a replacement
episode. No new build, lint, or test run was needed for this documentation and
evidence-only completion.

## Decision

**REJECTED. Do not ship this candidate.**

The frozen candidate fails the preregistered paired gates:

1. Oracle regression deaths increase **53→54**.
2. Unified D5 objectives decrease **54→53**, and deaths increase **5→7**.
3. Fresh Minetown Weak-or-worse deaths increase **10→11**.

Clean action/integrity records and category-(ii) causal findings do not override
these aggregate failures. No changed-rule identity/permit/priority defect was
identified in the reviewed endpoints; inherited combat, hidden-mimic, guard,
status and navigation failures are not declared solved or safe.

This is a recorded rejection pending user review, not shipping or integration.
The qualification-only policy identity, suite pins, and frozen candidate code
remain unchanged; the main checkout/index is untouched and no commit was made.
Seeds541–570 are consumed and must not be reused as a fresh qualification sample.
