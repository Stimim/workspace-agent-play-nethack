# ADR 0007: Mines, Minetown temple, and peaceful Oracle

- Status: proposed
- Date: 2026-10-05
- Refines: [ADR 0004](0004-traversal-goals-and-task-progression.md), [ADR 0005](0005-early-survival-and-seed-evaluation.md), and [ADR 0006](0006-unified-goal-suites.md)

## Context

Milestone 3 measures two places with the same lawful dwarven Valkyrie, not
one tour of both places. D5 acceptance failed on a Fainting death despite
16/20 objectives ([0046](../notes/0046-descend-d5-v2-real-model-acceptance.md)).
Longer routes must solve navigation, food, and peaceful handling together.
This is a design only: the existing `FindOracleLeg`/`ApproachOracleGoal`
contracts have no planner behavior, `TaskSpec` rejects Oracle on Score, and
there is no Minetown leg or peaceful-kill metric yet.

Source authority is **NLE 1.3.0's NetHack 3.6.7**, inspected locally at
`/tmp/item9-nle-1.3.0-source`; linked source below identifies the corresponding
release. The local wiki reader supplied [Minetown][wiki-town],
[Oracle (level)][wiki-oracle-level], and [Oracle (monster)][wiki-oracle].
The Minetown dump now describes 5.0.0: its Lua maps and extra peaceful
inhabitants are not evidence about 3.6.7. Source wins where they differ.

## Decision

### 1. Targets and public success evidence

**Minetown:** enter the temple's interior on Mines level 3 or 4. **Orcish
Town counts**, with a different final predicate: stand on its unaligned
altar, not merely in the surrounding building. **Oracle:** stand in one of
the eight neighboring cells of a currently peaceful Oracle, without ever
attacking her in this episode. Consultations are unnecessary.

**Verified Orcish Town exception.** `dat/mines.des:55-92` declares `minetn-1`,
a single lit `"ordinary"` region (line 83), and
`ALTAR:(20,13),noalign,shrine` (line 92). No temple region/subroom is declared
in that variant; the priest and Watch are corpses (`118-128`). The word
`shrine` does **not** create a temple: `src/sp_lev.c:2082-2091,2114-2126`
sets the altar but returns before priest/shrine setup outside a `TEMPLE`.
`src/hack.c:2523-2524` calls `intemple` only for `TEMPLE`. Thus this ordinary
region has no temple-entry message, not even the untended-temple random
message. By contrast minetn-2..7 declare temples at
`dat/mines.des:259,328,428,634,674,799` ([maps][src-mines], [altar creation][src-special],
[room entry][src-hack]). This resolves the roadmap's provisional rule.

| Detector | Required public evidence | False-positive / false-negative risks |
| --- | --- | --- |
| Mines level 3/4 | Public `blstats` dungeon identity `(dnum=2,dlevel=3 or 4)`, plus recorded branch-stair arrival `(0,b) → (2,1)` for `b=2..4`. Count branch-relative levels, not visits: Mines level `m` has Dlvl `b+m`. Verify stair links and reconcile skipped levels with public DLEVEL/depth, rather than incrementing once per descent. | Dlvl alone overlaps main dungeon; a second `>` is not proof of a branch before crossing. Trap falls can skip levels. Missing entry link leaves identity/count provenance incomplete, not guessed. |
| Temple entry | On that candidate Mines level, an entry transition plus one exact message below; retain the evidence and room boundary in memory. | Feelings also occur outside temples; require local altar/room evidence for generic untended messages. Messages may be suppressed, combined, or lost in MORE pages; preserve complete public message/tty history. |
| Silent temple fallback | Remember an observed altar cmap and its enclosing interior floor component bounded by observed walls/doors; count an outside→interior crossing only after the enclosure and altar are established. If already inside when the altar is discovered, current interior occupancy proves entry. An ambiguous/open enclosure is insufficient; standing on the publicly identified altar is a conservative sufficient fallback for non-Orcish temples. | An altar glyph alone does not prove room type, alignment, or actual occupancy. Objects/hero cover terrain; reuse same-level observed terrain or look-here text. Incomplete boundaries cause delayed/missed success, never an invented room. |
| Orcish Town altar | Candidate Mines level, public town layout/barricade evidence, remembered altar location, and non-hallucinatory look description `unaligned altar`; hero coordinates equal that cell. | Noalign is not encoded in the altar glyph. A mimic or incomplete town identification can deceive; cross-check persistent layout and on-cell look evidence. Bones/altered layouts require uncertainty, not a template coordinate shortcut. |
| Peaceful Oracle adjacency | Exact normal monster glyph for `Oracle` (270 in this build, derive by species name), current same-cell public description `peaceful Oracle`, Chebyshev distance exactly 1, live observation, and episode attack count 0. | `@`, statues, fountains, and sounds are only search hints. Hallucination, stale descriptions, invisible/covered Oracle, bones without her, or hostility prevent success. Neither her normal glyph nor presumed initial peacefulness proves current attitude. |

