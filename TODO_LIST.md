# Roadmap

This file tracks product work. Completed work and reasoning belong in `docs/notes/`; durable choices belong in `docs/decisions/` and `ARCHITECTURE.md`. Consolidated history and dispositions: [0056].

## Done: milestone 1 — Staircase agent (accepted)

Accepted: fixed local policy met the committed staircase gate, including seed 6, with lawful actions and complete replay records ([ADR 0001](docs/decisions/0001-initial-product-and-runtime.md), [0007](docs/notes/0007-exploration-policy-and-staircase-acceptance.md)).

## Done: milestone 2 — Survive the early dungeon (evaluated; acceptance failed)

Implemented/evaluated; D5 fresh-sample gate passed, traversal and Eat regressions failed. Original one-run acceptance remains failed ([ADR 0005](docs/decisions/0005-early-survival-and-seed-evaluation.md), [0036](docs/notes/0036-milestone-2-real-model-evaluation.md)).

## Done: milestone 2 acceptance remediation

Unified survival remediation shipped; `descend-d5-v2` passed its objective-rate gate but failed its Fainting-death gate. Milestone 3 subsumes the D5 retry ([ADR 0006](docs/decisions/0006-unified-goal-suites.md), [0046](docs/notes/0046-descend-d5-v2-real-model-acceptance.md), [0056]).

## Now: milestone 3A — Find the way down

Goal ([ADR 0008](docs/decisions/0008-find-the-way-down.md), accepted 2026-10-25): on main Dlvl 1-9 and Mines levels 1-4 the hero reaches a goal-compatible staircase without long single-level stalls. A run is stalled when one contiguous level stay exceeds 1,000 game turns; baseline 48/40/11 of 67 (Minetown/Oracle/D5), where 72%/66%/32% of turns are past the 500th on one level. Acceptance: at most 10 stalled runs per Minetown and Oracle regression suite, D5 not above 11, at most 4 of 30 per fresh target, and ADR 0007 §4.1 outcome gates unchanged. Each rule qualifies separately.

- [x] Phase 1: stall causes classified ([0060](docs/notes/0060-stall-cause-diagnosis.md)). 58% of stall turns search a level for a target it lacks (Mines branch, Oracle, Mines temple), because range levels count as visited only after hidden-passage search is exhausted; secret-passage exits 25%; seen-but-not-taken 8%.
- [ ] Phase 2: long-cap Minetown/Oracle stall seeds in the representative-seed catalog. Done: stall and loop diagnostics (longest level stay, stalled runs, arrive-then-leave, fallback waits) in [`stalls.py`](_agents/skills/evidence-record/SKILL.md), beside the report-only `compare.py`.
- [ ] Phase 3: one rule per cause class, largest first. First: explore every range level's frontier before hidden-passage search for the branch, Oracle or Mines temple ([0060](docs/notes/0060-stall-cause-diagnosis.md)); then secret-passage search targeting. Carry the 0059 lessons: distance-aware search-stand ranking; known floor on a new route must not restart the no-progress clock ([0059](docs/notes/0059-rest-plus-stall-budget-development.md)).
- [ ] Phase 4: acceptance per ADR 0008 §3.

## Paused: milestone 3 — Mines to Minetown, and the Oracle

Paused 2026-10-25 until milestone 3A is accepted ([ADR 0008](docs/decisions/0008-find-the-way-down.md)); its items below stay open.

Goal: the same single agent, in two separate suites, (1) reaches **Minetown** (Gnomish Mines level 3 or 4, Dlvl 5-8) and **enters its temple**, and (2) reaches the **Oracle** level (Dlvl 5-9) and **stands next to the peaceful Oracle** without attacking her. Orcish Town counts as Minetown; in NetHack 3.6.7 (`dat/mines.des`, `minetn-1`) its altar lies in an ordinary region, not a temple room, so its success is standing on that unaligned altar (confirmed in [ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md), accepted). Scope: capability areas A (survive), B (food), F (navigation) below. ADR 0007 defines the accepted objectives, detectors, suites, and gates.

