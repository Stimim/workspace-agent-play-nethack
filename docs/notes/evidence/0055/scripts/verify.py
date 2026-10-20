"""Recompute note 0056's Phase 3 numbers from the committed 0055 rows.

Usage: verify.py RECORD_DIR
The mid-fight prayer figure needs the 0052 databases; see prayers.py.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERO_SPEED = 12
# NetHack 3.6.7 onscary(): @ humans/elves, minotaurs and the Riders ignore
# Elbereth. The cause string cannot tell a werecreature's @ form from its
# animal form; both are counted as @ here.
IGNORE_ELBERETH = {"guard", "Green-elf", "werejackal", "wererat", "werewolf", "minotaur",
                   "watchman", "shopkeeper", "aligned priest", "Death", "Pestilence", "Famine"}
NOT_MONSTERS = {"wand", "little dart", "orcish arrow", "boulder", "brainlessness", "gas spore's explosion"}


def killer(cause):
    m = re.match(r"(?:killed|poisoned) by (?:an? |the )?(.*)$", cause or "")
    return m.group(1) if m and m.group(1) not in NOT_MONSTERS else None


def main():
    d = Path(sys.argv[1])
    rows = json.load(open(d / "baseline-deaths.json"))["rows"]
    cand = json.load(open(d / "candidate-0054-deaths.json"))["rows"]
    print("deaths:", len(rows), " classes:", dict(sorted(Counter(r["class"] for r in rows).items())))
    nh = [r for r in rows if r["class"] != "A"]
    band = [r for r in nh if not r["last_live_critical"] and r["last_live_hp"] * 3 <= r["last_live_max"]]
    lo = min(r["last_live_hp"] / r["last_live_max"] for r in band)
    print(f"last decision above the prayer trigger at <=1/3 HP: {len(band)}/{len(nh)} (min {lo:.1%})")
    cde = [k for r in rows if r["class"] in "CDE" and (k := killer(r["cause"]))]
    respect = [k for k in cde if k not in IGNORE_ELBERETH]
    print(f"named killers (classes C-E) respecting Elbereth: {len(respect)}/{len(cde)}",
          dict(Counter(k for k in cde if k in IGNORE_ELBERETH)))
    de = [r for r in rows if r["class"] in "DE"]
    print(f"healthy entry (D+E) with a faster hostile nearby: "
          f"{sum(r['max_nearby_speed'] > HERO_SPEED for r in de)}/{len(de)}")
    print(f"healthy entry (D+E) with known upstairs within 10 steps: "
          f"{sum(r['up_dist'] is not None and r['up_dist'] <= 10 for r in de)}/{len(de)}")
    print("entered fatal fight below 50% HP (class C):", sum(r["class"] == "C" for r in rows))
    print("non-hunger deaths with a mid-fight prayer:", sum(r["prayed_in_fight"] for r in nh))
    print("candidate deaths:", len(cand), " Weak or worse (class A):", sum(r["class"] == "A" for r in cand),
          " baseline truncated -> death:", sum(r["baseline_outcome"] == "truncated" for r in cand))


if __name__ == "__main__":
    main()
