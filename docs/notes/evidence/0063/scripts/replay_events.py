"""Replay and log knowledge/abandon/search-goal transitions (read-only)."""
import json, sqlite3, sys
from nethack_agent.events import event_payload_from_json, EventKind, StepPayload
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import TaskSpec

db, seed, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rid, task = c.execute("select id, task from runs where suite_seed=?", (seed,)).fetchone()
task = TaskSpec.from_json(json.loads(task))
rows = c.execute("select kind, payload_json from events where run_id=? order by sequence", (rid,)).fetchall()
c.close()
prev = None
for kind, pj in rows:
    p = event_payload_from_json(EventKind(kind), json.loads(pj))
    if kind == 'run_started':
        replay = ExplorationReplay(task, p.legal_actions, p.observation); continue
    if not isinstance(p, StepPayload): continue
    s = p.observation.step_index
    if s > hi: break
    m = replay._dungeon.current
    state = (m.knowledge, len(m.abandoned_goals), m.search_round)
    if lo <= s and state != prev:
        print(s, m.level, m.position, 'kn', m.knowledge, 'nab', len(m.abandoned_goals), 'round', m.search_round, 'goal', m.search_goal, '|', p.selection.rationale[:70])
    prev = state
    replay.step(p)
