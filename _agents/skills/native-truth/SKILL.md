# Native ground-truth diagnosis

Use this coding-agent skill to explain a recorded NetHack failure against the
engine's true current map. **Diagnosis only:** never import these modules from
`nethack-agent/src`, put their output in a gameplay prompt, or use it to choose
policy actions. Requires Linux x86_64, NLE **1.3.0** (NetHack 3.6.7), and the
repository's Python environment. No wizard mode, writes to game memory, or
engine-function calls are used.

## Replay a recorded run

From the repository root:

```bash
uv run --project nethack-agent python _agents/skills/native-truth/replay.py \
  nethack-agent/data/evaluations/descend-d5-v2/runs.sqlite3 \
  --seed 2064852799 --at first-on-final-level --at end \
  --output /tmp/native-truth-2064852799.json
```

1. Select exactly one `--seed N` or `--run-id UUID`. A seed appearing more than
   once is refused; choose its run id instead.
2. Select repeatable `--at STEP`, `--at end`, or `--at first-on-final-level`.
   STEP is the public observation's `step_index`; **0 is reset**. Add
   `--every-level-entry` to capture every change of level, including revisits.
   Without selectors, capture `end`.
3. Read the JSON and terminal ASCII maps. Without `--output`, stdout is a single
   JSON document; each snapshot includes its ASCII rendering. With `--output`,
   stdout shows maps and compact diagnoses and the file contains the full JSON.

Replay reconstructs `ScenarioConfig` from the recorded task, episode cap, and
suite seed; it checks the recorded core/display/level seeds against `SeedSet`
derivation, NLE/character identity, and the complete legal-action table. This
reuses the adapter's task options, disabled reseeding, fixed moon phase, and
pickup/drop/look pagination. It reissues **every** recorded action and compares
reset plus every projected observation, including maps, changed cells,
inventory, prompts and statistics. Text normalization covers only values NetHack
derives from `ubirthday`, the wall-clock game start: shopkeeper names from the
NetHack 3.6.7 `shknam.c` fixed lists wherever they occur in text fields, and the
quoted price of unidentified gems (`shk.c` `get_cost()`). Any other mismatch
aborts without publishing snapshots. Terminal booleans must also agree. Run
against the adapter version
that recorded the run if historical transport/options changed; do not weaken
comparison to make a divergent replay pass.

## Snapshot API

The three sibling modules are scripts, not a product package. For an independent
coding-agent probe, add this skill directory to `sys.path`, then:

```python
from native_truth import NativeTruth
from nethack_agent.environment import NleEnvironment, ScenarioConfig

with NleEnvironment(config) as env:
    observation = env.reset()
    with NativeTruth(env, observation) as truth:
        snapshot = truth.snapshot(observation)
        transition = env.step(action_index)
        next_snapshot = truth.snapshot(transition.observation)
```

The environment must stay alive until the reader closes. **Close the extra
handle before closing NLE**, including before a coordinator method that closes
its environment automatically. The reader refuses access after either closes.
For coordinator probes, attach/snapshot/close between actions rather than
holding the reader across coordinator-owned termination.

Coordinates are NLE coordinates, **x = native x − 1**, y unchanged. Snapshots
contain:

- The full 79×21 true terrain grid (`rm.typ`, name, door state, flags, `seenv`,
  room number), including `SDOOR` and `SCORR`.
- Main up/down stairs, ladders, and `sstairs` with branch destination. Main
  stair direction/destination follows the current level; their native `up` and
  `tolev` fields are not initialized like branch stairs.
- Hero position and dungeon level; dungeon name, exported special-level
  prototype, level flags, ordinary rooms **and subrooms**, current/original
  room type and temple/shop classification.
- Live traps (type/seen/destination), boulders, and non-pet peaceful monsters.

The exported special table distinguishes `minetn`, `minend`, `oracle`, and
`soko1`–`soko4`. The selected randomized filename (for example `minetn-2`) is
**not exported**: `mkmaze.c` stores it in a local stack buffer. Minetown variant
*candidates* are separately inferred from v1.3.0 `dat/mines.des` temple
bounds and altar/fountain geometry, invariant under map flips. They are not a
claim of an exported name. Missing/dried fountains may leave variants 2/7
ambiguous; unexpected geometry leaves no candidate. Always retain the true
map, room evidence, and prototype rather than assuming a candidate is certain.

## Validation guarantees

Each attach locates **this environment's memfd inode** in `/proc/self/maps`
using NLE's instance `dlpath`, then acquires only its already-loaded library
with `RTLD_NOLOAD`. Identical-seed simultaneous environments remain distinct.
The extra handle is explicitly `dlclose`d by the context manager.

Offsets come from the v1.3.0 release headers and an x86_64 GCC layout probe,
not a scan for plausible values. Every attach and live snapshot refuses output
unless native `u.ux/u.uy`, `u.uz` agree with the public observation, `rm` has the
expected size/offsets, true stair cells agree with exported stair coordinates,
and currently visible public stairs/walls/doors agree with native data. NetHack
retains glyphs for locations outside current vision; those remembered glyphs
are not evidence of current terrain. Current sight is read from `viz_array`
using `IN_SIGHT` from `vision.h`. Wall junctions are checked as wall terrain,
not identical subtypes: `wall_angle()` depends on `seenv`. A secret door's low
three flag bits are **wall mode**, not OPEN/BROKEN; mask `WM_MASK` before
decoding, and an unlocked SDOOR converts to CLOSED.

## Route analysis and limits

`analysis.analyze(snapshot)` reports the shortest route to the true main
downstairs, a route minimizing blocker cells then movement steps,
inclusion-minimal sets of barrier **classes** that permit some route, and a
route with each class individually held blocked: secret, locked, closed,
boulder, non-pet peaceful monster. Each route reports its actual blocker cells.
SEARCH coverage counts recorded before-action hero positions on the same level
within Chebyshev distance 1 of any secret cell on that snapshot's shortest
route, counting each action once. ASCII reserves hero/stairs/secret markers,
shows the recorded public map alongside, and overlays known glyphs on other
true cells.

This is geometry, **not combat, pushing, key possession, or opening-cost
simulation**. Solid terrain, trees, bars, water and lava are excluded; intact
doors (including open/secret doors) forbid diagonal entry/exit, and diagonal
movement cannot squeeze between two impassable terrain cells. Movement steps
are not NetHack turns. Different equally short paths may contain different
secret cells; the output includes the selected deterministic path.

**Unvisited levels' terrain is unreadable.** Only the currently loaded level is
read; the special table is metadata, not remote-level ground truth.

**Death frees heap data before NLE returns.** Direct terminal snapshots read
only static globals, static room arrays, and the special table copied while
alive: no trap/object/monster/special-chain dereference. Replay captures heap
collections immediately before the terminal action and, if still on the same
level, labels reused collections `last_live_before_terminal` with their step.
Those monsters may have moved during the last action; do not treat them as
post-death positions. The recorded map overlay is also last-live when death
zeros the public screen. Static terminal snapshots cannot be revalidated
against zeroed terminal statistics, so their `validation` field is null; the
attach and last-live snapshot were validated. No data is fabricated for a
missing collection.

Development method and acceptance-failure evidence:
[0047](../../../docs/notes/0047-native-truth-reader.md).
