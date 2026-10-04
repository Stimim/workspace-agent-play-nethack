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

### Post-ship correction: three of rule1's commits never staged its product code

While starting rule 2, `git status` on a prior rule2 baseline worktree checkout failed with `ModuleNotFoundError: nethack_agent.burden`: the three rule1 commits (preregister, EAT-letter fix, defense-priority fix) only ever passed `coordinator.py`/`test_coordinator.py` to `--only`, never `burden.py` (new file), `decision.py`, `tasks.py`, `foraging.py`, `evaluation.py`, `test_skills.py`, or `test_tasks.py`. The checked-in tree was non-functional from a clean checkout despite the ship commit's docs/policy-version changes. This was a commit-hygiene gap, not a behavior change: every one of those files was exactly the content already qualified and described above. Commit `90535b1` adds precisely the missing files unchanged; a fresh worktree checkout at `90535b1` now imports and passes the full 619-test suite (fewer than main because rule2's in-progress tests are not yet committed). No new fresh sample was needed since nothing behavioral changed.

## Rule 2: frozen before either fresh arm

Baseline is shipped HEAD `90535b1` (rule1 shipped plus the catch-up commit above), worktree-checked-out and verified isolated (`uv run python -c "import nethack_agent.coordinator as c; print(c.__file__)"` resolves under `/tmp/rule2-baseline`, 619 tests pass).

Candidate adds look-here discovery of a staircase covered by an ambiguous object pile. NetHack's arrival line collapses two or more objects on one cell into "There are several/many objects here.", which previously left the covered terrain permanently unknown; the existing stairs-traversal card already anticipated this ("known only if observed before being covered, or from the look-here message... when standing on it") without the agent having any way to invoke it. `Command.LOOK` (':') is added to the survival action profile (role ROUTINE, matching SEARCH/WAIT; no new permit). A new deterministic check (`discover_ambiguous_pile`, lowest priority, after burden/defense/prayer/hunger/food/corpse and before kick-continuation/exploration) presses it once when the current message is exactly one of those two phrases and no prompt is active.

NetHack's explicit look response for a genuine multi-object pile is **not** a one-line message: it renders a full-screen "Things that are here:" overlay with its own `--More--` pagination, which NLE auto-dismisses by default (confirmed via raw `misc`/`tty_chars` probing: `message` stays empty while `misc[2]` (xwaitformore) is 1 and the real listing is only in `tty_chars`). `environment.py` now preserves this screen exactly like the existing pickup/drop special-casing (`_look_menu_open`, mirroring `_pickup_menu_open`/`_drop_prompt_open`), tracked via the same `misc`-derived wait-for-space signal across however many pages the pile needs; the existing generic `SafePromptHandler` already acknowledges every page, unchanged. A new narrow parser (`stair_here_from_tty`, alongside `pickup_menu_from_tty`) scans the preserved rows for the two public look-here staircase fragments already in `navigation.py`'s `_STAIR_HERE_MESSAGES`; `ObservationProjector` exposes the match as a new optional `ProjectedObservation.look_stair` field (old stored events without it still round-trip; empty string is rejected), and `DungeonMemory.observe` feeds it into the existing `_correct_terrain_here` call alongside the arrival message, reusing that function entirely unchanged. No other pile contents (ordinary item names) are parsed or fed anywhere; this stays as narrow as rule 1.

