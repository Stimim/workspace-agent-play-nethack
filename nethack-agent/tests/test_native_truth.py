"""Diagnosis-only skill tests; product code must never import native truth."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from nle import nethack

from nethack_agent.coordinator import AgentCoordinator
from nethack_agent.environment import NleEnvironment, NleObservation, ScenarioConfig
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.observation import ObservationProjector
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager

SKILL = Path(__file__).resolve().parents[2] / "_agents/skills/native-truth"


@pytest.fixture
def native_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(SKILL))
    import native_truth

    spec = importlib.util.spec_from_file_location(
        "native_truth_replay", SKILL / "replay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return native_truth, module


def test_attach_validates_hero_and_rejects_wrong_observation(tmp_path, native_modules):
    native, _ = native_modules
    with NleEnvironment(ScenarioConfig(6, tmp_path)) as env:
        observation = env.reset()
        with native.NativeTruth(env, observation) as truth:
            snapshot = truth.snapshot(observation)
            assert snapshot["hero"] == {
                "x": int(observation.blstats[nethack.NLE_BL_X]),
                "y": int(observation.blstats[nethack.NLE_BL_Y]),
                "dnum": int(observation.blstats[nethack.NLE_BL_DNUM]),
                "dlevel": int(observation.blstats[nethack.NLE_BL_DLEVEL]),
            }
            assert snapshot["dungeon_name"] == "The Dungeons of Doom"
            assert (
                snapshot["terrain"][snapshot["hero"]["y"]][snapshot["hero"]["x"]][
                    "terrain"
                ]
                == "STAIRS"
            )
            original = observation.blstats[0]
            observation.blstats[0] += 1
            try:
                with pytest.raises(native.ValidationError, match="native hero"):
                    truth.validate(observation)
            finally:
                observation.blstats[0] = original


def test_instances_with_identical_seeds_attach_to_their_own_memfd(
    tmp_path, native_modules
):
    native, _ = native_modules
    with (
        NleEnvironment(ScenarioConfig(6, tmp_path / "one")) as first,
        NleEnvironment(ScenarioConfig(6, tmp_path / "two")) as second,
    ):
        a, b = first.reset(), second.reset()
        with (
            native.NativeTruth(first, a) as left,
            native.NativeTruth(second, b) as right,
        ):
            assert left.inode != right.inode
            first.step(
                next(
                    action.index
                    for action in first.legal_actions
                    if action.name == "Command.SEARCH"
                )
            )
            assert right.snapshot(b)["hero"] == left.snapshot(a)["hero"]


def test_committed_seed_two_visible_downstairs_agrees(tmp_path, native_modules):
    native, _ = native_modules
    env = NleEnvironment(ScenarioConfig(2, tmp_path, max_episode_steps=200))
    agent = AgentCoordinator(env, ObservationProjector(), ScriptedDevelopmentModel())
    observation = agent.start()
    try:
        # Seed 2 is in the committed staircase evaluation suite. Its early
        # public downstairs observation supplies independent native evidence.
        raw = NleObservation.from_nle(env._raw_environment.nethack._obs_buffers)
        with native.NativeTruth(env, raw) as truth:
            for _ in range(100):
                cells = [
                    (x, y)
                    for y, row in enumerate(observation.map.glyph_rows)
                    for x, glyph in enumerate(row)
                    if glyph == nethack.GLYPH_CMAP_OFF + 24
                ]
                if cells:
                    snapshot = truth.snapshot(raw)
                    downstairs = snapshot["stairs"]["dnstair"]
                    assert snapshot["validation"]["visible_stairs_checked"] >= 1
                    assert cells == [(downstairs["x"], downstairs["y"])]
                    break
                record = agent.advance(single_step=True)
                assert record is not None
                observation = record.after
            else:
                pytest.fail(
                    "committed seed 2 downstairs was not visible in the early prefix"
                )
    finally:
        agent.stop()


def test_short_recorded_scripted_episode_replays_and_rejects_corruption(
    tmp_path, native_modules
):
    _, replay = native_modules
    manager = RunManager(
        tmp_path,
        OllamaConfig(model="test-model"),
        model_factory=lambda _: ScriptedDevelopmentModel(),
    )
    try:
        run = manager.create_run(seed=1, max_episode_steps=6)
        for _ in range(6):
            manager.step(run.id)
    finally:
        manager.close()
    database = tmp_path / "runs.sqlite3"
    result = replay.replay(
        database, run_id=run.id, at=("0", "end"), every_level_entry=True
    )
    assert result["recorded_actions"] == 6
    assert result["observation_comparisons"] == 7
    assert [snapshot["step"] for snapshot in result["snapshots"]] == [0, 6]
    assert result["snapshots"][-1]["hero"]["dlevel"] == 1
    assert "@" in result["snapshots"][-1]["ascii"]
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT id,payload_json FROM events WHERE kind='step' "
            "ORDER BY sequence LIMIT 1"
        ).fetchone()
        payload = json.loads(row[1])
        payload["observation"]["player"]["hit_points"] += 1
        connection.execute(
            "UPDATE events SET payload_json=? WHERE id=?", (json.dumps(payload), row[0])
        )
    with pytest.raises(replay.ReplayMismatch, match="observation mismatch at step 1"):
        replay.replay(database, seed=1)


@pytest.mark.parametrize(
    "flags,expected", [(1, "CLOSED"), (2, "CLOSED"), (7, "CLOSED"), (9, "LOCKED")]
)
def test_secret_wall_mode_is_not_door_state(native_modules, flags, expected):
    native, _ = native_modules
    assert native.door_state(14, flags) == expected


def test_terminal_snapshot_contains_static_data_only(tmp_path, native_modules):
    native, _ = native_modules
    with NleEnvironment(ScenarioConfig(6, tmp_path, max_episode_steps=1)) as env:
        raw = env.reset()
        with native.NativeTruth(env, raw) as truth:
            before = truth.snapshot(raw)
            transition = env.step(0)
            assert transition.is_terminal
            after = truth.snapshot(transition.observation)
            assert after["hero"] == before["hero"]
            assert after["stairs"] == before["stairs"]
            assert after["dynamic_status"] == "unavailable_post_terminal"
            assert "traps" not in after and "boulders" not in after


def test_route_reports_secret_and_locked_cutsets(native_modules):
    native, replay = native_modules
    stone = {"typ": 0, "door_state": None}
    grid = [[stone.copy() for _ in range(79)] for _ in range(21)]
    for x in range(1, 8):
        grid[1][x] = {"typ": 23, "door_state": None}
    grid[1][3] = {"typ": 14, "door_state": native.door_state(14, 7)}
    grid[1][5] = {"typ": 22, "door_state": "LOCKED"}
    snapshot = {
        "terrain": grid,
        "hero": {"x": 1, "y": 1},
        "stairs": {"dnstair": {"x": 7, "y": 1}},
        "dynamic_status": "live",
    }
    diagnosis = replay.analyze(snapshot)
    assert diagnosis["shortest"]["steps"] == 6
    assert diagnosis["shortest"]["classes"] == ["locked", "secret"]
    assert diagnosis["minimal_blocker_sets"] == [["secret", "locked"]]
    assert diagnosis["held_blocked"]["secret"] is None
    assert diagnosis["held_blocked"]["locked"] is None
    assert diagnosis["held_blocked"]["closed"]["steps"] == 6