Placement follows `dat/dungeon.def:19,22-24,71-76` and
`src/dungeon.c:350-377,870-872,1092`: Mines entrance Dlvl 2-4, Minetown
branch level 3-4 (Dlvl 5-8), Oracle Dlvl 5-9. `minefill` supplies the other
Mines levels (`dat/mines.des:7-48`); cave shape is not Minetown identity.
**Sokoban's up-branch is on the level below the Oracle**, Dlvl 6-10, not
above it ([placement][src-dungeon-def], [depth arithmetic][src-dungeon]).

Exact Minetown-relevant entry text from `src/priest.c:399-495` ([source][src-priest]):

- `Pilgrim, you enter a sacred place!` / `Pilgrim, you enter a desecrated place!`
  (spoken, with the displayed quotation marks).
- `You have a forbidding feeling...` / `You have a strange forbidding feeling...`
- `You experience a sense of peace.` / `You experience an unusual sense of peace.`
- Untended: `You have an eerie feeling...`, `You feel like you are being watched.`,
  or `A shiver runs down your spine.` (body-part wording can change with form).
- Untended has a **1/4 no-message branch**; tended speech needs a mobile,
  awake priest, hearing, and elapsed entry timer; feelings have their own
  timers. Already-in-temple returns immediately. The `intones:` introduction
  and optional ghost appearance are not success predicates. Sanctum-only
  `Infidel...`, `Be gone!`, and `You desecrate...` are excluded by location.

Request NLE's **public `screen_descriptions`** and persist only relevant
cell descriptions/attitude evidence in the typed observation. NLE generates
these via `do_screen_description`, the ordinary player look interface
(`win/rl/winrl.cc:491-515,939-941`); `src/pager.c:283-297` supplies `peaceful`
only when accurate, and `492-507` supplies altar alignment. Current adapter
keys do not include this field. `specials` and monster glyphs do not encode
peaceful status; `blstats` exposes alignment **type**, not alignment record
or Luck (`winrl.cc:535-562`). Do not read `mpeaceful` directly ([NLE projection][src-winrl],
[player descriptions][src-pager]). A local reset smoke verified NLE 1.3.0's
`(21,79,80)` description array and normal Oracle glyph 270; it did not exercise
temple entry or Oracle adjacency.

**Phase 1 amendment (2026-10-05): opt-in observation transport.**
Request `screen_descriptions` only for `enter_minetown_temple` and
`find_oracle`. It is not a passive observation addition in this NLE build:
`win/rl/winrl.cc:940-941` conditionally calls `store_screen_description`,
which calls `do_screen_description` at line 508. The call chain
`src/pager.c:1119` (`lookat`) → `466` (`look_at_object`) → `247`
(`object_from_map`) → `192` (`mksobj(glyphotyp, FALSE, FALSE)`) constructs
temporary objects for stale/covered/mimic object glyphs. Even with `init=FALSE`,
`src/mkobj.c:1072-1086` calls `rndmonnum` for corpse/statue/figurine species;
`rndmonnum` calls `rndmonst` at `364`, which consumes
`rnd(rndmonst_state.choice_count)` at `src/makemon.c:1591`; its fallback
consumes `rn1` at `src/mkobj.c:371`. Object allocation also increments
`context.ident` at `783`, and
look evidence can set `dknown` at `src/pager.c:231`. Thus asking for public
look descriptions can affect gameplay RNG and state. An early live seed-16
staircase test changed from its expected exhausted search to success at
step 181 when descriptions were unconditionally enabled.

Existing objectives retain their exact old observation-key tuple. The same
seed therefore plays a different game under Minetown/Oracle than under
reach-D5: **cross-objective comparisons are not paired**. Pairing is valid
only with the same objective and observation transport. The new sparse,
typed description evidence remains ordinary public look evidence; no native
state enters policy or completion.


