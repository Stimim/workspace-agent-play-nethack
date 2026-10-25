"""Tests for the evidence-record skill's stall and loop diagnostics (ADR 0008)."""

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "_agents/skills/evidence-record"


@pytest.fixture
def stalls():
    spec = importlib.util.spec_from_file_location("stalls", SKILL / "stalls.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["stalls"] = module
    spec.loader.exec_module(module)
    return module


def _step(level, turn, *, source="arbiter", rationale="Explore."):
    return {
        "observation": {
            "player": {"dungeon_number": 0, "dungeon_level": level, "turn": turn}
        },
        "selection": {"source": source, "rationale": rationale},
    }


def _database(path, runs):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE runs (id TEXT, suite_seed INTEGER, outcome TEXT)")
    connection.execute(
        "CREATE TABLE events (run_id TEXT, sequence INTEGER, kind TEXT, payload_json TEXT)"
    )
    for seed, steps in runs.items():
        run_id = f"run-{seed}"
        connection.execute("INSERT INTO runs VALUES (?, ?, 'death')", (run_id, seed))
        connection.execute(
            "INSERT INTO events VALUES (?, 0, 'run_started', '{}')", (run_id,)
        )
        for sequence, step in enumerate(steps, 1):
            connection.execute(
                "INSERT INTO events VALUES (?, ?, 'step', ?)",
                (run_id, sequence, json.dumps(step)),
            )
    connection.commit()
    connection.close()
    return path


def test_contiguous_stay_over_limit_is_a_stall(stalls):
    rows = [(0, 1, 1, None, None), (0, 1, 1002, None, None)]
    assert stalls.run_diagnostics(rows)["stalled"]
    assert not stalls.run_diagnostics(
        [(0, 1, 1, None, None), (0, 1, 1001, None, None)]
    )["stalled"]


def test_split_visits_and_death_screen_do_not_stall(stalls):
    rows = [
        (0, 2, 10, None, None),
        (0, 2, 700, None, None),
        (0, 3, 701, None, None),
        (0, 2, 702, None, None),
        (0, 2, 1400, None, None),
        (0, 0, 0, None, None),  # zeroed death screen
    ]
    result = stalls.run_diagnostics(rows)
    assert result["longest_stay_turns"] == 698
    assert not result["stalled"]
    assert result["longest_stay_level"] == {"dungeon_number": 0, "dungeon_level": 2}


def test_arrive_then_leave_and_fallback_steps(stalls):
    spot = "Move to search spot ({}, {}) ({} steps); no reachable unexplored space."
    rows = [
        (0, 1, 1, None, spot.format(15, 8, 2)),
        (0, 1, 2, None, spot.format(15, 8, 1)),
        (0, 1, 3, None, spot.format(74, 2, 76)),  # left without searching
        (0, 1, 4, "model_fallback", "Wait."),
        (0, 1, 5, None, spot.format(74, 2, 1)),
        (0, 1, 6, None, spot.format(74, 2, 0)),  # stayed: not a departure
    ]
    result = stalls.run_diagnostics(rows)
    assert result["arrive_then_leave"] == 1
    assert result["model_fallback_steps"] == 1


def test_pair_flags_new_and_removed_stalls(stalls, tmp_path, capsys):
    long_stay = [_step(2, 1), _step(2, 1500)]
    short_stay = [_step(2, 1), _step(3, 900)]
    base = _database(tmp_path / "base.sqlite3", {1: long_stay, 2: short_stay})
    cand = _database(tmp_path / "cand.sqlite3", {1: short_stay, 2: long_stay})
    output = tmp_path / "stalls.json"
    assert (
        stalls.main(["--pair", "mt", str(base), str(cand), "--output", str(output)])
        == 0
    )
    record = json.loads(output.read_text())
    pair = record["pairs"][0]
    assert pair["baseline"]["stalled_runs"] == pair["candidate"]["stalled_runs"] == 1
    assert {row["seed"]: row["flags"] for row in pair["changed_seeds"]} == {
        1: ["removed_stall"],
        2: ["new_stall"],
    }
    assert "| mt | 1 -> 1 |" in capsys.readouterr().out


def test_databases_are_opened_read_only(stalls, tmp_path):
    database = _database(tmp_path / "arm.sqlite3", {1: [_step(1, 1)]})
    before = database.stat().st_mtime_ns
    stalls.load_arm(database)
    assert database.stat().st_mtime_ns == before
    assert not (tmp_path / "arm.sqlite3-wal").exists()
