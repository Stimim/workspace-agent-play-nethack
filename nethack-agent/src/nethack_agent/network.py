from __future__ import annotations

import ipaddress
import urllib.parse
import urllib.request


class LoopbackUrlError(ValueError):
    pass


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
