from __future__ import annotations

import math
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from nethack_agent.control_client import (
    ControlClient,
    ControlClientError,
    ControlWaitTimeout,
    MalformedControlResponse,
)
from nethack_agent.decision import RunState
from nethack_agent.network import LoopbackUrlError, normalize_loopback_http_url

_ACTIVE_STATES = frozenset({RunState.IDLE, RunState.RUNNING, RunState.PAUSED})


class ScenarioError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScenarioRunConfig:
    seed: int
    max_episode_steps: int
    data_directory: Path
    host: str = "127.0.0.1"
    port: int = 8000
    timeout_seconds: float = 300.0
    auto_run: bool = False
    steps: int | None = None
    development_scripted_model: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.host, str):
            raise TypeError("scenario host must be a string")
        if not isinstance(self.auto_run, bool):
            raise TypeError("scenario auto_run must be a boolean")
        if not isinstance(self.development_scripted_model, bool):
            raise TypeError("scenario development model flag must be a boolean")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("scenario seed must be an integer")
        if not 1 <= self.seed <= sys.maxsize:
            raise ValueError(f"scenario seed must be between 1 and {sys.maxsize}")
        if isinstance(self.max_episode_steps, bool) or not isinstance(
            self.max_episode_steps, int
        ):
            raise TypeError("scenario max steps must be an integer")
        if not 1 <= self.max_episode_steps <= 100_000:
            raise ValueError("scenario max steps must be between 1 and 100000")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65_535
        ):
            raise ValueError("scenario port must be an integer between 1 and 65535")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError(
                "scenario timeout must be a finite number greater than zero"
            )
        if self.auto_run == (self.steps is not None):
            raise ValueError(
                "scenario requires exactly one of auto_run or bounded steps"
            )
        if self.steps is not None and (
            isinstance(self.steps, bool)
            or not isinstance(self.steps, int)
            or self.steps <= 0
        ):
            raise ValueError("scenario steps must be a positive integer")
        data_directory = Path(self.data_directory).expanduser().resolve()
        if data_directory.exists() and not data_directory.is_dir():
            raise ValueError("scenario data directory must be a directory")
        object.__setattr__(self, "data_directory", data_directory)
        try:
            normalized = normalize_loopback_http_url(_http_url(self.host, self.port))
        except LoopbackUrlError as error:
            raise ValueError(f"invalid scenario host: {error}") from error
        object.__setattr__(self, "host", _url_host(normalized))

    @property
    def base_url(self) -> str:
        return normalize_loopback_http_url(_http_url(self.host, self.port))


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    service_pid: int
    service_return_code: int
    run_id: str
    execution_state: RunState
    final_status: dict[str, Any]
    events: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, object]:
        return {
            "service_pid": self.service_pid,
            "service_return_code": self.service_return_code,
            "run_id": self.run_id,
            "execution_state": self.execution_state.value,
            "final_status": self.final_status,
            "events": list(self.events),
        }


@dataclass(slots=True)
class ServiceProcess:
    process: subprocess.Popen[bytes]
    command: tuple[str, ...]

    @classmethod
    def launch(
        cls,
        config: ScenarioRunConfig,
        *,
        python_executable: str = sys.executable,
    ) -> Self:
        command = [
            python_executable,
            "-m",
            "nethack_agent",
            "serve",
            "--host",
            config.host,
            "--port",
            str(config.port),
            "--data-dir",
            str(config.data_directory),
        ]
        if config.development_scripted_model:
            command.append("--development-scripted-model")
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
        return cls(process, tuple(command))

    @classmethod
    def launch_command(cls, command: tuple[str, ...]) -> Self:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return cls(process, command)

    def terminate(self, *, timeout_seconds: float = 5.0) -> int:
        timeout = _positive_finite(timeout_seconds, "service shutdown timeout")
        return_code = self.process.poll()
        if return_code is not None:
            self.process.wait(timeout=0)
            return return_code
        self.process.terminate()
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            return self.process.wait(timeout=timeout)


