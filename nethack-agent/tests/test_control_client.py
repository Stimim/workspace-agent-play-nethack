from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from typing import Any

import pytest

import nethack_agent.control_client as control_client_module
from nethack_agent.control_client import (
    ControlClient,
    ControlWaitTimeout,
    MalformedControlResponse,
    UnexpectedRunState,
)
from nethack_agent.decision import RunState


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _JsonResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _PaginatedOpener:
    def __init__(self) -> None:
        self.cursors: list[int] = []

    def open(self, request: Any, *, timeout: float) -> _JsonResponse:
        assert timeout > 0
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        cursor = int(query["after"][0])
        limit = int(query["limit"][0])
        self.cursors.append(cursor)
        sequences = [sequence for sequence in range(cursor + 1, 3)][:limit]
        events = [
            {
                "sequence": sequence,
                "kind": "test_event",
                "payload": {"sequence": sequence},
            }
            for sequence in sequences
        ]
        return _JsonResponse(
            {
                "events": events,
                "next_after": sequences[-1] if sequences else cursor,
                "has_more": bool(sequences and sequences[-1] < 2),
                "limit": limit,
            }
        )


def _status(state: RunState) -> dict[str, object]:
    return {"run": {"id": "run-1", "state": state.value}}


def test_iter_events_retrieves_every_page() -> None:
    client = ControlClient()
    opener = _PaginatedOpener()
    object.__setattr__(client, "_opener", opener)

    events = list(client.iter_events("run-1", page_limit=1))

    assert [event["sequence"] for event in events] == [0, 1, 2]
    assert opener.cursors == [-1, 0, 1]


def test_wait_for_state_uses_monotonic_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: Iterator[dict[str, object]] = iter(
        [_status(RunState.RUNNING), _status(RunState.PAUSED)]
    )
    monkeypatch.setattr(
        ControlClient,
        "status",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(control_client_module.time, "sleep", lambda _seconds: None)

    response = ControlClient().wait_for_state(
        "run-1", {RunState.PAUSED}, timeout_seconds=1.0
    )

    assert ControlClient.status_state(response) is RunState.PAUSED


@pytest.mark.parametrize(
    "state", [RunState.PAUSED, RunState.TERMINAL, RunState.STOPPED, RunState.ERROR]
)
def test_wait_for_state_distinguishes_unexpected_stable_states(
    monkeypatch: pytest.MonkeyPatch, state: RunState
) -> None:
    monkeypatch.setattr(
        ControlClient,
        "status",
        lambda *_args, **_kwargs: _status(state),
    )
    expected = RunState.TERMINAL if state is not RunState.TERMINAL else RunState.PAUSED

    with pytest.raises(UnexpectedRunState) as captured:
        ControlClient().wait_for_state("run-1", {expected}, timeout_seconds=1.0)

    assert captured.value.state is state


def test_wait_for_state_has_a_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((0.0, 0.1, 0.2, 0.6))
    monkeypatch.setattr(control_client_module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(control_client_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        ControlClient,
        "status",
        lambda *_args, **_kwargs: _status(RunState.RUNNING),
    )

    with pytest.raises(ControlWaitTimeout, match="last state was running"):
        ControlClient().wait_for_state(
            "run-1", {RunState.TERMINAL}, timeout_seconds=0.5
        )


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"run": None},
        {"run": {"state": None}},
        {"run": {"state": "unknown"}},
    ],
)
def test_malformed_run_state_is_distinct(response: object) -> None:
    with pytest.raises(MalformedControlResponse):
        ControlClient.status_state(response)
