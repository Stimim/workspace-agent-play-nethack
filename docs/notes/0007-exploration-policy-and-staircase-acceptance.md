# 0007: Deterministic exploration policy and first passing staircase suite

Date: 2026-09-27

## Why the first suite run was aborted

The `hierarchical-staircase-v1` run started in note 0006 routed only toward a
visible `>`. Everything else was a model fallback. On seed 1 all 1,000 actions
were fallbacks (wait 615, run south 190, search 69, eat 45, north 37,
`MiscDirection.UP` 35). The model averaged about 6.4 s per action and the hero
never left level 1. The operator stopped the process with SIGINT during seed 2.
`nethack-agent eval abort` then finalized the report as `aborted` with reason
"policy replaced before completion". Every recorded result is unchanged.

| Seed | Outcome | Ended by | Steps | Wall s | Model decisions | p50 / p95 / max ms | Skill/prompt/model | Integrity |
| ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | truncated | episode_end | 1000 | 6860.2 | 1001 | 6402 / 9494 / 19139 | 0/0/1000 | ok |
| 2 | stopped | interrupted | 156 | 1053.1 | 157 | 6673 / 7680 / 8768 | 0/0/156 | ok |

Report: `nethack-agent/evaluation/reports/staircase-v1-20260926T181151Z.{json,md}`
(0644, schema 2). Across both seeds: 1,158 model decisions, p50/p95/max
6443/9367/19139 ms.

## Changes (policy `hierarchical-explore-v1`)

- **Gate.** `MiscDirection.UP` is banned along with `DOWN`
  (`decision.FORBIDDEN_ACTION_NAMES`). `<` on dungeon level 1 leaves the dungeon.
  The evaluator's invalid-action audit uses the same set.
- **Level memory** (`navigation.py`). The coordinator owns a per-level record,
  reset on start and on level change. It holds the last terrain seen under the
  hero, monsters, and objects, plus observed cells, search coverage, learned
  blocked or suspect moves, locked doors, kicks, peaceful monster glyphs,
  abandoned goals, and position history.
- **Door rules.** These were checked against NetHackWiki "Door" and the 3.4.3
  and 3.6.0 `hack.c` source pages (`test_move`, `doorless_door`,
  `cant_squeeze_thru`). There is no diagonal move into or out of a doorway that
  has a door, whether open or closed. Doorless and broken doorways (`S_ndoor`)
  allow diagonal moves. Moving into a closed door opens it (`autoopen`), and a
  locked one reports `This door is locked.`. The Valkyrie may squeeze diagonally
  between rock cells. The old rule required both orthogonal cells to be walkable,
  which wrongly blocked diagonal corridor bends.
- **`explore_level` skill.** In priority order it:
  - attacks an adjacent hostile. There is no fight command in the action set,
    so it moves into the monster. Pets, peaceful monsters learned from a
    "Really attack?" prompt, and passive-damage monsters are excluded.
  - walks to the nearest reachable frontier;
  - approaches, fights, or waits out a monster blocking a frontier;
  - kicks a known-locked door that leads to unexplored space. It does this only
    on dungeon level 1, where shops and the watch cannot exist.
  - searches the best reachable wall or dead-end spot. It does 10 searches per
    adjacent cell per round and stays committed to the spot.
  - When none of these applies, it reports `search_exhausted` or
    `monster_blocked`.
- **Arbiter and consultations.** A routable remembered `>` selects
  `staircase_navigation`. Otherwise `explore_level` runs. The model is consulted
  at the start, when exploration reports stuck (at most every 20 steps), and for
  unhandled prompts. If it chooses `explore_level` while stuck, exploration is
  re-armed. Steps record `skill_selection` (`arbiter` or `model`) and
  `stuck_reason`. Clean cutover: step events recorded under the old contract no
  longer parse.
- **Fallback bounds.** Fallbacks now allow at most 3 candidates, 100-character
  reasons, and 200-character rationales. On seed 1, warm fallbacks took
  3.1–3.7 s with about 171 output tokens, down from about 6.4 s with about 220.
  Skill consultations take 0.9–1.4 s with about 48 output tokens. The first stuck
  prompt got the answer `staircase_navigation` from the model. The prompt now
  states that navigation cannot act while stuck, and the model then chose
  `explore_level`.

## Development iterations

All runs below used the explicit scripted model, which always re-arms
exploration and waits as its fallback. Failures were diagnosed from event
traces and map dumps, and each fix is general:

| Change | Evidence | Suite seeds 1–10 |
| --- | --- | --- |
| First exploration version | seed 10 died searching beside a biting fox; seed 5 stalled by a lichen and dithered between search spots | 8/10 |
| Fight back, commit to search spots, count up to 6 revisited cells as oscillation, treat stuck-to-lichen failures as transient | seed 3 searched a dead end that only looked dead: a corpse in a corridor, terrain never drawn | 9/10 |
| Treat cells with objects or footsteps as passable | — | 10/10 |
| Navigation fights back when `>` is more than one step away; diagonal-aware dead ends; a closed door under the hero is open; a kicked door that "crashes open" is doorless even when a pet hides it | held-out seeds 12, 16, 44, 58 | 10/10 |

