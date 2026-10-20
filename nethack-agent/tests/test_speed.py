import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nethack_agent.api import create_app
from nethack_agent.events import EventKind
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager
from nethack_agent.tasks import STAIRCASE_TASK


def manager(tmp_path: Path, **kwargs: object) -> RunManager:
    return RunManager(
        tmp_path,
        OllamaConfig(model="scripted-development"),
        model_factory=lambda _: ScriptedDevelopmentModel(),
        **kwargs,  # type: ignore[arg-type]
    )


def finish_worker(runs: RunManager, run_id: str) -> None:
    with runs._lock:
        worker = runs._runs[run_id].worker
    if worker is not None:
        worker.join(timeout=3)
        assert not worker.is_alive()


@pytest.mark.parametrize("work", [0.17, 0.7])
def test_pacing_accounts_for_step_work_without_changing_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, work: float
) -> None:
    now = 0.0
    waits: list[float] = []

    def wait(_: threading.Condition, delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    paced = manager(tmp_path / "paced", clock=lambda: now, wait=wait)
    original = paced._persist_step

    def persist(*args: object, **kwargs: object) -> None:
        nonlocal now
        original(*args, **kwargs)  # type: ignore[arg-type]
        now += work

    monkeypatch.setattr(paced, "_persist_step", persist)
    full = manager(tmp_path / "full")
    try:
        limited = paced.create_run(
            seed=6, max_episode_steps=5, auto_start=True, max_steps_per_second=2
        )
        unlimited = full.create_run(seed=6, max_episode_steps=5, auto_start=True)
        finish_worker(paced, limited.id)
        finish_worker(full, unlimited.id)
        assert paced.status(limited.id)["run"]["state"] == "terminal"
        assert waits == pytest.approx([0.5 - work] * 4 if work < 0.5 else [])
        limited_events = paced.events_after(limited.id)
        unlimited_events = full.events_after(unlimited.id)
        assert [(e.kind, e.payload.to_json()) for e in limited_events] == [
            (e.kind, e.payload.to_json()) for e in unlimited_events
        ]
    finally:
        paced.close()
        full.close()


@pytest.mark.parametrize("command", ["pause", "stop"])
def test_slow_pacing_is_interrupted_promptly(tmp_path: Path, command: str) -> None:
    waiting = threading.Event()

    def wait(condition: threading.Condition, delay: float) -> None:
        waiting.set()
        condition.wait(delay)

    runs = manager(tmp_path, wait=wait)
    try:
        run = runs.create_run(seed=6, auto_start=True, max_steps_per_second=0.2)
        assert waiting.wait(timeout=2)
        done = threading.Event()
        thread = threading.Thread(
            target=lambda: (getattr(runs, command)(run.id), done.set())
        )
        thread.start()
        assert done.wait(timeout=0.5)
        thread.join(timeout=1)
        finish_worker(runs, run.id)
        steps = [e for e in runs.events_after(run.id) if e.kind is EventKind.STEP]
        assert len(steps) == 1
    finally:
        runs.close()


@pytest.mark.parametrize("bad", [-1, "2", True, "Infinity", [], {}])
def test_api_rejects_bad_speed(tmp_path: Path, bad: object) -> None:
    with TestClient(create_app(manager(tmp_path), STAIRCASE_TASK)) as api:
        assert (
            api.post(
                "/api/runs", json={"seed": 6, "max_steps_per_second": bad}
            ).status_code
            == 422
        )
        created = api.post("/api/runs", json={"seed": 6}).json()
        run_id = created["run"]["id"]
        assert (
            api.post(
                f"/api/runs/{run_id}/speed", json={"max_steps_per_second": bad}
            ).status_code
            == 422
        )
        assert api.post(f"/api/runs/{run_id}/speed", json={}).status_code == 422


@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN", "Infinity"])
def test_api_nonfinite_speed_returns_json_422(tmp_path: Path, number: str) -> None:
    with TestClient(create_app(manager(tmp_path), STAIRCASE_TASK)) as api:
        body = '{"seed":6,"max_steps_per_second":' + number + "}"
        response = api.post(
            "/api/runs", content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
        assert response.json()["detail"]
        run_id = api.post("/api/runs", json={"seed": 6}).json()["run"]["id"]
        response = api.post(
            f"/api/runs/{run_id}/speed",
            content='{"max_steps_per_second":' + number + "}",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["detail"]


def test_api_live_speed_change_wakes_worker_and_is_not_persisted(
    tmp_path: Path,
) -> None:
    waiting = threading.Event()

    def wait(condition: threading.Condition, delay: float) -> None:
        waiting.set()
        condition.wait(delay)

    runs = manager(tmp_path, wait=wait)
    with TestClient(create_app(runs, STAIRCASE_TASK)) as api:
        created = api.post(
            "/api/runs",
            json={
                "seed": 6,
                "max_episode_steps": 5,
                "auto_start": True,
                "max_steps_per_second": 0.2,
            },
        ).json()
        run_id = created["run"]["id"]
        assert created["max_steps_per_second"] == 0.2
        assert waiting.wait(timeout=2)
        changed = api.post(
            f"/api/runs/{run_id}/speed", json={"max_steps_per_second": 0}
        )
        assert changed.status_code == 200
        assert changed.json()["max_steps_per_second"] is None
        finish_worker(runs, run_id)
        assert api.get(f"/api/runs/{run_id}").json()["run"]["state"] == "terminal"
    with TestClient(create_app(manager(tmp_path), STAIRCASE_TASK)) as api:
        status = api.get(f"/api/runs/{run_id}").json()
        assert status["coordinator"] is None
        assert status["max_steps_per_second"] is None
        assert (
            api.post(
                f"/api/runs/{run_id}/speed", json={"max_steps_per_second": 2}
            ).status_code
            == 409
        )
