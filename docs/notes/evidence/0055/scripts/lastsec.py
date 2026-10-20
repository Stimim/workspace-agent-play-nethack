"""Last live decisions of each non-hunger death: was the prayer trigger ever
seen at a decision point, and with what action?"""

import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from summarize import klass  # noqa: E402

FIRST_SAFE, REPEAT = 100, 1229
rows = json.load(open(sys.argv[1]))
want = {(r["arm"], r["seed"], r["case"]) for r in rows if klass(r)[0] != "A"}
out = []
for arm in sorted({a for a, _, _ in want}):
    A = Path(os.path.expanduser(f"~/nethack-evidence/0052/{arm}"))
    rep = json.load(open(glob.glob(str(A / "reports/*.json"))[0]))
    con = sqlite3.connect(f"file:{A}/runs.sqlite3?mode=ro", uri=True)
    for c in rep["case_results"]:
        for e in c["results"]:
            if (arm, e["seed"], c["case_id"]) not in want:
                continue
            raw = con.execute("select payload_json from events where run_id=? and kind='step' "
                              "order by sequence desc limit 12", (e["run_id"],)).fetchall()
            st = [json.loads(p) for (p,) in reversed(raw)]
            live = [s for s in st if s["observation"]["player"]["max_hit_points"] > 0]
            prays = [t for (t,) in con.execute(
                "select json_extract(payload_json,'$.observation.player.turn') from events where run_id=? "
                "and kind='step' and payload_json like '%\"name\":\"Command.PRAY\"%'", (e["run_id"],))]
            # A decision is made on the observation *before* each step, i.e.
            # the previous step's observation. Collect (hp,max,turn) seen at
            # each decision and the action chosen.
            decisions = []
            for prev, cur in zip(live, live[1:]):
                q = prev["observation"]["player"]
                decisions.append((q["hit_points"], q["max_hit_points"], q["turn"], q["hit_dice"],
                                  cur["selection"]["skill"], cur["action"]["name"]))
            def crit(hp, mx, hd):
                return hd == 0 and (hp <= 5 or hp * 7 <= mx)
            def pray_ok(t):
                prior = [x for x in prays if x is not None and x < t]
                return t >= FIRST_SAFE and (not prior or t - max(prior) >= REPEAT)
            crit_decisions = [d for d in decisions if crit(d[0], d[1], d[3])]
            last = live[-1]["observation"]["player"]
            out.append({
                "arm": arm, "seed": e["seed"], "cause": e["metrics"].get("death_cause"),
                "last_live_hp": last["hit_points"], "last_live_max": last["max_hit_points"],
                "last_live_critical": crit(last["hit_points"], last["max_hit_points"], last["hit_dice"]),
                "pray_ok_at_last": pray_ok(last["turn"]),
                "critical_decisions": [list(d) for d in crit_decisions],
                "critical_decision_with_prayer_ok": [list(d) for d in crit_decisions if pray_ok(d[2])],
            })
    con.close()
json.dump(out, open(sys.argv[2], "w"), indent=1)
n = len(out)
print("non-hunger deaths:", n)
print("last live state already critical (HP<=5 or <=1/7):", sum(o["last_live_critical"] for o in out))
print("  of which prayer would have been safe:", sum(o["last_live_critical"] and o["pray_ok_at_last"] for o in out))
print("died from above the prayer threshold in one monster round:", sum(not o["last_live_critical"] for o in out))
skip = [o for o in out if o["critical_decision_with_prayer_ok"]]
print("a decision saw critical HP with prayer safe, yet no prayer happened:", len(skip))
for o in skip:
    print("  ", o["arm"], o["seed"], o["cause"], o["critical_decision_with_prayer_ok"][:3])
