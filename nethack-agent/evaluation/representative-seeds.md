# Representative seeds

Generated from `representative-seeds.json` by `nethack-agent eval catalog render`; do not edit by hand.

Expectations were established with the scripted development model under policy `hierarchical-task-specialists-v1`.

| Entry | Seed | Task | Cap | Expectation | Scripted outcome | Represents | Provenance | Test |
| --- | ---: | --- | ---: | --- | --- | --- | --- | --- |
| `staircase-anchor-6` | 6 | NetHackStaircase-v0 stand_on_stairs(down, any) | 1000 | must_pass | task_success | Milestone 1 reference seed on the staircase task. | staircase-v1 accepted report staircase-v1-20260926T211301Z. | - |
| `descend-d3-covered-stairs-5` | 5 | NetHackScore-v0 reach_level(0, 3) | 1000 | must_pass | objective_complete | The first downstairs is covered by food rations and is known only from the look-here message. | ADR 0004 baseline: the old policy starved on level 1 with the covered stairs unfound. | - |
| `descend-d3-stair-defense-1` | 1 | NetHackScore-v0 reach_level(0, 3) | 1000 | known_failure | death | Adjacent-hostile stair defense on level 1, then a level-2 search that outlasts the food supply; the hero dies while Fainting. | ADR 0004 baseline: a fox (seeds 1 and 4) and a newt (seed 2) killed the waiting hero; note 0016. | - |
| `descend-d3-stair-defense-2` | 2 | NetHackScore-v0 reach_level(0, 3) | 1000 | known_failure | death | Adjacent-hostile stair defense on level 1, then a level-2 search that outlasts the food supply; the hero dies while Fainting. | ADR 0004 baseline: a fox (seeds 1 and 4) and a newt (seed 2) killed the waiting hero; note 0016. | - |
| `descend-d3-stair-defense-4` | 4 | NetHackScore-v0 reach_level(0, 3) | 1000 | must_pass | objective_complete | Early hostiles reach the hero near the stairs; the stair defense must fight adjacent hostiles. | ADR 0004 baseline: a fox (seeds 1 and 4) and a newt (seed 2) killed the waiting hero; note 0016. | - |
| `descend-d3-hidden-downstairs-701` | 701 | NetHackScore-v0 reach_level(0, 3) | 1000 | known_failure | death | No downstairs is found on levels 1-2 before hunger reaches Fainting. | traversal-v2-20260928T091446Z: seed 701 died at 965 steps and seed 702 was truncated at 1,000, both Fainting. | - |
| `descend-d3-hidden-downstairs-702` | 702 | NetHackScore-v0 reach_level(0, 3) | 1000 | known_failure | truncated | No downstairs is found on levels 1-2 before hunger reaches Fainting. | traversal-v2-20260928T091446Z: seed 701 died at 965 steps and seed 702 was truncated at 1,000, both Fainting. | - |
| `enter-mines-4` | 4 | NetHackScore-v0 enter_dungeon(2) | 1000 | must_pass | objective_complete | The Gnomish Mines branch on levels 2-4 is found through stair identity probes and recovery. | ADR 0004 traversal probe: seeds 4 and 7 took a level-2 downstairs to Mines level (2, 1). | - |
| `enter-mines-7` | 7 | NetHackScore-v0 enter_dungeon(2) | 1000 | must_pass | objective_complete | The Gnomish Mines branch on levels 2-4 is found through stair identity probes and recovery. | ADR 0004 traversal probe: seeds 4 and 7 took a level-2 downstairs to Mines level (2, 1). | - |
| `scout-explore-d1-53` | 53 | NetHackScout-v0 explore_dungeon(1) | 2000 | must_pass | objective_complete | Exploration exhausts level 1 and the run ends with the WAIT confirmation. | note 0017 development smoke: objective_complete at step 322. | `tests/test_coordinator.py::test_exploring_the_last_required_level_ends_without_a_model_consultation` |
| `eat-stuck-after-exhaustion-824` | 824 | NetHackEat-v0 explore_dungeon(5) | 2000 | known_failure | truncated | Level 1 is exhausted with no known downstairs, and the rest of the episode is stuck consultations and re-armed searches. | note 0017 Eat probe seed 824. | - |
