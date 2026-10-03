# ADR 0005: Early survival and representative-plus-fresh seed evaluation

- Status: accepted (design implemented and evaluated; milestone acceptance failed)
- Date: 2026-09-30
- Refines: [ADR 0004](0004-traversal-goals-and-task-progression.md) sections 6-8
  (action profiles, evaluation suites, staged skills)
- Evaluation: [note 0036](../notes/0036-milestone-2-real-model-evaluation.md)
  records the first real-model runs. `descend-d5-v1` passed (18/20 fresh,
  all must-pass baselines, no fresh hunger deaths), but milestone 2's full
  acceptance failed: traversal's Mines case passed 1/5 against 2/5, and Eat
  recorded two starvation deaths against at most one. Failed reports remain
  immutable; a retry requires a new policy, suites, and fresh draw.

## Context

Milestone 1 and ADR 0004 milestones A and B (first wave) are complete. Their
committed real-model runs share one failure class.

| Suite (report) | Failed episodes | Worst hunger when failing | Ends |
| --- | ---: | --- | --- |
| `traversal-v2` (`traversal-v2-20260928T091446Z`) | 8 of 15 (seeds 701-704) | Fainting in all 8 | 5 deaths (newt, fox, grid bug), 3 truncated (seed 702) |
| `scout-v1` (`scout-v1-20260928T091827Z`) | 5 of 5 | Fainting in all 5 | 2 starvations (900, 903); fox, sewer rat, kobold zombie |
| `eat-v1` (`eat-v1-20260928T092011Z`) | 5 of 5 | Fainting in all 5 | sewer rat, goblin, grid bug, sewer rat, garter snake |

Every successful episode stayed not hungry. Scout and Eat have no NLE success
state, so a failed episode there is one that did not complete its objective;
all ten died.

- **Cause.** Exploration marks a level exhausted only after a bounded
  hidden-passage search of every wall and dead end facing unexplored rock. That
  search outlasts the hunger horizon: about 1,000 steps without eating on
  `nle-task-actions` (Scout) and about 1,700 with one ration (Eat)
  ([note 0017](../notes/0017-scout-and-eat-task-suites.md)). Seeds 701 and 702
  never found `>` on levels 1-2.
- **No recovery.** `TASK_ACTIONS` has no PRAY (ADR 0004). The only eating path
  is `ActionProfile.NLE_HUNGER_ACTIONS` in `tasks.py`, which adds ESC and
  inventory letters so the hunger skill can eat an exactly recognized ration
  under a `HungerPermit`/`PromptPermit` (`decision.py`). The corpse
  "eat it?" prompt is always declined.
- **Evaluation.** Every committed suite fixes its exact seeds. Developing
  against the same seeds repeatedly risks overfitting, and no run measures
  unseen games.

### NetHack facts

Source: the local NetHackWiki dump (vanilla NetHack 3.6), by page title.

| Fact | Page |
| --- | --- |
| A hero starts with 900 nutrition and normally loses 1 per turn; attacking costs one extra turn's worth. | Nutrition |
| Not hungry 150-999, Hungry 50-149, Weak 0-49, Fainting below 0; starvation at -100 - 10 x Con. | Nutrition |
| Hungry is a minor trouble; Weak or worse is a major trouble. A successful prayer raises nutrition to 900 if it is lower. | Nutrition |
| A food ration gives 800 nutrition in about 5 actions. Valkyries start with 1-2 uncursed rations. | Food ration, Valkyrie |
| The prayer timeout starts at 300 and falls by 1 per turn. With a major trouble, prayer is accepted while the timeout is below 201; with a minor trouble, below 101; otherwise only at 0. | Prayer timeout |
| Praying resets the timeout to a random value, usually 50-1,000. For a pleased god, 95% of resets are at most 1,229. | Prayer timeout |
| Prayer is also unsafe with negative Luck, a negative alignment record, an angry god, in Gehennom, or on another god's altar. Praying takes 3 helpless turns. Praying with too high a timeout angers the god, costs 3 Luck, and smites. | Prayer |
| Corpse rottenness is age / rnd(10..29), +2 if cursed, -2 if blessed. At 6 or more the corpse is tainted (fatal food poisoning); at 4 or more it is old (20% chance of 1d8 damage). Lizard and lichen corpses never rot; acid blobs are never tainted. Other corpses keep a 1/7 chance of "rotten" effects. | Corpse |
| Harmful corpses include poisonous ones (all kobolds, rabid rats; 1-4 Str and 1-15 HP without poison resistance), acidic ones (1-15 HP without acid resistance), cockatrice and chickatrice (petrification), bats (stun), cats and dogs (aggravate monster), the hero's own race (cannibalism; dwarves for a dwarf), all human `@` including werecreatures, and undead (food poisoning). | Corpse |

