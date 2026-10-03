# 0029: Corpse-meal lifecycle and hunger-death diagnosis

Date: 2026-10-03. Milestone 2, item 8 defect correction; item 9 remains
unchecked and no search budget is shipped. This diagnosis follows the rejected
[bounded-search probes](0028-bounded-search-probes.md), not a fresh acceptance
sample. The known development seeds remain excluded from future acceptance.

## Original eleven-death diagnosis

The original traces include nine legacy-search deaths (1170, 1174, 1186,
1194, 1197, 1199, 1204, 1207, 1209) and two candidate-ordering deaths (1190,
1206). Seed 1190 was **successful at legacy search**, not a legacy death;
legacy 1206 was truncated. Candidate 300/450/600 deaths in these two seeds
shared the same recorded trajectories. This distinction matters when comparing
the all-legacy rerun below.

All heroes start with 18 HP and NotHungry. `min/last/max` below means minimum
observed live HP, final live HP, and final live maximum HP; terminal NLE stats
are zeroed and are not treated as a live hunger/HP observation. Hunger turns are
the first public decision at each transition, including recovery transitions.
The `while` qualifiers come from each episode's public terminal xlog, not an
inference from the Fainting hunger category. Legacy 1209 repeatedly fainted and
recovered before starvation, but its final xlog has no helpless qualifier.

| Seed / original arm | Hunger transitions (game turns) | HP min/last/max | Death / helplessness | Known ration inventory transitions | Corpse WAIT decisions | Weak/Fainting prayer dispatch | Missed eligible corpse candidates (kill turn) |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| 1194 (legacy) | Hungry@732 → Weak@829 → Fainting@886 | 8/8/31 | coyote; fainted from lack of food | 1: an uncursed food ration | 545 | meal: 46; defense: 3 | lichen@505, newt@654 |
| 1197 (legacy) | Hungry@942 → NotHungry@948 | 3/3/32 | sewer rat; not specified | 1: an uncursed food ration; 948: none | 0 | never Weak | none |
| 1199 (legacy) | Hungry@738 → NotHungry@744 → Hungry@2135 → Weak@2235 → Fainting@2294 | 14/28/46 | iguana; fainted from lack of food | 1: an uncursed food ration; 744: none | 729 | meal: 140; defense: 7 | giant rat@2042, newt@2308 |
| 1204 (legacy) | Hungry@950 → NotHungry@956 → Hungry@1760 → Weak@1860 → Fainting@1919 | 10/36/36 | sewer rat; fainted from lack of food | 1: an uncursed food ration; 956: none | 478 | meal: 70; defense: 4 | none |
| 1207 (legacy) | Hungry@758 → NotHungry@764 → Hungry@1553 → Weak@1653 → NotHungry@1656 → Hungry@2405 → Weak@2505 → Fainting@2564 | 7/7/18 | jackal; fainted from lack of food | 1: an uncursed food ration; 764: none | 0 | eligible: 1; confirmed: 1; repeat timeout: 85; defense: 1 | none |
| 1209 (legacy) | Hungry@1143 → Weak@1243 → Fainting@1302 | 12/23/23 | starvation; not specified | 1: 2 uncursed food rations | 1007 | meal: 186 | none |
| 1190 (candidate300) | Hungry@742 → Weak@842 → Fainting@896 | 7/16/26 | jackal; fainted from lack of food | 1: an uncursed food ration | 527 | meal: 139; defense: 8 | none |
| 1206 (candidate300) | Hungry@1138 → Weak@1237 → Fainting@1296 | 16/40/40 | starvation; fainted | 1: an uncursed food ration | 870 | meal: 190; defense: 2 | newt@654 |
| 1170 (corrected) | Hungry@751 → Weak@851 → Fainting@910 | 8/16/18 | gecko; fainted from lack of food | 1: an uncursed food ration | 460 | meal: 142; defense: 3 | newt@686 |
| 1174 (corrected) | Hungry@946 → Weak@1046 → Fainting@1105 | 9/12/27 | jackal; fainted from lack of food | 1: an uncursed food ration | 917 | meal: 135; defense: 5 | newt@1467 |
| 1186 (corrected) | Hungry@760 → Weak@860 → Fainting@918 | 12/24/24 | kobold zombie; fainted from lack of food | 1: an uncursed food ration | 335 | meal: 115; defense: 4 | none |

