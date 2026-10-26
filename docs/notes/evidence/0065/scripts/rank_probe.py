"""Rank of the stands next to the true hidden cell in the search skill's scoring (read-only, diagnosis only).

Usage: rank_probe.py DB SEED STEP SX SY [STEP ...]
Rebuilds LevelMemory from stored events with ExplorationReplay and, at each
STEP, scores every reachable stand the way skills._search does.
"""
import json, sqlite3, sys
from nethack_agent.events import event_payload_from_json, EventKind, StepPayload
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import TaskSpec
from nethack_agent.navigation import route_tree, CellKind
from nethack_agent import skills as S

db, seed, sx, sy = sys.argv[1], int(sys.argv[2]), int(sys.argv[4]), int(sys.argv[5])
steps = {int(sys.argv[3])} | {int(a) for a in sys.argv[6:]}
secret = (sx, sy)
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rid, task = c.execute("select id, task from runs where suite_seed=?", (seed,)).fetchone()
task = TaskSpec.from_json(json.loads(task))
rows = c.execute("select kind, payload_json from events where run_id=? order by sequence", (rid,)).fetchall()
c.close()

def probe(m, step):
    tree = route_tree(m)
    budget = S.SEARCHES_PER_ROUND * (m.search_round + 1)
    dens = S._UnexploredDensity(m, S.SEARCH_DENSITY_RADIUS)
    scored = []
    for p, d in tree.distances.items():
        if p in m.monsters or m.kind(p) is CellKind.CLOSED_DOOR or p in m.abandoned_goals:
            continue
        all_t = S._search_targets(m, p)
        t = [q for q in all_t if m.search_coverage.get(q, 0) < budget]
        sc = sum(dens.around(q) for q in t)
        if sc < S.MIN_SEARCH_SCORE:
            continue
        scored.append((-(sc - S.SEARCH_DISTANCE_WEIGHT * d), d, p[1], p[0], p, sc, secret in all_t, secret in t))
    scored.sort()
    rank = {e[4]: i for i, e in enumerate(scored)}
    stands = [(sx + dx, sy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
    out = {'step': step, 'hero': m.position, 'goal': m.search_goal, 'round': m.search_round,
           'candidates': len(scored), 'secret_kind_known': m.kind(secret).name,
           'secret_coverage': m.search_coverage.get(secret, 0),
           'top': [(e[4], e[5], e[1], e[6]) for e in scored[:3]], 'stands': []}
    for p in stands:
        if not (0 <= p[0] < m.width and 0 <= p[1] < m.height):
            continue
        k = m.kind(p)
        if k in (CellKind.UNKNOWN,) or not m.passable(p) and k is not CellKind.CLOSED_DOOR:
            continue
        all_t = S._search_targets(m, p)
        out['stands'].append({'stand': p, 'kind': k.name, 'reachable': p in tree.distances,
                              'dist': tree.distances.get(p), 'targets_secret': secret in all_t,
                              'n_targets': len(all_t), 'rank': rank.get(p),
                              'score': next((e[5] for e in scored if e[4] == p), None)})
    print(json.dumps(out, default=str))

replay = None
for kind, pj in rows:
    p = event_payload_from_json(EventKind(kind), json.loads(pj))
    if kind == 'run_started':
        replay = ExplorationReplay(task, p.legal_actions, p.observation); continue
    if not isinstance(p, StepPayload):
        continue
    s = p.observation.step_index
    if s in steps:
        probe(replay._dungeon.current, s)
    if s >= max(steps):
        break
    replay.step(p)
