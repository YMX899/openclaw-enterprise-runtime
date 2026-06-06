from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic


_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


class Phase4ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Phase4Config:
    tenant_allowlist_hashes: frozenset[str]
    account_allowlist_hashes: frozenset[str]
    user_active_job_limit: int
    user_rate_limit_per_minute: int
    data_retention_days: int
    max_upload_bytes: int
    knowledge_base_version: str | None
    bridge_version: str
    openclaw_version: str


def _parse_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise Phase4ConfigError(f"{name} must be an integer") from exc
    if value < 0:
        raise Phase4ConfigError(f"{name} must be zero or positive")
    return value


def positive_int_from_env(name: str, default: int) -> int:
    return _parse_positive_int(name, default)


def parse_hash_allowlist(raw: str | None, *, name: str) -> frozenset[str]:
    if not raw:
        return frozenset()
    values = frozenset(item.strip().lower() for item in raw.split(",") if item.strip())
    invalid = sorted(item for item in values if not _HASH_RE.fullmatch(item))
    if invalid:
        raise Phase4ConfigError(f"{name} contains invalid HMAC hash values")
    return values


def read_version_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value:
        return None
    return value[:120]


def load_phase4_config() -> Phase4Config:
    max_upload_bytes = _parse_positive_int("MAX_UPLOAD_BYTES", 512 * 1024 * 1024)
    return Phase4Config(
        tenant_allowlist_hashes=parse_hash_allowlist(
            os.environ.get("OPENCLAW_TENANT_ALLOWLIST_HASHES"),
            name="OPENCLAW_TENANT_ALLOWLIST_HASHES",
        ),
        account_allowlist_hashes=parse_hash_allowlist(
            os.environ.get("OPENCLAW_ACCOUNT_ALLOWLIST_HASHES"),
            name="OPENCLAW_ACCOUNT_ALLOWLIST_HASHES",
        ),
        user_active_job_limit=_parse_positive_int("OPENCLAW_USER_ACTIVE_JOB_LIMIT", 0),
        user_rate_limit_per_minute=_parse_positive_int("OPENCLAW_USER_RATE_LIMIT_PER_MINUTE", 0),
        data_retention_days=_parse_positive_int("OPENCLAW_DATA_RETENTION_DAYS", 0),
        max_upload_bytes=max_upload_bytes,
        knowledge_base_version=read_version_file(os.environ.get("KNOWLEDGE_BASE_VERSION_FILE")),
        bridge_version=os.environ.get("OPENCLAW_VIDEO_RELEASE", "unknown")[:120],
        openclaw_version=os.environ.get("OPENCLAW_VERSION", "2026.3.13")[:120],
    )


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, now: float | None = None) -> bool:
        if limit <= 0:
            return True
        reference = monotonic() if now is None else now
        window_start = reference - 60
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= window_start:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(reference)
            return True
