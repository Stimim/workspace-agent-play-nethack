import os
import socket
import urllib.request
from pathlib import Path

import pytest

from nethack_agent.control_client import ControlClient, ControlClientError
from nethack_agent.network import (
    LoopbackUrlError,
    NonLoopbackConnectionError,
    audit_loopback_connections,
    normalize_loopback_http_url,
)
from nethack_agent.ollama import OllamaClient, OllamaConfig, OllamaError
from nethack_agent.verification import verify_network_boundary


def test_loopback_urls_are_literal_or_safely_pinned_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("loopback validation used DNS"),
    )

    assert normalize_loopback_http_url("http://localhost:8000/") == (
        "http://127.0.0.1:8000"
    )
    assert normalize_loopback_http_url("http://[::1]:11434") == ("http://[::1]:11434")
    with pytest.raises(LoopbackUrlError, match="literal loopback"):
        normalize_loopback_http_url("http://example.invalid:8000")
    with pytest.raises(LoopbackUrlError, match="invalid port"):
        normalize_loopback_http_url("http://127.0.0.1:99999")
    with pytest.raises(LoopbackUrlError, match="between 1 and 65535"):
        normalize_loopback_http_url("http://127.0.0.1:0")


def test_http_clients_disable_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_handlers: list[urllib.request.ProxyHandler] = []

    def build_opener(*handlers: object) -> object:
        proxy_handlers.extend(
            handler
            for handler in handlers
            if isinstance(handler, urllib.request.ProxyHandler)
        )
        return object()

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setattr(urllib.request, "build_opener", build_opener)

    ControlClient()
    OllamaClient(OllamaConfig())

    assert len(proxy_handlers) == 2
    assert all(handler.proxies == {} for handler in proxy_handlers)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0.0, -1.0, True])
def test_ollama_timeout_must_be_finite_and_positive(timeout: float) -> None:
    with pytest.raises(OllamaError, match="finite"):
        OllamaConfig(timeout_seconds=timeout)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0.0, -1.0, True])
def test_control_timeout_must_be_finite_and_positive(timeout: float) -> None:
    with pytest.raises(ControlClientError, match="finite"):
        ControlClient(timeout_seconds=timeout)


def test_malformed_ports_are_domain_errors() -> None:
    with pytest.raises(OllamaError, match="invalid Ollama URL"):
        OllamaConfig(url="http://127.0.0.1:not-a-port")
    with pytest.raises(ControlClientError, match="invalid control API URL"):
        ControlClient(base_url="http://[::1]:99999")


def test_socket_audit_records_and_blocks_non_loopback_destinations() -> None:
    with (
        audit_loopback_connections() as audit,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as outbound,
        pytest.raises(NonLoopbackConnectionError, match="blocked non-loopback"),
    ):
        outbound.connect(("192.0.2.1", 80))

    assert len(audit.destinations) == 1
    assert audit.destinations[0].address == "192.0.2.1"
    assert not audit.destinations[0].loopback


def test_executable_network_verification_observes_only_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://original.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://original.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "original.invalid")

    result = verify_network_boundary(data_directory=tmp_path, timeout_seconds=20.0)

    assert result.proxy_bypass_verified
    assert result.event_count >= 3
    assert result.destinations
    assert all(destination.loopback for destination in result.destinations)
    assert os.environ["HTTP_PROXY"] == "http://original.invalid:8080"
    assert os.environ["HTTPS_PROXY"] == "http://original.invalid:8080"
    assert os.environ["NO_PROXY"] == "original.invalid"
