"""Classify each stalled stay by whether the search found / could find the hidden cell on the fewest-blocker route (diagnosis only)."""
import collections, gzip, json, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'workspace-agent-play-nethack/_agents/skills/native-truth'))
sys.path.insert(0, str(Path.home() / 'nethack-evidence/3a-diagnosis'))
from analysis import analyze  # noqa: E402
from classify import goal_cell  # noqa: E402
D = Path.home() / 'nethack-evidence/0062/diag'
Q = Path.home() / 'nethack-evidence/0061q'
WALK = set('.#<>{_')

def searches(arm, run_id, s0, s1):
    c = sqlite3.connect(f'file:{Q}/cand-{arm}-reg/runs.sqlite3?mode=ro', uri=True)
    rows = c.execute("""select json_extract(payload_json,'$.observation.player.x'), json_extract(payload_json,'$.observation.player.y')
      from events where run_id=? and kind='step' and json_extract(payload_json,'$.action.name')='Command.SEARCH'
      and json_extract(payload_json,'$.observation.step_index') between ? and ?""", (run_id, s0, s1)).fetchall()
    c.close()
    return collections.Counter(rows)

def classify_one(job, snap, goal, cnt):
    cell, label = goal_cell(snap, goal)
    rec = {'step': snap['step'], 'target': label}
    if cell is None:
        rec['class'] = 'no_target_' + label; return rec
    a = analyze(snap, cell)
    route = a.get('fewest_blocker_cells')
    if route is None:
        rec['class'] = 'unreachable'; return rec
    secrets = [(b['x'], b['y']) for b in route['blockers'] if 'secret' in b['classes']]
    others = sorted({c for b in route['blockers'] for c in b['classes'] if c != 'secret'})
    km = snap['known_map']
    def known(p):
        x, y = p
        return 0 <= y < len(km) and 0 <= x < len(km[y]) and km[y][x] != ' '
    unknown_path = sum(not known(tuple(p)) for p in route['path'])
    rec.update(route_steps=route['steps'], secrets=secrets, other_barriers=others, unknown_path_cells=unknown_path)
    if not secrets:
        rec['class'] = ('other_barrier' if others else 'seen_not_taken' if unknown_path == 0 else 'unexplored_open_route')
        return rec
    first = secrets[0]
    near = sum(n for (x, y), n in cnt.items() if max(abs(x - first[0]), abs(y - first[1])) <= 1)
    stands = [(first[0] + dx, first[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy)]
    ks = [p for p in stands if known(p) and km[p[1]][p[0]] in WALK]
    rec.update(first_secret=first, searches_next_to_first=near, known_stands=len(ks))
    rec['class'] = ('searched_next_to_it' if near >= 30 else 'stand_known_not_searched' if ks else 'stand_not_known')
    return rec

out = []
for job in json.load(open(D / 'stays.json')):
    f = D / 'snapshots3' / f"{job['arm']}-{job['seed']}.json.gz"
    rec = {k: job[k] for k in ('arm', 'seed', 'level', 'turns')}
    if not f.exists():
        rec['class'] = 'replay_missing'; out.append(rec); continue
    snaps = {s['step']: s for s in json.load(gzip.open(f, 'rt'))['snapshots']}
    cnt = searches(job['arm'], job['run_id'], job['start_step'], job['end_step'])
    rec['searches'] = sum(cnt.values()); rec['stands'] = len(cnt)
    for phase, step_key, goal_key in (('first_search', 'first_search', 'first_search_goal'), ('stall', 'stall_step', 'stall_goal'), ('end', 'end_step', 'goal')):
        st = job.get(step_key)
        if st is not None and st in snaps:
            rec[phase] = classify_one(job, snaps[st], job.get(goal_key), cnt)
    rec['class'] = (rec.get('stall') or rec.get('end') or {}).get('class')
    out.append(rec)
json.dump(out, open(D / 'classified.json', 'w'), indent=1)
print(collections.Counter(r['class'] for r in out))
tot = collections.Counter()
for r in out: tot[r['class']] += r['turns']
print('turns', tot)
for r in sorted(out, key=lambda r: -r['turns']):
    ph = lambda k: (lambda d: f"{d.get('target')}:{d.get('class')} s{d.get('secrets')} o{d.get('other_barriers')} u{d.get('unknown_path_cells')} n{d.get('searches_next_to_first')}" if d else '-')(r.get(k))
    print(r['arm'], r['seed'], r['level'], r['turns'], 'srch', r.get('searches'), r.get('stands'), '| FIRST', ph('first_search'), '| STALL', ph('stall'), '| END', ph('end'))
