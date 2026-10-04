# 0045: Three ordered single-rule qualifications

The director authorizes, in order: (1) load-refusal recovery including surplus food; (2) bounded look-here discovery retaining MORE pages; (3) corrected hazard behavior including reviewed ranged dagger clearing and a shipped-behavior fallback in trapped states. Each decision uses its own new frozen thirty-seed paired sample and every note0040 aggregate and trace-causal gate. Finish each decision, commit its disposition, then continue; stop after these three decisions. Vault guard 1377, combat without an available safe prayer, and hidden-continuation search remain unchanged.

## Rule 1: frozen before either fresh arm

Baseline is shipped HEAD `2b7740e`, copied before product edits to `/tmp/rule-drop-baseline`. Import isolation was checked: its module resolves to `/tmp/rule-drop-baseline/src/nethack_agent/coordinator.py`. The completed baseline 67-seed development report is reused, not rerun or replaced: `/tmp/3b-base-dev/reports/unified-d5-regression-v2-development-20261004T092820Z.json` (54 objectives, five deaths, eight truncations). Its public events remain in `/tmp/3b-base-dev/runs.sqlite3`.

Fresh seeds **301-330** are reserved in the global ledger before either arm. Frozen suite `/tmp/rule1-burden-fresh.json` uses Score/survival/reach-D5/cap3000 and the scripted development model. Both fresh arms and the candidate full 67-seed development arm use survival-reviewed-v2. Qualification reports retain the baseline policy label until a decision; candidate identity is the source fingerprint below, not a claim that the baseline immutable policy already contains this behavior. A qualifying ship must create a new policy/suite pin, leaving old reports and suite labels unchanged.

Candidate changes only load-refusal recovery. Observed encumbrance Stressed or worse (>=2), plus a public refusal about carrying too much or being unable to move a handspan, activates dropping. Stop at Burdened or better (<=1). Protect one food ration, the publicly wielded weapon (or the first held weapon if polymorph unwields it), and publicly worn equipment. Surplus food and other nonessential items may be dropped. Choose by conservative public object-class unit-value estimates, then inventory letter; these estimates are not unidentified-item identities or exact shop prices. Partial stacks use a count followed by the exact currently offered item letter. Runtime gate and stored-event audit share the same stateful predicate, including inventory description, quantity, offered letter, next command, and refusal step. Preserve the native drop question and its bounded MORE acknowledgements; hunger item-letter `d` is not mistaken for opening DROP.

The food pickup encumbrance rule remains unburdened-only. A cell where this recovery dropped surplus food is excluded from proactive food collection while a carried food reserve remains, preventing immediately retrieving the discarded load and dropping it again. Once carried food is exhausted, existing floor-food eligibility and prompt rules govern retrieval; no new idle action or loop retry is added.

### Actual cause of seed 5

Stored public observations identify **wererat polymorph**, not an assumed normal carrying capacity or strength drain. At step1902/turn1913 hit dice becomes positive (2), maximum HP becomes 9, encumbrance is Overloaded (5); surrounding messages include collapse under the load and a werejackal bite. A later transition at step1933/turn1945 gives maximum HP7, still encumbrance5. Public hero glyph90 identifies wererat; `strength_25=19` and `strength_125=24` stay unchanged. Native diagnostic replay found capacity27 and inventory weight236, but neither hidden value is a policy input. The rule keys off public encumbrance and refusal, not HP7 or guessed capacity.

A real native replay of the recorded seed5 prefix reached step1972 and `You can't do that while carrying so much stuff.` Opening DROP and answering only offered `$`, `e`, `g`, `f`, `h`, `i`, `j` dropped gold, four surplus rations, a scroll and potions. Encumbrance changed **5 -> 4 -> 2 -> 1**; the MORE pages reported rebalancing and finally movement only slightly slowed. Final inventory was exactly the alternate dagger and one uncursed food ration. Every changed DROP/count/item step passed the actual runtime gate and stored-event action predicate. Existing MORE transport was exercised separately. No qualification episode was substituted by this diagnostic smoke.

Before freezing, the existing full suite exercised 617 passing cases and one obsolete action-table-copy assertion; that copy-only test was deleted, not repinned. The resulting affected skill/task tests passed **134/134**; Ruff check and format check passed. Permanent consumer regressions cover refusal/encumbrance boundaries, protected gear/reserved food, non-ration surplus food, partial-stack quantity/offered-item mismatch, shared runtime/audit rejection, and drop -> Burdened -> no pickup -> no repeated drop, including an unburdened stash with the reserve still held.

