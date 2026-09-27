# 0014: Compact Player state grid

Date: 2026-09-27

## Delivered behavior

The browser UI now renders Player state as a specialized semantic description
list instead of applying the generic two-column facts layout. Each stat is a
native `dt`/`dd` pair inside one grid cell, so labels and values retain their
description-list relationship. The field labels and focusable tooltips are
unchanged, including the full Strength, Dexterity, Constitution, Intelligence,
Wisdom, and Charisma names.

The normal 50rem primary column fits three stat cells per row. The cells remain
in reading order as related triplets: HP/Pw/AC, level/depth/position,
turn/gold/score, hunger/encumbrance/alignment, and the two ability rows.
Conditions occupies the full final row. CSS auto-fitting reduces the grid to two
or one column if the component is constrained, without changing generic fact
lists elsewhere in the UI.

## Browser evidence

A scripted seed-6 run was opened in headless Windows Edge 154 through the
existing CDP workflow. Before the change, the populated panel was 441.46875 CSS
px high and its 19-row list was 398.6875 px high. At 1920x1080 after the change,
the panel was 205.125 px high and its list was 162.34375 px high: a 236.34375 px
(53.5%) panel-height reduction. Computed layout had three columns of about
218.66 px, seven visual rows, all 19 fields visible, and no horizontal or
vertical clipping in either the panel or grid.

At 900x1000, the fixed 50rem primary column retained the same three-column grid
and dimensions, while the existing workspace remained horizontally reachable
as designed. All 19 labels and values remained visible with no panel or grid
overflow. Focusing Strength showed its existing tooltip fully within the
viewport; after a live API-driven step changed Turn from 1 to 2, focus returned
to Strength with the same valid `aria-describedby` relationship and the tooltip
remained usable. Screenshots are `/tmp/nethack-player-grid-wide.png` and
`/tmp/nethack-player-grid-narrow.png`.

## Verification

- `uv run pytest -q tests/test_ui.py`: 17 passed. The renderer test exercises
  all 19 labels and values, native `dt`/`dd` pairs, grouped stat cells, the
  full-width Conditions cell, and accessible tooltip relationships.
- The Edge checks above used the shipped HTML, CSS, and JavaScript from the live
  loopback service; the browser identified itself as
  `Edg/154.0.4258.37`.
- `uv run pytest -q`: 248 passed with three dependency deprecation warnings.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 40 files already formatted.
- `node --check` passed for `app.js`, `client.js`, `event-log.js`, `render.js`,
  and `view.js`.
- The pinned `mkdocs build --strict` command from `docs/development.md` built
  the documentation without warnings.
- `git diff --check`: passed.
