"""Spot flips (note 0062 definition) in each run's longest level stay over 1,000 turns.

Usage: pingpong.py DB [DB...]; prints per-seed flips/travel/search for stalled stays.
"""
import json, re, sqlite3, sys
for db in sys.argv[1:]:
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    runs = c.execute("select id, suite_seed from runs").fetchall()
    total = {'stays': 0, 'flip': 0, 'travel': 0, 'search': 0, 'pp20': []}
    for rid, seed in runs:
        rows = c.execute("""select json_extract(payload_json,'$.observation.player.dungeon_number'), json_extract(payload_json,'$.observation.player.dungeon_level'),
            json_extract(payload_json,'$.observation.player.turn'), json_extract(payload_json,'$.selection.rationale') from events where run_id=? and kind='step' order by sequence""", (rid,)).fetchall()
        stays = []; start = 0
        for i in range(1, len(rows) + 1):
            if i == len(rows) or rows[i][:2] != rows[start][:2]:
                stays.append((rows[i - 1][2] - rows[start][2], start, i)); start = i
        if not stays: continue
        turns, a, b = max(stays)
        if turns <= 1000: continue
        flip = travel = search = 0; last = None
        for _, _, _, r in rows[a:b]:
            r = r or ''
            if r.startswith('Search for hidden'): search += 1; last = None
            elif r.startswith('Move to search spot'):
                travel += 1; spot = re.search(r'spot \((\d+, \d+)\)', r).group(1)
                if last is not None and spot != last: flip += 1
                last = spot
        total['stays'] += 1; total['flip'] += flip; total['travel'] += travel; total['search'] += search
        if flip >= 20: total['pp20'].append((seed, flip))
        print(db.split('/')[-2], seed, rows[a][:2], 'turns', turns, 'flip', flip, 'travel', travel, 'search', search)
    c.close()
    print('TOTAL', db, json.dumps(total))
