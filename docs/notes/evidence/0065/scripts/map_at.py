"""Print the agent's LevelMemory map around a point at a step (read-only replay)."""
import json, sqlite3, sys
from nethack_agent.events import event_payload_from_json, EventKind, StepPayload
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import TaskSpec
from nethack_agent.navigation import route_tree, CellKind
db, seed, step = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
x0, x1, y0, y1 = [int(v) for v in sys.argv[4].split(',')]
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rid, task = c.execute("select id, task from runs where suite_seed=?", (seed,)).fetchone()
task = TaskSpec.from_json(json.loads(task))
rows = c.execute("select kind, payload_json from events where run_id=? order by sequence", (rid,)).fetchall()
c.close()
CH = {CellKind.UNKNOWN: ' ', CellKind.WALL: '#', CellKind.FLOOR: '.', CellKind.CORRIDOR: ':', CellKind.CLOSED_DOOR: '+',
      CellKind.OPEN_DOOR: '|', CellKind.DOORWAY: 'o'}
for kind, pj in rows:
    p = event_payload_from_json(EventKind(kind), json.loads(pj))
    if kind == 'run_started':
        replay = ExplorationReplay(task, p.legal_actions, p.observation); continue
    if not isinstance(p, StepPayload):
        continue
    if p.observation.step_index == step:
        m = replay._dungeon.current
        tree = route_tree(m)
        print('hero', m.position, 'locked', sorted(m.locked_doors), 'boulders', sorted(m.boulders), 'monsters', {k: v.name for k, v in m.monsters.items()})
        for y in range(y0, y1 + 1):
            row = ''
            for x in range(x0, x1 + 1):
                ch = '@' if (x, y) == m.position else 'M' if (x, y) in m.monsters else '0' if (x, y) in m.boulders else CH.get(m.kind((x, y)), '?')
                if ch in '.:' and (x, y) not in tree.distances:
                    ch = ch.replace('.', ',').replace(':', ';')
                row += ch
            print(f'{y:2d} {row}')
        print('kinds', sorted({k.name for k in CellKind}))
        break
    replay.step(p)
