"""First step where baseline and candidate selections differ for a seed (read-only)."""
import json, sqlite3, sys
def load(db, seed):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    rid = c.execute("select id from runs where suite_seed=?", (seed,)).fetchone()[0]
    rows = c.execute("""select json_extract(payload_json,'$.observation.step_index'), json_extract(payload_json,'$.observation.player.turn'),
      json_extract(payload_json,'$.observation.player.dungeon_number'), json_extract(payload_json,'$.observation.player.dungeon_level'),
      json_extract(payload_json,'$.observation.player.x'), json_extract(payload_json,'$.observation.player.y'),
      json_extract(payload_json,'$.observation.player.hunger'), json_extract(payload_json,'$.observation.player.hit_points'),
      json_extract(payload_json,'$.selection.rationale'), json_extract(payload_json,'$.observation.message') from events where run_id=? and kind='step' order by sequence""", (rid,)).fetchall()
    c.close(); return rows
b, cnd, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
B, C = load(b, seed), load(cnd, seed)
for i, (x, y) in enumerate(zip(B, C)):
    if x[8] != y[8]:
        print('diverge at', i)
        for r in B[max(0,i-3):i+4]: print(' B', r)
        for r in C[max(0,i-3):i+4]: print(' C', r)
        break
else: print('no divergence in common prefix', len(B), len(C))
