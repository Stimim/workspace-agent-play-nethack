from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Final

from nethack_agent.decision import RunState
from nethack_agent.network import (
    LoopbackUrlError,
    loopback_http_opener,
    normalize_loopback_http_url,
)
from nethack_agent.tasks import TaskSpec

DEFAULT_API_URL: Final = "http://127.0.0.1:8000"
DEFAULT_API_TIMEOUT_SECONDS: Final = 300.0


class ControlClientError(RuntimeError):
    pass


class MalformedControlResponse(ControlClientError):
    pass


class ControlWaitTimeout(ControlClientError):
    pass


class UnexpectedRunState(ControlClientError):
    def __init__(self, state: RunState, expected: frozenset[RunState]) -> None:
        expected_text = ", ".join(sorted(item.value for item in expected))
        super().__init__(
            f"run reached {state.value!r} while waiting for {expected_text}"
        )
        self.state = state
        self.expected = expected


@dataclass(frozen=True, slots=True)
class ControlClient:
    base_url: str = DEFAULT_API_URL
    timeout_seconds: float = DEFAULT_API_TIMEOUT_SECONDS
    _opener: urllib.request.OpenerDirector = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        try:
            normalized_url = normalize_loopback_http_url(self.base_url)
        except LoopbackUrlError as error:
            raise ControlClientError(f"invalid control API URL: {error}") from error
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ControlClientError(
                "API timeout must be a finite number greater than zero"
            )
        object.__setattr__(self, "base_url", normalized_url)
        object.__setattr__(self, "_opener", loopback_http_opener())

    @classmethod
    def from_environment(cls) -> ControlClient:
        timeout_text = os.environ.get(
            "NETHACK_AGENT_API_TIMEOUT_SECONDS",
            str(DEFAULT_API_TIMEOUT_SECONDS),
        )
        try:
            timeout = float(timeout_text)
        except ValueError as error:
            raise ControlClientError(
                "NETHACK_AGENT_API_TIMEOUT_SECONDS must be a number"
            ) from error
        return cls(
            base_url=os.environ.get("NETHACK_AGENT_API_URL", DEFAULT_API_URL),
            timeout_seconds=timeout,
        )

    def health(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        response = self._request("GET", "/api/health", timeout_seconds=timeout_seconds)
        if response.get("status") != "ok":
            raise MalformedControlResponse(
                "control API health response must contain status 'ok'"
            )
        return response

    def wait_for_health(
        self, *, timeout_seconds: float, poll_interval_seconds: float = 0.05
    ) -> dict[str, Any]:
        deadline = _deadline(timeout_seconds, "health timeout")
        poll_interval = _positive_finite(poll_interval_seconds, "health poll interval")
        last_error: ControlClientError | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = f": {last_error}" if last_error else ""
                raise ControlWaitTimeout(
                    f"control API health readiness timed out{detail}"
                )
            try:
                return self.health(timeout_seconds=min(self.timeout_seconds, remaining))
            except MalformedControlResponse:
                raise
            except ControlClientError as error:
                last_error = error
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    def create_run(
        self,
        *,
        seed: int,
        max_episode_steps: int,
        auto_start: bool,
        task: TaskSpec | None = None,
    ) -> dict[str, Any]:
        """Create a run; without `task` the service runs the staircase task."""
        payload: dict[str, object] = {
            "seed": seed,
            "max_episode_steps": max_episode_steps,
            "auto_start": auto_start,
        }
        if task is not None:
            payload["task"] = task.to_json()
        response = self._request("POST", "/api/runs", payload)
        self.status_state(response)
        return response

    def status(
        self, run_id: str, *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/api/runs/{_run_id(run_id)}",
            timeout_seconds=timeout_seconds,
        )
        self.status_state(response)
        return response

    @staticmethod
    def status_state(response: object) -> RunState:
        if not isinstance(response, dict):
            raise MalformedControlResponse("run status response must be an object")
        run = response.get("run")
        if not isinstance(run, dict):
            raise MalformedControlResponse(
                "run status response must contain a run object"
            )
        state = run.get("state")
        if not isinstance(state, str):
            raise MalformedControlResponse(
                "run status response must contain a string run.state"
            )
        try:
            return RunState(state)
        except ValueError as error:
            raise MalformedControlResponse(
                f"run status response has unknown state {state!r}"
            ) from error

    def wait_for_state(
        self,
        run_id: str,
        states: Iterable[RunState],
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 0.05,
    ) -> dict[str, Any]:
        expected = frozenset(states)
        if not expected or not all(isinstance(state, RunState) for state in expected):
            raise ValueError("states must contain at least one RunState")
        deadline = _deadline(timeout_seconds, "state wait timeout")
        poll_interval = _positive_finite(poll_interval_seconds, "state poll interval")
        last_state: RunState | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                suffix = f"; last state was {last_state.value}" if last_state else ""
                raise ControlWaitTimeout(f"timed out waiting for run state{suffix}")
            response = self.status(
                run_id, timeout_seconds=min(self.timeout_seconds, remaining)
            )
            last_state = self.status_state(response)
            if last_state in expected:
                return response
            if last_state in {
                RunState.PAUSED,
                RunState.TERMINAL,
                RunState.STOPPED,
                RunState.ERROR,
            }:
                raise UnexpectedRunState(last_state, expected)
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    def events(
        self, run_id: str, *, after: int = -1, limit: int = 100
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/api/runs/{_run_id(run_id)}/events?after={after}&limit={limit}",
        )
        _validate_event_page(response, after=after, limit=limit)
        return response

    def iter_events(
        self, run_id: str, *, after: int = -1, page_limit: int = 100
    ) -> Iterator[dict[str, Any]]:
        if isinstance(after, bool) or not isinstance(after, int) or after < -1:
            raise ValueError("after must be an integer greater than or equal to -1")
        if (
            isinstance(page_limit, bool)
            or not isinstance(page_limit, int)
            or not 1 <= page_limit <= 1_000
        ):
            raise ValueError("page_limit must be an integer between 1 and 1000")
        cursor = after
        while True:
            page = self.events(run_id, after=cursor, limit=page_limit)
            events = page["events"]
            assert isinstance(events, list)
            for event in events:
                assert isinstance(event, dict)
                yield event
            next_after = page["next_after"]
            has_more = page["has_more"]
            assert isinstance(next_after, int)
            assert isinstance(has_more, bool)
            cursor = next_after
            if not has_more:
                return

    def control(self, run_id: str, operation: str) -> dict[str, Any]:
        if operation not in {"pause", "resume", "step", "stop"}:
            raise ControlClientError(f"unsupported operation {operation!r}")
        response = self._request("POST", f"/api/runs/{_run_id(run_id)}/{operation}")
        self.status_state(response)
        return response

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        timeout = (
            self.timeout_seconds
            if timeout_seconds is None
            else _positive_finite(timeout_seconds, "request timeout")
        )
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ControlClientError(
                f"control API returned HTTP {error.code}: {detail}"
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise ControlClientError(f"control API request failed: {error}") from error
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MalformedControlResponse(
                "control API returned invalid JSON"
            ) from error
        if not isinstance(decoded, dict):
            raise MalformedControlResponse("control API returned a non-object response")
        return decoded


def _run_id(run_id: str) -> str:
    return urllib.parse.quote(run_id, safe="")


def _deadline(timeout_seconds: float, name: str) -> float:
    return time.monotonic() + _positive_finite(timeout_seconds, name)


def _positive_finite(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a finite number greater than zero")
    return float(value)


def _validate_event_page(page: dict[str, Any], *, after: int, limit: int) -> None:
    events = page.get("events")
    next_after = page.get("next_after")
    has_more = page.get("has_more")
    returned_limit = page.get("limit")
    if not isinstance(events, list):
        raise MalformedControlResponse("event page events must be an array")
    if isinstance(next_after, bool) or not isinstance(next_after, int):
        raise MalformedControlResponse("event page next_after must be an integer")
    if not isinstance(has_more, bool):
        raise MalformedControlResponse("event page has_more must be a boolean")
    if returned_limit != limit:
        raise MalformedControlResponse("event page limit does not match the request")
    expected_sequence = after + 1
    for event in events:
        if not isinstance(event, dict):
            raise MalformedControlResponse("event page entries must be objects")
        sequence = event.get("sequence")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence != expected_sequence
        ):
            raise MalformedControlResponse(
                "event page sequences must be contiguous and ordered"
            )
        if not isinstance(event.get("kind"), str) or not isinstance(
            event.get("payload"), dict
        ):
            raise MalformedControlResponse(
                "event entries must contain string kind and object payload"
            )
        expected_sequence += 1
    expected_cursor = events[-1]["sequence"] if events else after
    if next_after != expected_cursor:
        raise MalformedControlResponse("event page next_after does not match events")
    if has_more and not events:
        raise MalformedControlResponse(
            "event page cannot claim more data without cursor progress"
        )
