"""Classify each stalled stay from saved native snapshots (diagnosis only)."""
import collections, gzip, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'workspace-agent-play-nethack/_agents/skills/native-truth'))
from analysis import analyze  # noqa: E402

def goal_cell(snap, goal):
    kind = (goal or {}).get('kind')
    stairs = snap['stairs']
    if kind == 'traverse_stairs':
        t = goal['target']
        if t['connection'] == 'branch':
            s = stairs['sstairs']
            return (s['x'], s['y']) if s and s['up'] == (t['direction'] == 'up') else None, 'branch_' + t['direction']
        s = stairs['dnstair' if t['direction'] == 'down' else 'upstair']
        return (s['x'], s['y']) if s else None, 'main_' + t['direction']
    if kind == 'enter_temple':
        temples = [r for r in snap['rooms'] if r['kind'] == 'temple']
        if not temples:
            return None, 'temple'
        x0, x1, y0, y1 = temples[0]['bounds']  # struct mkroom order: lx, hx, ly, hy
        return ((x0 + x1) // 2, (y0 + y1) // 2), 'temple'
    if kind == 'approach_oracle':
        if snap.get('special_level') != 'oracle':
            return None, 'oracle_not_this_level'
        mons = snap.get('peaceful_monsters') or []
        if not mons:
            return None, 'oracle_unreadable'
        m = min(mons, key=lambda m: abs(m['x'] - 38) + abs(m['y'] - 11))
        return (m['x'], m['y']), 'oracle'
    return None, kind or 'none'

def classify(snap, goal):
    cell, label = goal_cell(snap, goal)
    if cell is None:
        return {'target': label, 'class': 'no_target_' + label}
    a = analyze(snap, cell)
    sets = a['minimal_blocker_sets']
    if label == 'oracle':  # the Oracle herself is a peaceful monster on the goal cell
        sets = [[c for c in s if c != 'peaceful_monster'] for s in sets]
        sets = [s for s in sets if not any(set(o) < set(s) for o in sets)]
    x, y = cell
    try:
        seen = snap["known_map"][y][x] != " "
    except IndexError:
        print("bad cell", label, cell, len(snap["known_map"]), len(snap["known_map"][min(y, 20)]))
        raise
    if not sets:
        cls = 'unreachable'
    elif [] in sets:
        cls = 'open_seen' if seen else 'open_unseen'
    else:
        common = set.intersection(*map(set, sets))
        cls = '+'.join(sorted(common)) if common else 'any_of:' + '|'.join('+'.join(s) for s in sets)
    return {'target': label, 'class': cls, 'seen': seen, 'sets': sets,
            'route_steps': (a['shortest'] or {}).get('steps'),
            'searches_on_level': None}

stays = json.load(open('stays.json'))
rows = []
for s in stays:
    path = Path('snapshots') / f"{s['arm']}-{s['run_id']}.json.gz"
    if not path.exists():
        rows.append({**s, 'class': 'missing_replay'}); continue
    result = json.load(gzip.open(path, 'rt'))
    snap = next(x for x in result['snapshots'] if x['step'] == s['stall_step'])
    c = classify(snap, s['stall_goal'])
    c['special_level'] = snap.get('special_level')
    c['searches_on_level'] = snap['analysis']['search_actions_on_level']
    sec = snap['analysis']['route_secret_cells']
    c['search_adjacent_main_route_secret'] = snap['analysis']['search_adjacent_to_route_secret']
    rows.append({**s, **c})
json.dump(rows, open('classified.json', 'w'), indent=1)
print('stays', len(rows))
for arm in ('mt', 'or', 'd5', None):
    sub = [r for r in rows if arm is None or r['arm'] == arm]
    print(arm or 'all', len(sub), collections.Counter(r['class'] for r in sub).most_common())
print('by target', collections.Counter((r.get('target'), r['class']) for r in rows).most_common(25))
