"""Classify deaths from stored public step events (diagnosis only).

Usage: deaths.py OUT_JSON ARM_DIR [ARM_DIR ...]
Each ARM_DIR has runs.sqlite3 and reports/*.json. Reads only the last
WINDOW step events of each death plus a LIKE scan for PRAY steps.
"""

from __future__ import annotations

import glob
import json
import sqlite3
import re
import sys
from collections import deque
from pathlib import Path

from nle import nethack

from nethack_agent.navigation import _CMAP_KINDS, PASSABLE_KINDS

WINDOW = 400
FIGHT_GAP = 10
FIRST_SAFE, REPEAT = 100, 1229
UP = {23}  # defsym.h S_upstair
DOWN = {24}  # S_dnstair
ATTACKER = re.compile(r"\bThe ([a-z][a-z' -]*?) (?:hits|bites|stings|butts|kicks|claws|touches|smites|thrusts|swings)")
UNSEEN = re.compile(r"\bIt (?:hits|bites|stings|butts|kicks|claws|touches|misses)")


def cmap(glyph: int) -> int | None:
    return nethack.glyph_to_cmap(glyph) if nethack.glyph_is_cmap(glyph) else None


def walkable(glyph: int) -> bool:
    c = cmap(glyph)
    if c is not None:
        return _CMAP_KINDS[c] in PASSABLE_KINDS
    # Objects and monsters stand on some walkable cell we cannot see.
    return nethack.glyph_is_object(glyph) or nethack.glyph_is_monster(glyph)


def bfs(glyphs, start, goal_cmaps):
    h, w = len(glyphs), len(glyphs[0])
    seen = {start: 0}
    q = deque([start])
    while q:
        x, y = q.popleft()
        c = cmap(glyphs[y][x])
        if c in goal_cmaps and (x, y) != start:
            return seen[(x, y)]
        if (x, y) == start and c in goal_cmaps:
            return 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if (dx or dy) and 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen:
                    if walkable(glyphs[ny][nx]):
                        seen[(nx, ny)] = seen[(x, y)] + 1
                        q.append((nx, ny))
    return None


def monsters_near(obs, radius=1):
    m = obs["map"]
    glyphs, pets = m["glyph_rows"], m.get("pet_rows")
    px, py = obs["player"]["x"], obs["player"]["y"]
    out = []
    for y in range(max(0, py - radius), min(len(glyphs), py + radius + 1)):
        for x in range(max(0, px - radius), min(len(glyphs[0]), px + radius + 1)):
            if (x, y) == (px, py):
                continue
            g = glyphs[y][x]
            if not nethack.glyph_is_monster(g):
                continue
            if pets is not None and pets[y][x] in ("1", 1, True):
                continue
            pm = nethack.permonst(nethack.glyph_to_mon(g))
            out.append({"name": pm.mname, "speed": pm.mmove, "level": pm.mlevel})
    return out


def regen_period(xl: int) -> int:
    return 3 if xl > 9 else (30 + 12) // (xl + 2) + 1


