# 0016: Evidence-gated survival skills

Date: 2026-09-28

## Evidence and failing-before proof

ADR 0004 and note 0015 fixed the pre-change baseline on `NetHackScore-v0` with the scripted development model and a 2,000-step cap. Seeds 1 and 4 were killed by foxes while the staircase skill waited on `>`; seed 2 was killed by a newt while Fainting on `>`; seeds 3 and 5 starved with an inventory food ration uneaten. The staircase wait/traverse branch ran before adjacent-hostile defense, and `TASK_ACTIONS` could issue `EAT` but could not answer its inventory-letter prompt.

A regression test was added before the combat change. Both cases failed: while the hero stood on a remembered `>` beside a jackal, `stand_on_stairs` returned `MiscDirection.WAIT` instead of east and `traverse_stairs` returned `MiscDirection.DOWN` instead of east. This reproduced the ordering defect without introducing a broader combat policy.

## Bounded design

Policy `hierarchical-survival-v1` retains knowledge bundle `staircase-reviewed-v3` and makes only these evidence-backed changes:

- **Adjacent staircase defense.** On the chosen staircase, deterministic staircase navigation checks the existing safe-to-melee adjacent-hostile predicate before either WAIT or traversal. Stepping onto an adjacent staircase still wins immediately. Pets, learned peaceful glyphs, passive-damage monsters, and the always-peaceful Oracle are never attacked; the Oracle is recognized by exact public NLE monster glyph/name before any `Really attack?` prompt.
- **Hunger action profile.** `nle-hunger-actions` preserves all 23 `TASK_ACTIONS` in order and appends ESC plus one NLE enum member for every otherwise-missing `a-z`/`A-Z` inventory command, with integer commands deduplicated. Added members are `prompt_key`; existing movement-letter collisions keep their routine role.
- **Known-ration threshold.** The deterministic hunger skill runs only with that profile, only at NLE hunger value 2 (Hungry) or worse, and only for a typed inventory item whose ASCII letter, food object class, exact normalized food-ration description, and projected BUC agree. Articles or counts, a leading BUC adjective, and a signed enchantment are parsed only around the exact noun `food ration(s)`. Corpses, partly eaten rations, unknown foods, malformed descriptions, and BUC disagreement are not inferred safe.
- **One bounded prompt.** After `EAT`, one pending ration may answer only the exact NLE `What do you want to eat? [...]` item prompt. The skill rechecks the item's typed evidence and uses its current letter only when that command is literally offered. Changed, missing, or unoffered evidence clears the pending sequence and cancels the recognized prompt with ESC. A floor-food `eat it?` yes/no prompt is declined by the existing conservative prompt handler.
- **Contextual permits.** `EAT` needs a typed `HungerPermit`; added prompt keys need a matching `PromptPermit`. Pure predicates validate the deterministic source/skill plus hunger or prompt evidence. The event contract reuses the structural predicate, so persisted model-selected EAT or prompt-key steps are rejected. Movement letters remain routine outside prompts but can answer when the same active item prompt literally offers them.
- **No model exposure.** Model fallback receives only routine gate-allowed actions: no level changes, EAT, or added prompt keys. Its inventory summary omits raw letters. Hunger remains deterministic and is omitted from the model's offered skill schema.

This does not add retreat, rest, weapon choice, floor-food consumption, general inventory management, prayer, or speculative navigation. Those remain evidence-gated roadmap items.

The committed `staircase-v2` and `traversal-v1` suites and report pairs remain immutable evidence for `hierarchical-traversal-v1`. The survival checkout refuses their policy pins before creating a run store, report, or episode; it does not rerun or relabel them.

## Observed real-NLE smoke

The fixed smoke used `NetHackScore-v0`, `nle-hunger-actions`, the scripted development model, the same seeds 1-5 and 2,000-step cap as the baseline, and a `reach_level(0, 12)` objective so ordinary deaths or the cap, rather than an early traversal objective, ended each run. No behavior was tuned after these results.

| Seed | Baseline end | Survival steps/end | Max depth | Ration EAT/item sequences | Score reward | First Hungry turn |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | 558, fox while waiting on `>` | 1,376, killed by a giant rat | 2 | 1 | 191.96 | 740 |
| 2 | 961, newt while Fainting on `>` | 1,224, killed by a gecko | 3 | 1 | 275.99 | 734 |
| 3 | 1,065, starvation | 1,730, killed by a kobold | 4 | 1 | 265.95 | 738 |
| 4 | 183, fox while waiting on `>` | 947, killed by a wand | 7 | 1 | 643.93 | 718 |
| 5 | 1,042, starvation while fainted | 2,000, truncated alive | 4 | 2 | 284.94 | 743 |

Every sequence selected current slot `d` from an offered prompt (`[d or ?*]`, or `[de or ?*]` on seed 5) as `deterministic_prompt`/`hunger`. Seed 5's second inventory also contained `an uncursed partly eaten food ration` in slot `e`; the exact parser rejected it and selected the intact ration in `d`. All five runs had zero model fallbacks. The smoke changed the observed aggregate from five deaths including two starvation deaths to four later non-starvation deaths and one live truncation; it is development evidence, not a predeclared acceptance suite.

The old `nle-task-actions` staircase regression was also run on real NLE seeds 1-10 with the scripted model and 1,000-step cap. All ten ended `task_success` at exactly the recorded traversal-policy step counts: 217, 44, 222, 47, 147, 151, 286, 222, 102, and 430.

## Verification

Behavior tests cover combat before both stair WAIT and traversal, the hunger
threshold, exact ration/BUC recognition, current-letter selection, mismatch
cancellation, unknown food and floor-corpse decline, prompt-key permits,
movement-letter collisions, model-action and inventory-letter exclusion,
structural event validation, the Oracle safeguard, and the unchanged legacy
action profile.

- `uv run pytest -q`: 372 passed (three dependency deprecation warnings).
- `uv run ruff check .` and `uv run ruff format --check .`: passed; 46 files
  already formatted.
- `node --check` on all five browser JavaScript modules: passed. No UI file
  changed, so no browser smoke was required.
- Pinned MkDocs 1.6.1 strict build: passed.
- `verify network --timeout 20 --json`: stopped cleanly with three events,
  proxy bypass verified, and all nine observed destinations at one loopback
  `127.0.0.1` endpoint.
