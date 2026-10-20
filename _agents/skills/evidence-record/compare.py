"""Paired per-seed comparison of baseline and candidate evaluation reports.

Applies the ADR 0007 section 4.1 qualification gates to each paired set and
writes a compact JSON record for docs/notes/evidence/ plus a Markdown summary.
Reads report JSON only; never opens run databases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from record import iter_results, seed_row  # noqa: E402

SCHEMA_VERSION = 1
SUCCESS = "objective_complete"
DEATH = "death"
WEAK_OR_WORSE = frozenset({"weak", "fainting", "fainted", "starved"})
CONDUCT_METRICS = ("oracle_attacks", "peaceful_attacks")
GATE_ORDER = (
    "objectives_not_lower",
    "deaths_not_higher",
    "weak_or_worse_not_higher",
    "starvation_not_higher",
    "zero_invalid_actions",
    "zero_gate_rejections",
    "zero_integrity_failures",
    "complete_comparable_records",
)
GATE_TEXT = {
    "objectives_not_lower": "candidate objectives >= baseline",
    "deaths_not_higher": "candidate deaths <= baseline",
    "weak_or_worse_not_higher": (
        "candidate last-live Weak-or-worse deaths <= baseline; unknown when a "
        "death lacks hunger evidence"
    ),
    "starvation_not_higher": "candidate starvation deaths <= baseline",
    "zero_invalid_actions": "zero invalid actions in both arms",
    "zero_gate_rejections": "zero gate rejections in both arms",
    "zero_integrity_failures": "zero integrity failures in both arms",
    "complete_comparable_records": (
        "both reports complete, every requested seed evaluated with a terminal "
        "record and ttyrec, same seeds, model, character, tasks and step caps"
    ),
}
ROW_FIELDS = ("outcome", "death_cause", "hunger_at_death", "game_turns", "max_depth")


def is_starvation(result: dict[str, Any]) -> bool:
    cause = result.get("metrics", {}).get("death_cause") or ""
    return result.get("outcome") == DEATH and "starvation" in cause


def is_weak_or_worse(result: dict[str, Any]) -> bool | None:
    """Last-live Weak-or-worse death; None for a death without hunger evidence."""
    if result.get("outcome") != DEATH:
        return False
    if is_starvation(result):
        return True
    hunger = result.get("metrics", {}).get("hunger_at_death")
    if hunger is None:
        return None
    return hunger in WEAK_OR_WORSE


def _median(values: list[float]) -> float | None:
    return None if not values else statistics.median(values)


def _sorted_counts(counter: Counter[Any]) -> dict[str, int]:
    return {
        str(key): count
        for key, count in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    }


def _first_configuration(report: dict[str, Any]) -> dict[str, Any]:
    for _case_id, result in iter_results(report):
        return result.get("configuration") or {}
    return {}


def load_arm(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    report = json.loads(raw)
    suite = report.get("suite") or {}
    configuration = report.get("configuration") or {}
    first = _first_configuration(report)
    results = iter_results(report)
    keys = [(case_id, result.get("seed")) for case_id, result in results]
    problems: list[str] = []
    if len(set(keys)) != len(keys):
        problems.append(f"{path.name}: duplicate (case_id, seed) results")
    if report.get("status") != "complete":
        problems.append(f"{path.name}: report status {report.get('status')!r}")
    for case in report.get("case_results", []):
        requested = case.get("requested_seeds")
        evaluated = [result.get("seed") for result in case.get("results", [])]
        if requested is not None and sorted(requested) != sorted(evaluated):
            problems.append(
                f"{path.name}: case {case.get('case_id')} evaluated "
                f"{len(evaluated)} of {len(requested)} requested seeds"
            )
    return {
        "path": path,
        "report": report,
        "results": dict(zip(keys, (result for _c, result in results), strict=True)),
        "problems": problems,
        "header": {
            "report_file": path.name,
            "report_sha256": hashlib.sha256(raw).hexdigest(),
            "suite_id": suite.get("suite_id"),
            "suite_sha256": suite.get("sha256"),
            "status": report.get("status"),
            "started_at": report.get("started_at"),
            "model": configuration.get("model") or first.get("model"),
            "policy_version": configuration.get("policy_version")
            or first.get("policy_version"),
            "knowledge_version": configuration.get("knowledge_version")
            or first.get("knowledge_version"),
        },
    }


def arm_summary(arm: dict[str, Any]) -> dict[str, Any]:
    rows = list(arm["results"].values())
    outcomes = Counter(row.get("outcome") for row in rows)
    deaths = [row for row in rows if row.get("outcome") == DEATH]
    weak = [is_weak_or_worse(row) for row in deaths]
    quality = {
        "invalid_actions": sum(row.get("invalid_actions") or 0 for row in rows),
        "gate_rejections": sum(row.get("gate_rejections") or 0 for row in rows),
        "integrity_failures": sum(not row.get("integrity_ok") for row in rows),
        "incomplete_records": sum(
            not row.get("ttyrec_exists") or row.get("final_state") != "terminal"
            for row in rows
        ),
        "errors": sum(row.get("error") is not None for row in rows),
        "decision_failures": sum(row.get("decision_failures") or 0 for row in rows),
    }
    conduct: dict[str, int | None] = {}
    for name in CONDUCT_METRICS:
        values = [row.get("metrics", {}).get(name) for row in rows]
        conduct[name] = None if any(v is None for v in values) else sum(values)
    death_metrics = [row.get("metrics", {}) for row in deaths]
    return {
        **arm["header"],
        "episodes": len(rows),
        "objectives": outcomes.get(SUCCESS, 0),
        "deaths": outcomes.get(DEATH, 0),
        "truncations": outcomes.get("truncated", 0),
        "outcomes": _sorted_counts(outcomes),
        "weak_or_worse_deaths": sum(value is True for value in weak),
        "deaths_without_hunger_evidence": sum(value is None for value in weak),
        "starvation_deaths": sum(is_starvation(row) for row in rows),
        "quality": quality,
        "conduct": conduct,
        "diagnostics": {
            "death_causes": _sorted_counts(
                Counter(m.get("death_cause") or "unknown" for m in death_metrics)
            ),
            "hunger_at_death": _sorted_counts(
                Counter(m.get("hunger_at_death") or "unknown" for m in death_metrics)
            ),
            "deaths_by_max_depth": {
                str(depth): count
                for depth, count in sorted(
                    Counter(m.get("max_depth") for m in death_metrics).items(),
                    key=lambda kv: (kv[0] is None, kv[0] or 0),
                )
            },
            "median_death_turn": _median(
                [m["game_turns"] for m in death_metrics if m.get("game_turns")]
            ),
            "median_max_depth": _median(
                [
                    row["metrics"]["max_depth"]
                    for row in rows
                    if row.get("metrics", {}).get("max_depth") is not None
                ]
            ),
            "median_final_experience_level": _median(
                [
                    row["metrics"]["final_experience_level"]
                    for row in rows
                    if row.get("metrics", {}).get("final_experience_level") is not None
                ]
            ),
        },
    }


def comparability_problems(base: dict[str, Any], cand: dict[str, Any]) -> list[str]:
    problems = [*base["problems"], *cand["problems"]]
    base_keys, cand_keys = set(base["results"]), set(cand["results"])
    if base_keys != cand_keys:
        problems.append(
            f"paired seeds differ: {len(base_keys - cand_keys)} baseline-only, "
            f"{len(cand_keys - base_keys)} candidate-only"
        )
    if base["header"]["model"] != cand["header"]["model"]:
        problems.append(
            f"model differs: {base['header']['model']!r} vs {cand['header']['model']!r}"
        )
    base_character = base["report"].get("suite", {}).get("character")
    if base_character != cand["report"].get("suite", {}).get("character"):
        problems.append("suite character differs")
    base_cases = {c.get("case_id"): c for c in base["report"].get("case_results", [])}
    cand_cases = {c.get("case_id"): c for c in cand["report"].get("case_results", [])}
    for case_id in sorted(set(base_cases) & set(cand_cases), key=str):
        for field in ("task", "max_episode_steps"):
            if base_cases[case_id].get(field) != cand_cases[case_id].get(field):
                problems.append(f"case {case_id} {field} differs")
    return problems


def arm_differences(base: dict[str, Any], cand: dict[str, Any]) -> list[str]:
    """Header fields a candidate may legitimately change; reported, not gated."""
    return [
        field
        for field in ("suite_id", "suite_sha256", "policy_version", "knowledge_version")
        if base["header"][field] != cand["header"][field]
    ]


def _transition_flags(base: dict[str, Any], cand: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    b_out, c_out = base.get("outcome"), cand.get("outcome")
    if b_out == SUCCESS and c_out != SUCCESS:
        flags.append("lost_success")
    if b_out != SUCCESS and c_out == SUCCESS:
        flags.append("new_success")
    if b_out != DEATH and c_out == DEATH:
        flags.append("new_death")
    if b_out == DEATH and c_out != DEATH:
        flags.append("avoided_death")
    if b_out == DEATH and c_out == DEATH:
        b_metrics, c_metrics = base.get("metrics", {}), cand.get("metrics", {})
        if b_metrics.get("death_cause") != c_metrics.get("death_cause"):
            flags.append("cause_changed")
        if b_metrics.get("hunger_at_death") != c_metrics.get("hunger_at_death"):
            flags.append("hunger_changed")
    b_weak, c_weak = is_weak_or_worse(base), is_weak_or_worse(cand)
    if c_weak is True and b_weak is not True:
        flags.append("new_weak_or_worse")
    if b_weak is True and c_weak is not True:
        flags.append("removed_weak_or_worse")
    if is_starvation(cand) and not is_starvation(base):
        flags.append("new_starvation")
    if is_starvation(base) and not is_starvation(cand):
        flags.append("removed_starvation")
    return flags


def _endpoint(result: dict[str, Any]) -> tuple[Any, ...]:
    metrics = result.get("metrics", {})
    return (
        result.get("outcome"),
        metrics.get("death_cause"),
        metrics.get("hunger_at_death"),
    )


def _delta(base: Any, cand: Any) -> Any:
    if isinstance(base, int | float) and isinstance(cand, int | float):
        return cand - base
    return None


def _compact(case_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    row = seed_row(case_id, result)
    return {field: row[field] for field in ROW_FIELDS}


def compare_pair(name: str, base_path: Path, cand_path: Path) -> dict[str, Any]:
    base, cand = load_arm(base_path), load_arm(cand_path)
    b_sum, c_sum = arm_summary(base), arm_summary(cand)
    problems = comparability_problems(base, cand)
    seeds: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    transitions: Counter[str] = Counter()
    for key in sorted(set(base["results"]) & set(cand["results"]), key=str):
        case_id, seed = key
        b_row, c_row = base["results"][key], cand["results"][key]
        is_changed = _endpoint(b_row) != _endpoint(c_row)
        seeds.append(
            {
                "case_id": case_id,
                "seed": seed,
                "baseline": b_row.get("outcome"),
                "candidate": c_row.get("outcome"),
                "changed": is_changed,
            }
        )
        if b_row.get("outcome") != c_row.get("outcome"):
            transitions[f"{b_row.get('outcome')}->{c_row.get('outcome')}"] += 1
        if not is_changed:
            continue
        b_metrics, c_metrics = b_row.get("metrics", {}), c_row.get("metrics", {})
        changed.append(
            {
                "case_id": case_id,
                "seed": seed,
                "flags": _transition_flags(b_row, c_row),
                "baseline": _compact(case_id, b_row),
                "candidate": _compact(case_id, c_row),
                "delta": {
                    "game_turns": _delta(
                        b_metrics.get("game_turns"), c_metrics.get("game_turns")
                    ),
                    "max_depth": _delta(
                        b_metrics.get("max_depth"), c_metrics.get("max_depth")
                    ),
                    "steps": _delta(b_row.get("steps"), c_row.get("steps")),
                },
            }
        )
    unknown_hunger = (
        b_sum["deaths_without_hunger_evidence"]
        + c_sum["deaths_without_hunger_evidence"]
    )
    b_q, c_q = b_sum["quality"], c_sum["quality"]
    gates: dict[str, dict[str, Any]] = {
        "objectives_not_lower": _gate(
            b_sum["objectives"],
            c_sum["objectives"],
            c_sum["objectives"] >= b_sum["objectives"],
        ),
        "deaths_not_higher": _gate(
            b_sum["deaths"], c_sum["deaths"], c_sum["deaths"] <= b_sum["deaths"]
        ),
        "weak_or_worse_not_higher": _gate(
            b_sum["weak_or_worse_deaths"],
            c_sum["weak_or_worse_deaths"],
            None
            if unknown_hunger
            else c_sum["weak_or_worse_deaths"] <= b_sum["weak_or_worse_deaths"],
        ),
        "starvation_not_higher": _gate(
            b_sum["starvation_deaths"],
            c_sum["starvation_deaths"],
            c_sum["starvation_deaths"] <= b_sum["starvation_deaths"],
        ),
    }
    for gate, field in (
        ("zero_invalid_actions", "invalid_actions"),
        ("zero_gate_rejections", "gate_rejections"),
        ("zero_integrity_failures", "integrity_failures"),
    ):
        gates[gate] = _gate(b_q[field], c_q[field], b_q[field] == 0 == c_q[field])
    incomplete = (
        b_q["incomplete_records"]
        + c_q["incomplete_records"]
        + b_q["errors"]
        + c_q["errors"]
    )
    gates["complete_comparable_records"] = _gate(
        len(base["problems"]) + b_q["incomplete_records"] + b_q["errors"],
        len(cand["problems"]) + c_q["incomplete_records"] + c_q["errors"],
        not problems and incomplete == 0,
    )
    failed = [gate for gate in GATE_ORDER if gates[gate]["passed"] is False]
    unknown = [gate for gate in GATE_ORDER if gates[gate]["passed"] is None]
    return {
        "name": name,
        "verdict": "fail" if failed else "unknown" if unknown else "pass",
        "failed_gates": failed,
        "unknown_gates": unknown,
        "gates": gates,
        "comparability_problems": problems,
        "arm_differences": arm_differences(base, cand),
        "baseline": b_sum,
        "candidate": c_sum,
        "transitions": _sorted_counts(transitions),
        "changed_seeds": changed,
        "seeds": seeds,
    }


def _gate(base: Any, cand: Any, passed: bool | None) -> dict[str, Any]:
    return {"baseline": base, "candidate": cand, "passed": passed}


def compare(
    pairs: list[tuple[str, Path, Path]],
    base_commit: str | None = None,
    candidate_commit: str | None = None,
) -> dict[str, Any]:
    names = [name for name, _b, _c in pairs]
    if len(set(names)) != len(names):
        raise ValueError("pair names must be unique")
    results = [compare_pair(name, base, cand) for name, base, cand in pairs]
    verdicts = {pair["verdict"] for pair in results}
    overall = (
        "fail" if "fail" in verdicts else "unknown" if "unknown" in verdicts else "pass"
    )
    return {
        "header": {
            "schema_version": SCHEMA_VERSION,
            "tool": "_agents/skills/evidence-record/compare.py",
            "base_commit": base_commit,
            "candidate_commit": candidate_commit,
            "verdict": overall,
            "gates": {gate: GATE_TEXT[gate] for gate in GATE_ORDER},
            "weak_or_worse_states": sorted(WEAK_OR_WORSE),
        },
        "pairs": results,
    }


def write_comparison(record: dict[str, Any], output_path: Path) -> None:
    """Indented JSON with one line per seed row, like record.py records."""
    rows: list[str] = []

    def placeholder(row: dict[str, Any]) -> str:
        rows.append(json.dumps(row))
        return f"@@row{len(rows) - 1}@@"

    shaped = {
        **record,
        "pairs": [
            {
                **pair,
                "changed_seeds": [placeholder(r) for r in pair["changed_seeds"]],
                "seeds": [placeholder(r) for r in pair["seeds"]],
            }
            for pair in record["pairs"]
        ],
    }
    text = json.dumps(shaped, indent=2)
    for index, row in enumerate(rows):
        text = text.replace(f'"@@row{index}@@"', row, 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")


def _odt(arm: dict[str, Any]) -> str:
    return f"{arm['objectives']}/{arm['deaths']}/{arm['truncations']}"


def _iqi(arm: dict[str, Any]) -> str:
    q = arm["quality"]
    return f"{q['invalid_actions']}/{q['gate_rejections']}/{q['integrity_failures']}"


def _row_text(row: dict[str, Any]) -> str:
    if row["outcome"] != DEATH:
        return f"{row['outcome']} (T{row['game_turns']}, D{row['max_depth']})"
    return (
        f"death: {row['death_cause'] or 'unknown'}, "
        f"{row['hunger_at_death'] or 'hunger unknown'} "
        f"(T{row['game_turns']}, D{row['max_depth']})"
    )


def render_markdown(record: dict[str, Any]) -> str:
    header = record["header"]
    lines = [
        "# Paired qualification comparison",
        "",
        f"Overall verdict: **{header['verdict'].upper()}** "
        f"(baseline commit {header['base_commit'] or 'unrecorded'}, "
        f"candidate commit {header['candidate_commit'] or 'unrecorded'}).",
        "",
        "O/D/T = objectives/deaths/truncations; W = last-live Weak-or-worse "
        "deaths; S = starvation deaths; I/G/Int = invalid actions/gate "
        "rejections/integrity failures.",
        "",
        "| Paired set | Baseline O/D/T, W, S | Candidate O/D/T, W, S | "
        "I/G/Int base, cand | Verdict |",
        "| --- | --- | --- | --- | --- |",
    ]
    for pair in record["pairs"]:
        b, c = pair["baseline"], pair["candidate"]
        verdict = pair["verdict"]
        detail = pair["failed_gates"] or pair["unknown_gates"]
        if detail:
            verdict += " (" + ", ".join(detail) + ")"
        lines.append(
            f"| {pair['name']}, {b['episodes']} | {_odt(b)}, "
            f"{b['weak_or_worse_deaths']}, {b['starvation_deaths']} | {_odt(c)}, "
            f"{c['weak_or_worse_deaths']}, {c['starvation_deaths']} | "
            f"{_iqi(b)}, {_iqi(c)} | {verdict} |"
        )
    for pair in record["pairs"]:
        b, c = pair["baseline"], pair["candidate"]
        lines += [
            "",
            f"## {pair['name']}",
            "",
            f"Baseline `{b['suite_id']}` ({b['policy_version']}); candidate "
            f"`{c['suite_id']}` ({c['policy_version']}).",
        ]
        if pair["arm_differences"]:
            lines.append("")
            lines.append(
                "Changed between arms: " + ", ".join(pair["arm_differences"]) + "."
            )
        if pair["comparability_problems"]:
            lines.append("")
            lines.append("Comparability problems:")
            lines += [f"- {problem}" for problem in pair["comparability_problems"]]
        if pair["transitions"]:
            lines.append("")
            lines.append(
                "Outcome transitions: "
                + ", ".join(f"{k} {v}" for k, v in pair["transitions"].items())
                + "."
            )
        if not pair["changed_seeds"]:
            lines += ["", "No seed changed endpoint (outcome, cause, hunger)."]
            continue
        lines += [
            "",
            "| Seed | Baseline | Candidate | Flags |",
            "| --- | --- | --- | --- |",
        ]
        for row in pair["changed_seeds"]:
            lines.append(
                f"| {row['case_id']} {row['seed']} | {_row_text(row['baseline'])} | "
                f"{_row_text(row['candidate'])} | {', '.join(row['flags'])} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paired baseline/candidate comparison with ADR 0007 gates"
    )
    parser.add_argument(
        "--pair",
        nargs=3,
        action="append",
        required=True,
        metavar=("NAME", "BASELINE_REPORT", "CANDIDATE_REPORT"),
        help="one paired set; repeat for every set of the qualification",
    )
    parser.add_argument("--base-commit", help="commit the baseline arms ran at")
    parser.add_argument("--candidate-commit", help="commit the candidate arms ran at")
    parser.add_argument("--output", type=Path, help="compact JSON record path")
    parser.add_argument(
        "--markdown", type=Path, help="Markdown summary path (default: stdout)"
    )
    args = parser.parse_args(argv)
    try:
        record = compare(
            [(name, Path(b), Path(c)) for name, b, c in args.pair],
            base_commit=args.base_commit,
            candidate_commit=args.candidate_commit,
        )
    except (OSError, ValueError) as error:
        print(f"compare: {error}", file=sys.stderr)
        return 2
    if args.output:
        write_comparison(record, args.output)
    markdown = render_markdown(record)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
