"""List contiguous level stays over LIMIT game turns, with step mix (read-only)."""
import collections, json, sqlite3, sys
LIMIT = 1000
out = []
for arm, db in (a.split('=') for a in sys.argv[1:]):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    for rid, seed, outcome in c.execute("select id,suite_seed,outcome from runs").fetchall():
        rows = c.execute("""select json_extract(payload_json,'$.observation.step_index'),
          json_extract(payload_json,'$.observation.player.depth'),json_extract(payload_json,'$.observation.player.dungeon_number'),
          json_extract(payload_json,'$.observation.player.dungeon_level'),json_extract(payload_json,'$.observation.player.turn'),
          json_extract(payload_json,'$.selection.goal'),json_extract(payload_json,'$.selection.skill'),
          json_extract(payload_json,'$.action.name'),json_extract(payload_json,'$.selection.stuck_reason'),
          json_extract(payload_json,'$.selection.source')
          from events where run_id=? and kind='step' order by sequence""", (rid,)).fetchall()
        segs = []
        for r in rows:
            step, depth, dn, dl, turn = r[:5]
            if turn is None or (turn == 0 and segs):
                continue  # zeroed terminal screen
            if not segs or segs[-1]['level'] != (dn, dl):
                segs.append({'level': (dn, dl), 'depth': depth, 'rows': []})
            segs[-1]['rows'].append(r)
        for s in segs:
            t0, t1 = s['rows'][0][4], s['rows'][-1][4]
            if t1 - t0 <= LIMIT:
                continue
            point = next(r for r in s['rows'] if r[4] - t0 >= LIMIT)
            skills = collections.Counter(r[6] for r in s['rows'])
            acts = collections.Counter((r[7] or '').split('.')[0] + ('.' + r[7].split('.')[1] if r[7] and r[7].startswith('Command') or (r[7] or '').startswith('Misc') else '') for r in s['rows'])
            out.append({
                'arm': arm, 'run_id': rid, 'seed': seed, 'outcome': outcome,
                'dnum': s['level'][0], 'dlevel': s['level'][1], 'depth': s['depth'],
                'start_step': s['rows'][0][0], 'end_step': s['rows'][-1][0],
                'turns': t1 - t0, 'stall_step': point[0], 'stall_goal': json.loads(point[5]) if point[5] else None,
                'last_stay': s is segs[-1], 'steps': len(s['rows']),
                'skills': dict(skills.most_common()),
                'actions': dict(acts.most_common(6)),
                'stuck': dict(collections.Counter(r[8] for r in s['rows'] if r[8])),
                'fallback': sum(r[9] == 'model_fallback' for r in s['rows']),
            })
    c.close()
json.dump(out, open('stays.json', 'w'), indent=1)
print(len(out), 'stays')
for k in ('arm',):
    print(collections.Counter(o[k] for o in out))
print('levels', collections.Counter((o['arm'], o['dnum'], o['dlevel']) for o in out).most_common(20))
print('goal kinds', collections.Counter((o['stall_goal'] or {}).get('kind') for o in out))
print('skills total', sum((collections.Counter(o['skills']) for o in out), collections.Counter()).most_common(12))
