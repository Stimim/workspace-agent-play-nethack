from __future__ import annotations

import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Final

from nethack_agent.network import (
    LoopbackUrlError,
    loopback_http_opener,
    normalize_loopback_http_url,
)

DEFAULT_OLLAMA_URL: Final = "http://127.0.0.1:11434"
DEFAULT_MODEL: Final = "gemma4-nethack:latest"
DEFAULT_TIMEOUT_SECONDS: Final = 180.0
DEFAULT_NUM_CTX: Final = 8_192
MAX_NUM_CTX: Final = 1_048_576
_DECIMAL_INTEGER = re.compile(r"[1-9][0-9]*\Z")


class OllamaError(RuntimeError):
    """The local Ollama runtime could not satisfy a validated request."""


class OllamaContextLimitError(OllamaError):
    """A generation may have been truncated by the configured context window."""

    def __init__(self, message: str, generation: Generation) -> None:
        super().__init__(message)
        self.generation = generation


@dataclass(frozen=True, slots=True)
class OllamaConfig:
    url: str = DEFAULT_OLLAMA_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    num_ctx: int = DEFAULT_NUM_CTX

    def __post_init__(self) -> None:
        try:
            normalized_url = normalize_loopback_http_url(self.url)
        except LoopbackUrlError as error:
            raise OllamaError(f"invalid Ollama URL: {error}") from error
        if not self.model.strip():
            raise OllamaError("Ollama model must not be empty")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise OllamaError(
                "Ollama timeout must be a finite number greater than zero"
            )
        if (
            isinstance(self.num_ctx, bool)
            or not isinstance(self.num_ctx, int)
            or not 1 <= self.num_ctx <= MAX_NUM_CTX
        ):
            raise OllamaError(
                f"Ollama num_ctx must be an integer between 1 and {MAX_NUM_CTX}"
            )
        object.__setattr__(self, "url", normalized_url)

    @classmethod
    def from_environment(cls) -> OllamaConfig:
        timeout_text = os.environ.get(
            "NETHACK_AGENT_OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)
        )
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as error:
            raise OllamaError(
                "NETHACK_AGENT_OLLAMA_TIMEOUT_SECONDS must be a number"
            ) from error
        num_ctx_text = os.environ.get(
            "NETHACK_AGENT_OLLAMA_NUM_CTX", str(DEFAULT_NUM_CTX)
        )
        if not _DECIMAL_INTEGER.fullmatch(num_ctx_text):
            raise OllamaError(
                "NETHACK_AGENT_OLLAMA_NUM_CTX must be a positive decimal integer"
            )
        return cls(
            url=os.environ.get("NETHACK_AGENT_OLLAMA_URL", DEFAULT_OLLAMA_URL),
            model=os.environ.get("NETHACK_AGENT_MODEL", DEFAULT_MODEL),
            timeout_seconds=timeout_seconds,
            num_ctx=int(num_ctx_text),
        )


@dataclass(frozen=True, slots=True)
class Generation:
    text: str
    prompt_tokens: int
    output_tokens: int
    total_duration_ns: int


class OllamaClient:
    def __init__(self, config: OllamaConfig) -> None:
        self.config = config
        self._version: str | None = None
        self._opener = loopback_http_opener()

    @property
    def version(self) -> str | None:
        return self._version

    def ensure_ready(self) -> str:
        if self._version is not None:
            return self._version
        self._require_matching_versions()
        version_data = self._request_json("/api/version")
        version = version_data.get("version")
        if not isinstance(version, str) or not version:
            raise OllamaError("Ollama did not report a version")

        tags_data = self._request_json("/api/tags")
        models = tags_data.get("models")
        if not isinstance(models, list):
            raise OllamaError("Ollama did not return a model list")
        installed = {item.get("name") for item in models if isinstance(item, dict)}
        if self.config.model not in installed:
            installed_names = ", ".join(sorted(str(name) for name in installed))
            raise OllamaError(
                f"configured model {self.config.model!r} is not installed; "
                f"installed models: {installed_names}"
            )
        self._version = version
        return version

    def generate(
        self,
        prompt: str,
        *,
        format_schema: dict[str, object] | None = None,
        max_tokens: int = 512,
    ) -> Generation:
        self.ensure_ready()
        payload: dict[str, object] = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0,
                "num_predict": max_tokens,
                "num_ctx": self.config.num_ctx,
            },
        }
        if format_schema is not None:
            payload["format"] = format_schema
        generated = self._request_json("/api/generate", payload)
        response_text = generated.get("response")
        thinking_text = generated.get("thinking")
        if not isinstance(response_text, str) or not response_text.strip():
            if isinstance(thinking_text, str) and thinking_text.strip():
                raise OllamaError("Ollama returned thinking but no final response")
            raise OllamaError("Ollama generation returned no text")
        generation = Generation(
            text=response_text,
            prompt_tokens=_nonnegative_int(generated, "prompt_eval_count"),
            output_tokens=_nonnegative_int(generated, "eval_count"),
            total_duration_ns=_nonnegative_int(generated, "total_duration"),
        )
        if (
            generation.prompt_tokens >= self.config.num_ctx
            or generation.prompt_tokens + max_tokens > self.config.num_ctx
        ):
            raise OllamaContextLimitError(
                f"prompt used {generation.prompt_tokens} tokens; with "
                f"{max_tokens} requested output tokens it exceeds "
                f"num_ctx {self.config.num_ctx}, so Ollama may have truncated it",
                generation,
            )
        return generation

    def _request_json(
        self, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        method = "GET"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"
        request = urllib.request.Request(
            f"{self.config.url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(
                request, timeout=self.config.timeout_seconds
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise OllamaError(
                f"Ollama request {path} failed with HTTP {error.code}: {detail}"
            ) from error
        except (OSError, urllib.error.URLError) as error:
            raise OllamaError(f"Ollama request {path} failed: {error}") from error
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OllamaError(f"Ollama request {path} returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise OllamaError(f"Ollama request {path} returned a non-object response")
        return decoded

    def _require_matching_versions(self) -> None:
        environment = os.environ.copy()
        environment["OLLAMA_HOST"] = self.config.url
        try:
            completed = subprocess.run(
                ("ollama", "--version"),
                capture_output=True,
                check=False,
                env=environment,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise OllamaError(f"cannot run 'ollama --version': {error}") from error
        output = "\n".join((completed.stdout, completed.stderr))
        mismatch = next(
            (
                line.strip()
                for line in output.splitlines()
                if "warning: client version is" in line.casefold()
            ),
            None,
        )
        if mismatch:
            raise OllamaError(
                f"{mismatch}; restart the Ollama server before running inference"
            )


def _nonnegative_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
