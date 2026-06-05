from __future__ import annotations

from collections.abc import Mapping

SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-csrf-token",
    "x-xsrf-token",
    "csrf-token",
    "x-api-key",
    "openclaw-token",
}


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADER_NAMES:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def safe_error_message(exc: BaseException) -> str:
    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    for marker in ("Bearer ", "Cookie:", "Authorization:", "OPENCLAW_GATEWAY_TOKEN"):
        if marker.lower() in text.lower():
            return "internal error"
    return text[:300]

