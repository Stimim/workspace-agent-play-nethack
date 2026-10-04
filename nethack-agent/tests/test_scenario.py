from __future__ import annotations

import os
import signal
import socket
import sys

import pytest

import nethack_agent.scenario as scenario_module
from nethack_agent.control_client import ControlClientError, ControlWaitTimeout
from nethack_agent.decision import RunState
from nethack_agent.scenario import (
    ScenarioRunConfig,
    ServiceProcess,
    run_scenario,
    wait_for_service,
)
from nethack_agent.tasks import ActionProfile, NleTask, TaskSpec
from nethack_agent.traversal import ExploreDungeonLeg, Objective


@pytest.mark.parametrize(
    ("task", "seed", "max_level"),
    [(NleTask.SCOUT, 53, 3), (NleTask.EAT, 824, 5)],
)
def test_scout_and_eat_run_with_survival_profile(
    tmp_path, task: NleTask, seed: int, max_level: int
) -> None:
    spec = TaskSpec(
        task,
        ActionProfile.NLE_SURVIVAL_ACTIONS,
        Objective((ExploreDungeonLeg(max_level),)),
    )
    result = run_scenario(
        ScenarioRunConfig(
            seed=seed,
            max_episode_steps=100,
            data_directory=tmp_path / task.name,
            port=_unused_port(),
            timeout_seconds=60.0,
            auto_run=True,
            development_scripted_model=True,
            task=spec,
        )
    )

    assert result.execution_state is RunState.TERMINAL
    steps = [event for event in result.events if event["kind"] == "step"]
    assert steps
    assert result.final_status["run"]["state"] == RunState.TERMINAL.value


class _UnavailableClient:
    timeout_seconds = 0.01

    def health(self, *, timeout_seconds: float) -> dict[str, object]:
        assert timeout_seconds > 0
        raise ControlClientError("not ready")


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_readiness_timeout_still_terminates_and_reaps_child() -> None:
    service = ServiceProcess.launch_command(
        (sys.executable, "-c", "import time; time.sleep(60)")
    )
    try:
        with pytest.raises(ControlWaitTimeout, match="readiness timed out"):
            wait_for_service(
                service,
                _UnavailableClient(),  # type: ignore[arg-type]
                timeout_seconds=0.03,
                poll_interval_seconds=0.005,
            )
    finally:
        service.terminate(timeout_seconds=1.0)

    assert service.process.poll() is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(service.process.pid, os.WNOHANG)


def test_scenario_stops_run_and_gracefully_reaps_service(tmp_path) -> None:
    result = run_scenario(
        ScenarioRunConfig(
            seed=6,
            max_episode_steps=3,
            data_directory=tmp_path,
            port=_unused_port(),
            timeout_seconds=20.0,
            steps=1,
            development_scripted_model=True,
        )
    )

    assert result.execution_state is RunState.PAUSED
    assert result.service_return_code == -signal.SIGTERM
    assert result.final_status["run"]["state"] == RunState.STOPPED.value
    assert {event["kind"] for event in result.events} >= {
        "run_started",
        "step",
        "run_stopped",
    }
    assert list(tmp_path.rglob("*.ttyrec*.bz2"))
    with pytest.raises(ChildProcessError):
        os.waitpid(result.service_pid, os.WNOHANG)


def test_auto_scenario_waits_for_terminal_state(tmp_path) -> None:
    result = run_scenario(
        ScenarioRunConfig(
            seed=6,
            max_episode_steps=1,
            data_directory=tmp_path,
            port=_unused_port(),
            timeout_seconds=20.0,
            auto_run=True,
            development_scripted_model=True,
        )
    )

    assert result.execution_state is RunState.TERMINAL
    assert result.final_status["run"]["state"] == RunState.TERMINAL.value
    assert result.service_return_code == -signal.SIGTERM
    assert "step" in {event["kind"] for event in result.events}
    with pytest.raises(ChildProcessError):
        os.waitpid(result.service_pid, os.WNOHANG)


def test_interruption_stops_active_run_and_terminates_service(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations: list[str] = []

    class InterruptedClient:
        timeout_seconds = 1.0

        def __init__(self, **_kwargs) -> None:
            pass

        def create_run(self, **_kwargs):
            return {"run": {"id": "run-1", "state": "paused"}}

        @staticmethod
        def status_state(response):
            return RunState(response["run"]["state"])

        def status(self, _run_id, **_kwargs):
            return {"run": {"id": "run-1", "state": "paused"}}

        def control(self, _run_id, operation):
            operations.append(operation)
            if operation == "step":
                raise KeyboardInterrupt
            return {"run": {"id": "run-1", "state": "stopped"}}

        def iter_events(self, _run_id, **_kwargs):
            return iter(())

    class InterruptedService:
        terminated = False

        def terminate(self, **_kwargs):
            self.terminated = True
            return -signal.SIGTERM

    service = InterruptedService()
    monkeypatch.setattr(scenario_module, "ControlClient", InterruptedClient)
    monkeypatch.setattr(
        scenario_module.ServiceProcess,
        "launch",
        staticmethod(lambda _config: service),
    )
    monkeypatch.setattr(
        scenario_module, "wait_for_service", lambda *_args, **_kwargs: {}
    )

    with pytest.raises(KeyboardInterrupt):
        run_scenario(
            ScenarioRunConfig(
                seed=6,
                max_episode_steps=3,
                data_directory=tmp_path,
                steps=1,
            )
        )

    assert operations == ["step", "stop"]
    assert service.terminated


def test_scenario_configuration_requires_loopback_and_one_mode(tmp_path) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ScenarioRunConfig(seed=6, max_episode_steps=3, data_directory=tmp_path)
    with pytest.raises(ValueError, match="invalid scenario host"):
        ScenarioRunConfig(
            seed=6,
            max_episode_steps=3,
            data_directory=tmp_path,
            host="192.0.2.1",
            steps=1,
        )
