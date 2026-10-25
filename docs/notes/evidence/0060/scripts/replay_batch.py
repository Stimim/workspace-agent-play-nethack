"""Replay each stalled run once; save native snapshots at the stall and end of each stay."""
import collections, gzip, json, sys, traceback
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'workspace-agent-play-nethack/_agents/skills/native-truth'))
from replay import replay  # noqa: E402

DBS = {k: Path.home() / f'nethack-evidence/0052/0052-base-{k}-reg/runs.sqlite3' for k in ('mt', 'or', 'd5')}
OUT = Path('snapshots'); OUT.mkdir(exist_ok=True)

def work(job):
    arm, run_id, steps = job
    target = OUT / f'{arm}-{run_id}.json.gz'
    if target.exists():
        return arm, run_id, 'cached'
    try:
        result = replay(DBS[arm], run_id=run_id, at=tuple(str(s) for s in sorted(steps)))
        with gzip.open(target, 'wt') as f:
            json.dump(result, f)
        return arm, run_id, 'ok'
    except Exception as error:  # record and continue; never fabricate
        (OUT / f'{arm}-{run_id}.error.txt').write_text(traceback.format_exc())
        return arm, run_id, f'error: {error!r}'

if __name__ == '__main__':
    stays = json.load(open('stays.json'))
    jobs = collections.defaultdict(set)
    for s in stays:
        jobs[s['arm'], s['run_id']].update((s['stall_step'], s['end_step']))
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 5) as pool:
        for i, result in enumerate(pool.imap_unordered(work, [(a, r, st) for (a, r), st in jobs.items()]), 1):
            print(i, len(jobs), *result, flush=True)