Held-out seeds 11–60 (not in the suite, used only to avoid overfitting):
47/50 succeed. Seeds 12, 24, and 29 truncate after long unlucky searches, with
fainting from hunger near turn 1,000. The Staircase action set has no letter to
eat the food ration.

Official development-mode suite
(`data/evaluations/staircase-v1-explore-dev/reports/staircase-v1-development-20260926T211040Z.md`):
10/10, integrity ok, never milestone evidence.

## Real-model suite

Command, from `nethack-agent/`, after `uv run nethack-agent doctor` (Ollama
0.34.4, `gemma4-nethack:latest`, 3.2 GB, 100% GPU, `num_ctx` 8,192):

```bash
uv run nethack-agent eval run --suite evaluation/staircase-v1.json \
  --data-dir data/evaluations/staircase-v1-explore --report-dir evaluation/reports \
  --progress-interval 60
```

Report: `nethack-agent/evaluation/reports/staircase-v1-20260926T211301Z.{json,md}`
(status `complete`, 0644). Acceptance **PASS**, milestone accepted by the suite
gate: 10/10 task successes including seed 6, 0 invalid actions, 0 gate
rejections, all records complete, fixed configuration, inputs unchanged.

| Seed | Outcome | Steps | Wall s | Model decisions | Latency ms | Tokens in/out | Skill/prompt/model | Integrity |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 1 | task_success | 217 | 3.8 | 1 | 1170 | 992/48 | 217/0/0 | ok |
| 2 | task_success | 44 | 1.8 | 1 | 1187 | 1003/48 | 44/0/0 | ok |
| 3 | task_success | 222 | 3.6 | 1 | 881 | 1003/48 | 222/0/0 | ok |
| 4 | task_success | 47 | 1.8 | 1 | 1159 | 1003/48 | 47/0/0 | ok |
| 5 | task_success | 147 | 2.8 | 1 | 876 | 992/48 | 147/0/0 | ok |
| 6 | task_success | 151 | 2.8 | 1 | 1011 | 992/48 | 151/0/0 | ok |
| 7 | task_success | 286 | 4.6 | 1 | 1103 | 1003/48 | 286/0/0 | ok |
| 8 | task_success | 222 | 3.8 | 1 | 1130 | 992/48 | 222/0/0 | ok |
| 9 | task_success | 102 | 2.6 | 1 | 1128 | 1003/48 | 102/0/0 | ok |
| 10 | task_success | 430 | 6.4 | 1 | 892 | 991/47 | 430/0/0 | ok |

Each seed made one model decision, so its p50, p95, and max are the same value.
Across all seeds, latency p50/p95/max was 1103/1187/1187 ms; the suite ran
1,868 steps in 34 s. At the start consultation the model chose
`staircase_navigation` for every seed. The arbiter overrode it with
`explore_level`, which ran 1,828 steps; navigation ran 38. Step counts match the
development run because no suite seed reached a stuck state or an unhandled
prompt.

A real-model smoke on held-out seeds exercised the stuck path. Seed 16 was
stuck at step 211; the model chose `explore_level` (1064 ms) and the hero
succeeded at step 352. Seed 29 was consulted at steps 427 and 778 (both
`explore_level`) and was truncated at 1,000.

## Verification

- `uv run pytest -q`: 173 passed. The new or changed tests cover:
  - gate bans on UP and DOWN;
  - diagonal rules for doorless, open, and closed doors, and the rock squeeze;
  - orthogonal routes through doors;
  - frontier choice and closed-door opening;
  - the locked door, kick, direction, and broken-door memory sequence;
  - self-defense exclusions;
  - object-covered corridors;
  - search rotation, exhaustion, and re-arm;
  - explicit versus suspect edges;
  - oscillation abandonment and level-change reset;
  - real-NLE exploration to `>` on seeds 2, 4, and 58 (58 needs a kick);
  - real-NLE stuck consultation with re-arm, and a stuck model fallback
    proposing UP that is rejected (seed 16);
  - selection contract invariants and the three-candidate bound.
- `uv run ruff check .` and `uv run ruff format --check .` passed.

## Limitations

- Success comes almost entirely from deterministic skills. The local model's
  start decision is recorded but overridden. Its influence is limited to stuck
  consultations and unhandled prompts, neither of which occurred in the suite.
- Hidden-passage search is probabilistic. Long searches can end in truncation
  or in fainting from hunger, because food cannot be eaten in this action set.
- Kicking is limited to dungeon level 1. The reviewed knowledge card still
  advises the model not to force doors. The card is unchanged and hash-pinned;
  only deterministic code kicks.
- A "Really attack?" prompt teaches peacefulness by monster glyph for the
  level. A hostile monster that shares the glyph of a peaceful one is then
  avoided.
- Ollama at temperature 0 on a GPU is not guaranteed bit-exact. The trajectories
  here do not depend on model output unless the model is consulted when stuck.
