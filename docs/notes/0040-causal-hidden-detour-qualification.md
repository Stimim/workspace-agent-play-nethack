# 0040: Causal qualification of hidden-passage detours

## Infrastructure integration (step A)

Commit `1262497f4521f8e9ed208b5fe5e67584c1fc04bb`, **Unify evaluation goals
under one survival agent**, integrates the reviewed `unify-infra` branch after
rebasing it onto `80a06f2`. The merge had no conflicts. Review restored
leg-specific error reporting accidentally dropped by the branch, corrected
ADR 0006's stated display floor from zero to the suite's actual minimum one,
and removed a scenario test asserting only terminal state/nonempty steps.

Verification: **604 full pytest tests passed** (46.21s; three dependency
warnings), working and staged `git diff --check` passed, strict pinned MkDocs
built successfully, and the provenance commit helper passed Ruff lint and
format checks. Actual Scout, Gold and Eat survival-profile engine smokes
consumed their inventory ration through the item prompt and advanced turns.
The first throwaway smoke assertion assumed a food-specific response string;
NLE instead said "You're finally finished." It was corrected to inventory
consumption and turn advancement, and the corrected smoke passed all three
tasks. That smoke script was removed. The integrated worktree and branch were
removed safely after the merge commit.

From now on, development episodes use the committed runner
`evaluation/unified-d5-regression-v1.json`: all 67 historical seeds exactly
once, Score/survival/reach-D5/cap-3000. Its 67/67 aspirational target is not
a commit gate. The retained HEAD baseline is **52 objectives, eight deaths,
one hunger death**, as measured before and by the infrastructure worker.
Historical task/profile suites and reports remain unchanged.

## Revised protocol (supersedes individual retention in notes 0038/0039)

This protocol is the user's revised rule, recorded before any new episode:

1. **Development aggregates:** on all 67 seeds, candidate objectives must not
   be lower and deaths must not be higher than HEAD's development result.
   Individual successful trajectories need not be retained.
2. **Causal review:** diagnose every lost success and every new death on both
   the development set and frozen fresh sample from stored traces:
   - **(i), behavior defect:** the changed behavior acts wrongly, for example
     searching beside a gas spore, creating a vault-guard situation, or
     abandoning a reachable exit.
   - **(ii), trajectory divergence:** the run diverges earlier for unrelated
     reasons, then fails through a pre-existing failure class.
   Ship only if there is no class-(i) loss, or all class-(i) defects are fixed
   first. Do not relabel a behavior defect merely because aggregate gains
   compensate for it. A fixed candidate requires a new frozen fresh sample.
3. **Frozen fresh 30-seed gate unchanged:** objectives not lower, deaths not
   higher, hunger deaths not higher than HEAD, complete records, and zero
   invalid actions, gate rejections, and integrity problems. Hunger death
   means starvation or last-live hunger Weak or worse, not zeroed terminal
   stats or worst-ever hunger.
4. **Freeze and no replacement:** preregister and reserve the next 30 unused
   seeds before either new arm; freeze product/tests before episodes; never
   mutate an evaluated candidate mid-suite, replace or rerun failed runs,
   or redraw failures. Disclose preflight failures. Retain all evidence.
5. **Retained candidate exception:** note 0039's unchanged frozen candidate
   already has aggregate evidence (development 52→52, deaths 8→8; sample
   1440–1469 objectives 17→20, deaths 7→6, hunger deaths 0→0). If all required
   causal classifications are (ii), ship that exact evaluated product without
   a new sample. If any is (i), fix it, freeze a new candidate and evaluate
   the committed development runner plus an entirely new 30-seed sample.

Required causal cases: development lost successes 1, 1369, 1377,
1528054415 and 1887524929; new development deaths 703 and 1379 (1377 overlaps
a lost success); fresh lost successes/new deaths 1446 and 1467. Diagnosis
uses public recorded observations, actions and memory replay. Native engine
state may support a diagnosis but must never become policy input. Evaluate
old and retained proposals on the same recorded public state where useful;
do not run replacement episodes to explain a failed seed.

