from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UrlRejected(ValueError):
    """Raised when a video URL is outside the worker safety policy."""


Resolver = Callable[[str, int | None], list[str]]

ALLOWED_HOST_SUFFIXES = (
    "douyin.com",
    "iesdouyin.com",
)

BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
}


@dataclass(frozen=True)
class ValidatedUrl:
    original: str
    canonical: str
    host: str
    resolved_ips: tuple[str, ...]


def default_resolver(host: str, port: int | None) -> list[str]:
    infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and sockaddr[0] not in addresses:
            addresses.append(sockaddr[0])
    return addresses


def _is_allowed_host(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    return any(normalized == suffix or normalized.endswith("." + suffix) for suffix in ALLOWED_HOST_SUFFIXES)


def _check_ip(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if ip in BLOCKED_IPS:
        raise UrlRejected(f"blocked metadata IP: {ip}")
    site_local = getattr(ip, "is_site_local", False)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or site_local
    ):
        raise UrlRejected(f"blocked non-public IP: {ip}")


def _canonicalize(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise UrlRejected("only http and https URLs are supported")
    if parsed.username or parsed.password:
        raise UrlRejected("userinfo in URL is not allowed")
    if not parsed.hostname:
        raise UrlRejected("URL host is required")
    host = parsed.hostname.rstrip(".").lower()
    if not _is_allowed_host(host):
        raise UrlRejected("host is not in the Douyin allowlist")
    if parsed.port not in (None, 80, 443):
        raise UrlRejected("only standard http/https ports are allowed")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)), doseq=True)
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    canonical = urlunsplit((parsed.scheme, netloc, path, query, ""))
    return canonical, host, parsed.port


def validate_video_url(url: str, resolver: Resolver = default_resolver) -> ValidatedUrl:
    canonical, host, port = _canonicalize(url)
    resolved = resolver(host, port)
    if not resolved:
        raise UrlRejected("host did not resolve")
    for address in resolved:
        _check_ip(address)
    return ValidatedUrl(original=url, canonical=canonical, host=host, resolved_ips=tuple(resolved))
