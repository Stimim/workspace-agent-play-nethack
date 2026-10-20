"""Mid-fight prayers of non-hunger deaths: did HP reach max, and when did
the hero die? Read-only over the 0052 baseline databases (diagnosis only).

Usage: prayers.py ROWS_JSON [EVIDENCE_ROOT]
ROWS_JSON is baseline-deaths.json (this record's or the original list).
EVIDENCE_ROOT defaults to ~/nethack-evidence/0052.
"""

import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from summarize import klass  # noqa: E402

HEAL_WINDOW = 5  # steps after the PRAY keypress in which prayer resolves


def main():
    data = json.load(open(sys.argv[1]))
    rows = data["rows"] if isinstance(data, dict) else data
    root = Path(os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else "~/nethack-evidence/0052"))
    for r in rows:  # committed rows carry their class; the original list does not
        r.setdefault("class", klass(r)[0] if "hunger" in r else None)
    want = [r for r in rows if r["prayed_in_fight"] and r["class"] != "A"]
    out = []
    for arm in sorted({r["arm"] for r in want}):
        A = root / arm
        rep = json.load(open(glob.glob(str(A / "reports/*.json"))[0]))
        runs = {(c["case_id"], e["seed"]): e["run_id"] for c in rep["case_results"] for e in c["results"]}
        con = sqlite3.connect(f"file:{A}/runs.sqlite3?mode=ro", uri=True)
        try:
            for r in (r for r in want if r["arm"] == arm):
                run = runs[(r["case"], r["seed"])]
                t_entry = r["death_turn"] - r["fight_turns"]
                prays = [
                    (s, json.loads(p)["observation"]["player"]["turn"])
                    for s, p in con.execute(
                        "select sequence, payload_json from events where run_id=? and kind='step' "
                        "and payload_json like '%\"name\":\"Command.PRAY\"%' order by sequence",
                        (run,),
                    )
                ]
                seq, pray_turn = [p for p in prays if p[1] >= t_entry][-1]
                after = [
                    json.loads(p)["observation"]["player"]
                    for (p,) in con.execute(
                        "select payload_json from events where run_id=? and kind='step' "
                        "and sequence > ? and sequence <= ? order by sequence",
                        (run, seq, seq + HEAL_WINDOW),
                    )
                ]
                healed = next(
                    (q for q in after if q["max_hit_points"] > 0 and q["hit_points"] == q["max_hit_points"]),
                    None,
                )
                out.append({
                    "arm": arm, "case": r["case"], "seed": r["seed"], "class": r["class"],
                    "pray_turn": pray_turn, "death_turn": r["death_turn"],
                    "healed_full": healed is not None,
                    "heal_turn": None if healed is None else healed["turn"],
                })
        finally:
            con.close()
    healed = [o for o in out if o["healed_full"]]
    print("non-hunger deaths with a mid-fight prayer:", len(out))
    print("prayer restored full HP:", len(healed))
    if healed:
        d = sorted(o["death_turn"] - o["pray_turn"] for o in healed)
        h = sorted(o["death_turn"] - o["heal_turn"] for o in healed)
        print("death turns after prayer:", d[0], "-", d[-1], d)
        print("death turns after full-HP observation:", h[0], "-", h[-1], h)
    json.dump(out, sys.stdout if len(sys.argv) < 4 else open(sys.argv[3], "w"), indent=None)
    print()


if __name__ == "__main__":
    main()