The full read-only reconstruction at `/tmp/item9-hunger-diagnosis.json` records
**every live decision**: whether prayer selection was reached, its guard or
higher-priority preemption, every HP change, hunger transition, ration change,
meal/prayer action, eligible corpse proposal, and faint/recovery message.
Before Weak, evaluated prayers reject `not_Weak_yet`; food prompts and adjacent
hostile defense can return earlier. At Weak, the table's preemption/guard counts
cover every decision. Seven of the nine latched-meal runs keep known uncursed
rations until death. The other two (1199/1204) have already eaten their ration
and never reach an otherwise eligible first prayer. A known ration correctly
rejects prayer but must not also be blocked from eating.

### Classification and missed opportunities

- **Nine corpse lifecycle failures:** 1170, 1174, 1186, 1194, 1199, 1204,
  1209, candidate 1190, candidate 1206. Confirmation records a final message
  without the exact expected completion/interruption text, sets `_meal_corpse`,
  and then issues hundreds of WAITs **before** prayer, ration, and fresh-corpse
  selection. These are not SEARCH actions. For example, 1209 has zero SEARCH
  and starves while holding two rations; candidate 1190 has only one SEARCH.
- **Combat collapse:** 1197 eats its ration at 942–948 and dies NotHungry.
  During the final rat/wererat pressure, HP falls 32→27→16→14→7→3 across
  turns 969–974. Prayer is never hunger-eligible. No corpse opportunity was
  missed; changing prayer timeout or food priority does not address this death.
- **Long-search nutrition exhaustion:** 1207 performs 1,659 SEARCH actions.
  The first prayer at 1653 is correctly confirmed and restores NotHungry at
  1656. At the second Weak episode, 85 evaluated decisions reject the tracked
  repeat interval; earliest allowed prayer is 2882, after death at 2674. This
  is not evidence that shortening the conservative timeout would be safe.
- The table's missed candidates were actually proposed by the existing
  freshness/identity/BFS predicate, but the stale meal returned first. They
  must not be counted as completed meals or guaranteed retained nutrition.
- A separate exact-whole-message defect misses candidate 1206's early newt:
  turn 19 says `There is an open door here.  You see here a newt corpse.`;
  the skill steps away and the kitten eats it next turn. Legacy 1199 also
  alternates ten approaches to a lichen corpse (kill 749) with exploration:
  the arrival message is empty, so identification is not retained until
  freshness expires. **Only exact-clause matching is fixed here; the
  empty-message route oscillation is explicitly left for later.**

Original public tty output provides stronger completion evidence than the final
projected message in two cases: 1199 emits `You finish eating the gecko corpse.`
then a shoplifters message in the same environment transition; 1204 emits
`You finish eating the newt corpse.` then `You feel a mild buzz.`. Candidate
1206 emits rotten food, darkness, then mild buzz. Even a recent kill can produce
rotten food: 1194's rat was only three turns old when offered. Tightening the
freshness cutoff alone would not fix the latch.

## Exact-prefix causal experiments before the fix

These throwaway experiments replayed original actions and public observations,
then cleared **only** the stale latch once; they did not modify the product.

