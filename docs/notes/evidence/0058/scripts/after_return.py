"""Turns on the branch level before the Mines descent and after the return,
until the main downstairs was taken (or the run ended there).
Usage: after_return.py DB REPORT.json"""
import json, sqlite3, sys
db, report = sys.argv[1], sys.argv[2]
r = json.load(open(report))
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
for case in r["case_results"]:
    for s in case["results"]:
        if not any(x["dungeon_number"] == 2 for x in s["metrics"]["levels_visited"]):
            continue
        rows = c.execute(
            "select json_extract(payload_json,'$.observation.player.dungeon_number'),"
            " json_extract(payload_json,'$.observation.player.dungeon_level'),"
            " json_extract(payload_json,'$.observation.player.turn')"
            " from events where run_id=? and kind='step' order by sequence", (s["run_id"],)).fetchall()
        i = next(k for k, row in enumerate(rows) if row[0] == 2)
        b = rows[i - 1][1]
        start = next(k for k, row in enumerate(rows) if row[:2] == (0, b))
        j = next(k for k in range(i, len(rows)) if rows[k][0] == 0)
        end = next((k for k in range(j, len(rows)) if rows[k][:2] != (0, b)), len(rows) - 1)
        left = "descended" if rows[end][:2] == (0, b + 1) else f"ended {s['outcome']} at {rows[end][:2]}"
        print(s["seed"], "b", b, "turns before", rows[i-1][2] - rows[start][2], "after return", rows[end][2] - rows[j][2], left)
c.close()