Not yet verified: the exact prayer confirmation prompt and whether NLE's
options enable it; the exact corpse "eat it?" prompt text under NLE; and each
monster on the corpse allow-list below.

## Decision

### 1. Milestone 2 goal and acceptance

Reach Dungeons of Doom level 5, the shallowest Oracle level, without hunger
deaths.

- **Suite `descend-d5-v1`** (suite schema 3): `NetHackScore-v0`, the
  `nle-survival-actions` profile (section 4), objective `reach_level(0, 5)`,
  and a step cap fixed from held-out probes, at least 3,000.
- **Fresh sample** (section 3): 20 drawn seeds. Pass requires at least 50%
  `objective_complete` (held-out probes may raise, never lower, this bound),
  zero starvation deaths, and zero deaths while Weak or Fainting.
- **Baseline** (section 2): every catalog entry for the suite's task runs in
  the same report. No `must_pass` entry may regress.
- **Suite-wide:** zero invalid actions and gate rejections, complete records,
  and every prayer and corpse meal replayed by the evaluator against the gate's
  predicate.
- **Regressions under the new policy:** the staircase cases pass 10/10; the
  traversal cases meet their original thresholds, including `enter-mines` at
  least 2/5; Scout and Eat thresholds are no worse than `scout-v1` and `eat-v1`.
- **Unchanged:** `gemma4-nethack:latest`, `num_ctx` 8,192, offline gameplay,
  and immutable committed suites and reports.

The milestone is judged on the first committed real-model run of the suite. A
failed run is kept; a retry needs a new policy version and a new draw.

### 2. Representative-seed catalog

`nethack-agent/evaluation/representative-seeds.json` is the strict typed source
of truth (ADR 0003); `representative-seeds.md` is rendered from it for people
and is never edited by hand.

Each entry records the seed, its `TaskSpec`, the step cap, the behavior it
represents (one sentence), its provenance (report, run id, step, or note), its
expectation under the current policy (`must_pass` or `known_failure`), and the
permanent test that uses it, if any. Initial entries:

| Seeds | Represents | Provenance |
| --- | --- | --- |
| 6 | milestone 1 anchor | `staircase-v1` accepted report |
| 5 | downstairs covered by food rations | ADR 0004 baseline, covered-stairs memory |
| 1, 2, 4 | deaths while waiting on stairs; adjacent-hostile defense | ADR 0004 baseline, note 0016 |
| 4, 7 | Mines branch probe and recovery | ADR 0004 traversal probe |
| 53 | Scout `explore_dungeon(1)` completion | note 0017 development smoke |
| 701, 702 | `>` never found; Fainting | `traversal-v2` report |
| 824 | stuck after exhaustion with no known `>` | note 0017 Eat probe |

- Expectations are established by running each entry under the current policy
  when the catalog is created, not assumed.
- A scripted-model catalog check asserts each entry's outcome class and key
  invariants (for example no Fainting death, covered stairs recognized, no gate
  rejection), never step counts.
- An intentional expectation change is committed with the policy change that
  causes it and recorded in a note.
- A fresh-sample episode that exposes a new failure class is promoted into the
  catalog.