| Seed | Replayed prefix / intervention | Observed result |
| --- | --- | --- |
| 1170 | 756 actions; clear gecko latch at Hungry turn 751 | Immediately EAT ration; finished 757, NotHungry. Later successful prayers 1642–1645 and 2891–2894. Survived to 3,000-step truncation, turn 3266, Dlvl3, HP26; original gecko death was 1362. |
| 1209 | 1,140 actions; clear gecko latch at Hungry turn 1143 | Immediately EAT held ration, finished 1149. Reached Dlvl5 objective at step 1416, NotHungry, rather than starving. |
| 1204 | 1,847 actions; clear newt latch at Weak turn 1860 | Immediately PRAY, confirmed 1860–1863 with `Your stomach feels content.`. A later gecko re-created the latch; death at step 2792, last live turn 2919. One-off clearing restores prayer but does not fix recurring lifecycle failures. |

1170's shopkeeper proper name varied (Siirt/Tirebolu); only that known name in
its greeting and attack question was normalized. Actions, all other messages,
and all non-message observation fields had to match. 1209/1204 prefixes matched
all projected observations exactly. Detailed results/recordings:
`/tmp/item9-hunger-branches.json`, `/tmp/item9-hunger-branch-data/`.

## Verify the NLE step boundary first

A direct **real NLE 1.3.0** replay was run before editing. After each recorded
confirmation, the next EAT is processed as a new command rather than as a meal
continuation:

| Seed / meal | Confirmation turn span | Final projected message | Immediately following EAT |
| --- | --- | --- | --- |
| 1197 lichen | 138→142 | completion text | inventory-eat question at 142 |
| 1194 sewer rat | 314→315 | `Blecch!  Rotten food!` | inventory-eat question at 315 |
| 1204 newt | 1442→1446 | `You feel a mild buzz.` | `You don't have anything to eat.` at 1446 |
| candidate 1206 giant rat | 426→428 | `You stop eating the giant rat corpse.` | exact **partly eaten** giant-rat floor question at 428 |

All four returns report ordinary gameplay public `program_state`
`[0, 0, 0, 1, 0, 1]`, not an eating-input prompt. This agrees with the earlier
ration observation: the eating occupation advances multiple game turns inside
one environment step until it ends or is interrupted. The relevant NLE wrapper
also automatically dismisses `--More--`, which explains why only its later
message can survive projection. The occupation is not carried between these
coordinator decisions. No observed case supports a continuation latch;
`WAIT` cannot finish the occupation that NLE has already ended.

## Fix and typed contract

- Delete `_meal_corpse`, the corpse WAIT issuer, evaluator `pending_meal`, and
  continuation validation. There is no meal state to preempt nutrition: the
  next eligible prayer/ration decision wins immediately (a **zero-decision**
  bound, stronger than the requested one-decision maximum).
- Every live corpse-confirmation return records an explicit typed outcome from
  **one shared classifier** used by coordinator, event validation, and evaluation:
  `finished` for exact species completion, `interrupted` for an observed stop or
  interruption, and new `ended_unrecognized` otherwise. The last kind means
  the NLE step ended its occupation; it does **not** fabricate completion,
  nutrition gained, rotten-food specificity, or hidden prayer favor. A later
  unrelated final message and rotten food both use this honest explicit end.
  Existing `declined` remains tied to an actual deterministic floor-prompt
  decline; terminal/truncated returns never invent a live outcome.
- An explicitly interrupted corpse is not marked consumed. A later EAT may
  resume a publicly identified `partly eaten` corpse only with the same observed
  kill, exact species, original <=19-turn freshness, cell, and floor question.
  Finished, declined, and unrecognized ends retain conservative consumed handling.
- The shared underfoot matcher accepts the exact `You see here a <name> corpse.`
  clause inside a compound message, plus the exact partly-eaten qualifier for
  resumption. It does not accept another species, a suffix/prefix species match,
  or relax the separate exact floor-confirmation question.
- Replay now records map-free nutrition intents as OTHER, rather than asserting
  every deterministic intent has a map destination. The longer surviving runs
  exercised this existing assertion at corpse EAT; step reconstruction agrees
  with the coordinator's actual non-navigation record.

