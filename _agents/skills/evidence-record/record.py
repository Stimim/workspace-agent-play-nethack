"""Generate a compact per-seed evidence record from an eval report JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def generate_evidence_record(
    report_path: Path,
    commit: str,
    command: str,
    classes: dict[str, str] | None = None,
) -> dict[str, Any]:
    with report_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    suite = data.get("suite", {})
    suite_id = suite.get("suite_id")
    suite_sha256 = suite.get("sha256")
    report_filename = report_path.name
    started_at = data.get("started_at")

    top_conf = data.get("configuration") or {}

    # Sample result for configuration fallbacks if missing at top level
    first_res_conf: dict[str, Any] = {}
    for cr in data.get("case_results", []):
        results = cr.get("results", [])
        if results:
            first_res_conf = results[0].get("configuration", {})
            break

    model = top_conf.get("model") or first_res_conf.get("model")
    policy_version = top_conf.get("policy_version") or first_res_conf.get(
        "policy_version"
    )
    knowledge_version = top_conf.get("knowledge_version") or first_res_conf.get(
        "knowledge_version"
    )

    # max_episode_steps is typically in case_results or result configuration
    max_episode_steps = None
    if "max_episode_steps" in first_res_conf:
        max_episode_steps = first_res_conf["max_episode_steps"]
    elif data.get("case_results"):
        max_episode_steps = data["case_results"][0].get("max_episode_steps")

    rerun_hint = f"{command.strip()} --seeds <seed>"

    header: dict[str, Any] = {
        "suite_id": suite_id,
        "suite_sha256": suite_sha256,
        "report_file": report_filename,
        "started_at": started_at,
        "model": model,
        "policy_version": policy_version,
        "knowledge_version": knowledge_version,
        "max_episode_steps": max_episode_steps,
        "commit": commit,
        "command": command,
        "rerun_hint": rerun_hint,
    }

    rows: list[dict[str, Any]] = []
    classes_map = classes or {}

    for cr in data.get("case_results", []):
        default_case_id = cr.get("case_id")
        for res in cr.get("results", []):
            case_id = res.get("case_id", default_case_id)
            seed = res.get("seed")
            outcome = res.get("outcome")
            steps = res.get("steps")
            metrics = res.get("metrics", {})
            game_turns = metrics.get("game_turns")
            death_cause = metrics.get("death_cause")
            if outcome != "death" or death_cause in (None, "unknown"):
                death_cause = None
            hunger_at_death = metrics.get("hunger_at_death")
            max_depth = metrics.get("max_depth")
            levels_visited = metrics.get("levels_visited", [])
            final_level = None
            if levels_visited:
                last_lv = levels_visited[-1]
                dnum = last_lv.get("dungeon_number")
                dlevel = last_lv.get("dungeon_level")
                if dnum is not None and dlevel is not None:
                    final_level = f"{dnum}:{dlevel}"

            # Check failure class: classes_map may have string or int keys
            failure_class = classes_map.get(str(seed))

            rows.append(
                {
                    "case_id": case_id,
                    "seed": seed,
                    "outcome": outcome,
                    "steps": steps,
                    "game_turns": game_turns,
                    "death_cause": death_cause,
                    "hunger_at_death": hunger_at_death,
                    "max_depth": max_depth,
                    "final_level": final_level,
                    "failure_class": failure_class,
                }
            )

    rows.sort(key=lambda r: (r["case_id"], r["seed"]))

    return {
        "header": header,
        "rows": rows,
    }


def write_evidence_record(record: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("{\n")
        f.write('  "header": ')
        f.write(json.dumps(record["header"], indent=2).replace("\n", "\n  "))
        f.write(',\n  "rows": [\n')
        rows = record["rows"]
        for idx, row in enumerate(rows):
            line = "    " + json.dumps(row, separators=(", ", ": "))
            if idx < len(rows) - 1:
                line += ","
            f.write(line + "\n")
        f.write("  ]\n}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create compact evidence record from eval report JSON"
    )
    parser.add_argument("report", type=Path, help="Path to evaluation report JSON")
    parser.add_argument(
        "--commit", required=True, type=str, help="Commit SHA of evaluation run"
    )
    parser.add_argument(
        "--command", required=True, type=str, help="Command needed to rerun"
    )
    parser.add_argument(
        "--classes",
        type=Path,
        default=None,
        help="Optional JSON file mapping seed -> failure class",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Output path for record JSON"
    )

    args = parser.parse_args()

    classes_map: dict[str, str] | None = None
    if args.classes:
        with args.classes.open("r", encoding="utf-8") as f:
            classes_map = json.load(f)

    record = generate_evidence_record(
        report_path=args.report,
        commit=args.commit,
        command=args.command,
        classes=classes_map,
    )

    write_evidence_record(record, args.output)


if __name__ == "__main__":
    main()
