# 0013: Review feedback resolutions

Date: 2026-09-27

The comments in `_agents/feedback.xml` were checked against the code, NLE,
and local evidence before any change was made. The Modelfile location and
fallback-configuration comment was handled separately and is not covered here.

## Model role and learning loop

ADR 0002 now says what the model is for. The deterministic arbiter still
chooses skills for the current staircase milestone, because the evaluation shows
that deterministic skills are enough there. When later benchmarks involve real
trade-offs, the local model should make the high-level decisions: whether to
descend or gather resources and experience first, whether to pray or use another
recovery, which threat to handle first, and which branch to pursue.

During a fixed episode, the model may handle an unfamiliar situation. It never
modifies policy, prompts, skills, or knowledge. After an episode or suite, a
coding agent reviews the persisted evidence. If a recurring case is nuanced, the
coding agent updates reviewed knowledge. If the case is simple, it adds a tested
deterministic skill. These changes apply only to later runs.

## Knowledge corrections

- **Autoopen.** NLE 1.3.0 passed its default `NETHACKOPTIONS` tuple, which does
  not list `autoopen`. The adapter now passes `NLE_OPTIONS`, which is NLE's
  defaults plus `autoopen`. A real-environment test checks the option list that
  the live NLE engine received. The safe-interaction card now states this as a
  fixed scenario setting, not a choice the player makes.
- **Covered stairs.** NLE exposes one scalar glyph and one displayed character
  per map cell. A staircase glyph is a cmap glyph, while an inventory object
  glyph is an object glyph. No public parallel terrain array exists. The agent
  therefore cannot see a staircase under a covering object or monster in the
  current observation. It can know about that staircase only if level memory
  saw it earlier. The staircase card now says so.
- **Branch stairs.** The local wiki's Staircase page says that branching levels
  have extra stairs. The Gnomish Mines page places the Mines entrance on dungeon
  levels 2-4. The Sokoban page, tagged NetHack 3.6.7, places the Sokoban upstair
  on levels 6-10. The staircase card now names both cases. The milestone
  policy's goal and non-goal text are unchanged.
- The bundle ID is now `staircase-reviewed-v2`. The updated card hashes are
  pinned, the version test was updated, and the rendered context is 4,437
  characters (1,110 estimated tokens).

## Gameplay effect

### Scripted trace comparison

Explicit `autoopen` and knowledge v2 were checked for gameplay changes with a
throwaway harness outside the repository. It created a detached worktree of
HEAD (`70ae56f`), ran `uv sync --locked` there, and ran `nethack-agent
scenario run --auto --development-scripted-model --max-steps 1000` on suite
seeds 1-10 and seed 58 in both HEAD and the current tree. It then compared
every stored step event.

- Of the 1,956 steps, none differ in action index, selection source, skill,
  `skill_selection`, `stuck_reason`, rationale, intent (destination, attack
  target, and path), outcome, or game message. All 11 runs end in
  `task_success` with identical step counts.
- All 1,967 stored observations are identical, excluding only the new inventory
  `buc` key.
- The traces include 22 "The door opens." and 3 "This door is locked." messages
  after moves into closed doors. These are identical in both trees.

NetHack 3.6.7 already enables `autoopen` by default, so adding it to NLE's
option list makes the existing engine behavior explicit and does not change it.
The scripted model does not read knowledge, so this comparison isolates the
option change.

### Real-model suite with knowledge v2

The knowledge change alters the model prompt, so the committed suite was run
once with the local model (Ollama 0.34.4, `gemma4-nethack:latest`, `num_ctx`
8,192, after a passing `nethack-agent doctor`):

```bash
uv run nethack-agent eval run --suite evaluation/staircase-v1.json \
  --data-dir data/evaluations/staircase-v1-knowledge-v2 \
  --report-dir evaluation/reports
```

`staircase-v1.json` records the knowledge version in each report rather than
pinning it, so knowledge v2 was accepted without changing the suite. The
report is `nethack-agent/evaluation/reports/staircase-v1-20260927T065500Z.{json,md}`
(status `complete`, 0644). It passed every acceptance check.

| Metric | Accepted v1 (`20260926T211301Z`) | Knowledge v2 (`20260927T065500Z`) |
| --- | --- | --- |
| Task successes | 10/10 | 10/10 |
| Steps per seed 1-10 | 217, 44, 222, 47, 147, 151, 286, 222, 102, 430 | identical |
| Total steps / wall time | 1,868 / 34.0 s | 1,868 / 39.3 s |
| Model decisions (failed, repaired) | 10 (0, 0) | 10 (0, 0) |
| Selection sources | 1,868 deterministic skill | 1,868 deterministic skill |
| Latency p50/p95/max | 1103/1187/1187 ms | 1106/1649/1649 ms |
| Prompt/output tokens | 9,974/479 | 11,924/467 |

Each model decision used about 195 more prompt tokens. This matches the 993
characters added to the knowledge context. The 1,649 ms maximum came from seed
1, the suite's first decision; every other seed stayed at or below 1,253 ms.

At the start consultation, the model again chose `staircase_navigation` for
every seed, and the arbiter again overrode it. Compared with the accepted
milestone records, all 1,868 steps match in action index, source, skill,
skill-selection source, stuck reason, rationale, outcome, and game message.

Milestone acceptance still rests on the original report. This run shows that
the knowledge-v2 configuration also passes the suite. It says nothing new about
model reasoning, because no seed reached a stuck consultation or an unhandled
prompt.