Process rules (milestone-2 lessons, notes 0037-0046, and [ADR 0007 process decisions](docs/decisions/0007-mines-minetown-and-oracle.md#process-decisions-2026-10-06)): one rule per worker session; each product change ships with its qualification note ([0040 protocol](docs/notes/0040-causal-hidden-detour-qualification.md), frozen fresh sample), gated on both targets plus `unified-d5-regression-v5`. Evaluations run with `timeout: 0` or detached. Native-memory ground truth is diagnosis-only, never policy input. Raw evaluation data stays outside git; each note commits a compact per-seed record. Only the orchestrating session commits ([AGENTS.md](AGENTS.md)).

Order of work (current 2026-10-19; supersedes 10-06/10-18; diagnosis/history in [0056]):

1. Disengage-and-rest rule (Phase 3): REJECTED ([0057](docs/notes/0057-elbereth-disengage-qualification.md)); fewer deaths, but objectives fell and fresh Weak-or-worse deaths rose. Next step decided 2026-10-21: combined rest + stall-budget candidate 0059 was developed as one unit under the recorded [ADR 0007 exception](docs/decisions/0007-mines-minetown-and-oracle.md#process-decision-2026-10-21-combined-candidate-0059) and NOT QUALIFIED after three development passes ([0059](docs/notes/0059-rest-plus-stall-budget-development.md)): pass 3 passed Minetown (19 objectives, 37 deaths) and Oracle (14, 50) but failed D5 (53 objectives, 6 deaths, 3 Weak-or-worse); no fresh seeds spent. Next step: milestone 3A ([ADR 0008](docs/decisions/0008-find-the-way-down.md)).
2. Stall budget (Phase 2): candidate 0054 was rejected with 0059 as a unit. A successor needs a distance-aware search-stand ranking, or a no-progress clock that known floor seen on a new route does not restart ([0059](docs/notes/0059-rest-plus-stall-budget-development.md)).
3. Optional ADR 0007 gate amendment: objectives not lower, starvation/Weak-or-worse deaths not higher; this would not rescue measured 0054 or 0057.

Phase 0 tooling may proceed alongside this order.

### Phase 0 — tooling

Done: commit guard, native-truth reader, detached/parallel evaluation, [detached-eval stop](_agents/skills/detached-eval/SKILL.md), [RunStore connection reuse](docs/development.md), evidence records, [paired report comparison](_agents/skills/evidence-record/SKILL.md), step-history map and live speed limit ([0047](docs/notes/0047-native-truth-reader.md), [0050](docs/notes/0050-phase1-objectives-baselines-detector-audit.md), [0056]).

- [ ] Add step-level replay comparison (first divergent step and rule firing between paired arms from stored events). Paired report comparison with ADR 0007 gates and aggregate diagnostics is done ([evidence-record compare](_agents/skills/evidence-record/SKILL.md)) ([ADR 0004](docs/decisions/0004-traversal-goals-and-task-progression.md#8-staged-plan-after-a), [0056]).
- [ ] Record actual tool/script executions for Tools, replacing its deterministic-step-only view; preserve provenance ([UI limits](docs/development.md), [0056]).
- [ ] Automate browser layout, overlay, focus and tooltip tests; cover behaviors currently checked only by recorded smokes ([0009](docs/notes/0009-ui-agent-information-redesign.md), [0018](docs/notes/0018-agent-column-viewport-fit.md)).
- [ ] Box destinations on the hero's own cell; show replanning divergence and record computed-but-unfollowed routes (blocker waits/stair defense) ([0011](docs/notes/0011-map-intent-annotations.md), [0012](docs/notes/0012-planned-path-overlay.md)).

### Phase 1 — objectives and measurement

Done: Minetown/Oracle objective planning, peaceful adjacency/attack conduct, development suites, detector audit and classified baselines ([0050](docs/notes/0050-phase1-objectives-baselines-detector-audit.md)); Oracle recognition currently requires seeing her.

- [ ] Replace Minetown's wall/door/bar counter with seen-altar or priest-greeting evidence on branch-confirmed Mines level 3/4; qualify separately after the shipped hunger fix ([0056] source rationale).
- [ ] Add Oracle-level cues (centaur statues, fountains, sounds) and avoid the Sokoban up-branch below her level; preserve peaceful adjacency/no attack ([0050](docs/notes/0050-phase1-objectives-baselines-detector-audit.md), [0056]).

### Phase 2 — F: navigation

- [x] Downward branch-stair identity: closed without a rule; the Mines `>` detour costs 2 turns and no objectives in the shipped baseline, and recovery via the recorded branch link already works ([0058](docs/notes/0058-branch-stair-identity-diagnosis.md)).
- [ ] Diagnose exit discovery with true-map evidence on every stalled level, including milestone-2 failures; turn recurring blockers into qualified rules ([0056] seed/evidence list).
- [ ] Requalify stall breaker 0054 after disengagement: fix `stuck_consult_step` crash/re-consult replay rejection, probe budget, then qualify strategy changes for unknown/blocked exits ([0056] candidate/mechanisms/failed probes).
- [ ] Qualify Mines cave navigation (no secret doors, narrow diagonals, boulders) and branch identity down/back up ([ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).
- [ ] Enforce Minetown conduct: no watch/priest anger, door kicking, fountain quaff/dip or shop theft; audit the gates ([ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).
- [ ] Acquire/use pick-axe, mattock or digging wand only under ADR 0007 conduct gates; qualify navigation benefit ([ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).
- [ ] Obtain an ammunition source before requalifying rebuilt ranged gas-spore/floating-eye rule 3; candidate 0053 is paused/unqualified ([0045](docs/notes/0045-three-single-rule-qualification.md), [0056] patch provenance/probes).

### Phase 3 — A: survival in a crowded, deeper dungeon

- [ ] Build a reviewed-card threat model covering difficulty/special attacks, including floating eyes, cockatrices, nymphs, leprechauns, ants, werecreatures, gas spores, shop mimics and mattock dwarves ([ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).
- [ ] Cure publicly evident lycanthropy by safe-timeout prayer (3.6.7 major-trouble/cure semantics confirmed); qualify beyond the current corpse-eating exclusion ([0056]).
- [ ] Preserve dwarven-hero peaceful handling: never attack peaceful gnomes/dwarves/watch and keep declining `Really attack?`; qualify conduct on Mines runs ([ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).
- [ ] Disengage/rest: the first combat-only Elbereth rule was rejected ([0057](docs/notes/0057-elbereth-disengage-qualification.md)); candidate on branch `rule-0057-elbereth-disengage`. Combined with the 0054 stall budget (candidate 0059) it passed Minetown and Oracle regression but failed D5 and was not qualified ([0059](docs/notes/0059-rest-plus-stall-budget-development.md)). Resting needs stall reduction and a food budget to turn survival into objectives; quiet rest and retreat movement remain untried.
- [ ] Handle stun/confusion/blindness safely and remember/route around known traps; qualify recurring failure classes ([0051](docs/notes/0051-ration-livelock-qualification.md), [ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).
- [ ] Comply with vault guards after involuntary relocation; reproduce and fix the recorded failure ([0056] seed 1377).

### Phase 4 — B: food and prayer over a longer horizon

Done: ration `EAT`/`ESC` live-lock fixed and qualified ([0051](docs/notes/0051-ration-livelock-qualification.md)).

- [ ] Reconcile code's prayer interval with ADR 0005 from wiki/source evidence; change only if supported ([0024](docs/notes/0024-reviewed-survival-knowledge.md), [ADR 0005](docs/decisions/0005-early-survival-and-seed-evaluation.md)).
- [ ] Carry unburdened, non-shop floor-food reserves and eat before long stalls; measure turns/level versus food horizon, without reviving rejected slime-mold rule ([0052](docs/notes/0052-canonical-slime-mold-qualification.md), [0056]).

### Phase 5 — acceptance

- [ ] Freeze policy, run ADR 0007 §4.2 held-out cap probes (30 reserved seeds/target, 30,000-step ceiling), and fix each cap/declared success rate ([ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).
- [ ] Run fresh-draw `minetown-v1` and `oracle-v1` once with that policy/cap: meet declared rates, no starvation/Weak-or-worse deaths, peaceful kills, invalid actions or gate rejections ([ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md)).

## Capability roadmap to ascension

Tracks what the agent must eventually do. Milestones pull items from here; check an item only when a qualified, shipped skill covers it. Order: A, B, F (survive/explore), then C, D, E (power), then G (endgame); H underpins all. Contracts/evidence: [architecture](ARCHITECTURE.md), [ADR 0004](docs/decisions/0004-traversal-goals-and-task-progression.md), [ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md).

### A. Survive moment to moment

- [ ] Tactical combat: target choice, corridors/doorways, Elbereth, retreat, stair escape (now: melee, low-HP prayer).
- [ ] Dangerous-monster rules: floating eye, cockatrice, nymph, leprechaun, soldier ant, werecreature, mind flayer, engulfers.
- [ ] Rest/heal safely; use healing items.
- [ ] Escape items/actions: teleport scrolls, digging down, Elbereth (now: prayer only).
- [ ] Recognize/avoid traps, including sinks, fountains, altars.
- [ ] Cure blindness, confusion, stun, hallucination, sickness, sliming, stoning.

### B. Food and luck

- [ ] Whole-game nutrition: rations, corpses, tins, prayer (now: partial, `survival-reviewed-v2`).
- [ ] Avoid deadly/harmful corpses: cockatrice, poisonous, acidic, cannibalism, rotten (now: reviewed safe list).
- [ ] Manage prayer timeout/luck: no peaceful kills or luck penalties.

### C. Build a strong character

- [ ] Pick up/evaluate weapons, armor, tools; respect weight limit (now: burden recovery only).
- [ ] Use `#enhance`; obtain Excalibur by fountain dipping at XL 5+.
- [ ] Improve AC: wear/enchant/swap armor; handle cursed items.
- [ ] Gain levels safely: experience, gain-level potions, wraith corpses.
- [ ] Gain corpse intrinsics: fire/cold/poison/shock/sleep/disintegration resistance, telepathy; speed, see invisible, teleport control.
- [ ] Obtain reflection and magic resistance before late game.
- [ ] Use pet for curse testing and keep it alive.

### D. Items and identification

- [ ] Use scrolls, potions, rings, amulets, wands.
- [ ] Identify via prices, wand engrave-testing, identify scrolls, altar BUC testing.
- [ ] Manage bless/curse: holy water, altars, remove curse.
- [ ] Use containers/stashes; avoid bag-of-holding cancellation accidents.

### E. Economy and NPCs

- [ ] Shops: buy/sell/price-identify/pay without angering shopkeepers (now: avoid only).
- [ ] Temples/priests: buy protection, convert altars.
- [ ] Handle vault guards, Watch, Oracle and quest leader.

### F. Navigation and dungeon knowledge

- [ ] Robust exit discovery: search, kick, dig, unlock (now: partial; main open weakness).
- [ ] Branches: Mines/Minetown, Sokoban rules, Oracle, Big Room, Fort Ludios.
- [ ] Special levels: Medusa, Castle (wishing wand/drawbridge), Valley of the Dead, Gehennom mazes, Vlad's/Wizard's Towers.
- [ ] Movement tools: pick-axe/mattock/digging wand, levitation, water walking, controlled teleport.

### G. Endgame (mandatory for ascension)

- [ ] Use wishes well.
- [ ] Complete Quest: XL 14, nemesis, artifact, Bell of Opening.
- [ ] Obtain Candelabrum (Vlad), Book (Wizard), Bell; invoke at vibrating square.
- [ ] Take Amulet of Yendor from Sanctum, reject fakes and ascend while harassed.
- [ ] Traverse Elemental/Astral Planes; offer at correct high altar.

### H. Agent-level capabilities

- [ ] Long-horizon planning/cross-level memory: stashes, altars, identified items.
- [ ] Assess threat to choose fight, flee or pray.
- [ ] Cover menus, prompts, extended commands, multi-turn actions; handlers ship with causing actions ([ADR 0004](docs/decisions/0004-traversal-goals-and-task-progression.md#8-staged-plan-after-a)).
- [ ] Retrieve local-model knowledge beyond hand-curated cards.
- [ ] Stage full-game benchmarks/survival metrics: full `NetHackScore-v0`, then ascension suite.

## Explicitly deferred

- Separate `gold-v1` NLE reward benchmark: gold navigation shipped, but unified place-reaching suites are current scope; legacy NLE Oracle work is superseded by milestone 3 ([0056 dispositions](docs/notes/0056-roadmap-consolidation.md#robust-dungeon-play-adr-0004)).
- Laya routine-ranking runtime and FlyEM connectome research: not milestone-3 prerequisites; require bounded baseline comparisons before any production commitment ([0013](docs/notes/0013-review-feedback-resolutions.md), [0056](docs/notes/0056-roadmap-consolidation.md#robust-dungeon-play-adr-0004)).
- Model-owned high-level choices: after milestone 3 and sufficient multi-goal decision points; paired arbiter/model study must win without extra deaths ([ADR 0004 protocol](docs/decisions/0004-traversal-goals-and-task-progression.md#8-staged-plan-after-a), [ADR 0007](docs/decisions/0007-mines-minetown-and-oracle.md#process-decisions-2026-10-06)).
- Forking/vendoring NLE without a concrete engine-level requirement.
- Cloud inference during gameplay.
- Automatic self-modification or online learning during evaluation.
- Displaying/persisting private chain-of-thought as a product feature.

[0056]: docs/notes/0056-roadmap-consolidation.md