### 3. Used-seed ledger and fresh sampling (suite schema 3)

- A schema 3 suite fixes the draw procedure, not the seeds: the count (20 for
  `descend-d5-v1`), a seed range (10^6 to 2^31 - 1), and the exclusion ledger.
- The ledger lists every seed used by a committed suite, a recorded probe, a
  recorded development run, or the catalog. Drawn seeds join it after each run.
- The report records the draw seed and the drawn seeds before its first
  episode, so any run reproduces with `--seeds`.
- Acceptance is reported separately for the baseline and the fresh sample. The
  baseline also gets a paired per-seed diff against the previous report of the
  same suite.
- Improvement claims on fresh samples use rates with intervals, because the
  seeds differ between runs: the 95% Wilson interval is 23.7-76.3% for 5/10 and
  29.9-70.1% for 10/20. Paired per-seed claims come only from the baseline.
- No redraw-until-pass (section 1).
- Schemas 1 and 2 stay readable, and every existing report re-renders byte for
  byte.

### 4. Survival action profile and gate

- New profile `nle-survival-actions`: `nle-hunger-actions` plus `Command.PRAY`.
  PRAY gets its own static gate role; EAT keeps its hunger role.
- `y` shares its code with `CompassDirection.NW` in `TASK_ACTIONS`. It and the
  inventory letters are accepted as answers only while the current prompt offers
  them: the prayer confirmation, the corpse "eat it?" prompt, and the food item
  prompt. Otherwise `y` keeps its movement role.
- The coordinator issues a prayer permit only to the prayer skill (section 5);
  model fallbacks can never pray or eat. The evaluator reruns the same
  predicate over the stored observation and action table.

### 5. Deterministic prayer skill

- **Trigger:** hunger status Weak or Fainting.
- **Timeout estimate:** the first prayer is allowed from game turn 101 (timeout
  300 minus elapsed turns is then below 201). After a prayer at turn T, the next
  is allowed from turn T + 1,029 (a reset of at most 1,229, minus the 200 allowed
  with a major trouble; at least 95% safe).
- **Other conditions:** the policy already avoids attacking peacefuls; it never
  prays on an altar. After a prayer that does not restore nutrition, the skill
  does not pray again in the episode.
- **Evidence:** the intent records the trigger, the game turn, and the timeout
  bound; the outcome is read from the following messages and hunger status.
- The model does not choose prayer. It is a later milestone D decision class.

### 6. Corpse eating and floor foraging

