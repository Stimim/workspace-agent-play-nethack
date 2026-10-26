"""Replay each stalled stay (one level stay > 1,000 turns) of the shipped policy's regression runs; snapshot its last step (diagnosis only)."""
import gzip, json, sqlite3, sys, traceback
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'workspace-agent-play-nethack/_agents/skills/native-truth'))
from replay import replay  # noqa: E402
Q = Path.home() / 'nethack-evidence/0061q'
DBS = {a: Q / f'cand-{a}-reg/runs.sqlite3' for a in ('mt', 'or')}
OUT = Path.home() / 'nethack-evidence/0062/diag/snapshots3'; OUT.mkdir(parents=True, exist_ok=True)

def stays(arm):
    c = sqlite3.connect(f'file:{DBS[arm]}?mode=ro', uri=True)
    jobs = []
    for rid, seed in c.execute('select id, suite_seed from runs').fetchall():
        rows = c.execute("""select json_extract(payload_json,'$.observation.step_index'), json_extract(payload_json,'$.observation.player.dungeon_number'),
          json_extract(payload_json,'$.observation.player.depth'), json_extract(payload_json,'$.observation.player.turn'), json_extract(payload_json,'$.selection.goal'), json_extract(payload_json,'$.action.name')
          from events where run_id=? and kind='step' order by sequence""", (rid,)).fetchall()
        segs = []
        for i, dn, d, t, g, a in rows:
            if d is None: continue
            if not segs or segs[-1]['k'] != (dn, d): segs.append({'k': (dn, d), 't0': t, 's0': i, 'first_search': None, 'stall_step': None})
            e = segs[-1]; e.update(t1=t, s1=i, goal=g)
            if a == 'Command.SEARCH' and e['first_search'] is None: e['first_search'] = i; e['first_search_goal'] = g
            if e['stall_step'] is None and t - e['t0'] > 1000: e['stall_step'] = i; e['stall_goal'] = g
        if not segs: continue
        L = max(segs, key=lambda e: e['t1'] - e['t0'])
        if L['t1'] - L['t0'] > 1000:
            jobs.append({'arm': arm, 'run_id': rid, 'seed': seed, 'level': L['k'], 'turns': L['t1'] - L['t0'], 'start_step': L['s0'], 'end_step': L['s1'], 'goal': json.loads(L['goal']) if L['goal'] else None,
              'first_search': L['first_search'], 'first_search_goal': json.loads(L['first_search_goal']) if L.get('first_search_goal') else None,
              'stall_step': L['stall_step'], 'stall_goal': json.loads(L['stall_goal']) if L.get('stall_goal') else None})
    c.close()
    return jobs

def work(job):
    target = OUT / f"{job['arm']}-{job['seed']}.json.gz"
    if target.exists(): return job['arm'], job['seed'], 'cached'
    try:
        result = replay(DBS[job['arm']], run_id=job['run_id'], at=tuple(str(x) for x in sorted({job['first_search'], job['stall_step'], job['end_step']} - {None})))
        result['stay'] = job
        with gzip.open(target, 'wt') as f: json.dump(result, f)
        return job['arm'], job['seed'], 'ok'
    except Exception as error:
        (OUT / f"{job['arm']}-{job['seed']}.error.txt").write_text(traceback.format_exc())
        return job['arm'], job['seed'], f'error: {error!r}'

if __name__ == '__main__':
    jobs = stays('mt') + stays('or')
    json.dump(jobs, open(OUT.parent / 'stays.json', 'w'), indent=1)
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as pool:
        for i, r in enumerate(pool.imap_unordered(work, jobs), 1): print(i, len(jobs), *r, flush=True)