## Retained trace diagnosis

No episode was rerun. Both policies were executed as pure proposal functions
on the **same reconstructed public states** from the retained candidate
SQLite events. Memory replay uses the recorded actions, objective planner,
level links, search coverage, and model re-arms in coordinator order; every
replay marker and kick audit passed. The comparison also finds the earliest
changed *destination*, not just the first changed action: two routes can
share several initial moves before their trajectories separate.

Evidence export: `/tmp/causal-hidden-replay.json`. Stored observations before
each decision are used, not zeroed terminal observations. Event sequence and
executed action-step index differ by one because of the initial resume event;
the action-step indices below are explicit. The earliest changed destination
and the failure mechanism were examined together. Identical terminal
proposals alone would not excuse a wrong decision earlier in a run.

| Set / seed | Earliest changed behavior (action step) | Failure evidence and causal classification |
| --- | --- | --- |
| Dev 1 | 204, D1: legitimate search route (74,6) instead of (56,12); no stairs known | **(ii)**. At cap on D4 the main downstairs (46,15) is known but unreachable: the hero's component contains only one cell, with floating eyes and a gas spore surrounding it. Both policies make the same bounded monster-wait proposal. This is the pre-existing unsafe-monster route blockage, not abandonment of a reachable exit. |
| Dev 1369 | 947, D2: search destination (28,15) instead of (23,18); no monsters or known downstairs | **(ii)**. At cap it still searches D2 with no known compatible stairs; 334 known cells are reachable. Both policies select the same 34-step route to search stand (49,12), and sampled steps 1499/2499 also agree. Legitimate changed search attempts precede an existing hidden-exit/search-budget failure; no known reachable exit is discarded. |
| Dev 1377 | 216, D1: valid search route (46,6) instead of (45,16), sharing the initial pet-swap move | **(ii)**. At action 1851, unchanged stair navigation walks toward known stairs (8,5), onto publicly ordinary floor (13,6), and an uncommanded level change relocates the hero to a gold-filled D2 room. It does not choose a vault as its search destination. Both policies then propose the same covered-cell checks, guard attack at 1881, and final SEARCH at 1891 (12 HP). Involuntary relocation plus pre-existing vault/guard handling causes the death, not a new vault-entry or guard-compliance rule. |
| Dev 1528054415 | 715, D3: search route (30,15) instead of (41,14); nearest gas spore five cells away | **(ii)**. At cap a gas spore and shopkeeper block the eight-cell reachable component; no compatible downstairs is known. Both policies search in place, with the inherited increasing search-round budget, at sampled steps 2499 and 3000. This is existing blocked-component/re-arm behavior after an earlier harmless search divergence. |
| Dev 1887524929 | 757, D4: continue reachable search (25,7) instead of approaching a frontier behind a floating eye | **(ii)**. The displaced frontier is not freely reachable and no downstairs are known; searching a reachable alternative is legitimate. At cap a floating eye isolates the hero in one cell. Both policies make exactly the same in-place search proposal with the inherited re-arm budget. No reachable exit is abandoned. |
| Dev 703 | 193, D3: seek search stand (19,8) instead of waiting next to the gas spore at (17,7), moving away from that blocker | **(ii)**. Much later, the fatal room-wall search at (55,3) is eligible under the *unchanged* room-wall rule, not a new corridor target. At steps 535, 550 and 552 both policies propose the same SEARCH there; at 552 the hero has 11 HP and the gas spore is at (53,3). Even the route to this stand at 532 is identical. The explosion exposes pre-existing search/threat recovery weakness after earlier unrelated exploration divergence; this is not a newly introduced preference to search beside a spore. That behavior remains unsafe and is not called a solved blocker. |
| Dev 1379 | 1713, D3: continue search (17,9) instead of approaching the frontier occupied by a red mold at (8,12) | **(ii)**. The alternative is reachable and the old frontier unsafe; there is no known compatible exit. Its long search inherits round 109 from the earlier unchanged re-arm churn. Both policies make identical SEARCH proposals at 1899/1999; when the homunculus becomes adjacent, both make the same melee proposal at action 2042 with 15 HP. The eventual death is the pre-existing HP/threat combat class, not search continuing in preference to defense against that visible adjacent hostile. |
| Fresh 1446 | 642, D4: nearer search stand (48,11) instead of (44,16); 27 HP, no visible monsters or known downstairs | **(ii)**. At action 1293 the hero has 2 HP, a cave spider and wererat adjacent, and known stairs (8,14) blocked. Both policies attack the same cave spider; the wererat kills the hero. Earlier search ordering diverges without a visible hazard, and unchanged low-HP melee/recovery fails. |
| Fresh 1467 | 316, D4: search a newly eligible continuation at (69,17) instead of routing to (50,11); 18 HP, no visible monsters or stairs | **(ii)**. At action 1357 the hero has 4 HP beside a giant bat. Both policies make the same melee proposal and it dies to the bat. Neither the first changed search nor the terminal combat state introduces a new attack/recovery rule. |