Verified before freezing with real native NLE I/O, not fixtures: a direct `misc`/`tty_chars` probe first showed the screen being silently discarded (`message=b''`, no preservation), then after the fix a controlled scenario (drop the hero's own starting items back onto the native upstairs they spawned on, force the next decision to see the ambiguous arrival message) showed the coordinator press a genuine `Command.LOOK`, preserve a real "There is a staircase up here." / "Things that are here:" / `--More--` screen, correct the remembered terrain to the upstairs cmap, and the existing MORE handler close out the page on the next step. A permanent regression (`test_look_discovers_a_covered_staircase_under_a_real_native_pile`) reproduces this exact real-I/O sequence; `stair_here_from_tty` and `discover_ambiguous_pile` also have direct unit coverage, and `ProjectedObservation.look_stair` has round-trip/validation coverage. Full suite (630 tests) and Ruff passed before freezing.

Fresh seeds **391-420** are reserved before either arm in the global ledger. Frozen suite reuses the same Score/survival/reachD5/cap3000/survival-reviewed-v2 protocol and scripted development model as rule 1; the candidate full 67-seed development arm also uses survival-reviewed-v2. Objectives must not decrease and deaths must not increase on either set; fresh hunger deaths must not increase; zero invalid actions, gate rejections, or integrity failures; complete records. Trace every lost success/new death to a changed-rule defect versus unrelated divergence; any behavior correction consumes this sample and requires a new frozen fresh sample before either arm, exactly as rule 1's two corrections did.

### Frozen SHA-256

- menus.py: `49247f58df1fa4c2b918e02c71252274626bfd2d56dd8c38568ad44ae3ae3d73`
- observation.py: `e868f45bbe94dfce9358b338c7addbb5f3ca4299483de5ca9617e25669550251`
- navigation.py: `134f6db19e697e946ebf32f67918552165ca577713d588e9c626d2e7ea847ae2`
- environment.py: `5322c490c7c5a30d31589650ddec557a77a06fca393f3de2b7044bb66cf4f591`
- skills.py: `2df7b40318520f535d05e6fc7f7834d914c4efa15a5d0e46d26d8bbc084525bf`
- coordinator.py: `3ab2d4558c7e5de0a484115d0f4725cfd15c0f5d285dbcb660bc50f5a2413ff6`
- tasks.py: `3fb85df2b4b72ba8170cc7fcba088264d8cbb4b32eff7ad951df03af0d857af2`
- test_menus.py: `4564961d262ac1fdd0ff5b8f39d6c58152dd0d8fdde4b29c98a6664b5427e50a`
- test_observation.py: `8856e23ae08029cce3315c434cff23467ffbc8c65edd7fefb6a677d9c74e32ad`
- test_skills.py: `18fba92f39281825685ccbdbd6c91e77f512105dd7796e37eba7d1dee2a86b13`
- test_coordinator.py: `10ac1c3377dab7e72d7d3a36f41fef1a69b4a7a4984e3d5908800bded523fc75`

No qualification result is claimed at preregistration. Run all arms as finite background jobs with explicit 3600-second deadlines. Product and tests remain frozen during qualification.

## Rule 2 completed: QUALIFIED and shipped

Both arms completed without tooling cutoff or replacement episodes, compared against a fresh rule1-HEAD baseline (`90535b1`, the first baseline this project has had to isolate in a git worktree rather than reuse an old report, since the corrected rule1 baseline post-dates every earlier saved report).

| Set | Baseline | Candidate | Changes |
| --- | --- | --- | --- |
| Unified development, 67 seeds | 54 objective, 6 death (1 starvation), 7 truncated | 54 objective, 5 death, 8 truncated | seed 5 only |
| Fresh 391-420, 30 seeds | 18 objective, 8 death (1 starvation, seed 406), 4 truncated | identical | 0 |

Fresh matches baseline on every one of 30 episodes, including the one fresh starvation death (seed 406, unaffected since LOOK never fires there). The single development-set change is a **gain**, traced causally rather than assumed: seed 5's stored events show `Command.LOOK` firing six times starting at step 1976 (confirming the new rule actually activated, not a coincidental unrelated divergence), and the hero's recorded fate changes from `died of starvation` (fainting, step 2122) in the baseline to `truncated` at the step cap, still exploring dungeon level 4, in the candidate. Both arms have zero invalid actions, zero gate rejections, zero integrity failures, and complete records. No new deaths anywhere; fresh hunger deaths are unchanged at 1 (the same seed).

Shipped the exact qualified decision/skill/coordinator/evaluator/environment behavior as policy `hierarchical-survival-hp-prayer-burden-look-v1`, pinning new immutable `unified-d5-regression-v4.json` (copied from v3 with only `suite_id`/`policy_version` changed). Qualification reports retain their original policy label and frozen file hashes. Knowledge remains `survival-reviewed-v2`, unchanged by this rule. `run_manager.py POLICY_VERSION`, `README.md`, and `ARCHITECTURE.md` updated; `docs/development.md` points at v4. Fresh seeds 391-420 are permanently consumed per the ledger.

Proceeding to rule 3 (corrected hazard behavior) next, with its own new frozen thirty-seed sample.

## Rule 3: frozen before either fresh arm

Baseline is shipped HEAD `5536c7d`, worktree-checked-out and verified isolated.

The note 0044 rejected candidate's blanket gas-spore adjacency avoidance is **not** reintroduced: a public NetHackWiki source check (On-death explosion, Gas spore) found a gas spore "cannot attack on its own" and only explodes "when it is killed by HP loss" — mere adjacency is not itself dangerous, so avoiding it bought no real safety and caused note 0044's trapped-state rejections for nothing. The existing `_NEVER_MELEE` exclusion (unchanged, already shipped) already stops the hero from ever being the one to kill a spore in melee. The real residual risk, confirmed from stored seed703 events (the hero died from a plain `Command.SEARCH` three squares from where it had been, `HP11->0`, matching the historical "killed by a gas spore's explosion" xlog cause), is something *else* — a monster, not the hero — killing an adjacent spore. Rule 3 adds one narrow, purely additive capability: when a displayed non-pet gas spore is aligned with the hero (row/column/diagonal) at Chebyshev distance >= 2, with a clear ray and no pet/peaceful inside its blast radius, throw a reviewed non-cursed dagger at it from outside the blast (NetHack 3.6.7 `src/explode.c`: 3x3 centered on the spore, Chebyshev radius 1, already cited in note 0044). Nothing restricts any existing move, search, or wait, so there is no new trapped state; this is the "shipped-behavior fallback" the director's prerequisites named — when no safe throw exists, existing behavior is simply unchanged.

New `ActionRole.RANGED_THROW` for `Command.THROW` (checked before the prompt-key classification, exactly like `BURDEN_DROP` for `DROP`, since letter 't' would otherwise misclassify). New `Skill.RANGED_THROW` and `ThrowEvidence` (letter, target cell, direction, next command), validated end-to-end by `throw_action_error` dispatched first in both `ActionGate.resolve()` and the stored-event audit, exactly mirroring `burden_action_error`. `_hunger_permit` and `_prompt_permit` gained the same early bypass already needed for `drop`/`food`, since inventory letters and direction keys collide with other commands (the dagger's own letter 'b' is also the SW direction key; NW direction is also the "yes" confirmation key) — found and fixed during this implementation, not after a failed qualification run, by directly tracing every existing early-permit guard rather than waiting to rediscover the collision class rule 1 already taught.

Verified with real native NLE I/O at each step, not assumptions: a direct raw probe first showed NLE silently auto-dismissing the open `Command.THROW` prompt ("Never mind.") exactly like the undiscovered LOOK/pickup/drop cases, confirming `environment.py` needed the same `_allow_all_modes` preservation (`_throw_open`, tracked across both the item-selection and direction sub-prompts via their exact public message prefixes) before any higher-level behavior could be tested at all. After the fix, a controlled native scenario (direct native dagger in starting inventory, a synthetic aligned gas-spore target re-asserted into memory each step since `LevelMemory.observe` rebuilds `monsters` from real glyphs every step) drove a genuine `Command.THROW` -> dagger-letter -> direction sequence through the full coordinator and runtime gate with zero `ActionGateError`s. A permanent regression (`test_ranged_throw_presses_a_genuine_native_throw_open_letter_direction`) reproduces this exact sequence. Pure-function unit tests cover alignment/minimum-distance/blocked-ray rejection, pet/peaceful blast-radius exclusion, the full open/letter/direction re-derivation, and shared runtime-gate/audit rejection of mismatched evidence. Full suite (635 tests) and Ruff passed before freezing.

Fresh seeds **421-450** are reserved before either arm in the global ledger. Same Score/survival/reachD5/cap3000/survival-reviewed-v2 protocol and note0040 gates as rules 1 and 2. No qualification result is claimed at preregistration; product and tests remain frozen during qualification.

### Frozen SHA-256

- hazard.py: `e2d573414f3ac505c46b1541d92b0604169738ec934014e9924199f220de184f`
- decision.py: `f8c3c4304a45353ef133a69e65b70057f6aafc005f672cf574cc4f2fb749fcf0`
- tasks.py: `84ba6d482824ee980cc57864ba707d973648ba5220886a8bacf1991239529f4f`
- coordinator.py: `6fb9ce9e0410707331cbf0e1b846ed37f26e1d8473bf69edf3d8f6bf19efc061`
- environment.py: `2bb9fd040fca58b85d786e07615e5b3e22605c6e4841c8c84d2a3fe2bf203eb7`
- evaluation.py: `de5d28baae572b89b0d25c2a96e13b50b2101622fa6438111b159c21a6b93050`
- test_skills.py: `d298a0bc6cfca34c09f4dc31d01ebff7b1fbe08b72d69826810efe0aab4cb450`
- test_coordinator.py: `789ca77a1607697b33967e5654adbd8258ae1cd5c2f4c77127b1c68c5d9c8d9c`

## Rule 3 spoiled sample: a real permit-collision defect, not a trapped-state limitation

Fresh 421-450 matched baseline closely but was not the decisive evidence: the full 67-seed development arm found **8 errors** (seeds 1, 703, 902, 1370, 1376, 1379, 1528054415, 2105401147), and the fresh arm found 4 more (422, 436, 441, 450) — all the identical contract error, `"step survival action is invalid: prompt-key actions require the deterministic hunger or corpse cancel flow"`.

Traced immediately (not guessed): `Command.THROW`'s own name, `"Command.THROW"`, is itself a member of `PROMPT_KEY_ACTION_NAMES` (that frozenset is still built from `_HUNGER_ADDITIONS`, which still includes the THROW command — adding the new `RANGED_THROW` role in `tasks.py` only changed `role()`'s classification, not this separate static name set). `survival_action_selection_error` checks `action_name in PROMPT_KEY_ACTION_NAMES` as an unconditional blanket gate with no throw exemption, called directly and unconditionally by `events.py`'s `StepPayload.__post_init__` on every recorded step — a **third** independent validation surface, entirely separate from `ActionGate.resolve()` and `evaluation.py`'s `_action_is_valid`, both of which already had correct early throw bypasses. The earlier native coordinator smoke tests and the permanent regression never exercised `StepPayload` construction, so they could not have caught this; the full evaluation harness, which stores every step as a `StepPayload`, did.

Fix: added the same early-return block already used for `drop` at the very top of `survival_action_selection_error`, authorizing a throw selection before the generic `PROMPT_KEY_ACTION_NAMES` check is ever reached. Verified directly (not just by rerunning): `"Command.THROW" in PROMPT_KEY_ACTION_NAMES` is confirmed `True`, and `survival_action_selection_error` now returns `None` for the exact previously-failing selection. A second, unrelated bug was caught by the same full-suite run: the rule3 ledger note exceeded the ledger's 300-character limit, breaking five unrelated fresh-draw tests; shortened and reverified. Full suite (635 tests) and Ruff passed again after both fixes.

Per the same preregistered protocol, fresh 421-450 is spoiled and never reused; a new range **451-480** is reserved before either corrected arm.

### Corrected frozen SHA-256

- decision.py: `ae22f1c2bdb556159a0f4f483bf44c0153c5af811a4be9ae0f91cdda163af6c0`
- all other files: unchanged from the SHA-256 list above.

## Rule 3 second spoiled sample: a real oscillation defect, not a trapped-state limitation

Fresh 451-480 completed with zero errors (the first fix worked), but 4 of 30 episodes (451, 452, 454, 472) changed from a clean `objective_complete` in baseline to `truncated` with 300-900+ model decisions each in the candidate, versus 1-3 normally; the full development arm found the identical pattern on 8 seeds (1, 5, 703, 1370, 1376, 1379, 1528054415, 2105401147).

Traced directly from stored events, not inferred: seed 451 opens `Command.THROW` correctly (`"What do you want to throw? [$ab or ?*]"`, the hero was carrying gold), but the *next* decision falls through to `model_fallback` choosing `MiscDirection.WAIT` ("You don't have that object."), `MiscAction.MORE` cancels it ("Never mind."), and since the gas-spore trigger condition is still true, `Command.THROW` immediately reopens — an unbounded open/reject/cancel cycle until the step cap. Root cause: `_THROW_PROMPT`'s letter group was `[A-Za-z]+` (copied from the EAT-item regex), which cannot match an offered `$` — NetHack always offers gold as throwable when the hero carries any, so any gas-spore throw opportunity while holding gold broke immediately. `burden.py`'s own `_DROP_PROMPT` already uses a permissive `.*?` group for exactly this reason; `hazard.py` did not.

Fix: changed `_THROW_PROMPT` to the same permissive `.*?` pattern (the existing per-character `frozenset` membership check after the match already handles `$` correctly). Verified directly: the fixed regex matches `"What do you want to throw? [$ab or ?*]"`; a real native replay of seed 451's exact recorded prefix (steps 1-408) now completes the full open/letter/direction sequence cleanly (`"The dagger misses the gas spore."`) and resumes ordinary exploration immediately, zero oscillation. A new permanent regression covers a gold-offered throw prompt. Full suite (635 tests) and Ruff passed again.

Per the same preregistered protocol, fresh 451-480 is spoiled and never reused; a third range **481-510** is reserved before either twice-corrected arm.

### Twice-corrected frozen SHA-256

- hazard.py: `71ca98c0596c6e9f7105d4e434b520dcc7257251932c8dc0b1f952638eeeb0e0`
- test_skills.py: `8a3db6c481c1aa508bc94cf187c4f8948df52638e754832a003c7902930222a4`
- all other files: unchanged from the SHA-256 lists above.
