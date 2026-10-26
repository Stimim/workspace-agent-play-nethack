"""Per stalled stay: steps by mechanism (search, travel to a search spot, flipped spot targets, waits for a blocking monster)."""
import json, sqlite3, re, collections, sys
from pathlib import Path
D = Path.home() / 'nethack-evidence/0062/diag'; Q = Path.home() / 'nethack-evidence/0061q'
res = []; seen = set()
for j in json.load(open(D / 'stays.json')):
    k = (j['seed'], tuple(j['level']), j['turns'])
    if k in seen: continue
    seen.add(k)
    c = sqlite3.connect(f"file:{Q}/cand-{j['arm']}-reg/runs.sqlite3?mode=ro", uri=True)
    rows = c.execute("""select json_extract(payload_json,'$.selection.rationale'), json_extract(payload_json,'$.action.name') from events where run_id=? and kind='step'
      and json_extract(payload_json,'$.observation.step_index') between ? and ? order by sequence""", (j['run_id'], j['start_step'], j['end_step'])).fetchall()
    c.close()
    m = collections.Counter(); last = None; waiters = collections.Counter()
    for r, a in rows:
        r = r or ''
        if r.startswith('Search for hidden'): m['search'] += 1; last = None
        elif r.startswith('Move to search spot'):
            m['travel'] += 1
            spot = re.search(r'spot \((\d+, \d+)\)', r).group(1)
            if last is not None and spot != last: m['flip'] += 1
            last = spot
        elif r.startswith('Wait in place for the'):
            m['wait_blocker'] += 1; waiters[re.search(r'for the (.+?) blocking', r).group(1)] += 1
        elif 'a monster currently blocks' in r: m['blocked_approach'] += 1
        else: m['other'] += 1
    res.append({'arm': j['arm'], 'seed': j['seed'], 'level': j['level'], 'turns': j['turns'], 'steps': len(rows), **m, 'waiters': dict(waiters.most_common(3))})
json.dump(res, open(D / 'mechanisms.json', 'w'), indent=1)
tot = collections.Counter()
for r in res:
    for key in ('search', 'travel', 'flip', 'wait_blocker', 'blocked_approach', 'other', 'steps'): tot[key] += r.get(key, 0)
print(len(res), 'stays', dict(tot))
print('stays with flips>=20:', [(r['seed'], r['flip'], r['travel']) for r in res if r.get('flip', 0) >= 20])
print('stays with blocker waits>=200:', [(r['seed'], r['wait_blocker'], r['waiters']) for r in res if r.get('wait_blocker', 0) >= 200])
