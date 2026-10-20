"""Tests for the evidence-record skill's paired report comparison."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "_agents/skills/evidence-record"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SKILL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def compare_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SKILL))
    return _load("compare")


def _result(seed, outcome, *, cause=None, hunger=None, turns=1000, depth=3):
    return {
        "case_id": "fresh-sample",
        "seed": seed,
        "outcome": outcome,
        "steps": turns // 2,
        "invalid_actions": 0,
        "gate_rejections": 0,
        "integrity_ok": True,
        "ttyrec_exists": True,
        "final_state": "terminal",
        "error": None,
        "decision_failures": 0,
        "configuration": {"model": "scripted-development"},
        "metrics": {
            "death_cause": cause,
            "hunger_at_death": hunger,
            "game_turns": turns,
            "max_depth": depth,
            "final_experience_level": 4,
            "levels_visited": [{"dungeon_number": 0, "dungeon_level": depth}],
            "oracle_attacks": 0,
            "peaceful_attacks": 0,
        },
    }


def _report(results, *, suite_id="minetown-fresh-v9", knowledge="k-v1"):
    return {
        "status": "complete",
        "started_at": "2026-10-21T00:00:00Z",
        "suite": {"suite_id": suite_id, "sha256": suite_id, "character": "val"},
        "configuration": {
            "model": "scripted-development",
            "policy_version": "policy-v1",
            "knowledge_version": knowledge,
        },
        "case_results": [
            {
                "case_id": "fresh-sample",
                "task": {"objective": "minetown"},
                "max_episode_steps": 10000,
                "requested_seeds": [r["seed"] for r in results],
                "results": results,
            }
        ],
    }


BASE_RESULTS = [
    _result(1, "objective_complete"),
    _result(2, "death", cause="killed by a jackal", hunger="not_hungry"),
    _result(3, "death", cause="killed by a newt", hunger="weak"),
    _result(4, "truncated"),
]


def _write(tmp_path: Path, name: str, report) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _pair(compare_module, tmp_path, base, cand):
    record = compare_module.compare(
        [
            (
                "set",
                _write(tmp_path, "base", base),
                _write(tmp_path, "cand", cand),
            )
        ]
    )
    return record, record["pairs"][0]


def test_identical_reports_pass_with_no_changed_seeds(compare_module, tmp_path):
    record, pair = _pair(
        compare_module, tmp_path, _report(BASE_RESULTS), _report(BASE_RESULTS)
    )
    assert record["header"]["verdict"] == "pass"
    assert pair["verdict"] == "pass"
    assert pair["changed_seeds"] == []
    assert pair["baseline"]["weak_or_worse_deaths"] == 1
    assert [row["changed"] for row in pair["seeds"]] == [False] * 4


def test_lost_success_and_new_weak_death_fail_their_gates(compare_module, tmp_path):
    cand = copy.deepcopy(BASE_RESULTS)
    cand[0] = _result(1, "death", cause="killed by a kitten", hunger="fainting")
    record, pair = _pair(compare_module, tmp_path, _report(BASE_RESULTS), _report(cand))
    assert record["header"]["verdict"] == "fail"
    assert pair["failed_gates"] == [
        "objectives_not_lower",
        "deaths_not_higher",
        "weak_or_worse_not_higher",
    ]
    (changed,) = pair["changed_seeds"]
    assert changed["seed"] == 1
    assert changed["flags"] == ["lost_success", "new_death", "new_weak_or_worse"]
    assert changed["candidate"]["hunger_at_death"] == "fainting"
    assert pair["transitions"] == {"objective_complete->death": 1}


def test_starvation_counts_as_weak_or_worse(compare_module, tmp_path):
    cand = copy.deepcopy(BASE_RESULTS)
    cand[3] = _result(4, "death", cause="died of starvation", hunger="hungry")
    _record, pair = _pair(
        compare_module, tmp_path, _report(BASE_RESULTS), _report(cand)
    )
    assert pair["gates"]["starvation_not_higher"]["passed"] is False
    assert pair["candidate"]["weak_or_worse_deaths"] == 2
    assert "new_starvation" in pair["changed_seeds"][0]["flags"]


def test_death_without_hunger_evidence_is_unknown_not_zero(compare_module, tmp_path):
    cand = copy.deepcopy(BASE_RESULTS)
    cand[1] = _result(2, "death", cause="killed by a jackal", hunger=None)
    record, pair = _pair(compare_module, tmp_path, _report(BASE_RESULTS), _report(cand))
    assert pair["gates"]["weak_or_worse_not_higher"]["passed"] is None
    assert pair["verdict"] == "unknown"
    assert record["header"]["verdict"] == "unknown"
    assert pair["candidate"]["deaths_without_hunger_evidence"] == 1


def test_quality_failures_fail_zero_gates(compare_module, tmp_path):
    cand = copy.deepcopy(BASE_RESULTS)
    cand[0]["invalid_actions"] = 2
    cand[1]["gate_rejections"] = 1
    cand[2]["integrity_ok"] = False
    _record, pair = _pair(
        compare_module, tmp_path, _report(BASE_RESULTS), _report(cand)
    )
    assert pair["failed_gates"] == [
        "zero_invalid_actions",
        "zero_gate_rejections",
        "zero_integrity_failures",
    ]
    assert pair["candidate"]["quality"]["invalid_actions"] == 2


def test_missing_seed_or_changed_cap_is_not_comparable(compare_module, tmp_path):
    cand_report = _report(BASE_RESULTS[:3])
    cand_report["case_results"][0]["requested_seeds"] = [1, 2, 3, 4]
    cand_report["case_results"][0]["max_episode_steps"] = 5000
    _record, pair = _pair(compare_module, tmp_path, _report(BASE_RESULTS), cand_report)
    assert pair["gates"]["complete_comparable_records"]["passed"] is False
    problems = " ".join(pair["comparability_problems"])
    assert "evaluated 3 of 4 requested seeds" in problems
    assert "1 baseline-only" in problems
    assert "max_episode_steps differs" in problems


def test_candidate_knowledge_and_suite_label_are_reported_not_gated(
    compare_module, tmp_path
):
    _record, pair = _pair(
        compare_module,
        tmp_path,
        _report(BASE_RESULTS),
        _report(BASE_RESULTS, suite_id="minetown-fresh-v9-q", knowledge="k-v2"),
    )
    assert pair["verdict"] == "pass"
    assert pair["comparability_problems"] == []
    assert pair["arm_differences"] == ["suite_id", "suite_sha256", "knowledge_version"]


def test_cli_writes_compact_json_and_markdown(compare_module, tmp_path):
    cand = copy.deepcopy(BASE_RESULTS)
    cand[1] = _result(2, "truncated")
    base_path = _write(tmp_path, "base", _report(BASE_RESULTS))
    cand_path = _write(tmp_path, "cand", _report(cand))
    out, md = tmp_path / "out" / "cmp.json", tmp_path / "out" / "cmp.md"
    code = compare_module.main(
        [
            "--pair",
            "mt",
            str(base_path),
            str(cand_path),
            "--base-commit",
            "abc1234",
            "--output",
            str(out),
            "--markdown",
            str(md),
        ]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    record = json.loads(text)
    assert record["header"]["base_commit"] == "abc1234"
    assert record["pairs"][0]["changed_seeds"][0]["flags"] == ["avoided_death"]
    seed_lines = [line for line in text.splitlines() if '"seed": ' in line]
    assert len(seed_lines) == 4 + 1  # one line per paired seed and changed seed
    summary = md.read_text(encoding="utf-8")
    assert "| mt, 4 | 1/2/1, 1, 0 | 1/1/2, 1, 0 | 0/0/0, 0/0/0 | pass |" in summary
    assert "avoided_death" in summary


def test_cli_rejects_duplicate_pair_names(compare_module, tmp_path, capsys):
    path = _write(tmp_path, "base", _report(BASE_RESULTS))
    code = compare_module.main(
        ["--pair", "a", str(path), str(path), "--pair", "a", str(path), str(path)]
    )
    assert code == 2
    assert "unique" in capsys.readouterr().err


def test_record_rows_still_use_shared_seed_row(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SKILL))
    record = _load("record")
    path = _write(tmp_path, "base", _report(BASE_RESULTS))
    out = record.generate_evidence_record(path, "abc", "cmd", {"2": "combat"})
    assert [row["seed"] for row in out["rows"]] == [1, 2, 3, 4]
    assert out["rows"][1] == {
        "case_id": "fresh-sample",
        "seed": 2,
        "outcome": "death",
        "steps": 500,
        "game_turns": 1000,
        "death_cause": "killed by a jackal",
        "hunger_at_death": "not_hungry",
        "max_depth": 3,
        "final_level": "0:3",
        "failure_class": "combat",
    }
