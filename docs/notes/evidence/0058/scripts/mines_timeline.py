"""Per-run level timeline for runs that entered the Gnomish Mines (dnum 2).

Usage: mines_timeline.py DB REPORT.json
Opens DB read-only and uses json_extract to avoid loading map payloads.
"""
import json, sqlite3, sys
db, report = sys.argv[1], sys.argv[2]
r = json.load(open(report))
runs = []
for case in r["case_results"]:
    for s in case["results"]:
        runs.append((case["case_id"], s["seed"], s["run_id"], s["outcome"], s["metrics"]))
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
out = []
for case, seed, rid, outcome, m in runs:
    if not any(x["dungeon_number"] == 2 for x in m["levels_visited"]):
        continue
    rows = c.execute(
        "select json_extract(payload_json,'$.observation.step_index'),"
        " json_extract(payload_json,'$.observation.player.dungeon_number'),"
        " json_extract(payload_json,'$.observation.player.dungeon_level'),"
        " json_extract(payload_json,'$.observation.player.turn'),"
        " json_extract(payload_json,'$.observation.player.hunger'),"
        " json_extract(payload_json,'$.observation.player.hit_points'),"
        " json_extract(payload_json,'$.observation.player.experience_level')"
        " from events where run_id=? and kind='step' order by sequence", (rid,)).fetchall()
    segs = []
    for st, dn, dl, turn, hun, hp, xl in rows:
        if not segs or segs[-1]["lvl"] != (dn, dl):
            segs.append({"lvl": (dn, dl), "step0": st, "turn0": turn, "steps": 0, "hunger0": hun, "xl0": xl})
        segs[-1]["steps"] += 1; segs[-1]["turn1"] = turn
    final = segs[-1]["lvl"]
    mines_steps = sum(s["steps"] for s in segs if s["lvl"][0] == 2)
    mines_turns = sum(s["turn1"] - s["turn0"] for s in segs if s["lvl"][0] == 2)
    first = next(i for i, s in enumerate(segs) if s["lvl"][0] == 2)
    branch_level = segs[first - 1]["lvl"]
    rec = {"case": case, "seed": seed, "outcome": outcome,
           "success": m["objective_legs_completed"] >= 1,
           "death_cause": m.get("death_cause"), "hunger_at_death": m.get("hunger_at_death"),
           "branch_dlvl": branch_level[1], "mines_entries": sum(1 for s in segs if s["lvl"][0] == 2),
           "mines_steps": mines_steps, "mines_turns": mines_turns,
           "entry_turn": segs[first]["turn0"], "xl_at_entry": segs[first]["xl0"],
           "final_level": final, "died_in_mines": outcome == "death" and final[0] == 2,
           "max_main_dlvl": max(s["lvl"][1] for s in segs if s["lvl"][0] == 0),
           "path": [f"{s['lvl'][0]}:{s['lvl'][1]}" for s in segs]}
    out.append(rec)
c.close()
json.dump(out, open(sys.argv[3], "w"), indent=1)
for x in out:
    print(x["case"][:12], x["seed"], x["outcome"], "S" if x["success"] else "-", "b=", x["branch_dlvl"],
          "ent", x["mines_entries"], "msteps", x["mines_steps"], "mturns", x["mines_turns"],
          "final", x["final_level"], "dim", x["died_in_mines"], x["death_cause"], x["hunger_at_death"], " ".join(x["path"]))
