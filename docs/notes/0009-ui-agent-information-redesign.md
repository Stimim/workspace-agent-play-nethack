# 0009: UI layout and agent-information redesign

Date: 2026-09-27

## Delivered behavior

The browser control surface now puts all run controls in one full-width panel.
Below it, the run/map/player column and inventory column retain fixed widths,
while agent information uses the remaining width. The map has a fixed 79-by-21
viewport. At narrower widths the agent column no longer compresses either fixed
column: an accessible **Agent info** control opens it as an overlay, which can be
closed with its Close button, the background scrim, or Escape.

Agent information keeps metrics visible above three keyboard-navigable tabs:

- **Events** uses expandable event rows. Every new step becomes the latest
  decision expanded by default; older decision rows collapse but remain
  inspectable.
- **Tools** uses expandable rows only when a typed step event contains an
  executed action and records `deterministic_skill` or `deterministic_prompt`
  as `selection.source`. The UI does not infer or invent tool calls from model
  rationales or action names.
- **Verbose** groups persisted game messages, concise rationales, candidate
  reasons, and decision-attempt errors that do not fit the compact summaries.
  Raw model responses are intentionally omitted; this remains a structured
  decision trace rather than hidden chain-of-thought.

Each tab body scrolls independently and has its own enabled-by-default
auto-scroll checkbox. Semantic focusable tooltips explain run, player,
decision, and metric fields. Goal and skill values use explanations matching
the enums and behavior in `decision.py` and the coordinator.

The redesign preserves page-relative API and WebSocket URLs, reconnect and
attachment behavior, existing lifecycle/error controls, same-origin CSP, and
text-only insertion of model and game data.

## Review corrections

A follow-up accessibility review found one concrete overlay defect: resizing from
the desktop three-column layout to the narrow layout could hide and inert the
agent column while keyboard focus was still inside it. The responsive sync now
moves that focus to the visible **Agent info** control when it hides the panel.

The final browser pass found two more defects, both now fixed:

- Tooltips were absolutely positioned inside scrolling tab bodies and
  overflow-clipped panels, so explanations near a container edge could be cut
  off. Tooltips are now fixed-position layers whose coordinates `app.js` sets
  through CSSOM custom properties (allowed by the CSP; no inline `style`
  attribute). The open overlay uses `transform: none`, so fixed descendants
  remain viewport-relative. Escape dismisses a shown tooltip before it closes
  the overlay.
- Every event re-rendered metrics and run fields, replacing a hovered or
  keyboard-focused tooltip trigger and dropping focus to the page. Unchanged
  fact lists now keep their DOM, and a changed list restores focus to the
  trigger at the same position.

Verbose row summaries now preview their first text field instead of showing
only the event sequence and kind.

## Messages tab

A **Messages** tab now sits between Events and Tools. It lists NetHack's own
top-line text: one plain-text row per `run_started` or `step` event whose
`payload.observation.message` is non-blank, showing the observation step, the
event sequence, and the message. Surrounding whitespace is trimmed and
whitespace-only messages are skipped; identical consecutive messages are kept
because NetHack legitimately repeats them. The tab follows the other logs:
default-on auto-scroll, a scrolling body, reset on attach, and the
300-entry cap. Game messages still also appear in Verbose. `gameMessage` and
`renderMessageEntry` in `render.js` implement the row.

Verification:

- `uv run pytest -q tests/test_ui.py`: 13 passed, including a Node-executed test
  covering repeats, trimming, whitespace-only and missing messages, non-observation
  events, text-only row rendering, and the message remaining in Verbose.
- `node --check` for `app.js` and `render.js`, `uv run ruff check .`, and
  `uv run ruff format --check .`: passed.
- Live scripted seed 6 (`--max-steps 100 --auto`, port 8031): 102 events; the
  shipped `gameMessage` over them yielded 14 messages, starting with
  `step 0 · #0 You are lucky!  Full moon tonight.` and
  `step 12 · #13 You kill the grid bug!`.
- Headless Windows Edge over CDP attached to that run (last 50 events replayed)
  and selected Messages with ArrowRight from Events: Messages selected and
  focused, auto-scroll checked, 6 rows from `step 87 · #88 You miss the sewer
  rat.  The sewer rat bites!` (repeated at `#89`) to `step 96 · #97`, body at
  bottom, Verbose still holding 6 game-message rows, no error banner.
  Screenshot: `C:\Temp\nethack-messages-tab.png`.

