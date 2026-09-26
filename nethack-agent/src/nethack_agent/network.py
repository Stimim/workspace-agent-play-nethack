from __future__ import annotations

import ipaddress
import socket
import threading
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


class LoopbackUrlError(ValueError):
    pass


class NonLoopbackConnectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SocketDestination:
    address: str
    port: int
    loopback: bool

    def to_json(self) -> dict[str, object]:
        return {
            "address": self.address,
            "port": self.port,
            "loopback": self.loopback,
        }


@dataclass(slots=True)
class ConnectionAudit:
    destinations: list[SocketDestination] = field(default_factory=list)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def record(self, family: int, destination: object) -> None:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise NonLoopbackConnectionError(
                f"socket destination uses unsupported address family {family}"
            )
        if not isinstance(destination, tuple) or len(destination) < 2:
            raise NonLoopbackConnectionError("socket destination is malformed")
        address = str(destination[0])
        port = destination[1]
        if isinstance(port, bool) or not isinstance(port, int):
            raise NonLoopbackConnectionError("socket destination port is invalid")
        try:
            loopback = ipaddress.ip_address(address).is_loopback
        except ValueError as error:
            raise NonLoopbackConnectionError(
                f"socket destination {address!r} is not a literal IP address"
            ) from error
        attempt = SocketDestination(address, port, loopback)
        with self._lock:
            self.destinations.append(attempt)
        if not loopback:
            raise NonLoopbackConnectionError(
                f"blocked non-loopback socket destination {address}:{port}"
            )


_SOCKET_AUDIT_LOCK = threading.Lock()


@contextmanager
def audit_loopback_connections() -> Iterator[ConnectionAudit]:
    """Record TCP destinations and block any address outside loopback."""
    audit = ConnectionAudit()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(sock: socket.socket, address: object) -> None:
        audit.record(sock.family, address)
        original_connect(sock, address)  # type: ignore[arg-type]

    def guarded_connect_ex(sock: socket.socket, address: object) -> int:
        audit.record(sock.family, address)
        return original_connect_ex(sock, address)  # type: ignore[arg-type]

    with _SOCKET_AUDIT_LOCK:
        socket.socket.connect = guarded_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
        try:
            yield audit
        finally:
            socket.socket.connect = original_connect  # type: ignore[method-assign]
            socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def normalize_loopback_http_url(url: str) -> str:
    """Validate and pin an HTTP endpoint to a literal loopback address."""
    if not isinstance(url, str):
        raise LoopbackUrlError("URL must be a string")
    try:
        normalized = url.rstrip("/")
        parsed = urllib.parse.urlsplit(normalized)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise LoopbackUrlError("URL is malformed or has an invalid port") from error
    if parsed.scheme != "http" or not parsed.hostname:
        raise LoopbackUrlError("URL must be an http URL with a hostname")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise LoopbackUrlError(
            "URL must not contain credentials, path, query, or fragment"
        )
    if port == 0:
        raise LoopbackUrlError("URL port must be between 1 and 65535")

    hostname = parsed.hostname
    if hostname.casefold() == "localhost":
        address = ipaddress.ip_address("127.0.0.1")
    else:
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as error:
            raise LoopbackUrlError(
                "hostname must be a literal loopback IP address or localhost"
            ) from error
        if not address.is_loopback:
            raise LoopbackUrlError("URL host must be a loopback address")

    host = f"[{address}]" if address.version == 6 else str(address)
    authority = host if port is None else f"{host}:{port}"
    return urllib.parse.urlunsplit(("http", authority, "", "", ""))


def loopback_http_opener() -> urllib.request.OpenerDirector:
    """Build an opener that never consults HTTP proxy configuration."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))
