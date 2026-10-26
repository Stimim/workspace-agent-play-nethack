"""Search-step profile of stalled stays (read-only replay, diagnosis only).

Usage: search_profile.py ARM DB STAYS_JSON OUT_JSONL
For each stay of ARM in note 0062's stalled-stays.json, replays the run and,
at every hidden-passage search step (not blocker waits) inside the stay, records the search round, how many
stands still score as candidates, and whether the hero's stand targets the
stay's true first hidden cell (from the stall-step native-truth snapshot).
"""
import json, sqlite3, sys, collections
from nethack_agent.events import event_payload_from_json, EventKind, StepPayload
from nethack_agent.replay import ExplorationReplay
from nethack_agent.tasks import TaskSpec
from nethack_agent.navigation import route_tree, CellKind
from nethack_agent import skills as S

arm, db, stays_path, out_path = sys.argv[1:5]
stays = [s for s in json.load(open(stays_path))['stays'] if s['arm'] == arm]

def candidates(m):
    tree = route_tree(m)
    budget = S.SEARCHES_PER_ROUND * (m.search_round + 1)
    dens = S._UnexploredDensity(m, S.SEARCH_DENSITY_RADIUS)
    n = 0
    for p in tree.distances:
        if p in m.monsters or m.kind(p) is CellKind.CLOSED_DOOR or p in m.abandoned_goals:
            continue
        t = [q for q in S._search_targets(m, p) if m.search_coverage.get(q, 0) < budget]
        if sum(dens.around(q) for q in t) >= S.MIN_SEARCH_SCORE:
            n += 1
    return n

c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
with open(out_path, 'w') as out:
    for st in stays:
        rid, task = c.execute("select id, task from runs where suite_seed=?", (st['seed'],)).fetchone()
        task = TaskSpec.from_json(json.loads(task))
        lo, hi = st['steps']['start_step'], st['steps']['end_step']
        secret = st['phases']['stall'].get('first_secret')
        secret = tuple(secret) if secret else None
        replay = None
        prof = collections.Counter()
        rounds = collections.Counter()
        stands = collections.Counter()
        for kind, pj in c.execute("select kind, payload_json from events where run_id=? order by sequence", (rid,)):
            p = event_payload_from_json(EventKind(kind), json.loads(pj))
            if kind == 'run_started':
                replay = ExplorationReplay(task, p.legal_actions, p.observation); continue
            if not isinstance(p, StepPayload):
                continue
            s = p.observation.step_index
            if s > hi:
                break
            if (s >= lo and p.action is not None and p.action.name == 'Command.SEARCH'
                    and p.selection.rationale.startswith('Search for hidden passages')):
                m = replay._dungeon.current
                n = candidates(m)
                bucket = '1' if n <= 1 else '2-5' if n <= 5 else '6+'
                r = m.search_round
                rb = '0' if r == 0 else '1' if r == 1 else '2-9' if r < 10 else '10+'
                prof[f'cands_{bucket}'] += 1
                rounds[f'round_{rb}'] += 1
                stands[m.position] += 1
                if secret and max(abs(m.position[0] - secret[0]), abs(m.position[1] - secret[1])) <= 1:
                    prof['next_to_secret'] += 1
            replay.step(p)
        rec = {'arm': arm, 'seed': st['seed'], 'level': st['level'], 'turns': st['turns'],
               'stall_class': st['phases']['stall']['class'], 'searches': sum(rounds.values()),
               'stands': len(stands), 'top_stand': stands.most_common(1), **prof, **rounds}
        out.write(json.dumps(rec) + '\n'); out.flush()
c.close()
