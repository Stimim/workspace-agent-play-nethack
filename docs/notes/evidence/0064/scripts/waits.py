"""Count blocker-wait steps per database (read-only)."""
import sqlite3, sys, collections, re
for db in sys.argv[1:]:
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    n = 0; who = collections.Counter()
    for (r,) in c.execute("select json_extract(payload_json,'$.selection.rationale') from events where kind='step'"):
        if r and r.startswith('Wait in place for'):
            n += 1; m = re.match(r'Wait in place for (?:the |a |an )?(.+?) blocking', r); who[m.group(1) if m else '?'] += 1
    c.close(); print(db.split('nethack-evidence/')[1], n, who.most_common(6))
