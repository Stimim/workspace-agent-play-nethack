"""Classify why a committed search spot changed before arrival (read-only replay).

Usage: classify_flips.py DB SEED [SEED...]
"""
import json, sqlite3, sys
from collections import Counter
from nethack_agent.events import event_payload_from_json, EventKind, StepPayload
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import TaskSpec
from nethack_agent.navigation import route_tree
from nethack_agent.decision import DestinationKind

db = sys.argv[1]
for seed in map(int, sys.argv[2:]):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    rid, task = c.execute("select id, task from runs where suite_seed=?", (seed,)).fetchone()
    task = TaskSpec.from_json(json.loads(task))
    rows = c.execute("select kind, payload_json from events where run_id=? order by sequence", (rid,)).fetchall()
    c.close()
    causes = Counter(); blockers = Counter(); last = None; between = Counter()
    for kind, pj in rows:
        p = event_payload_from_json(EventKind(kind), json.loads(pj))
        if kind == 'run_started':
            replay = ExplorationReplay(task, p.legal_actions, p.observation); continue
        if not isinstance(p, StepPayload): continue
        m = replay._dungeon.current
        d = p.selection.intent.destination if p.selection.intent else None
        g = m.search_goal
        if g is None and last is not None and last != m.position and d is not None and d.kind is DestinationKind.SEARCH_SPOT and (d.x, d.y) != last:
            causes['cleared-by-other'] += 1; between[prev_other] += 1
        if d is not None and d.kind is DestinationKind.SEARCH_SPOT:
            last = (d.x, d.y)
        else:
            prev_other = p.selection.rationale[:40]
        if g is not None and g != m.position and d is not None and d.kind is DestinationKind.SEARCH_SPOT and (d.x, d.y) != g:
            tree = route_tree(m)
            if g in m.abandoned_goals: cause = 'abandoned'
            elif g not in tree.distances:
                through = route_tree(m, through_monsters=True)
                if g in through.distances:
                    cause = 'monster-cut'
                    for pt in through.route(g):
                        if pt in m.monsters: blockers[m.monsters[pt].name] += 1; break
                else: cause = 'unreachable'
            else: cause = 'evaluate-none/other'
            causes[cause] += 1
        replay.step(p)
    print(seed, dict(causes), dict(blockers), between.most_common(4), flush=True)
