"""Summarize deaths.py output into mutually exclusive classes."""

import json
import statistics
import sys
from collections import Counter, defaultdict

HUNGER_BAD = {"weak", "fainting", "fainted", "starved"}
HERO_SPEED = 12


def klass(r):
    if r["hunger"] in HUNGER_BAD or (r["cause"] or "").startswith("died of starvation"):
        return "A hunger (Weak+/starved)"
    if r["unseen_attack_msgs"] >= 3 or r["blind"]:
        return "B unseen attacker / blind"
    if r["frac_entry"] < 0.5:
        return "C entered fatal fight already <50% HP"
    if r["fight_turns"] <= 10:
        return "D healthy entry, killed within 10 turns"
    return "E healthy entry, fight >10 turns"


def main():
    rows = json.load(open(sys.argv[1]))
    print(f"deaths: {len(rows)}")
    by = defaultdict(list)
    for r in rows:
        by[klass(r)].append(r)
    arms = sorted({r["arm"] for r in rows})
    print("\nclass x arm")
    for k in sorted(by):
        c = Counter(r["arm"] for r in by[k])
        print(f"  {k:45s} {len(by[k]):3d}  " + " ".join(f"{a.split('-',1)[1]}:{c[a]}" for a in arms))
    print("\ndepth band x class")
    band = lambda d: "D1-2" if d <= 2 else "D3-4" if d <= 4 else "D5-6" if d <= 6 else "D7+"
    t = Counter((band(r["depth"]), klass(r)[0]) for r in rows)
    for b in ("D1-2", "D3-4", "D5-6", "D7+"):
        print(f"  {b}: " + " ".join(f"{k}={t[(b,k)]}" for k in "ABCDE") + f"  total={sum(t[(b,k)] for k in 'ABCDE')}")
    print("\nprayer availability at fight entry (non-hunger deaths)")
    nh = [r for r in rows if klass(r)[0] != "A"]
    print("  available:", sum(r["pray_ok_entry"] for r in nh), "/", len(nh))
    print("  prayed during fatal fight:", sum(r["prayed_in_fight"] for r in nh))
    print("  available at low-HP moment but died anyway:", sum(1 for r in nh if r["pray_ok_at_low"]))
    print("  median turns until prayer at entry (unavailable):",
          statistics.median([r["turns_until_prayer_entry"] for r in nh if not r["pray_ok_entry"]] or [0]))
    for k in ("C", "D", "E"):
        g = [r for r in rows if klass(r)[0] == k]
        if not g:
            continue
        print(f"\nclass {k}: n={len(g)}")
        ft = [r["fight_turns"] for r in g]
        print("  fight turns median/max:", statistics.median(ft), max(ft))
        fast = sum(1 for r in g if max(r["nearby_speeds"].values() or [0]) > HERO_SPEED)
        print("  a nearby hostile faster than hero (>12):", fast)
        up = [r["up_dist"] for r in g if r["up_dist"] is not None]
        print("  upstairs known & reachable:", len(up), " within fight_turns:",
              sum(1 for r in g if r["up_dist"] is not None and r["up_dist"] < r["fight_turns"]),
              " within 10 steps:", sum(1 for d in up if d <= 10))
        print("  wounded turns before fight median:", statistics.median([r["wounded_turns_before_fight"] for r in g]))
        print("  heal-to-80% turns from entry median/max:",
              statistics.median([r["heal_to_80pct_turns_from_entry"] for r in g]),
              max(r["heal_to_80pct_turns_from_entry"] for r in g))
        print("  food items at death >0:", sum(1 for r in g if r["food_items"] > 0),
              " hunger at entry NotHungry:", sum(1 for r in g if r["hunger_entry"] <= 1))
        print("  attackers:", Counter(a for r in g for a in r["attackers"]).most_common(12))
        print("  xl median:", statistics.median([r["xl"] for r in g]), " maxhp median:",
              statistics.median([r["maxhp"] for r in g]), " AC median:", statistics.median([r["ac"] for r in g]))
    print("\ntop death causes:", Counter(r["cause"] for r in rows).most_common(15))


if __name__ == "__main__":
    main()
