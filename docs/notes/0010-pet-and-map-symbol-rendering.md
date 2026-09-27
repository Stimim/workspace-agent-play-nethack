# 0010: Pet and map-symbol rendering

Date: 2026-09-27

## Change

The observation projection now carries `pet_rows`, a per-cell byte mask derived
only from NLE's `glyph_is_pet` result. Changed cells carry the corresponding
`pet` value. The browser gives those explicitly identified cells their own map
highlight while preserving the NetHack foreground color; it does not classify a
character as a pet when that evidence is absent.

Map display rows use glyph identities to render the boulder object as `0` and
the ghost monster class (including shades) as `X`. The projector retains the
original glyph IDs and colors, and exempts the player coordinate from symbol
overrides so player rendering remains authoritative.

The roadmap now records historical replay as distinct future product work:
selecting a persisted old event must redraw that event's map, player state,
inventory, and related observation. This change does not implement replay.

## Compatibility with stored events

The first cut made `pet_rows` required, and cross-review found that the strict
event reader then rejected every observation persisted before this change. On a
copy of `nethack-agent/data/evaluations/staircase-v1-explore/runs.sqlite3` it
failed with `stored run_started event 0 is corrupt: observation map fields are
invalid: missing ['pet_rows']`. Documenting that break was rejected: adding a
display feature must not make the accepted milestone 1 records unreadable
through the API, UI, or evaluation audit.

Legacy observations now load with pet evidence *unknown*: `MapView.pet_rows`
and `MapCellChange.pet` are `None` and serialize as JSON `null`. An absent
field and `null` mean the same thing. The reader does not invent an all-zero
mask, since a missing mask means that no evidence was recorded, not that no pet
was present. Present pet fields stay strictly validated, extra fields are still
rejected, and new projections always record evidence. `contracts.object_value`
gained an explicit `optional` field set for this purpose. The browser shows no
pet highlight for unknown evidence. Stored map rows keep the characters they
were recorded with; the `0`/`X` overrides apply to new projections.

Lesson: a new field in a persisted observation contract needs a defined meaning
for records that predate it before the reader is tightened.

## Verification

- `uv run pytest -q tests/test_observation.py tests/test_storage.py tests/test_run_manager.py tests/test_api.py tests/test_ui.py`: 38 passed.
- `uv run pytest -q tests/test_observation.py tests/test_skills.py`: 22 passed.
- `uv run ruff check src/nethack_agent/observation.py tests/test_observation.py tests/test_skills.py`: passed.
- `uv run ruff format --check src/nethack_agent/observation.py tests/test_observation.py tests/test_skills.py`: passed.
- A JavaScript DOM smoke invoked the shipped `renderMap`: the player, `0X`, an explicitly marked pet, and a same-color wild animal rendered as separate expected spans; omitting `pet_rows` did not infer a pet.
- `uv run pytest -q tests/test_ui.py`: 7 passed after integration with the
  concurrent UI layout changes.

Legacy-compatibility follow-up:

- `uv run pytest -q`: 187 passed. New or extended behavior tests: legacy
  observations without pet fields read as unknown and round-trip through JSON
  `null`; malformed present `pet_rows`/`pet` values and extra fields fail;
  a restarted API serves legacy-shaped stored events; the evaluation audit
  passes integrity on legacy-shaped development-suite events; the renderer
  highlights only explicit pets and none for `pet_rows: null`.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- `mkdocs build --strict --config-file docs/mkdocs.yml`: passed.
- On a copy of the accepted `staircase-v1-explore` data directory (10 runs,
  1,888 events, none with pet fields), `RunStore` read every event with
  unknown pet evidence and `summarize_run` reported integrity OK and
  `task_success` for all 10 seeds. A service on that copy returned HTTP 200 for
  the seed-6 run status and events, with `pet_rows: null` and changed-cell
  `pet: null`.