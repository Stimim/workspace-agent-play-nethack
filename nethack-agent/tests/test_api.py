import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nethack_agent.api import create_app
from nethack_agent.coordinator import CoordinatorInvariantError
from nethack_agent.decision import (
    ActionCandidate,
    ActionDecision,
    DecisionMetrics,
    ModelActionDecision,
    ModelSkillDecision,
    RunState,
    Skill,
    SkillDecision,
)
from nethack_agent.model import DecisionFailure
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager
from nethack_agent.traversal import STAND_ON_DOWNSTAIRS

_METRICS = DecisionMetrics(1, 1, 1.0, False)


class EastModel:
    def select_skill(self, *_: object) -> ModelSkillDecision:
        return ModelSkillDecision(
            SkillDecision(
                STAND_ON_DOWNSTAIRS,
                Skill.STAIRCASE_NAVIGATION,
                "Use staircase navigation.",
            ),
            _METRICS,
            "{}",
        )

    def select_action(self, *_: object) -> ModelActionDecision:
        return ModelActionDecision(
            ActionDecision(
                candidates=(ActionCandidate(2, 1.0, "visible open floor"),),
                action_index=2,
                rationale="Move east into visible floor.",
            ),
            _METRICS,
            "{}",
        )


class FailingSkillModel(EastModel):
    def select_skill(self, *_: object) -> ModelSkillDecision:
        raise DecisionFailure("malformed after repair")


class InvariantFailureModel(EastModel):
    def select_skill(self, *_: object) -> ModelSkillDecision:
        raise CoordinatorInvariantError("internal invariant failed")


def client(tmp_path: Path) -> TestClient:
    manager = RunManager(
        tmp_path,
        OllamaConfig(model="test-model"),
        model_factory=lambda _: EastModel(),
    )
    return TestClient(create_app(manager))