Synthetic regressions cover rotten food, an unrelated final message, interruption,
non-consumption of interrupted food, immediate eligible prayer/ration selection,
mandatory matching live outcomes, and terminal/truncated absence. Real NLE
regressions replay recorded legacy action prefixes for 1194's rotten rat and
1204's mild buzz from compact committed fixtures, fold the real confirmation,
then demonstrate actual ration/prayer recovery to NotHungry. The old synthetic
ongoing-meal/WAIT assumptions were removed, not re-pinned.

## All eleven requested seeds after the fix

All reruns use **legacy search**, scripted coordinator, `reach_level(0,5)`,
`nle-survival-actions`, cap 3,000. No budget or prototype ordering is enabled.
These known-seed regression results are not a held-out acceptance gate.

| Seed | Outcome | Steps | Max main depth | SEARCH | Ration EAT | PRAY | Last live hunger | Death cause |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1170 | truncated | 3000 | 3 | 1694 | 1 | 2 | Hungry | — |
| 1174 | objective_complete | 2042 | 5 | 524 | 1 | 1 | NotHungry | — |
| 1186 | objective_complete | 997 | 5 | 137 | 1 | 0 | NotHungry | — |
| 1194 | objective_complete | 1055 | 5 | 57 | 1 | 0 | NotHungry | — |
| 1197 | death | 966 | 4 | 78 | 1 | 0 | NotHungry | killed by a sewer rat |
| 1199 | truncated | 3000 | 2 | 888 | 1 | 1 | Hungry | — |
| 1204 | objective_complete | 1819 | 5 | 616 | 1 | 0 | Hungry | — |
| 1207 | death | 2585 | 2 | 1659 | 1 | 1 | Fainting | killed by a jackal |
| 1209 | objective_complete | 627 | 5 | 14 | 0 | 0 | NotHungry | — |
| 1190 | objective_complete | 815 | 5 | 18 | 1 | 0 | NotHungry | — |
| 1206 | death | 2786 | 4 | 1045 | 1 | 1 | Fainting | killed by a gecko |

Aggregate: **6 objective successes, 2 truncations, 3 deaths**. All eleven runs
have **zero invalid evaluator actions, zero gate rejections, and no integrity
problems**, including typed-event and exhaustion replay. Five of the nine
original legacy deaths become objective successes; two become live truncations.
1197's combat death and 1207's cooldown/search death are unchanged. Legacy 1190
remains its prior 815-step success. Legacy 1206 changes from a 3,000-step
truncation to gecko death while fainted at turn 2954 after one successful prayer
and ration; this is reported, not hidden. It still spends 1,045 SEARCH actions
and has no corpse continuation state. These observations justify the lifecycle
correction, not a claim of universal survival or a qualified search budget.

Free-running 1194 now has a different rat sequence (the final message is
`You are conscious again.`) and succeeds after ration eating; free-running 1204
reaches the objective before needing prayer. This is why the permanent targeted
replay fixtures preserve the original rotten-food/mild-buzz situations instead
of pinning the new free-running route. Raw traces and full food/prayer events:
`/tmp/item9-lifecycle-data/{seed}/trace.json`, `/tmp/item9-lifecycle-results.json`.

## Verification and remaining scope

- Full `uv run pytest -q`: **570 passed**, three dependency deprecation warnings.
- Full `uv run ruff check .` and `uv run ruff format --check .`: passed
  (50 Python files formatted).
- `git diff --check`: passed.
- Scripted staircase task, seeds 1–10, default task actions, cap 1,000:
  **10/10 task_success**, at steps 217, 44, 222, 47, 147, 151, 286, 222, 102, 430.
- Real NLE step-boundary probes, exact-prefix nutrition regressions, and all
  eleven complete real coordinator scenarios were exercised as described above.

The empty-message corpse-route oscillation remains outside this correction.
Repeat-prayer timeout, combat retreat, search ordering/budget, model/bundle policy,
and acceptance-suite pins are unchanged. A fresh baseline on unused seeds is
required before revisiting item 9; these retrospective runs do not supply one.