def analyze(arm: Path):
    report = json.load(open(glob.glob(str(arm / "reports" / "*.json"))[0]))
    con = sqlite3.connect(f"file:{arm / 'runs.sqlite3'}?mode=ro", uri=True)
    con.execute("PRAGMA cache_size=-4096")
    rows = []
    for case in report["case_results"]:
        for e in case["results"]:
            if e["outcome"] != "death":
                continue
            run = e["run_id"]
            raw = con.execute(
                "select payload_json from events where run_id=? and kind='step' "
                "order by sequence desc limit ?", (run, WINDOW)).fetchall()
            steps = [json.loads(p) for (p,) in reversed(raw)]
            live = [s for s in steps if s["observation"]["player"]["max_hit_points"] > 0]
            if not live:
                continue
            prays = [t for (t,) in con.execute(
                "select json_extract(payload_json,'$.observation.player.turn') from events "
                "where run_id=? and kind='step' and payload_json like '%\"name\":\"Command.PRAY\"%'",
                (run,))]
            last = live[-1]["observation"]
            p = last["player"]
            death_turn = p["turn"]
            obs = [s["observation"] for s in live]
            pl = [o["player"] for o in obs]
            # Fatal fight: the contiguous run of HP losses ending at death,
            # where consecutive losses are at most FIGHT_GAP game turns apart.
            loss = [i for i in range(1, len(pl)) if pl[i]["hit_points"] < pl[i - 1]["hit_points"]
                    and pl[i]["hit_dice"] == pl[i - 1]["hit_dice"]]
            first = len(pl) - 1
            if loss:
                first = loss[-1]
                for i in reversed(loss[:-1]):
                    if pl[first]["turn"] - pl[i]["turn"] > FIGHT_GAP:
                        break
                    first = i
            entry = max(0, first - 1)
            pe = pl[entry]
            frac_entry = pe["hit_points"] / pe["max_hit_points"]
            # Wounded time before the fight: consecutive steps below 50% HP
            # immediately before entry with no hostile adjacent.
            wounded_idle = 0
            j = entry
            while j > 0 and pl[j]["hit_points"] < 0.5 * pl[j]["max_hit_points"]:
                j -= 1
            wounded_idle = pe["turn"] - pl[j]["turn"] if j < entry else 0
            # Low-HP moment (the shipped prayer trigger: HP < 1/7 or < 6).
            low = next((k for k in range(entry, len(pl))
                        if pl[k]["hit_points"] < max(6, pl[k]["max_hit_points"] / 7)), None)
            t_entry = pe["turn"]
            def pray_ok(t):
                prior = [x for x in prays if x is not None and x < t]
                return t >= FIRST_SAFE and (not prior or t - max(prior) >= REPEAT)
            prior_e = [x for x in prays if x is not None and x < t_entry]
            next_pray = (max(prior_e) + REPEAT) if prior_e else FIRST_SAFE
            prayed_in_fight = any(x is not None and x >= t_entry for x in prays)
            oe = obs[entry]
            start = (pe["x"], pe["y"])
            up_dist = bfs(oe["map"]["glyph_rows"], start, UP)
            down_dist = bfs(oe["map"]["glyph_rows"], start, DOWN)
            fight = live[entry:]
            msgs = " ".join(s["observation"]["message"] for s in fight)
            attackers = sorted(set(m.group(1) for m in ATTACKER.finditer(msgs)))
            speeds = {}
            for o in obs[entry:]:
                for m in monsters_near(o, radius=2):
                    speeds[m["name"]] = m["speed"]
            unseen = len(UNSEEN.findall(msgs))
            blind = any("blind" in s["observation"]["player"]["conditions"] for s in fight)
            attacks = sum(1 for s in fight if (s["selection"].get("intent") or {}).get("attack_target"))
            searches = sum(1 for s in fight if s["action"]["name"] == "Command.SEARCH")
            food = sum(1 for it in last["inventory"] if it["object_class"] == 7)
            heal_turns = max(0, int(0.8 * pe["max_hit_points"]) - pe["hit_points"]) * regen_period(pe["experience_level"])
            rows.append({
                "arm": arm.name, "case": case["case_id"], "seed": e["seed"],
                "cause": e["metrics"].get("death_cause"), "hunger": e["metrics"].get("hunger_at_death"),
                "level": [p["dungeon_number"], p["dungeon_level"]], "depth": p["depth"],
                "xl": p["experience_level"], "maxhp": p["max_hit_points"], "ac": p["armor_class"],
                "death_turn": death_turn,
                "fight_turns": death_turn - t_entry,
                "hp_entry": pe["hit_points"], "frac_entry": round(frac_entry, 3),
                "polymorphed_entry": pe["hit_dice"] > 0,
                "wounded_turns_before_fight": wounded_idle,
                "pray_ok_entry": pray_ok(t_entry),
                "pray_ok_at_low": None if low is None else pray_ok(pl[low]["turn"]),
                "low_hp_turns_before_death": None if low is None else death_turn - pl[low]["turn"],
                "prayed_in_fight": prayed_in_fight,
                "turns_until_prayer_entry": max(0, next_pray - t_entry),
                "up_dist": up_dist, "down_dist": down_dist,
                "attackers": attackers, "nearby_speeds": speeds,
                "unseen_attack_msgs": unseen, "blind": blind,
                "attack_steps": attacks, "search_steps": searches, "fight_steps": len(fight),
                "food_items": food, "hunger_entry": pe["hunger"],
                "heal_to_80pct_turns_from_entry": heal_turns,
                "encumbrance": pe["encumbrance"],
            })
    con.close()
    return rows


def main():
    out = Path(sys.argv[1])
    rows = []
    for a in sys.argv[2:]:
        rows += analyze(Path(a).expanduser())
        print(a, len(rows), flush=True)
    out.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
