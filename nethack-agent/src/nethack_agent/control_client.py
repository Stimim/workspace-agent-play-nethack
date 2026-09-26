from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Final

from nethack_agent.network import (
    LoopbackUrlError,
    loopback_http_opener,
    normalize_loopback_http_url,
)

DEFAULT_API_URL: Final = "http://127.0.0.1:8000"
DEFAULT_API_TIMEOUT_SECONDS: Final = 300.0


class ControlClientError(RuntimeError):
    pass


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

    def create_run(
        self, *, seed: int, max_episode_steps: int, auto_start: bool
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/runs",
            {
                "seed": seed,
                "max_episode_steps": max_episode_steps,
                "auto_start": auto_start,
            },
        )

    def status(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/runs/{_run_id(run_id)}")

    def events(
        self, run_id: str, *, after: int = -1, limit: int = 100
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/runs/{_run_id(run_id)}/events?after={after}&limit={limit}",
        )

    def control(self, run_id: str, operation: str) -> dict[str, Any]:
        if operation not in {"pause", "resume", "step", "stop"}:
            raise ControlClientError(f"unsupported operation {operation!r}")
        return self._request("POST", f"/api/runs/{_run_id(run_id)}/{operation}")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
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
            raise ControlClientError("control API returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise ControlClientError("control API returned a non-object response")
        return decoded


def _run_id(run_id: str) -> str:
    return urllib.parse.quote(run_id, safe="")