def test_api_controls_run_and_persists_step_and_ttyrec(tmp_path: Path) -> None:
    api = client(tmp_path)
    created = api.post(
        "/api/runs",
        json={"seed": 6, "max_episode_steps": 20, "auto_start": False},
    )
    assert created.status_code == 201
    run_id = created.json()["run"]["id"]
    assert created.json()["coordinator"]["current_goal"] == (
        STAND_ON_DOWNSTAIRS.to_json()
    )
    assert created.json()["coordinator"]["current_skill"] is None
    assert created.json()["run"]["state"] == "paused"

    stepped = api.post(f"/api/runs/{run_id}/step")
    assert stepped.status_code == 200
    assert stepped.json()["coordinator"]["observation"]["step_index"] == 1
    assert stepped.json()["run"]["state"] == "paused"
    assert stepped.json()["coordinator"]["current_skill"] == "explore_level"

    stopped = api.post(f"/api/runs/{run_id}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["run"]["state"] == "stopped"
    ttyrec_path = Path(stopped.json()["run"]["ttyrec_path"])
    assert ttyrec_path.is_file()

    events = api.get(f"/api/runs/{run_id}/events").json()["events"]
    assert [event["kind"] for event in events] == [
        "run_started",
        "step",
        "run_stopped",
    ]
    step = events[1]["payload"]
    assert step["skill_decision"]["skill"] == "staircase_navigation"
    assert step["action_decision"] is None
    selection = step["selection"]
    assert selection["action_index"] == step["action"]["index"]
    assert {
        key: selection[key]
        for key in ("source", "goal", "skill", "skill_selection", "stuck_reason")
    } == {
        "source": "deterministic_skill",
        "goal": STAND_ON_DOWNSTAIRS.to_json(),
        "skill": "explore_level",
        "skill_selection": "arbiter",
        "stuck_reason": None,
    }
    # The skill's route goal, two steps away, not the cell stepped into, and
    # the route the step followed: the hero now stands on its first cell.
    assert selection["intent"] == {
        "destination": {"kind": "frontier", "x": 57, "y": 11},
        "attack_target": None,
        "path": [{"x": 58, "y": 12}, {"x": 57, "y": 11}],
    }
    player = step["observation"]["player"]
    assert (player["x"], player["y"]) == (58, 12)
    with api.websocket_connect(f"/api/runs/{run_id}/events/ws") as websocket:
        assert websocket.receive_json()["kind"] == "run_started"


def test_api_rejects_second_active_run(tmp_path: Path) -> None:
    api = client(tmp_path)
    first = api.post("/api/runs", json={"seed": 6})
    assert first.status_code == 201

    second = api.post("/api/runs", json={"seed": 7})

    assert second.status_code == 409
    assert second.json()["detail"] == "only one active run is supported"
    api.post(f"/api/runs/{first.json()['run']['id']}/stop")


@pytest.mark.parametrize(
    "payload",
    [
        {"seed": True},
        {"seed": "6"},
        {"seed": sys.maxsize + 1},
        {"seed": 6, "max_episode_steps": True},
        {"seed": 6, "auto_start": 1},
    ],
)
def test_create_request_uses_strict_domain_validation(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    response = client(tmp_path).post("/api/runs", json=payload)

    assert response.status_code == 422


def test_event_http_and_websocket_replay_are_paginated(tmp_path: Path) -> None:
    api = client(tmp_path)
    created = api.post("/api/runs", json={"seed": 6})
    run_id = created.json()["run"]["id"]
    api.post(f"/api/runs/{run_id}/stop")

    first = api.get(f"/api/runs/{run_id}/events?limit=1").json()
    second = api.get(
        f"/api/runs/{run_id}/events?after={first['next_after']}&limit=1"
    ).json()

    assert [event["kind"] for event in first["events"]] == ["run_started"]
    assert first["has_more"]
    assert [event["kind"] for event in second["events"]] == ["run_stopped"]
    assert not second["has_more"]
    with api.websocket_connect(f"/api/runs/{run_id}/events/ws?limit=1") as websocket:
        assert websocket.receive_json()["kind"] == "run_started"
        assert websocket.receive_json()["kind"] == "run_stopped"


def test_websocket_unknown_run_has_distinct_not_found_close(tmp_path: Path) -> None:
    api = client(tmp_path)

    with (
        pytest.raises(WebSocketDisconnect) as raised,
        api.websocket_connect("/api/runs/missing/events/ws"),
    ):
        pass

    assert raised.value.code == 4404
    assert raised.value.reason == "run not found"


def test_disconnected_paused_websocket_and_service_shutdown_finalize_run(
    tmp_path: Path,
) -> None:
    manager = RunManager(
        tmp_path,
        OllamaConfig(model="test-model"),
        model_factory=lambda _: EastModel(),
    )
    with TestClient(create_app(manager)) as api:
        created = api.post("/api/runs", json={"seed": 6})
        run_id = created.json()["run"]["id"]
        with api.websocket_connect(f"/api/runs/{run_id}/events/ws") as websocket:
            assert websocket.receive_json()["kind"] == "run_started"

    persisted = manager.store.get_run(run_id)
    assert persisted.state is RunState.STOPPED
    assert persisted.ttyrec_path is not None
    assert Path(persisted.ttyrec_path).is_file()


def test_model_failure_is_503_but_internal_coordinator_failure_is_500(
    tmp_path: Path,
) -> None:
    failing_manager = RunManager(
        tmp_path / "model",
        OllamaConfig(model="test-model"),
        model_factory=lambda _: FailingSkillModel(),
    )
    failing_api = TestClient(create_app(failing_manager), raise_server_exceptions=False)
    failing_run = failing_api.post("/api/runs", json={"seed": 6}).json()["run"]["id"]
    failing_response = failing_api.post(f"/api/runs/{failing_run}/step")
    assert failing_response.status_code == 503
    assert failing_manager.store.get_run(failing_run).state is RunState.PAUSED
    failing_api.post(f"/api/runs/{failing_run}/stop")

    internal_manager = RunManager(
        tmp_path / "internal",
        OllamaConfig(model="test-model"),
        model_factory=lambda _: InvariantFailureModel(),
    )
    internal_api = TestClient(
        create_app(internal_manager), raise_server_exceptions=False
    )
    internal_run = internal_api.post("/api/runs", json={"seed": 6}).json()["run"]["id"]
    internal_response = internal_api.post(f"/api/runs/{internal_run}/step")
    assert internal_response.status_code == 500
    assert internal_manager.store.get_run(internal_run).state is RunState.ERROR


def test_events_stored_in_the_milestone_1_shape_remain_readable(
    tmp_path: Path, to_milestone_1_shape: Callable[[Path], int]
) -> None:
    api = client(tmp_path)
    run_id = api.post("/api/runs", json={"seed": 6}).json()["run"]["id"]
    api.post(f"/api/runs/{run_id}/step")
    api.post(f"/api/runs/{run_id}/stop")
    assert to_milestone_1_shape(tmp_path / "runs.sqlite3") == 2
    with sqlite3.connect(tmp_path / "runs.sqlite3") as connection:
        stored = [
            json.loads(text)
            for (text,) in connection.execute(
                "SELECT payload_json FROM events ORDER BY sequence"
            )
        ]
    assert stored[0]["goal"] == "stand_on_downstairs"
    assert stored[1]["selection"]["goal"] == "stand_on_downstairs"
    assert stored[1]["skill_decision"]["goal"] == "stand_on_downstairs"

    # A restarted service reads the legacy records through the strict store.
    restarted = client(tmp_path)
    response = restarted.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["kind"] for event in events] == ["run_started", "step", "run_stopped"]
    step = events[1]["payload"]["observation"]
    assert events[0]["payload"]["observation"]["map"]["pet_rows"] is None
    assert step["map"]["pet_rows"] is None
    assert step["changed_cells"]
    assert all(cell["pet"] is None for cell in step["changed_cells"])
    # No intent was recorded, so none is served.
    assert events[1]["payload"]["selection"]["intent"] is None
    # The legacy goal string is the typed goal it always meant.
    staircase_goal = STAND_ON_DOWNSTAIRS.to_json()
    assert events[0]["payload"]["goal"] == staircase_goal
    assert events[1]["payload"]["selection"]["goal"] == staircase_goal
    assert events[1]["payload"]["skill_decision"]["goal"] == staircase_goal
    assert restarted.get(f"/api/runs/{run_id}").status_code == 200


def test_intents_stored_without_a_path_are_served_with_an_unknown_path(
    tmp_path: Path, to_pathless_intent_shape: Callable[[Path], int]
) -> None:
    api = client(tmp_path)
    run_id = api.post("/api/runs", json={"seed": 6}).json()["run"]["id"]
    api.post(f"/api/runs/{run_id}/step")
    api.post(f"/api/runs/{run_id}/stop")
    assert to_pathless_intent_shape(tmp_path / "runs.sqlite3") == 1

    restarted = client(tmp_path)
    response = restarted.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200
    # The recorded targets stay; the unrecorded route is null, not guessed.
    assert response.json()["events"][1]["payload"]["selection"]["intent"] == {
        "destination": {"kind": "frontier", "x": 57, "y": 11},
        "attack_target": None,
        "path": None,
    }