Native-truth validates all visited Mines levels and Oracle candidates
**offline** against special-level identity, room type, altar, and monster
attitude. Publish detector confusion counts and missed/no-message cases,
including every minetn variant, filler levels, both placement depths, and
suppressed entry text. Native memory must never select actions, populate
policy memory, or rescue an uncertain public success predicate.

### 2. Objective legs, goals, and environment

- Add strict `enter_minetown_temple` leg and level-scoped temple-entry/altar
  goals. Planner sequences `enter_dungeon(2)` → descend through filler levels
  → inspect level 3 → inspect level 4 if needed → locate altar/temple → enter
  interior, or occupy Orcish Town altar. Once town is publicly identified,
  stop descending. Preserve branch links on ascent and recovery.
- Enable `find_oracle` and reuse `ApproachOracleGoal`, strengthening completion
  to the peaceful/no-attack predicate above. Descend **main** Dungeons of Doom
  stairs; explore each Dlvl 5-9 sufficiently to find her. Centaur statues,
  four fountains, Delphi greetings and level sounds prioritize search but
  never complete the leg. If accidentally below her, climb the known main
  stairs, not Sokoban's second `<`; recover from other branches by recorded links.
- Both suites use **`NetHackScore-v0` + `nle-survival-actions`**, per ADR 0006.
  Update objective/environment validation, persisted leg/goal/evidence
  contracts and evaluator replay together; historical artifacts stay readable.
  `NetHackOracle-v0` checks only the exact glyph anywhere in the hero's 3×3
  neighborhood (`nle/env/tasks.py:146-170`), without peacefulness or attack
  history, and terminates immediately. Reject it as acceptance environment;
  its engine success is not our stricter objective ([NLE task][src-tasks]).

### 3. Conduct gates and audit

Planner/skills avoid forbidden actions **before proposing** them. Runtime
gate independently checks stored public evidence; evaluator reconstructs
memory and reruns that same predicate for every action, including prompt
answers, not merely specialist selections. Zero gate rejections remains a
quality gate: successfully blocking an unsafe proposal still fails a suite.

| Constraint | Gate and evaluator rule |
| --- | --- |
| Watch / locked doors | No door kicks anywhere on candidate Mines levels 3/4, even before town is recognized, including Orcish Town. This overrides the existing locked-door-kick rule; ordinary OPEN remains available. No wall/door vandalism or lock tampering in town. Audit kick initiation **and direction/continuation** against the pre-action level. |
| Fountains | No quaffing/dipping, fountain damage, or Excalibur attempt; keep these commands unavailable to this profile and reject offered fountain confirmations. Walking on fountains is allowed and necessary near the Oracle. |
| Shops | No unpaid pickup/eating, theft, shop damage, or pet-assisted theft. Unknown shop membership means no floor-item acquisition until public boundaries resolve it; track unpaid inventory/debt and prevent leaving with debt. Audit food, drop, and every offered item/confirmation as well as movement across exits. |
| Temple / priest | No priest attack, altar conversion/sacrifice, or prayer on any altar (existing safeguard). Entering a cross-aligned temple is allowed. Do not confuse entry feelings with a prayer permit. |
| Peaceful creatures | Read current public descriptions; never attack tame/peaceful creatures. Decline every `Really attack?` confirmation. Treat unknown attitude as non-attackable until public evidence resolves it; no attacks while hallucinating. Dwarven hero's usually peaceful gnomes/dwarves are not a universal species guarantee. |
| Oracle / centaurs | Never attack Oracle or living centaurs, even hostile; never break centaur statues. Protect them in melee destinations, kick directions, and any later ranged trajectory/area-effect permit. Route around, wait, or retreat; never bypass via forced-fight or a `y` answer. |

