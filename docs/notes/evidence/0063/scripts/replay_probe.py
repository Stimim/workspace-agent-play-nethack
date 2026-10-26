"""Rebuild LevelMemory from stored events (read-only) and probe search state."""
import json, sqlite3, sys
from nethack_agent.events import event_payload_from_json, EventKind, StepPayload
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import TaskSpec
from nethack_agent.navigation import route_tree

db, seed = sys.argv[1], int(sys.argv[2])
lo, hi = int(sys.argv[3]), int(sys.argv[4])
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rid, task = c.execute("select id, task from runs where suite_seed=?", (seed,)).fetchone()
task = TaskSpec.from_json(json.loads(task))
rows = c.execute("select kind, payload_json from events where run_id=? order by sequence", (rid,)).fetchall()
c.close()
replay = None
for kind, pj in rows:
    p = event_payload_from_json(EventKind(kind), json.loads(pj))
    if kind == 'run_started':
        replay = ExplorationReplay(task, p.legal_actions, p.observation); continue
    if not isinstance(p, StepPayload): continue
    s = p.observation.step_index
    m = replay._dungeon.current
    if lo <= s <= hi:
        tree = route_tree(m)
        sel = p.selection
        d = sel.intent.destination if sel.intent else None
        print(s, m.position, 'goal', m.search_goal, 'in_tree', m.search_goal in tree.distances if m.search_goal else None,
              'stale', m.stale_moves, 'kn', m.knowledge, 'aband', sorted(m.abandoned_goals),
              'mons', {k: v.name for k, v in m.monsters.items()}, '->', d and (d.kind.value, d.x, d.y), sel.rationale[:50])
    replay.step(p)
    if s > hi: break
