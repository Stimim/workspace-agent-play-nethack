# 0018: Agent column viewport fit

Date: 2026-09-29

## Problem

[Note 0009](0009-ui-agent-information-redesign.md) recorded that at 1920x1080,
before page scroll, the sticky agent column extended about 34 px below the
viewport. Its `height: calc(100vh - 1.5rem)` reserved only the 0.75rem top and
bottom gaps, as if the column started at the viewport's top edge. It actually
starts below `<header class="control-panel">` and, while shown, the `#error`
banner.

## Change

- `index.html`: the control panel header has `id="control-panel"`.
- `view.js`: `view.controlPanel` joins the element map. The exported
  `syncHeaderOffset()` writes `controlPanel.offsetHeight + error.offsetHeight`
  to the root `--header-offset` custom property through CSSOM, which the
  `style-src` CSP permits, as for tooltip coordinates. `initializeView` calls
  it once and on every window `resize`.
- `app.js`: `showError` and `clearError` call `syncHeaderOffset()` after
  changing the banner.
- `app.css`: the `.agent-column` height is
  `calc(100vh - var(--header-offset, 0px) - 1.5rem)`. The narrow overlay
  (`max-width: 1520px`) keeps its own `position: fixed; height: 100vh`.

## Browser evidence

Headless Windows Edge 154 (`Edg/154.0.0.0`) was driven over CDP by a throwaway
Windows PowerShell script. The CDP endpoint is local to Windows there, so no
WSL port relay was needed. The page came from
`uv run nethack-agent serve --development-scripted-model --port 8018`. M is
`innerHeight - agent-column.getBoundingClientRect().bottom` at `scrollY` 0; the
target is 10.5 px (0.75rem at the 14 px root font size), with 1 px tolerance.

- Before, 1920x1080: the old formula was reproduced in the fixed page by
  forcing `--header-offset: 0px`, which makes the new expression identical to
  the old one. The column top was 55.28125 and its bottom 1114.28125, so
  M = -34.28125 (overflow), matching note 0009.
- After, 1920x1080: `--header-offset` 45px (45 px control panel), top
  55.28125, bottom 1069.28125, M = 10.71875. The column's natural top is
  10.28125 px below the header rather than exactly 0.75rem, which accounts for
  the 0.22 px difference.
- Widths 1900, 1800, 1700, 1600, and 1521 at height 1080: the control panel
  stayed 45 px (it did not wrap at any width of 1521 px or more), and M was
  10.71875 at every width.
- Resize listener: at 900x1000 the control panel wrapped to 79 px and
  `--header-offset` followed to `79px`. Returning to 1920 restored `45px`.
- Error banner, 1920x1080: attaching the nonexistent run
  `does-not-exist-0018` showed `HTTP 404: run not found: does-not-exist-0018`
  (banner 33 px). `--header-offset` became 78px, top 88.28125, bottom
  1069.28125, M = 10.71875. After a reload cleared it, the offset returned to
  45px and M to 10.71875.
- Narrow regression, 900x1000: the agent column was `position: fixed`,
  1000 px high, and closed. **Agent info** opened it with focus on Close
  (`agent-close`); Escape closed it and returned focus to `agent-toggle`.
- Screenshots (Windows `C:\Temp\`): `nh-0018-a-before.jpg`,
  `nh-0018-b-after.jpg`, `nh-0018-c-narrow-open.jpg`, `nh-0018-d-1521.jpg`,
  and `nh-0018-e-error.jpg`.

## Out-of-scope observation

`grep -n "calc(100vh" nethack-agent/src/nethack_agent/ui/app.css` matches line
127, `.inventory-column { min-height: calc(100vh - 5rem); }`, and line 294, the
rule fixed here. The inventory column's minimum height uses a fixed 5rem
allowance rather than the measured header offset; it was neither changed nor
measured.

## Local worker models

This was the first real task delegated to the local OMP worker tiers. Worker
turn metadata named `ollama/omp-coder:latest:off` for `fast` and
`ollama/omp-coder:latest:high` for `good`. The planned subagent `task` spawns
ran as OMP `vibe_spawn` worker sessions.

- Fast, read-only anchor collection: the first turn returned JSON, elided file
  contents with ellipses, and fabricated the `.agent-column` rule body. It
  self-reported `ollama/omp-coder:latest` in a JSON field rather than the
  requested final "Resolved model:" line. One retry returned correct verbatim
  contents and grep matches but still omitted that line.
- Good, implementation: the first turn deleted `runId` from the `view` map,
  removed the closing brace of `setAgentPanelOpen`, skipped the `app.js` and
  `app.css` edits and all verification, and still reported completion. The
  corrective retry thrashed on the same edits and also deleted `runState`, so
  it was stopped. It never reported a "Resolved model:" line.
- Good, browser verification: ran 2 h 18 min without producing a measurement,
  wrote scratch scripts into the repository (removed), and added an unpinned
  `playwright` dependency (reverted). Its report contained claims that did not
  match the code.
- Fast, fully specified execution succeeded: restoring the four UI files and
  applying the edits as exact single-match replacements, running the checks,
  and running the director-authored CDP script.

Lesson: at this size, the local worker models are usable for deterministic,
fully specified execution, not for open-ended implementation or environment
discovery. Check every claim against the files and tool output.

## Verification

- Browser: the measurements above.
- `uv run pytest -q`: 456 passed, 3 warnings.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 47 files already formatted.
- `node --check` passed for `app.js`, `client.js`, `event-log.js`,
  `render.js`, and `view.js`.
- The pinned `mkdocs build --strict` command from `docs/development.md` built
  the documentation.
- `git diff --check`: passed.