## Stairs roadmap

`StaircaseNavigationSkill` selects the reachable remembered `>` with the
shortest BFS route. Ties are broken by lower `y`, then lower `x`. A new behavior
test shows that it prefers the upper-left `>` over an equally distant lower-left
`>`, and that it does so by moving west first. The current goal cannot request
`<`, and the skill cannot tell the main-dungeon stairs from branch stairs.
`TODO_LIST.md` now has an item for typed traversal goals with stair direction,
stair identity, memory, intents, and evaluation cases.

## UI evidence and structure

- Player stats now show separate Strength, Dexterity, Constitution,
  Intelligence, Wisdom, and Charisma rows. The field tooltips were updated to
  match.
- NLE exposes no inventory BUC array. The projector therefore records a typed
  `BucStatus` only when `blessed`, `uncursed`, or `cursed` appears as the first
  word of a description or directly after an article or count. All other
  descriptions are `unknown`, and older stored observations without `buc` are
  also read as `unknown`. Tests check that labels such as "scroll labeled
  CURSED", "called cursed hope", and "cursed-looking" are not treated as BUC.
- Each inventory row shows a visible `[B]`, `[U]`, `[C]`, or `[?]` marker with
  its own class and tooltip. The inventory panel also has a text legend, so
  color is never the only cue.
- `app.js` is now split into four modules:
  - `app.js` keeps run, API, and stream state;
  - `view.js` handles DOM elements, the overlay, tabs, focus, tooltips, and the
    path preference;
  - `event-log.js` handles the four bounded logs;
  - `render.js` handles rendering, as before.

  The two new modules were added to `_UI_ASSETS`, and the served-module-graph
  test covers them.
- Frontier visualization was already done: frontier intents use the
  destination box, and their routes use the path tint. The TODO list marks
  this as done instead of opening a duplicate item.
- A research item for the Janelia FlyEM male CNS connectome now sits next to
  the Laya item. It asks for an evidence-driven evaluation of planning and
  action ranking, and does not commit to using it in production.

## Contract validation decision

ADR 0003 declines a runtime JSON Schema validator. No such dependency exists
today. FastAPI's transitive Pydantic is a web dependency, not the storage
contract. The two JSON Schemas sent to Ollama only constrain what the model
generates. The domain parsers still have to check legal-action membership and
many cross-field rules: intent and source, map bounds, path contiguity and
endpoint, and legacy optional pet, intent, path, and BUC fields. Adding a schema
pass would walk and allocate every event payload twice without replacing those
typed constructors. The existing malformed-payload tests cover the typed
helpers' behavior.

## Commit skill

`_agents/skills/omp-commit/` adds a procedure and a Python script that uses no
shell evaluation. The script requires exactly one live OMP client for the
repository, reads its explicit `--resume` UUID, and checks the matching session
JSONL. It fails if any of this evidence is missing or ambiguous. It then runs
`ruff check` and `ruff format --check`, removes any existing
`OMP-Conversation` lines, and writes exactly one trailer to a temporary copy of
the message. If checks fail, no commit is made. AGENTS.md rule 9 now requires
following this skill.

## Verification

- `uv run pytest -q tests/test_commit_skill.py`: 8 passed. The tests use
  isolated OMP and proc evidence and cover:
  - one matching client;
  - ambiguous clients;
  - no matching client;
  - a missing UUID;
  - ambiguous session files;
  - replacing duplicate trailers in a scratch Git repository whose path
    contains spaces;
  - a check failure that leaves HEAD absent;
  - a dry run that prints the trailer and creates no commit.
- The real `omp_commit.py resolve` command returned
  `01a0dd35-4ec8-76dd-9c86-bcac1fdb25c5` from the live OMP process and session
  evidence.
- Focused tests passed for the environment, observation, knowledge, staircase
  selection, and UI modules.
- A headless Windows Edge 154 session was driven over CDP against the scripted
  service. It started seed 6 and stepped it 72 times. The results:
  - The stat labels read Strength through Charisma.
  - The live inventory showed `[?]`, `[?]`, `[U]`, `[U]`, and the legend listed
    B, U, C, and ?.
  - All four agent tabs could be selected.
  - The recorded frontier destination stayed visible with **Show path** off,
    while the two path spans disappeared. The stored preference was `"false"`
    with the path off and `"true"` after turning it back on.
  - The page loaded `app.js`, `client.js`, `event-log.js`, `render.js`, and
    `view.js`, and showed no error banner.
  - A browser-side call to the shipped `renderInventory` displayed all four BUC
    classes. The focused cursed-item tooltip was visible.
  - At 900x1000, the overlay opened with focus on Close, and every tab could be
    selected.
  - Screenshots: `C:\Temp\nethack-review-wide.png`,
    `C:\Temp\nethack-review-buc.png`, and `C:\Temp\nethack-review-overlay.png`.
- `uv run pytest -q`: 248 passed.
- `uv run ruff check . ../_agents/skills/omp-commit/scripts/omp_commit.py` and
  `uv run ruff format --check . ../_agents/skills/omp-commit/scripts/omp_commit.py`:
  passed (41 files).
- `node --check` passed for `app.js`, `client.js`, `event-log.js`,
  `render.js`, and `view.js`.
- The pinned strict MkDocs build in `docs/development.md` passed.
