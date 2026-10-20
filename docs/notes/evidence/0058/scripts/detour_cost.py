"""Exact step/turn cost of each Mines detour: from the last step on the branch
level before descending to the first step back on it. Also whether a second
`>` was already displayed on the branch level when the Mines `>` was taken.
Usage: detour_cost.py DB REPORT.json"""
import json, sqlite3, sys
db, report = sys.argv[1], sys.argv[2]
r = json.load(open(report))
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
tot_steps = tot_turns = 0; n = 0; both_seen = 0
for case in r["case_results"]:
    for s in case["results"]:
        if not any(x["dungeon_number"] == 2 for x in s["metrics"]["levels_visited"]):
            continue
        rows = c.execute(
            "select sequence, json_extract(payload_json,'$.observation.player.dungeon_number'),"
            " json_extract(payload_json,'$.observation.player.turn'),"
            " json_extract(payload_json,'$.observation.step_index')"
            " from events where run_id=? and kind='step' order by sequence", (s["run_id"],)).fetchall()
        i = next(k for k, row in enumerate(rows) if row[1] == 2)
        j = next(k for k in range(i, len(rows)) if rows[k][1] == 0)
        before, back = rows[i - 1], rows[j]
        rowsjson = json.loads(c.execute("select json_extract(payload_json,'$.observation.map.rows') from events where run_id=? and sequence=?", (s["run_id"], before[0])).fetchone()[0])
        downs = sum(row.count(">") for row in rowsjson)
        both_seen += downs >= 2
        n += 1; tot_steps += back[3] - before[3]; tot_turns += back[2] - before[2]
        print(s["seed"], "steps", back[3] - before[3], "turns", back[2] - before[2], "'>' on map before descent", downs)
c.close()
print("runs", n, "total steps", tot_steps, "total turns", tot_turns, "both > visible", both_seen)
