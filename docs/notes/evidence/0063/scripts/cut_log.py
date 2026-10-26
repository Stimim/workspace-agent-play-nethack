"""Log monster_cut_cells growth during a candidate run replay (read-only)."""
import json, sqlite3, sys
from nethack_agent.events import event_payload_from_json, EventKind, StepPayload
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import TaskSpec
db, seed, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rid, task = c.execute("select id, task from runs where suite_seed=?", (seed,)).fetchone()
task = TaskSpec.from_json(json.loads(task))
rows = c.execute("select kind, payload_json from events where run_id=? order by sequence", (rid,)).fetchall()
c.close()
prev = 0
for kind, pj in rows:
    p = event_payload_from_json(EventKind(kind), json.loads(pj))
    if kind == 'run_started':
        replay = ExplorationReplay(task, p.legal_actions, p.observation); continue
    if not isinstance(p, StepPayload): continue
    s = p.observation.step_index
    if s > hi: break
    replay.step(p)
    m = replay._dungeon.current
    n = len(m.monster_cut_cells)
    if n != prev:
        xs = sorted(m.monster_cut_cells)
        print(s, m.level.dungeon_level, m.position, 'goal', m.search_goal, 'cut', n, 'mons', {k: (v.name, m.hostile_blocker(k) is not None) for k, v in m.monsters.items()}, 'sample', xs[:3], xs[-3:])
    prev = n
