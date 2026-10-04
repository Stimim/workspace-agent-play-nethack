# Permanent native ground-truth reader

This is **development evidence and coding-agent tooling**, not a policy
qualification or a replayed acceptance retry. The evaluator database and
committed reports remain unchanged. No `nethack-agent/src` code changed.
The [native-truth skill](../../_agents/skills/native-truth/SKILL.md) makes the
methods previously rebuilt and deleted in notes
[0031](0031-exit-discovery-probes.md#native-memory-diagnosis-non-committed-development-evidence)
and [0045](0045-three-single-rule-qualification.md#actual-cause-of-seed-5)
permanent, runnable, and tested. Native data never enters gameplay.

## Method and ABI evidence

The reader attaches to the **per-instance memfd copy** of libnethack, not the
installed shared library. It obtains the instance's `dlpath`, matches its
inode in `/proc/self/maps`, and opens only that already-loaded copy with
`RTLD_NOLOAD`. Exported globals are read through ctypes; no native engine
function is called and no game-state memory is written. Context ownership
explicitly closes the additional handle before NLE closes. Separate instances
with identical seeds are tested so an attachment cannot silently select the
first matching hero in a different instance.

Source is [NetHack-LE/nle v1.3.0](https://github.com/NetHack-LE/nle/tree/v1.3.0),
commit `70cb9b5260d05b38ee1ee1b0228d5f6f8ca54655`, NetHack 3.6.7. An exercised
GCC layout probe against those headers measured:

| Structure / field | Size or byte offset |
| --- | ---: |
| `rm` size; `typ`, `seenv`, packed flags, room number | 8; 4, 5, 6, 7 |
| `level.locations` | `[80][21]`, x-major |
| `level.objects`, `objlist`, `monlist`, `flags` | 13440, 40320, 40336, 40360 |
| `u.ux`, `u.uy`, `u.uz` (header prefix) | 0, 1, 10 |
| `stairway`, `dungeon`, `s_level`, `mkroom` size | 5, 56, 32, 216 |
| `obj.ox`, `obj.otyp` | 28, 30 |
| `monst.mx`, `mtame`, peaceful bit | 28, 53, byte 65 bit 1 |
| `trap.tx`, trap type bits | 8, byte 14 low five bits |

Every attach **and live snapshot** checks hero coordinates and `u.uz` against
public `blstats`, expected ctypes map offsets/size, true stair terrain at
exported stair coordinates, and visible public stair/wall/door evidence.
All map coordinates below are NLE coordinates (native x minus one).

Two important implementation details were exercised rather than assumed:

- `SDOOR`'s low three flag bits are `WM_MASK`, **not** broken/open state.
  [detect.c](https://github.com/NetHack-LE/nle/blob/v1.3.0/src/detect.c)
  masks them before conversion and makes an unlocked secret door CLOSED.
  Permanent boundary tests cover misleading low-bit values 1, 2, and 7, plus
  the locked case. Route geometry forbids diagonal passage through intact
  doors, including open and secret doors.
- Wall glyph subtypes do not equal native wall subtypes in every cave:
  `wall_angle()` depends on `seenv`. A real Mines-entry probe found a native
  TDWALL rendered as a top-left corner. Validation checks the wall class,
  not an incorrect equality of those subtypes; it still refuses non-wall
  terrain under a wall glyph.

Snapshots include true terrain, stair/ladders and branch destinations, traps,
boulders, non-pet peaceful monsters, dungeon name, exported special prototype,
level flags, and **both ordinary rooms and subrooms**. Main stair structs'
`up`/destination fields are not populated like branch stairs; main direction
and destination follow their symbol and current level. Branch `sstairs` uses
its actual exported destination.

The special table distinguishes Minetown (`minetn`), Mines' End (`minend`),
Oracle (`oracle`), and Sokoban (`soko1`–`soko4`). The randomized file suffix is
not exported: `mkmaze.c` stores `protofile` on its stack. Separately labelled
Minetown variant candidates use temple bounds and altar/fountain distances
from v1.3.0 `dat/mines.des`; map flips preserve those signatures. They remain
candidates, not invented native filenames. A dry fountain can leave the two
4×4-temple variants ambiguous.

Additional real scripted probes exercised Minetown identity/room reads:

| Committed seed | Step | Native level | Prototype / structural candidate | Temple evidence |
| --- | ---: | --- | --- | --- |
| 4 | 721 | Mines 4 | `minetn` / `minetn-3` | subroom index 45, type/original type 10, bounds x35–37/y6–9 |
| 7 | 772 | Mines 4 | `minetn` / `minetn-6` | ordinary room index 15, type/original type 10, bounds x51–56/y15–17 |

These were diagnostics using existing seeds, not new acceptance episodes. A
seed-6 diagnostic reached Mines 3 but not Minetown within its 2000-action cap;
no Minetown claim is made for it.

## Replay contract and terminal safety

The CLI loads the evaluator's SQLite run metadata and ordered events read-only.
It reconstructs the recorded task/cap/suite seed through the unchanged adapter,
checks exact derived core/display/level seeds, character/NLE identity and
recorded action table, then reissues every action. Reset and every resulting
projected observation must match; only proper names in `named NAME` text are
normalized. No map/statistic/action normalization or skipped prefix is allowed.
The adapter preserves the real pickup/drop/look MORE transport noted in 0045.
A mismatch aborts without publishing diagnostic output.

At death, NetHack frees dynamic lists before returning the terminal NLE
observation. The earlier 0031 heap-read segfault is not repeated: direct
terminal snapshots read **static data only**. The special table was copied at
live attach. Replay captures dynamic collections just before the terminal
action, labels reused collections with their last-live step, and never
re-dereferences them after terminal. This conservative rule also applies to
truncation. Monsters may move during the final action. Zeroed death statistics
cannot validate a terminal snapshot; its validation field is explicitly null,
while attach and the pre-terminal capture were validated. Unvisited levels'
terrain is not readable through current-level globals.

## Acceptance-failure smoke: descend-d5-v2

Both commands replayed the original
`nethack-agent/data/evaluations/descend-d5-v2/runs.sqlite3`, not a new policy run:

```bash
uv run --project nethack-agent python _agents/skills/native-truth/replay.py \
  nethack-agent/data/evaluations/descend-d5-v2/runs.sqlite3 \
  --seed 2064852799 --at first-on-final-level --at end \
  --output /tmp/native-truth-2064852799.json

uv run --project nethack-agent python _agents/skills/native-truth/replay.py \
  nethack-agent/data/evaluations/descend-d5-v2/runs.sqlite3 \
  --seed 249447619 --at first-on-final-level --at end \
  --output /tmp/native-truth-249447619.json
```

| Seed / original run id | Replayed actions / matching projected observations | Final level / true main downstairs | End-route diagnosis | Adjacent SEARCH |
| --- | --- | --- | --- | --- |
| 2064852799 / `69ce1308-474a-4722-b86a-e7aef3e8e81b` | 2816 / 2817 | Doom 3 / **(6,16)** → Doom 4 | **36 steps**, one secret door **(13,6)**; minimal class set **{secret}** | **0 of 223** final-level SEARCH actions |
| 249447619 / `b10c4377-1502-4196-8f48-9664b456e8c6` | 3000 / 3001 | Doom 2 / **(23,16)** → Doom 3 | **65 steps**, peaceful hobbit **(60,7)** and secret corridor **(26,7)**; minimal class set **{secret, peaceful monster}** at the last-live endpoint | **10 of 1901** final-level SEARCH actions (**0.53%**) |

SEARCH counts use the recorded **before-action** hero positions on that level,
within Chebyshev distance 1 of any secret cell on the selected shortest true
route; an action adjacent to several secret cells counts only once. These
routes also minimize blocker-cell count, then steps. Individually holding
secret cells blocked makes both routes impossible, even when all other barrier
classes are relaxed. Holding locked, closed, or boulder cells blocked leaves
the same end-route lengths. Holding peaceful monsters blocked also disconnects
the second seed's endpoint (using its **step-2999** last-live monster positions).
This is geometric evidence, not proof that a moving hobbit is a permanent lock.

Entry snapshots disambiguate the late dynamic obstruction:

- Seed **2064852799** first entered its final level at **step 74**, hero (52,6).
  Its 52-step route already required SDOOR (13,6), with minimal set {secret}.
  At death step 2816, native hero is (36,7); static stairs/map persist. Heap and
  public overlay evidence are labelled last-live **step 2815**. The relevant
  hidden door received no adjacent SEARCH at any time on that level.
- Seed **249447619** first entered its final level at **step 68**, hero (30,3).
  Its 15-step route required only SCORR (26,7), minimal set {secret}; peaceful
  monsters were not a cutset there. At truncation step 3000, hero is (65,9);
  the last-live hobbit lies across the remote endpoint's corridor. The hidden
  corridor received only ten adjacent searches despite 1901 SEARCH actions.

The JSON artifacts include complete true maps, public-map overlays, native
collections, selected paths/blocker cells, and all five held-blocked analyses;
the terminal commands rendered actual ASCII map surfaces. They are diagnostic
artifacts under `/tmp`, not committed engine-state inputs or altered reports.

## Verification

Permanent real-NLE tests cover validated attach/hero agreement, rejection of a
wrong public hero, simultaneous same-seed instance identity, early visible
seed-2 downstairs agreement, and a six-action scripted run persisted by the
actual `RunManager` and replayed with all seven observations matching.
Corrupting recorded HP is refused. Boundary tests cover secret wall-mode
masking, static-only terminal snapshots, and secret/locked geometric cutsets.

Final validation:

- `uv run pytest -q`: **653 passed, 3 dependency deprecation warnings**, 50.27s.
- `uv run ruff check .`: passed; `uv run ruff format --check .`:
  **57 files already formatted** (from `nethack-agent/`).
- Explicit skill checks using `--config nethack-agent/pyproject.toml`:
  Ruff check passed; **3 skill Python files already formatted**.
- `git diff --check`: passed.