def wait_for_service(
    service: ServiceProcess,
    client: ControlClient,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.05,
) -> dict[str, Any]:
    timeout = _positive_finite(timeout_seconds, "service readiness timeout")
    poll_interval = _positive_finite(
        poll_interval_seconds, "service readiness poll interval"
    )
    deadline = time.monotonic() + timeout
    last_error: ControlClientError | None = None
    while True:
        return_code = service.process.poll()
        if return_code is not None:
            service.process.wait(timeout=0)
            raise ScenarioError(
                f"control service exited before readiness with code {return_code}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = f": {last_error}" if last_error else ""
            raise ControlWaitTimeout(f"control service readiness timed out{detail}")
        try:
            return client.health(timeout_seconds=min(client.timeout_seconds, remaining))
        except MalformedControlResponse:
            raise
        except ControlClientError as error:
            last_error = error
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


def run_scenario(config: ScenarioRunConfig) -> ScenarioResult:
    deadline = time.monotonic() + config.timeout_seconds
    client = ControlClient(
        base_url=config.base_url,
        timeout_seconds=min(config.timeout_seconds, 5.0),
    )
    service = ServiceProcess.launch(config)
    run_id: str | None = None
    execution_status: dict[str, Any] | None = None
    final_status: dict[str, Any] | None = None
    events: tuple[dict[str, Any], ...] = ()
    primary_error: BaseException | None = None
    cleanup_errors: list[Exception] = []
    return_code: int | None = None

    try:
        wait_for_service(
            service,
            client,
            timeout_seconds=_remaining(deadline),
        )
        execution_status = client.create_run(
            seed=config.seed,
            max_episode_steps=config.max_episode_steps,
            auto_start=config.auto_run,
        )
        run_id = _status_run_id(execution_status)
        if config.auto_run:
            execution_status = client.wait_for_state(
                run_id,
                {RunState.TERMINAL},
                timeout_seconds=_remaining(deadline),
            )
        elif config.steps is not None:
            for _ in range(config.steps):
                state = client.status_state(execution_status)
                if state not in _ACTIVE_STATES:
                    break
                if state is not RunState.PAUSED:
                    execution_status = client.wait_for_state(
                        run_id,
                        {RunState.PAUSED},
                        timeout_seconds=_remaining(deadline),
                    )
                execution_status = client.control(run_id, "step")
    except BaseException as error:
        primary_error = error
    finally:
        if run_id is not None:
            try:
                current = client.status(run_id, timeout_seconds=1.0)
                if client.status_state(current) in _ACTIVE_STATES:
                    final_status = client.control(run_id, "stop")
                else:
                    final_status = current
            except Exception as error:
                cleanup_errors.append(error)
            try:
                events = tuple(client.iter_events(run_id, page_limit=100))
            except Exception as error:
                cleanup_errors.append(error)
        try:
            return_code = service.terminate(timeout_seconds=5.0)
        except Exception as error:
            cleanup_errors.append(error)

    if primary_error is not None:
        raise primary_error
    if cleanup_errors:
        details = "; ".join(str(error) for error in cleanup_errors)
        raise ScenarioError(f"scenario cleanup failed: {details}")
    if run_id is None or execution_status is None or final_status is None:
        raise ScenarioError("scenario finished without complete run status")
    if return_code is None:
        raise ScenarioError("control service was not reaped")
    return ScenarioResult(
        service_pid=service.process.pid,
        service_return_code=return_code,
        run_id=run_id,
        execution_state=client.status_state(execution_status),
        final_status=final_status,
        events=events,
    )


def _status_run_id(response: object) -> str:
    ControlClient.status_state(response)
    assert isinstance(response, dict)
    run = response.get("run")
    assert isinstance(run, dict)
    run_id = run.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise MalformedControlResponse(
            "run status response must contain a nonempty run.id"
        )
    return run_id


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ControlWaitTimeout("scenario deadline expired")
    return remaining


def _positive_finite(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a finite number greater than zero")
    return float(value)


def _http_url(host: str, port: int) -> str:
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return f"http://{authority}"


def _url_host(url: str) -> str:
    hostname = urllib.parse.urlsplit(url).hostname
    assert hostname is not None
    return hostname
