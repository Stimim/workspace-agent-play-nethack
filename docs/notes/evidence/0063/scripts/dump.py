import sqlite3, json, sys
db, seed = sys.argv[1], int(sys.argv[2]); steps=[int(s) for s in sys.argv[3].split(',')]
y0,y1,x0,x1=[int(v) for v in sys.argv[4].split(',')]
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rid = c.execute("select id from runs where suite_seed=?", (seed,)).fetchone()[0]
for (pj,) in c.execute("select payload_json from events where run_id=? and kind='step' order by sequence", (rid,)):
    p=json.loads(pj); o=p['observation']
    if o['step_index'] in steps:
        pl=o['player']; print(o['step_index'], pl['turn'], (pl['x'],pl['y']), pl['conditions'], repr(o['message']), p['action']['name'], p['selection']['rationale'])
        print('    '+''.join(str(x%10) for x in range(x0,x1)))
        for y in range(y0,y1): print(f'{y:3d} '+o['map']['rows'][y][x0:x1])
        if len(sys.argv)>5: print(json.dumps(p['selection']['intent'])[:600])
c.close()
