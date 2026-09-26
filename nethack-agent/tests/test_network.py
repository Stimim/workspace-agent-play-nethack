import socket
import urllib.request

import pytest

from nethack_agent.control_client import ControlClient, ControlClientError
from nethack_agent.network import LoopbackUrlError, normalize_loopback_http_url
from nethack_agent.ollama import OllamaClient, OllamaConfig, OllamaError


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
