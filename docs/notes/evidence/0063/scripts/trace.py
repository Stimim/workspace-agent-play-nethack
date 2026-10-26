"""Dump compact per-step trace of one run: step turn dlvl x y skill dest rationale."""
import sqlite3, json, sys
db, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rid = c.execute("select id from runs where suite_seed=?", (seed,)).fetchone()[0]
with open(out, 'w') as f:
    for (pj,) in c.execute("select payload_json from events where run_id=? and kind='step' order by sequence", (rid,)):
        p = json.loads(pj); o = p['observation']; pl = o['player']; s = p.get('selection') or {}
        d = ((s.get('intent') or {}).get('destination') or {})
        f.write(json.dumps([o['step_index'], pl['turn'], pl['dungeon_number'], pl['dungeon_level'], pl['x'], pl['y'], s.get('skill'), d.get('kind'), d.get('x'), d.get('y'), s.get('rationale'), (p.get('action') or {}).get('name'), o['message'][:80]]) + '\n')
c.close()
