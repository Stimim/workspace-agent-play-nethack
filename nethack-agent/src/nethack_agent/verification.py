from __future__ import annotations

import math
import os
import socket
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from nethack_agent.api import create_app
from nethack_agent.control_client import ControlClient
from nethack_agent.decision import RunState
from nethack_agent.model import ScriptedDevelopmentModel
from nethack_agent.network import SocketDestination, audit_loopback_connections
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager

_PROXY_SENTINEL = "http://192.0.2.1:3128"
_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_NO_PROXY_VARIABLES = ("NO_PROXY", "no_proxy")


class NetworkVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class NetworkVerificationResult:
    run_id: str
    final_state: RunState
    event_count: int
    destinations: tuple[SocketDestination, ...]
    proxy_bypass_verified: bool

    def to_json(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "final_state": self.final_state.value,
            "event_count": self.event_count,
            "destinations": [item.to_json() for item in self.destinations],
            "proxy_bypass_verified": self.proxy_bypass_verified,
        }


def verify_network_boundary(
    *, data_directory: Path | None = None, timeout_seconds: float = 10.0
) -> NetworkVerificationResult:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int | float)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError(
            "network verification timeout must be a finite number greater than zero"
        )
    timeout_seconds = float(timeout_seconds)
    if data_directory is not None:
        directory = data_directory.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return _verify_network_boundary(directory, timeout_seconds)
    with tempfile.TemporaryDirectory(prefix="nethack-network-verification-") as path:
        return _verify_network_boundary(Path(path), timeout_seconds)


def _verify_network_boundary(
    data_directory: Path, timeout_seconds: float
) -> NetworkVerificationResult:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = int(listener.getsockname()[1])
    manager = RunManager(
        data_directory,
        OllamaConfig(model="scripted-development"),
        model_factory=lambda _client: ScriptedDevelopmentModel(),
    )
    config = uvicorn.Config(
        create_app(manager),
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="network-verification-service",
        daemon=False,
    )
    run_id: str | None = None
    final_state: RunState | None = None
    events: tuple[dict[str, object], ...] = ()
    audit_destinations: tuple[SocketDestination, ...] = ()
    primary_error: BaseException | None = None

    with _proxy_environment(), audit_loopback_connections() as audit:
        try:
            server_thread.start()
            client = ControlClient(
                base_url=f"http://127.0.0.1:{port}",
                timeout_seconds=timeout_seconds,
            )
            client.wait_for_health(timeout_seconds=timeout_seconds)
            created = client.create_run(seed=6, max_episode_steps=2, auto_start=False)
            run_id = _run_id(created)
            if client.status_state(created) is not RunState.PAUSED:
                raise NetworkVerificationError("created run was not paused")
            stepped = client.control(run_id, "step")
            if client.status_state(stepped) is not RunState.PAUSED:
                raise NetworkVerificationError("scripted step did not remain paused")
            events = tuple(client.iter_events(run_id, page_limit=1))
            stopped = client.control(run_id, "stop")
            final_state = client.status_state(stopped)
            if final_state is not RunState.STOPPED:
                raise NetworkVerificationError("verification run did not stop")
            events = tuple(client.iter_events(run_id, page_limit=1))
        except BaseException as error:
            primary_error = error
        finally:
            server.should_exit = True
            if server_thread.ident is not None:
                server_thread.join(timeout=timeout_seconds)
            if server_thread.is_alive():
                server.force_exit = True
                server_thread.join(timeout=timeout_seconds)
            audit_destinations = tuple(audit.destinations)

    termination_error: Exception | None = None
    if server_thread.is_alive():
        termination_error = NetworkVerificationError(
            "verification service did not terminate"
        )
    try:
        manager.close()
    except Exception as error:
        termination_error = error
    finally:
        listener.close()
    if primary_error is not None:
        raise primary_error
    if termination_error is not None:
        raise termination_error
    if run_id is None or final_state is None:
        raise NetworkVerificationError("verification did not complete a run")
    if not audit_destinations:
        raise NetworkVerificationError("verification observed no socket destinations")
    if any(not destination.loopback for destination in audit_destinations):
        raise NetworkVerificationError(
            "verification observed a non-loopback destination"
        )
    return NetworkVerificationResult(
        run_id=run_id,
        final_state=final_state,
        event_count=len(events),
        destinations=audit_destinations,
        proxy_bypass_verified=True,
    )


def _run_id(response: dict[str, object]) -> str:
    run = response.get("run")
    if not isinstance(run, dict):
        raise NetworkVerificationError("create response omitted run")
    run_id = run.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise NetworkVerificationError("create response omitted run id")
    return run_id


@contextmanager
def _proxy_environment() -> Iterator[None]:
    names = _PROXY_VARIABLES + _NO_PROXY_VARIABLES
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in _PROXY_VARIABLES:
            os.environ[name] = _PROXY_SENTINEL
        for name in _NO_PROXY_VARIABLES:
            os.environ[name] = ""
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
