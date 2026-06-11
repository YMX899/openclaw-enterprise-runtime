from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .url_guard import (
    RedirectFetcher,
    Resolver,
    UrlRejected,
    default_redirect_fetcher,
    default_resolver,
    validate_video_url_with_redirects,
)
from .video_limits import DEFAULT_MAX_DOWNLOAD_BYTES, DEFAULT_MAX_VIDEO_DURATION_SECONDS


class VideoLinkProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoLinkProbeConfig:
    max_duration_seconds: int = DEFAULT_MAX_VIDEO_DURATION_SECONDS
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _duration_seconds(video: Any) -> float | None:
    duration_ms = getattr(video, "duration_ms", None)
    if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
        return round(float(duration_ms) / 1000.0, 3)
    return None


def _size_bytes(video: Any) -> int | None:
    size_mb = getattr(video, "size_mb", None)
    if isinstance(size_mb, (int, float)) and size_mb >= 0:
        return int(float(size_mb) * 1024 * 1024)
    return None


def _add_legacy_pythonpath() -> None:
    candidates: list[str] = []
    raw_paths = os.environ.get("DOUYIN_CHONG_PYTHONPATH", "")
    candidates.extend(path.strip() for path in raw_paths.split(os.pathsep) if path.strip())
    candidates.append(str(Path(__file__).resolve().parents[2] / "vendor"))
    candidates.append("/app/vendor")
    for candidate in candidates:
        if Path(candidate).exists() and candidate not in sys.path:
            sys.path.insert(0, candidate)


def _load_resolver_class():
    _add_legacy_pythonpath()
    try:
        from douyin_chong.clients.resolver import UniversalVideoResolver
    except ImportError as exc:
        raise VideoLinkProbeError("douyin_chong resolver is not importable") from exc
    return UniversalVideoResolver


def _host(value: str) -> str:
    return (urlparse(value).hostname or "").lower()


def _video_candidate_count(video: Any) -> int:
    return sum(
        1
        for value in (
            getattr(video, "video_url", ""),
            getattr(video, "playwm_url", ""),
        )
        if value
    )


def _limit_status(*, duration: float | None, size_bytes: int | None, config: VideoLinkProbeConfig) -> dict[str, Any]:
    duration_ok = duration is not None and duration <= config.max_duration_seconds
    size_ok = size_bytes is not None and size_bytes <= config.max_download_bytes
    return {
        "max_duration_seconds": config.max_duration_seconds,
        "max_download_bytes": config.max_download_bytes,
        "duration_known": duration is not None,
        "size_known": size_bytes is not None,
        "duration_ok": duration_ok,
        "size_ok": size_ok,
        "eligible_for_model_analysis": duration_ok and size_ok,
    }


def probe_video_link(
    video_url: str,
    *,
    resolver: Resolver = default_resolver,
    redirect_fetcher: RedirectFetcher = default_redirect_fetcher,
    legacy_resolver: Any | None = None,
    config: VideoLinkProbeConfig | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    config = config or VideoLinkProbeConfig()
    validated = validate_video_url_with_redirects(
        video_url,
        resolver=resolver,
        redirect_fetcher=redirect_fetcher,
    )
    try:
        selected_resolver = legacy_resolver if legacy_resolver is not None else _load_resolver_class()()
        video = selected_resolver.resolve(validated.canonical)
    except Exception as exc:
        raise VideoLinkProbeError("douyin_chong resolver failed") from exc

    duration = _duration_seconds(video)
    size = _size_bytes(video)
    canonical_host = _host(validated.canonical)
    direct_host = _host(str(getattr(video, "video_url", "") or ""))
    playwm_host = _host(str(getattr(video, "playwm_url", "") or ""))
    candidate_count = _video_candidate_count(video)
    source_url = str(getattr(video, "source_url", "") or "")
    share_url = str(getattr(video, "share_url", "") or "")
    video_id = str(getattr(video, "video_id", "") or "")
    limit_status = _limit_status(duration=duration, size_bytes=size, config=config)
    status = "PASS" if candidate_count > 0 and limit_status["eligible_for_model_analysis"] else "WARN"
    return {
        "schema_version": "openclaw-video-link-read-check.v1",
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "input_url_sha256": _sha256_text(video_url),
        "canonical_url_sha256": _sha256_text(validated.canonical),
        "source_url_sha256": _sha256_text(source_url) if source_url else None,
        "share_url_sha256": _sha256_text(share_url) if share_url else None,
        "canonical_host": canonical_host,
        "redirect_hop_count": max(len(validated.redirect_chain) - 1, 0),
        "redirect_chain_hosts": [_host(item) for item in validated.redirect_chain],
        "resolved_ip_count": len(validated.resolved_ips),
        "resolver": "douyin_chong.UniversalVideoResolver",
        "video_id_present": bool(video_id),
        "video_id_sha256": _sha256_text(video_id) if video_id else None,
        "direct_video_candidate_count": candidate_count,
        "direct_video_host": direct_host or None,
        "playwm_host": playwm_host or None,
        "content_type_present": bool(getattr(video, "content_type", None)),
        "content_type": getattr(video, "content_type", None),
        "duration_seconds": duration,
        "size_bytes": size,
        "video_url_source": str(getattr(video, "video_url_source", "") or ""),
        "limits": limit_status,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "raw_url_recorded": False,
        "direct_video_url_recorded": False,
        "cookies_recorded": False,
        "headers_recorded": False,
        "tokens_recorded": False,
        "model_invoked": False,
    }
