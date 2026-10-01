# 0023: Early-hunger failure diagnostics

Date: 2026-10-01

## Recorded evidence

This is a **read-only re-derivation**, not a new run or milestone evidence. The
three committed reports
[`traversal-v2`](../../nethack-agent/evaluation/reports/traversal-v2-20260928T091446Z.json),
[`scout-v1`](../../nethack-agent/evaluation/reports/scout-v1-20260928T091827Z.json), and
[`eat-v1`](../../nethack-agent/evaluation/reports/eat-v1-20260928T092011Z.json)
identify run IDs. Their persisted `run_started` and `step` events were read from
`nethack-agent/data/evaluations/{traversal-v2,scout-v1,eat-v1}/runs.sqlite3`
using read-only SQLite connections. The evaluator's shared `_episode_metrics`
re-derived the counts below from typed events; no NLE episode was rerun. The
`First Hungry` column is the first *live* public observation with hunger at
least Hungry, in **game turns**, not a step index. The `Last live` column notes
hunger before a zeroed terminal observation; the report's new
`hunger_at_death` metric is null on truncation, even if the last live state was
Fainting. `E`/`S`/`H` are explore/stair-navigation/hunger skill step counts.

| Suite | Case | Seed | Outcome | Steps | E / S / H | SEARCH | First Hungry | Last live |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| traversal-v2 | descend-main-d3 | 701 | death | 965 | 965 / 0 / 0 | 372 | 741 | Fainting |
| traversal-v2 | descend-main-d3 | 702 | truncated | 1,000 | 996 / 4 / 0 | 473 | 738 | Fainting |
| traversal-v2 | round-trip-d3-d1 | 701 | death | 965 | 965 / 0 / 0 | 372 | 741 | Fainting |
| traversal-v2 | round-trip-d3-d1 | 702 | truncated | 1,000 | 996 / 4 / 0 | 473 | 738 | Fainting |
| traversal-v2 | enter-mines | 701 | death | 965 | 965 / 0 / 0 | 372 | 741 | Fainting |
| traversal-v2 | enter-mines | 702 | truncated | 1,000 | 996 / 4 / 0 | 473 | 738 | Fainting |
| traversal-v2 | enter-mines | 703 | death | 946 | 942 / 4 / 0 | 209 | 729 | Fainting |
| traversal-v2 | enter-mines | 704 | death | 954 | 949 / 5 / 0 | 65 | 730 | Fainting |
| scout-v1 | explore-d1-d3 | 900 | death | 1,039 | 1,039 / 0 / 0 | 367 | 739 | Fainting |
| scout-v1 | explore-d1-d3 | 901 | death | 924 | 924 / 0 / 0 | 278 | 742 | Fainting |
| scout-v1 | explore-d1-d3 | 902 | death | 899 | 899 / 0 / 0 | 308 | 728 | Fainting |
| scout-v1 | explore-d1-d3 | 903 | death | 1,048 | 1,048 / 0 / 0 | 357 | 746 | Fainting |
| scout-v1 | explore-d1-d3 | 904 | death | 1,031 | 1,031 / 0 / 0 | 277 | 740 | Fainting |
| eat-v1 | explore-d1-d5 | 920 | death | 1,380 | 1,378 / 0 / 2 | 455 | 742 | Fainting |
| eat-v1 | explore-d1-d5 | 921 | death | 1,774 | 1,772 / 0 / 2 | 577 | 740 | Fainting |
| eat-v1 | explore-d1-d5 | 922 | death | 1,699 | 1,609 / 88 / 2 | 581 | 736 | Fainting |
| eat-v1 | explore-d1-d5 | 923 | death | 1,711 | 1,668 / 41 / 2 | 518 | 737 | Fainting |
| eat-v1 | explore-d1-d5 | 924 | death | 1,776 | 1,586 / 188 / 2 | 275 | 730 | Fainting |

**Aggregate:** All 18 recorded failed episodes reached Fainting; 15 ended in
death and three at their step cap. SEARCH consumed **6,802 of 21,076 steps
(32.27% weighted)**. The median interval from Hungry to Fainting was **158
game turns**; the median from Fainting to the episode endpoint was **531.5
turns** (the three truncations have *truncation*, not death, endpoints). Seed
701 and seed 702 have identical trajectories repeated across three
`traversal-v2` cases each: these 18 case-result rows represent **14 distinct
trajectories**, not 18 independent samples. All 18 first-Hungry observations
showed a safe food ration in visible inventory. The five `eat-v1` rows have one
executed EAT action each near turn 740, with two hunger-skill steps;
the other 13 rows have no hunger skill or EAT action. Their task action profile
could not choose inventory letters, so these counts alone cannot identify how
much hunger contributed to each non-starvation death. Two Scout deaths have
xlog starvation causes; most other deaths were attributed to monsters.

## Evaluation contract

Newly evaluated episodes record the **executed** step's selection skill,
including prompts, fallback, and terminal steps; `search_steps` counts the
executed `Command.SEARCH` action, not search intent. Four optional, all-or-none
metrics fields distinguish an old report without this evidence from a newly
observed empty skill map or zero SEARCH steps: `steps_by_skill`, `search_steps`,
`first_hungry_turn`, and `hunger_at_death`. The first Hungry turn includes an
initial observation already Hungry or worse. Death hunger uses the last live
preterminal observation, never NLE's zeroed terminal stats. It is null for
non-deaths or for death without a live sample. A `hunger_at_death` maximum
`at_most 2` threshold permits Satiated/Not Hungry/Hungry deaths and nondeaths
with recorded diagnostics (value 0), but disallows Weak or worse deaths;
a death lacking live evidence or legacy diagnostics has no value and fails a
required threshold. The separate `starvation_death` metric remains unchanged.
Report schema 4 adds per-case Markdown diagnostics only when every available
result records this group; historical Markdown still renders byte-for-byte.

A temporary scripted-development-model schema-3 evaluation with a baseline and
two four-step fresh seeds exercised NLE, persisted SQLite events, and the new
JSON and Markdown fields; its failures are expected and are **not** milestone
evidence. The production `descend-d5-v1` suite and real-model run remain future
work.