- **Allow-list:** the reviewed `survival-reviewed-v2` bundle (superseding
  `survival-reviewed-v1`'s card, byte-identical and still available) widens
  identified-fresh-kill corpses to lichen, newt, sewer rat, giant rat, gecko,
  garter snake, hobbit, goblin, iguana, and shrieker for a normal dwarven
  Valkyrie. Grid bugs leave no corpse. Jackal, fox, and coyote are now
  included, but only while no public lycanthropy evidence (the "You feel
  feverish" or a were-creature bite message) has been observed and the hero
  is not polymorphed, since eating them while sharing a werejackal's species
  is cannibalism. The remaining harmful classes stay excluded
  ([note 0024](../notes/0024-reviewed-survival-knowledge.md),
  [note 0033](../notes/0033-reviewed-nutrition-probes.md)).
- **Freshness:** only a corpse on the cell of a monster the hero was observed
  killing, at most 19 game turns earlier. Rotten-age calculations divide age
  by a random integer from 10 to 29 and add 2 if cursed; at age 19 or less,
  this remains below 4 even with unknown BUC, avoiding the \"old\" and tainted
  age thresholds. The earlier proposed 30-turn limit did not account for
  cursed corpses reaching the \"old\" threshold. A separate 1/7 rotten-food
  chance remains for most ordinary corpses and is accepted and recorded
  ([note 0024](../notes/0024-reviewed-survival-knowledge.md)). Lichen alone is
  exempt from this age cap, since it never rots; a pet can drag a lichen
  corpse off its own kill cell, so lichen alone may also be identified at a
  new cell by its exact look-here or floor-eat text, without kill-turn
  provenance ([note 0033](../notes/0033-reviewed-nutrition-probes.md)).
- **Ration and fruit variants:** a held, partly-eaten identified food ration,
  cram ration, K-ration, C-ration, lembas wafer, or reviewed fruit/vegetable
  is still recognized and resumed, instead of being treated as unknown
  ([note 0033](../notes/0033-reviewed-nutrition-probes.md)).
- **Floor foraging:** an identified reviewed comestible on a non-shop floor
  cell is collected within a cheap, reachable route while unburdened;
  otherwise it is eaten from the floor only at Hungry or worse, confirming
  the exact offered item text. An undead hero skips garlic, which only makes
  it vomit ([note 0033](../notes/0033-reviewed-nutrition-probes.md)).
- **Trigger:** whenever the hero is not Satiated. Choking needs a meal started
  while Satiated, so this is safe, and it saves rations. Rations are eaten only
  when Hungry or worse with no eligible corpse or floor food; prayer covers
  Weak.
- Everything else, including the "eat it?" prompt for other corpses, stays
  declined.

### 7. Exit discovery, not a search-volume cap

The cap proposal did not qualify in [0028](../notes/0028-bounded-search-probes.md)
or [0030](../notes/0030-post-fix-bounded-search-probes.md). Native-memory replay
in [0031](../notes/0031-exit-discovery-probes.md) found eleven known locked
gates, two excluded open-door search stands, and one unvisited object-covered
downstairs among the fourteen legacy failures. SEARCH volume was the symptom,
not the dominant missing capability.

- Force known locked route gates while downstairs are unknown, in dungeon 0
  only, with at least 10 HP, hunger better than Weak, no closed-inventory or
  known shop/shopkeeper evidence, and at most eight kicks per door. Runtime
  execution and evaluation use the same predicate and observed outcomes.
- Search from visited open doors facing a blank outward corridor extension;
  the adjacent blank can have been observed without its passage being known.
- Visit unvisited walkable object-covered cells and reuse underfoot stair
  discovery instead of assuming the visible object proves ordinary floor.
- Keep the existing per-cell search rounds and commitment. No global per-level
  SEARCH cap or corridor reprioritization is installed: 1237 was solved by
  changes above. The ADR remains proposed; policy versioning and real-model
  milestone evaluation are still the next item.

### 8. Diagnostics

Every episode records steps by skill and by search action, the first Hungry
turn, the hunger state at death (`hunger_at_death`), and each prayer and corpse
meal with its outcome.

## Implementation sequence

1. Representative-seed catalog, used-seed ledger, and the scripted catalog
   check.
2. Suite schema 3 and the report changes.
3. Diagnostics and a failure-analysis note on the 18 Fainting episodes.
4. Knowledge cards for prayer and hunger and for corpses, in a new bundle.
5. The `nle-survival-actions` profile and its gate roles.
6. The prayer skill.
7. Corpse eating.
8. Exit discovery with guarded locked gates, open-door search, and covered cells.
9. A new policy version, held-out probes, committed suites, and one real-model
   run.
10. `ARCHITECTURE.md`, `README.md`, the development guide, a note, and this ADR
    marked accepted.

## Consequences

- Hunger becomes survivable through audited, deterministic paths: prayer and
  corpse meals pass the same gate predicate that the evaluator replays.
- Acceptance now measures unseen games while keeping a paired regression signal
  on reviewed seeds. The cost is a ledger to maintain and a suite schema whose
  seeds differ on every run.
- Unobservable risks remain: Luck and alignment are not in the observation, so
  prayer safety is estimated; pets may eat corpses first.
- Rejected alternatives:
  - fixed held-out seeds only, which overfit through repeated development;
  - a fresh random draw only, which gives no paired regression signal;
  - redrawing until a run passes;
  - letting the model decide when to pray before a milestone D study;
  - a generic "eat any corpse" rule.
