from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class UrlRejected(ValueError):
    """Raised when a video URL is outside the worker safety policy."""


Resolver = Callable[[str, int | None], list[str]]
RedirectFetcher = Callable[[str], str | None]

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
    redirect_chain: tuple[str, ...] = ()


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def default_resolver(host: str, port: int | None) -> list[str]:
    infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and sockaddr[0] not in addresses:
            addresses.append(sockaddr[0])
    return addresses


def default_redirect_fetcher(url: str) -> str | None:
    """Return a redirect Location without following it or reading a response body."""

    opener = build_opener(_NoRedirectHandler)
    for method in ("HEAD", "GET"):
        request = Request(url, method=method, headers={"User-Agent": "openclaw-video-url-guard/1.0"})
        try:
            response = opener.open(request, timeout=5)
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                location = exc.headers.get("Location")
                return urljoin(url, location) if location else None
            if exc.code == 405 and method == "HEAD":
                continue
            return None
        except URLError as exc:
            raise UrlRejected("redirect preflight failed") from exc
        try:
            if 300 <= response.status < 400:
                location = response.headers.get("Location")
                return urljoin(url, location) if location else None
            return None
        finally:
            response.close()
    return None


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
    return ValidatedUrl(original=url, canonical=canonical, host=host, resolved_ips=tuple(resolved), redirect_chain=(canonical,))


def validate_video_url_with_redirects(
    url: str,
    *,
    resolver: Resolver = default_resolver,
    redirect_fetcher: RedirectFetcher = default_redirect_fetcher,
    max_redirects: int = 5,
) -> ValidatedUrl:
    if max_redirects < 0:
        raise UrlRejected("max_redirects must be non-negative")
    original = url
    current = url
    seen: set[str] = set()
    chain: list[str] = []
    for hop in range(max_redirects + 1):
        validated = validate_video_url(current, resolver=resolver)
        if validated.canonical in seen:
            raise UrlRejected("redirect loop detected")
        seen.add(validated.canonical)
        chain.append(validated.canonical)
        next_url = redirect_fetcher(validated.canonical)
        if not next_url:
            return ValidatedUrl(
                original=original,
                canonical=validated.canonical,
                host=validated.host,
                resolved_ips=validated.resolved_ips,
                redirect_chain=tuple(chain),
            )
        if hop == max_redirects:
            raise UrlRejected("too many redirects")
        current = urljoin(validated.canonical, next_url)
    raise UrlRejected("too many redirects")