### Frozen SHA-256

- burden.py: `ed0370aeb3ba91636146fc4bcfa9e1a92be50f13b95c61a71a9d61d024ff61c9`
- decision.py: `dc37b7553fb1a5549d15fad08db83570d417a4b41708a11d78fe988db9b85983`
- tasks.py: `dd8383bf89fc5e0f51d15bad5334fc52c31721a292395c8fd3cf1f636e4099c2`
- coordinator.py: `44711e1b82abec0775a77b6a3265889ffbdbf300c1569de7528b4172839b94c7`
- environment.py: `562232f19e337f097006716f1b97d78b854e54f05b899f9ea969623f9a7ae386`
- evaluation.py: `d74a9a20d458d6f2ee70c98f492d6171ee81ecacba418444cfd815814913c9eb`
- foraging.py: `df9dfc3c9aa71d7a33a770024e0b620ba374002ab054a4a07423199e819b6618`
- test_skills.py: `5a52fc201603d487c8953fe6f89430fbd5eb7fd69af35918fcbd1035360ef876`
- test_tasks.py: `6706599643423d11b631b24ee3a58228e4ef7fe6fcf66abdcdabcb55288df4b0`

No qualification result is claimed at preregistration. Run all remaining three arms as finite background jobs with explicit 3600-second deadlines. Product and tests remain frozen during qualification. Objectives must not decrease and deaths must not increase on either set; fresh hunger deaths must not increase; all records complete with zero invalid actions, gate rejections, or integrity failures. Trace every lost success/new death in both sets to changed-rule defect versus unrelated divergence reaching an existing failure. No unexplained or changed-rule-defect loss may ship; any behavior correction consumes this sample and requires a new frozen fresh sample before either arm.

## Rule 1 spoiled sample: real wiring defect, not a trapped-state limitation

Fresh 301-330 matched baseline exactly (27/30 both arms, identical outcomes, zero invalid/gate/integrity on both). The full 67-seed development arm found one real gate rejection: seed5 stopped at step1905 (`EAT cannot answer an active prompt`) instead of truncating like baseline.

Root cause, confirmed from stored public events and source: `nethack.Command.EAT`'s raw key code (`'e'`, 101) is reused by the survival action profile as the ONLY action object for that key, because `role()` excludes it from the generic prompt-key set (`tasks.py` only adds a letter as a distinct prompt-key entry when its code is not already a task command, and EAT already is one). Burden recovery legitimately needs to press this same key to pick inventory letter `'e'` in the native drop menu (here, "4 food rations" at slot `e`). `AgentCoordinator.advance()` calls `self._hunger_permit(selection, before)` **unconditionally, before `gate.resolve()`**, and `_hunger_permit` only special-cased `selection.intent.food`, not `selection.intent.drop`; it proceeded to `hunger_action_error(..., prompt_active=True)`, which unconditionally returns "EAT cannot answer an active prompt" and raises before `resolve()`'s own correct `drop is not None` early-return (already present, validated through `burden_action_error`) ever ran. `evaluation.py`'s stored-event audit (`_action_is_valid`) and `ActionGate.resolve()` itself were already correct; only the coordinator's eager permit call had the gap.

Fix: `_hunger_permit` now also returns `None` immediately when `selection.intent.drop is not None`, mirroring its existing `food` bypass, so any burden-drop answer sharing EAT's letter skips hunger-permit computation entirely and reaches `resolve()`'s dedicated drop path. This is a one-line, narrowly-targeted fix to a genuine pre-existing collision (also latent for any future consumer of plain prompt-letter 'e'), not a scope change. A new permanent regression (`test_hunger_permit_defers_a_burden_drop_answer_sharing_the_eat_letter`) calls `_hunger_permit` with a real `AgentCoordinator` and a burden-skill drop intent whose action is literally `Command.EAT`, asserting it returns `None`; it fails without the fix and passes with it. Only `coordinator.py` and `test_coordinator.py` changed; every other file keeps its original SHA-256 above. Full suite and Ruff passed after the fix.

Per this note's own preregistered protocol, a behavior correction mid-qualification consumes the sample: fresh 301-330 is spoiled and never reused (ledger updated), both prior fresh reports are kept only as evidence of the defect, and the full development report that found the defect is likewise not reused as qualification evidence. A new fresh range **331-360** is reserved before either corrected arm.

### Corrected frozen SHA-256

