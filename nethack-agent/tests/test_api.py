import sys
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
    ModelDecision,
)
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager


class EastModel:
    def decide(self, *_: object) -> ModelDecision:
        return ModelDecision(
            ActionDecision(
                goal="explore east",
                candidates=(ActionCandidate(2, 1.0, "visible open floor"),),
                action_index=2,
                rationale="Move east into visible floor.",
            ),
            DecisionMetrics(1, 1, 1.0, False),
            "{}",
        )


class InvalidActionModel:
    def decide(self, *_: object) -> ModelDecision:
        return ModelDecision(
            ActionDecision(
                goal="invalid",
                candidates=(ActionCandidate(999, 1.0, "invalid"),),
                action_index=999,
                rationale="Invalid action.",
            ),
            DecisionMetrics(1, 1, 1.0, False),
            "{}",
        )


class InvariantFailureModel:
    def decide(self, *_: object) -> ModelDecision:
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
    assert created.json()["run"]["state"] == "paused"

    stepped = api.post(f"/api/runs/{run_id}/step")
    assert stepped.status_code == 200
    assert stepped.json()["coordinator"]["observation"]["step_index"] == 1
    assert stepped.json()["run"]["state"] == "paused"

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
    assert events[1]["payload"]["action"]["index"] == 2

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
    assert persisted.state == "stopped"
    assert persisted.ttyrec_path is not None
    assert Path(persisted.ttyrec_path).is_file()


def test_model_gate_failure_is_503_but_internal_coordinator_failure_is_500(
    tmp_path: Path,
) -> None:
    gate_manager = RunManager(
        tmp_path / "gate",
        OllamaConfig(model="test-model"),
        model_factory=lambda _: InvalidActionModel(),
    )
    gate_api = TestClient(create_app(gate_manager), raise_server_exceptions=False)
    gate_run = gate_api.post("/api/runs", json={"seed": 6}).json()["run"]["id"]
    gate_response = gate_api.post(f"/api/runs/{gate_run}/step")
    assert gate_response.status_code == 503
    assert gate_manager.store.get_run(gate_run).state == "paused"
    gate_api.post(f"/api/runs/{gate_run}/stop")

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
    assert internal_manager.store.get_run(internal_run).state == "error"
