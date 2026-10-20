from __future__ import annotations

import json
from typing import Any

import pytest

from nethack_agent import cli
from nethack_agent.control_client import ControlClient


@pytest.mark.parametrize("limit", [None, "0", "2.5"])
def test_run_start_speed_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    limit: str | None,
) -> None:
    requests: list[tuple[str, str, object]] = []
    status = {"run": {"id": "run-1", "state": "paused"}}

    def request(
        _self: ControlClient, method: str, path: str, payload: object
    ) -> dict[str, Any]:
        requests.append((method, path, payload))
        return status

    client = ControlClient()
    monkeypatch.setattr(
        ControlClient, "from_environment", classmethod(lambda _cls: client)
    )
    monkeypatch.setattr(ControlClient, "_request", request)
    arguments = ["run", "start", "--seed", "6"]
    if limit is not None:
        arguments.extend(["--max-steps-per-second", limit])

    assert cli.main(arguments) == 0

    payload: dict[str, object] = {
        "seed": 6,
        "max_episode_steps": 5_000,
        "auto_start": False,
    }
    if limit is not None:
        payload["max_steps_per_second"] = float(limit)
    assert requests == [("POST", "/api/runs", payload)]
    assert json.loads(capsys.readouterr().out) == status


@pytest.mark.parametrize("limit", ["0", "2.5"])
def test_run_speed_posts_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    limit: str,
) -> None:
    requests: list[tuple[str, str, object]] = []
    status = {"run": {"id": "run-1", "state": "running"}}

    def request(
        _self: ControlClient, method: str, path: str, payload: object
    ) -> dict[str, Any]:
        requests.append((method, path, payload))
        return status

    client = ControlClient()
    monkeypatch.setattr(
        ControlClient, "from_environment", classmethod(lambda _cls: client)
    )
    monkeypatch.setattr(ControlClient, "_request", request)

    assert cli.main(["run", "speed", "run-1", limit]) == 0
    assert requests == [
        ("POST", "/api/runs/run-1/speed", {"max_steps_per_second": float(limit)})
    ]
    assert json.loads(capsys.readouterr().out) == status


@pytest.mark.parametrize("limit", ["-1", "nan", "inf", "-inf", "not-a-number"])
@pytest.mark.parametrize("operation", ["start", "speed"])
def test_run_rejects_invalid_speed_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    limit: str,
) -> None:
    def unexpected_client(_cls: type[ControlClient]) -> ControlClient:
        pytest.fail("invalid speed must be rejected before connecting")

    monkeypatch.setattr(
        ControlClient, "from_environment", classmethod(unexpected_client)
    )
    arguments = (
        ["run", "start", "--seed", "6", f"--max-steps-per-second={limit}"]
        if operation == "start"
        else ["run", "speed", "run-1", "--", limit]
    )

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)

    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_run_speed_requires_limit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["run", "speed", "run-1"])

    assert error.value.code == 2
    assert "max_steps_per_second" in capsys.readouterr().err
