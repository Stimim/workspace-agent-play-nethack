from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from nethack_agent.environment import NleEnvironment, ScenarioConfig

DEFAULT_OLLAMA_URL: Final = "http://127.0.0.1:11434"
DEFAULT_MODEL: Final = "gemma4-nethack:latest"
DEFAULT_TIMEOUT_SECONDS: Final = 180.0


class CheckFailure(RuntimeError):
    """A diagnostic check could not prove its runtime path works."""


@dataclass(frozen=True)
class RuntimeConfig:
    ollama_url: str
    model: str
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> RuntimeConfig:
        url = os.environ.get("NETHACK_AGENT_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
        model = os.environ.get("NETHACK_AGENT_MODEL", DEFAULT_MODEL)
        timeout_text = os.environ.get(
            "NETHACK_AGENT_OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)
        )
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as error:
            raise CheckFailure(
                "NETHACK_AGENT_OLLAMA_TIMEOUT_SECONDS must be a number"
            ) from error
        if timeout_seconds <= 0:
            raise CheckFailure(
                "NETHACK_AGENT_OLLAMA_TIMEOUT_SECONDS must be greater than zero"
            )
        _require_loopback_url(url)
        if not model.strip():
            raise CheckFailure("NETHACK_AGENT_MODEL must not be empty")
        return cls(url, model, timeout_seconds)


def _require_loopback_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise CheckFailure("Ollama URL must be an http URL with a hostname")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CheckFailure(
            "Ollama URL must not contain credentials, query, or fragment"
        )
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(parsed.hostname, parsed.port or 80)
        }
    except socket.gaierror as error:
        raise CheckFailure(f"cannot resolve Ollama host {parsed.hostname!r}") from error
    if not addresses or any(
        not ipaddress.ip_address(address).is_loopback for address in addresses
    ):
        raise CheckFailure("Ollama URL must resolve only to loopback addresses")


def _request_json(
    config: RuntimeConfig,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(
        f"{config.ollama_url}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(
            request, timeout=config.timeout_seconds
        ) as response:
            body = response.read()
    except (OSError, urllib.error.URLError) as error:
        raise CheckFailure(f"Ollama request {path} failed: {error}") from error
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckFailure(f"Ollama request {path} returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise CheckFailure(f"Ollama request {path} returned a non-object response")
    return decoded


def _require_matching_ollama_versions(config: RuntimeConfig) -> None:
    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = config.ollama_url
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
        raise CheckFailure(f"cannot run 'ollama --version': {error}") from error
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
        raise CheckFailure(
            f"{mismatch}; restart the Ollama server before running inference"
        )


def smoke_ollama(config: RuntimeConfig) -> str:
    _require_matching_ollama_versions(config)
    version_data = _request_json(config, "/api/version")
    version = version_data.get("version")
    if not isinstance(version, str) or not version:
        raise CheckFailure("Ollama did not report a version")

    tags_data = _request_json(config, "/api/tags")
    models = tags_data.get("models")
    if not isinstance(models, list):
        raise CheckFailure("Ollama did not return a model list")
    installed = {item.get("name") for item in models if isinstance(item, dict)}
    if config.model not in installed:
        raise CheckFailure(
            f"configured model {config.model!r} is not installed; "
            f"installed models: {', '.join(sorted(str(name) for name in installed))}"
        )

    generated = _request_json(
        config,
        "/api/generate",
        {
            "model": config.model,
            "prompt": "Reply with the single word OK.",
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": 16},
        },
    )
    response_text = generated.get("response")
    thinking_text = generated.get("thinking")
    if not any(
        isinstance(value, str) and value.strip()
        for value in (response_text, thinking_text)
    ):
        raise CheckFailure("Ollama generation returned no text")
    return f"Ollama {version}; model {config.model}; local generation completed"


def smoke_nle() -> str:
    try:
        with tempfile.TemporaryDirectory(prefix="nethack-agent-smoke-") as directory:
            environment = NleEnvironment(
                ScenarioConfig(
                    seed=6,
                    artifact_directory=Path(directory),
                    max_episode_steps=10,
                )
            )
            with environment:
                observation = environment.reset()
                transition = environment.step(0)
                rows, columns = observation.chars.shape
                action_count = len(environment.legal_actions)
                seed_set = environment.seed_set
                if transition.step_index != 1:
                    raise CheckFailure("NLE adapter did not advance one step")
            ttyrec_count = len(environment.ttyrec_files)
            if ttyrec_count != 1:
                raise CheckFailure(
                    f"NLE adapter produced {ttyrec_count} ttyrecs instead of one"
                )
    except CheckFailure:
        raise
    except Exception as error:
        raise CheckFailure(f"NLE environment smoke failed: {error}") from error
    return (
        "NLE Staircase reset and step completed; "
        f"map {columns}x{rows}; {action_count} legal action indices; "
        f"RNG seeds {seed_set.core}/{seed_set.display}/{seed_set.level}; "
        "one ttyrec finalized"
    )


def _run_check(name: str, check: Any) -> bool:
    try:
        detail = check()
    except CheckFailure as error:
        print(f"FAIL {name}: {error}", file=sys.stderr)
        return False
    print(f"OK   {name}: {detail}")
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nethack-agent", description="NetHack agent developer diagnostics"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="check NLE and local Ollama end to end")
    smoke_parser = subparsers.add_parser("smoke", help="run one integration check")
    smoke_parser.add_argument("target", choices=("nle", "ollama"))
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "smoke" and arguments.target == "nle":
        return 0 if _run_check("nle", smoke_nle) else 1

    try:
        config = RuntimeConfig.from_environment()
    except CheckFailure as error:
        print(f"FAIL configuration: {error}", file=sys.stderr)
        return 1

    if arguments.command == "smoke":
        return 0 if _run_check("ollama", lambda: smoke_ollama(config)) else 1

    checks = {
        "nle": smoke_nle,
        "ollama": lambda: smoke_ollama(config),
    }
    successful = True
    for name, check in checks.items():
        successful = _run_check(name, check) and successful
    return 0 if successful else 1