The central fountains/statues and Oracle placement are explicit in
[dat/oracle.des:10-26](https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/dat/oracle.des#L10-L26);
[src/monst.c:2211-2217](https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/monst.c#L2211-L2217)
gives her `M2_PEACEFUL` at creation, not a public guarantee forever.

The Watch warns or arrests door vandals (`src/dokick.c:1294-1328`);
fountain use can warn and drying it angers guards (`src/fountain.c:168-217`).
Public `gets angry!`, arrest/warning text, and newly hostile Watch/priest/shop
attitudes become conduct incidents and invalidate a claimed clean run,
not evidence of a kill by themselves ([door conduct][src-kick],
[fountains][src-fountain], [Watch wiki][wiki-town]). Orcish Town's iron bars
are a real navigation blocker: qualification must cover a publicly justified,
reviewed digging/bar-breaching capability with target/tool/direction permits,
or report inability to enter as failure. Do not award success for seeing the
altar through bars or substitute temple-building proximity.

### 4. Suites, caps, and acceptance

1. **Development:** new immutable `minetown-regression-v1` and
   `oracle-regression-v1` each reuse exactly ADR 0006's 67 unique historical
   seeds, with target-specific objectives/caps. Track 67/67 as aspirational,
   not a commit gate. Baseline each target on the shipped policy once; classify
   deaths/hunger, true blockers, branch confusion, conduct, and detector errors.
   Each product rule qualifies separately under [0040](../notes/0040-causal-hidden-detour-qualification.md):
   paired aggregate objectives not lower, deaths not higher, fresh hunger
   deaths not higher; diagnose every lost success/new death; no changed-rule
   defect may ship. Freeze a new 30-seed paired sample per rule and never
   replace failures ([0045](../notes/0045-three-single-rule-qualification.md)).
2. **Held-out cap probes:** freeze policy/model/bundle and reserve 30 unused
   seeds **per target**, disjoint from development, qualification and acceptance.
   Preregister a 30,000-step ceiling and candidate caps
   `{5000,10000,15000,20000,30000}`. Choose the smallest retaining at least 90%
   of ceiling-run completions by their observed completion steps; zero
   completions cannot establish a cap. Report truncations and completion
   distribution; insufficient ceiling requires a new preregistered probe set,
   not rerunning censored failures. Longer-than-3,000 is a hypothesis, not a
   measured requirement. NLE defaults to **5,000**, a configurable abort cap,
   not a hard maximum (`nle/env/base.py:177,213-215,242`); our adapter already
   sets inner NLE cap to outer Gymnasium `cap+1` (`environment.py:199-205`).
   Suite/API validation allows up to **100,000**. Record both effective caps
   and distinguish action steps from game turns ([NLE base][src-base]).
3. **Fresh acceptance:** `minetown-v1` and `oracle-v1` each draw 20 fresh seeds
   from `[1000000,2147483647]`, excluding the entire used-seed ledger **and
   the other suite's reserved draw**. Record draw seed/seeds before any episode;
   reserve all probes/draws, including spoiled launches. Freeze policy, knowledge,
   `gemma4-nethack:latest`, context 8192, cap and gates before either run.
   Rate rule per target: `max(0.50, floor((p_probe - 0.15)/0.05)*0.05)`, using
   only that frozen target's held-out outcomes at the chosen cap, following
   [0035](../notes/0035-descend-d5-cap-probes.md). If probes cannot support
   the 0.50 floor, improve policy and reprobe; do not lower the floor.
4. **All episodes, baseline and fresh:** zero starvation (`sum <= 0`), zero
   Weak-or-worse deaths (`hunger_at_death maximum <= 2`, last **live** state;
   missing evidence fails), zero peaceful kills, Oracle/centaur attacks and
   conduct incidents, zero invalid actions/gate rejections, complete SQLite,
   ttyrec and replay/audit records. Fresh success rates decide each target;
   both must pass to accept milestone 3. Report paired historical changes
   separately; no heterogeneous Scout/Eat task-reward gate. First committed
   real-model runs decide acceptance; failure remains, retry requires a new
   qualified policy and fresh draws. Run detached with completion marker or
   tool `timeout: 0`, never accept cutoff as a result.

**Peaceful-kill measurement is not a message counter.** NLE exposes no public
peaceful-kill total, alignment record, or Luck. `You murderer!` applies to
certain non-chaotic human kills, not all peacefuls; peaceful kill luck loss
can be silent/random, and `You feel guilty...` concerns co-aligned unicorns
(`src/mon.c:2462-2478,2498-2516`). Attacking can first make the victim hostile
(`2916-2931`), so retain **pre-attack** public attitude, not only attitude at
its eventual death ([kill/anger source][src-mon]).

Define `peaceful_kills` as confirmed **hero-attributed kills of a creature
publicly peaceful/tame before hero aggression**, joining observed target
identity/position, pre-action descriptions, attack/anger and kill messages.
Do not count a pet/NPC kill or mere disappearance as a hero kill. Record
`You murderer!`, guilt/thunder, and Watch anger as supporting incidents:
none alone proves all peaceful kills, and some indicate conduct rather than
kills. Ambiguous attribution/identity, missed messages or lethal effects
with unobserved targets increment `peaceful_kills_unknown`; **both sums
must be zero**, with public audit coverage complete. Never silently encode
unknown as 0. Conservative attack/ranged gates reduce uncertainty; offline
native replay measures the detector's remaining false positives/negatives,
not supplies the policy with hidden counters. Acceptance is a publicly
supported clean-conduct claim, not omniscient proof of unobserved events.

### 5. Evaluation additions and report contract

Extend typed metrics, strict suite thresholds and versioned report/event
schemas together; absent legacy evidence remains unknown, not retroactive 0.
Keep existing report rendering unchanged.

- Add scalar `peaceful_kills`, `peaceful_kills_unknown`, `peaceful_attacks`,
  `oracle_attacks`, `centaur_attacks`, `conduct_incidents`, and
  `conduct_audit_unknown` (zero-sum acceptance gates). Keep death,
  starvation, last-live hunger and integrity metrics.
- Add `max_depth_by_branch` (relative DLEVEL and absolute Dlvl), level visits,
  and `turns_per_level` from public TIME deltas across **all** visits; separate
  prompt/action steps, SEARCH, travel, combat, food/prayer, and stall turns.
- Record target/goal/leg progress, branch-entry/link provenance, public town
  identity confidence, altar alignment/location, temple boundary and entry
  message or fallback reason, Oracle glyph/location/current attitude,
  completion turn/step, full attack/conduct evidence references and ambiguity.
- Report target-specific cap/rate derivation, policy/model/knowledge/NLE pins,
  draw/exclusion provenance, baseline/fresh gates, paired per-seed outcomes,
  deaths by cause/hunger, blocker class, branch errors, and detector confusion
  matrices by variant/level. Native diagnosis is a separately labeled offline
  annex inaccessible to policy input; complete records includes audit coverage.

## Rejected alternatives

- One combined Mines→Oracle tour: confounds targets and changes the user's two-suite decision.
- Native special-level/room/attitude flags as success or action input: leaks hidden state.
- Message-only temple detection, or any Mines altar: silent entry and Orcish Town defeat the former; filler/ambiguous evidence defeats the latter.
- NLE Oracle success, glyph-only peacefulness, or `You murderer!` as a universal kill counter: weaker than the target and incomplete public evidence.
- Continue kicking until warned, or exempt Orcish Town after guessing no Watch: unnecessary conduct risk and conflicting gate behavior.
- Reuse 3,000 by habit, tune thresholds on acceptance seeds, rerun losses, or forgive a Fainting death because the rate passes: repeats milestone-2 failure modes.

## Open questions for the user

- Approve the proposed **0.50 minimum**, per-target rate formula, 20 fresh
  acceptance seeds, and 30,000-step probe ceiling, or require a higher floor/sample?
- Does “zero peaceful kills” also forbid **autonomous pet/NPC kills**? Proposed
  gate counts hero-attributed kills and forbids deliberate pet-assisted harm;
  broaden attribution explicitly if all deaths must count.
- Approve reviewed digging/bar-breaching navigation for barricaded Orcish
  Town, or accept unavoidable target failures until an already-permitted
  public route appears? The success rule itself must not be weakened.

[src-mines]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/dat/mines.des#L55-L128
[src-special]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/sp_lev.c#L2073-L2127
[src-hack]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/hack.c#L2523-L2524
[src-priest]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/priest.c#L387-L495
[src-dungeon-def]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/dat/dungeon.def#L17-L76
[src-dungeon]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/dungeon.c#L350-L377
[src-pager]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/pager.c#L276-L297
[src-mon]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/mon.c#L2462-L2516
[src-kick]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/dokick.c#L1294-L1328
[src-fountain]: https://github.com/NetHack/NetHack/blob/NetHack-3.6.7_Released/src/fountain.c#L168-L217
[src-winrl]: https://github.com/NetHack-LE/nle/blob/v1.3.0/win/rl/winrl.cc#L491-L562
[src-tasks]: https://github.com/NetHack-LE/nle/blob/v1.3.0/nle/env/tasks.py#L146-L170
[src-base]: https://github.com/NetHack-LE/nle/blob/v1.3.0/nle/env/base.py#L177-L215
[wiki-town]: https://nethackwiki.com/wiki/Minetown
[wiki-oracle-level]: https://nethackwiki.com/wiki/Oracle_(level)
[wiki-oracle]: https://nethackwiki.com/wiki/Oracle_(monster)
