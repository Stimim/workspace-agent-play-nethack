"""Paired stall and loop diagnostics from evaluation run databases (ADR 0008).

`compare.py` reads reports only; stalls need step events, which only the
arm's `runs.sqlite3` holds. Each database is opened read-only and closed
before the next. A run is **stalled** when one contiguous stay on a level
(same dungeon number and level, first to last step event) lasts more than
1,000 game turns. Loop counters reproduce the note 0059 diagnostics:
model-fallback steps (runs with at least 100 of them) and arrive-then-leave
events, where the hero reaches a search spot and walks to another one
without searching.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STALL_TURNS = 1000
FALLBACK_LOOP_STEPS = 100
SEARCH_SPOT = re.compile(r"Move to search spot \((\d+), (\d+)\) \((\d+) steps\)")
STEP_QUERY = """
SELECT json_extract(payload_json, '$.observation.player.dungeon_number'),
       json_extract(payload_json, '$.observation.player.dungeon_level'),
       json_extract(payload_json, '$.observation.player.turn'),
       json_extract(payload_json, '$.selection.source'),
       json_extract(payload_json, '$.selection.rationale')
FROM events WHERE run_id = ? AND kind = 'step' ORDER BY sequence
"""


def run_diagnostics(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    """Longest contiguous level stay and loop counters for one run's steps."""
    stays: list[list[Any]] = []
    fallback = arrive_then_leave = 0
    previous_spot: tuple[str, str, str] | None = None
    for dungeon_number, dungeon_level, turn, source, rationale in rows:
        fallback += source == "model_fallback"
        match = SEARCH_SPOT.search(rationale or "")
        spot = match.groups() if match else None
        if (
            previous_spot is not None
            and previous_spot[2] == "1"
            and spot is not None
            and spot[:2] != previous_spot[:2]
        ):
            arrive_then_leave += 1
        previous_spot = spot
        # A death screen zeroes the statistics; it is not a stay anywhere.
        if turn is None or (turn == 0 and stays):
            continue
        level = (dungeon_number, dungeon_level)
        if not stays or stays[-1][0] != level:
            stays.append([level, turn, turn])
        stays[-1][2] = turn
    longest = max(stays, key=lambda stay: stay[2] - stay[1], default=None)
    turns = 0 if longest is None else longest[2] - longest[1]
    return {
        "longest_stay_turns": turns,
        "longest_stay_level": None
        if longest is None
        else {"dungeon_number": longest[0][0], "dungeon_level": longest[0][1]},
        "stalled": turns > STALL_TURNS,
        "model_fallback_steps": fallback,
        "arrive_then_leave": arrive_then_leave,
    }


def load_arm(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        runs = connection.execute(
            "SELECT id, suite_seed, outcome FROM runs ORDER BY suite_seed"
        ).fetchall()
        seeds = [seed for _id, seed, _outcome in runs]
        if len(set(seeds)) != len(seeds):
            raise ValueError(
                f"{database}: duplicate suite seeds; use one suite per arm"
            )
        results = {}
        for run_id, seed, outcome in runs:
            rows = connection.execute(STEP_QUERY, (run_id,)).fetchall()
            results[seed] = {
                "run_id": run_id,
                "outcome": outcome,
                **run_diagnostics(rows),
            }
    finally:
        connection.close()
    return {"database": str(database), "results": results}


def arm_summary(arm: dict[str, Any]) -> dict[str, Any]:
    rows = list(arm["results"].values())
    longest = [row["longest_stay_turns"] for row in rows]
    return {
        "database": arm["database"],
        "runs": len(rows),
        "stalled_runs": sum(row["stalled"] for row in rows),
        "median_longest_stay_turns": statistics.median(longest) if longest else None,
        "fallback_loop_runs": sum(
            row["model_fallback_steps"] >= FALLBACK_LOOP_STEPS for row in rows
        ),
        "arrive_then_leave_events": sum(row["arrive_then_leave"] for row in rows),
        "arrive_then_leave_runs": sum(row["arrive_then_leave"] > 0 for row in rows),
    }


def compare_pair(name: str, base_db: Path, cand_db: Path) -> dict[str, Any]:
    base, cand = load_arm(base_db), load_arm(cand_db)
    problems = []
    if set(base["results"]) != set(cand["results"]):
        problems.append("arms evaluated different seeds")
    changed = []
    for seed in sorted(set(base["results"]) & set(cand["results"])):
        b, c = base["results"][seed], cand["results"][seed]
        flags = []
        if c["stalled"] and not b["stalled"]:
            flags.append("new_stall")
        if b["stalled"] and not c["stalled"]:
            flags.append("removed_stall")
        if c["model_fallback_steps"] >= FALLBACK_LOOP_STEPS > b["model_fallback_steps"]:
            flags.append("new_fallback_loop")
        if flags:
            changed.append(
                {"seed": seed, "flags": flags, "baseline": b, "candidate": c}
            )
    return {
        "name": name,
        "comparability_problems": problems,
        "baseline": arm_summary(base),
        "candidate": arm_summary(cand),
        "changed_seeds": changed,
    }


def render_markdown(record: dict[str, Any]) -> str:
    lines = [
        "| Pair | Stalled runs | Median longest stay | Fallback-loop runs "
        "| Arrive-then-leave (runs) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for pair in record["pairs"]:
        b, c = pair["baseline"], pair["candidate"]
        lines.append(
            f"| {pair['name']} | {b['stalled_runs']} -> {c['stalled_runs']} "
            f"| {b['median_longest_stay_turns']} -> {c['median_longest_stay_turns']} "
            f"| {b['fallback_loop_runs']} -> {c['fallback_loop_runs']} "
            f"| {b['arrive_then_leave_events']} ({b['arrive_then_leave_runs']}) -> "
            f"{c['arrive_then_leave_events']} ({c['arrive_then_leave_runs']}) |"
        )
    for pair in record["pairs"]:
        flags = Counter(flag for row in pair["changed_seeds"] for flag in row["flags"])
        lines.append("")
        lines.append(f"{pair['name']}: {dict(sorted(flags.items())) or 'no changes'}")
        lines.extend(
            f"- problem: {problem}" for problem in pair["comparability_problems"]
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pair",
        nargs=3,
        action="append",
        required=True,
        metavar=("NAME", "BASE_DB", "CAND_DB"),
        help="paired arm databases (runs.sqlite3); repeat per suite",
    )
    parser.add_argument("--output", type=Path, help="JSON record path")
    args = parser.parse_args(argv)
    names = [name for name, _b, _c in args.pair]
    if len(set(names)) != len(names):
        parser.error("pair names must be unique")
    record = {
        "header": {
            "schema_version": SCHEMA_VERSION,
            "tool": "_agents/skills/evidence-record/stalls.py",
            "stall_turns": STALL_TURNS,
            "fallback_loop_steps": FALLBACK_LOOP_STEPS,
        },
        "pairs": [compare_pair(n, Path(b), Path(c)) for n, b, c in args.pair],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(render_markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