- coordinator.py: `ad47d75b88f7d222341a8e232cfd4593efb56a77752366e6cb1623fbfa627bf6`
- test_coordinator.py: `ef6c615c27092198b7d2638c57e19fbeaa578326bf220f8f11e048cb908ec414`

## Rule 1 second spoiled sample: burden preempted combat defense

Fresh 331-360 matched baseline exactly (22/30 both arms, identical outcomes, zero invalid/gate/integrity). The full 67-seed development arm had exactly one change: seed5 went `truncated`(baseline)->`death`(candidate, "killed by a jackal"), a raw death-count increase (5->6) that fails this note's own preregistered "deaths must not increase" gate.

Traced from stored public events: at step1902 a non-pet werejackal (confirmed via `nethack.permonst`) is displayed directly adjacent to the hero in the exact observation used for the next decision, the same turn the load refusal fires. `_decide()` checked `self._burden`'s drop-opening branch *before* `_attack_adjacent_hostile`, so the coordinator opened a multi-turn NetHack drop-item menu instead of fighting back. NetHack cannot process movement/attack commands while that menu is open, so the hero absorbed free bites for the whole ~10-action drop sequence (HP35->9->7->6->3), survived only via a forced low-HP prayer (HP3->31), then died to the werejackal plus a monster it summoned before escaping (HP31->0 over 4 more turns). This is a genuine changed-rule priority defect, not a pre-existing failure: defense already ran before hunger/food/corpse (all deliberately deferred while burden is active); burden's insertion ahead of defense, instead of behind it, was the mistake.

Fix: swapped the two blocks in `coordinator.py` so `_attack_adjacent_hostile` is checked before opening a new burden-drop sequence (an already-open multi-key answer is unaffected, since NetHack accepts no other input until it is answered). A new permanent regression (`test_adjacent_hostile_defense_preempts_opening_a_new_burden_drop`) places a displayed non-pet werejackal adjacent to the hero under an Overloaded refusal message and asserts `_decide` attacks it instead of opening DROP, then asserts burden proceeds normally once the monster is removed; it fails without the fix and passes with it. Full suite (620 tests) and Ruff passed after the fix.

Per the same preregistered protocol, this is a second behavior correction mid-qualification, so fresh 331-360 is also spoiled and never reused; both reports are kept only as defect evidence. A third fresh range **361-390** is reserved before either corrected arm.

### Twice-corrected frozen SHA-256

- coordinator.py: `19a58fef94a7eaba1529e0c687d222f8248bac1fb4e9a564dc632422d9393942`
- test_coordinator.py: `f2bc4bf080de4dec76ee28aa819bfc35c681a1babc10155e64caefb0ed4cc564`
- all other files: unchanged from the SHA-256 lists above.

## Rule 1 completed: QUALIFIED and shipped

Both twice-corrected arms completed without tooling cutoff or replacement episodes.

| Set | Baseline | Candidate | Changes |
| --- | --- | --- | --- |
| Unified development, 67 seeds | 54 objective, 5 death, 8 truncated | identical | 0 |
| Fresh 361-390, 30 seeds | 24 objective, 4 death, 2 truncated | identical | 0 |

Every one of the 97 combined episodes has an identical outcome to baseline, and both arms have zero invalid actions, zero gate rejections, zero integrity failures, and complete records on both sets. Fresh hunger deaths are 0->0. There is nothing to trace: this is a strict no-regression result, not a narrow win-loss tradeoff. The two real defects found during qualification (the EAT/inventory-letter key collision, and burden preempting combat defense) were fixed and reverified against the full suite before either corrected sample, not shipped unfixed or left as accepted limitations.

Shipped the exact qualified decision/skill/coordinator/evaluator behavior as policy `hierarchical-survival-hp-prayer-burden-v1`, pinning new immutable `unified-d5-regression-v3.json` (copied from v2 with only `suite_id`/`policy_version` changed). Qualification reports retain their original policy label and frozen file hashes, not relabeled evidence. Knowledge remains `survival-reviewed-v2`, unchanged by this rule. `run_manager.py POLICY_VERSION`, `README.md`, and `ARCHITECTURE.md` updated; `docs/development.md` points at v3. All three fresh samples (301-330, 331-360, 361-390) are permanently consumed per the ledger; only 361-390 is qualification evidence.

Proceeding to rule 2 (bounded look-here discovery preserving MORE pages) and rule 3 (corrected hazard behavior) next, each with its own new frozen thirty-seed sample.