**All nine required cases are (ii); no class-(i) loss was found.** This does
not declare monster waiting, SEARCH beside dangerous monsters, vault
handling, or low-HP melee safe. It distinguishes existing weaknesses reached
on changed trajectories from an erroneous rule introduced by this patch.
In particular, the recorded 703 blast and 1377 guard death are not waved away
without examining their immediately preceding public states and unchanged
proposals. These weaknesses remain important inputs to HP/threat recovery.

## Retained qualification decision

**Ship the exact retained frozen candidate, with no new sample.** Development
objectives 52 >= 52 and deaths 8 <= 8 pass the revised aggregate rule; the
1440–1469 frozen qualification improves objectives 17→20, deaths 7→6, and
hunger deaths remain 0→0. Every record is complete and invalid actions, gate
rejections, and integrity problems are zero. All required losses/new deaths
have trace-supported class-(ii) diagnoses.

The original note-0039 rejection remains immutable historical evidence under
the former rule; this note supersedes its shipment decision, not its runs.
The patch SHA-256 remains
`b1ba89b6c42c7fb77d16d10c68c4e45c2aa1228096a0c8028956f1d347d17a91`.
The committed unified runner and the old external development suite were
checked to have exactly the same 67 unique seed/task/cap contracts and the
same character, policy and knowledge pins. Unification changes supported
TaskSpec validation, not this valid Score objective's policy behavior.
There is therefore no substitution of a new implementation into old reports.

The reported development hunger-death change 1→0 still comes from 1376's
earlier Not-Hungry goblin death, not improved nutrition or prayer. Targeted
seeds 1368/1372 now complete; 5/701 still truncate and 703/1379 die. Those
remaining failures are disclosed, not counted as six solved seeds.

## Shipped integration verification

The main-tree `skills.py` and behavioral `test_skills.py` match the retained
evaluated candidate byte-for-byte. SHA-256:

- Product: `13e4fa57a76155a12ecb775faaf322384f9191665496dc5f32f29f0de81dbc80`.
- Tests: `b1e0b583f9b01763a7c98a3c10331f30e9fd15c98898a3c4e01e7b1d5aafe94a`.

The complete integrated suite passed **609 tests** (46.47s, three dependency
deprecation warnings). Actual coordinator behavior remains the unchanged
127 retained NLE episodes; public-state replay exercises the changed proposal
paths and confirms the causal comparisons without replacing failed episodes.
Earliest decision differences also remain in
`/tmp/causal-hidden-first-divergence.json`, complementing
`/tmp/causal-hidden-replay.json` and the complete original SQLite/ttyrec/report
artifacts identified in note 0039. No new seeds or sample were consumed.
The staged documentation export passed a strict build with pinned MkDocs
1.6.1, pymdown-extensions 12.1 and mermaid2-plugin 1.2.3. The throwaway causal
replay script was removed after preserving its JSON evidence.
