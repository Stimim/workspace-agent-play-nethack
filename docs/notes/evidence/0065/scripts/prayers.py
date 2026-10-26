"""Prayers and their outcome messages per run, with stall-stay overlap (read-only).

Usage: prayers.py DB [STAYS_JSON ARM]
Prints, per run, each Command.PRAY step with turn, level and the messages of
the next few steps.
"""
import json, sqlite3, sys, collections
db = sys.argv[1]
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
runs = c.execute("select id, suite_seed from runs").fetchall()
tot = collections.Counter()
per = {}
for rid, seed in runs:
    rows = c.execute("""select json_extract(payload_json,'$.observation.step_index'), json_extract(payload_json,'$.observation.player.turn'),
        json_extract(payload_json,'$.observation.player.dungeon_level'), json_extract(payload_json,'$.action.name'),
        json_extract(payload_json,'$.observation.message'), json_extract(payload_json,'$.selection.rationale')
        from events where run_id=? and kind='step' order by sequence""", (rid,)).fetchall()
    out = []
    for i, r in enumerate(rows):
        if r[3] == 'Command.PRAY':
            msgs = ' | '.join(m for m in (x[4] for x in rows[i + 1:i + 6]) if m)
            kind = ('too_soon' if 'displeased' in msgs or 'You feel guilty' in msgs or 'smiting' in msgs.lower() or 'lightning' in msgs.lower() or 'foolish' in msgs
                    else 'fixed' if any(k in msgs for k in ('hopeful feeling', 'You feel much better', 'Your stomach feels content', 'reassured', 'feel a feeling of hope'))
                    else 'other')
            tot[kind] += 1
            out.append((r[0], r[1], r[2], kind, (r[5] or '')[:60], msgs[:160]))
    if out:
        per[seed] = out
c.close()
print(json.dumps({'totals': tot, 'runs': per}))