## Verification

- `uv run pytest -q`: 178 passed (includes the 9 `tests/test_ui.py` tests: the
  renderer behavior tests that only event-evidenced deterministic actions appear
  as tool executions and that verbose diagnostics omit raw model responses, plus
  CSP, served module graph, relative/self-contained asset, and no-HTML-parsing
  checks).
- `uv run ruff check .` and `uv run ruff format --check .`: passed (38 files).
- `uvx --from mkdocs==1.6.1 --with pymdown-extensions==12.1 --with
  mkdocs-mermaid2-plugin==1.2.3 mkdocs build --strict --config-file
  docs/mkdocs.yml`: built without warnings.
- `node --check` passed for `app.js`, `render.js`, and `client.js`.
- Real browser: WSL's managed Chromium cannot start (`libnspr4.so` missing), so
  headless Windows Edge (`msedge.exe --headless=new
  --remote-debugging-port=9229`) was driven over CDP against a
  `--development-scripted-model` service on `127.0.0.1:8018`. The throwaway
  driver started seed 6 through the UI and stepped 33 times.
  - 1920x1080: control panel full width; primary column 756 px and inventory
    294 px (fixed); agent column 813 px (remaining width); **Agent info** hidden.
    The 79x21 map had equal client and scroll sizes (no clipping). 31 events;
    exactly one decision expanded (the latest); events body scrollable and
    auto-scrolled to the bottom; 30 Tools rows; no error banner.
  - With auto-scroll unchecked, three more steps left the events body at the top;
    re-checking it jumped to the newest row. Clicking the oldest event expanded it
    and left the latest decision expanded. ArrowRight from the Events tab selected
    and focused Tools.
  - A focused decision-field tooltip inside the scrolling events body rendered
    fully inside the viewport, above neighboring rows; Escape set its opacity to
    0.
  - 900x1000, overlay closed: fixed columns kept 756 and 294 px, reachable by
    horizontal page scroll (width 1071 px); the agent column was hidden, inert,
    `aria-hidden`, and off-screen; **Agent info** visible with
    `aria-expanded=false`.
  - Overlay open: 588 px panel entirely inside the viewport, scrim shown, focus
    on Close; its tab body stayed inside the panel. A metrics tooltip rendered
    inside the viewport. Tools and Verbose rows expanded; Tools evidence read
    `event.payload.selection.source = deterministic_skill`; Verbose contained no
    raw model response. Escape closed the overlay and returned focus to
    **Agent info**.
  - The live seed-6 observation contained a real pet: the map rendered one
    `pet c15` span (`f`) and a separate `player` span.
  - Boulder and ghost symbols do not occur in the scripted observation, so a
    browser-side fixture passed a synthetic observation to the shipped
    `renderMap` without changing product state. It produced `c3 "0"`,
    `c15 "X"`, `pet c2 "d"`, a separate same-color wild `c2 "d"`, and `player "@"`.
  - A focus probe kept keyboard focus on the "Steps seen" trigger across a
    live metrics update (value 1 to 2) with its tooltip visible, and kept the
    unchanged goal node.
  - Screenshots (Windows `C:\Temp\`): `nethack-ui-wide.png`,
    `nethack-ui-wide-tooltip.png`, `nethack-ui-wide-expanded-first-event.png`,
    `nethack-ui-narrow-closed.png`, `nethack-ui-narrow-open-events.png`,
    `nethack-ui-narrow-open-tooltip.png`, `nethack-ui-narrow-tools.png`,
    `nethack-ui-narrow-verbose.png`, `nethack-ui-narrow-symbol-fixture.png`,
    and `nethack-ui-symbol-fixture-zoom.png`.

## Limitations

- At 1920x1080 before page scroll, the sticky agent column extends about 34 px
  below the viewport because it starts below the control panel. Scrolling the
  page by the panel's height brings it fully into view; no content is lost.
  Fixed in [0018](0018-agent-column-viewport-fit.md).
- Automated DOM behavior tests are limited to renderer functions that run in
  Node without a DOM. Layout, overlay, focus, and tooltip behavior are verified
  by the recorded browser smoke only.
