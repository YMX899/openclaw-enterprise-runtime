from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from ..models import VideoSource


class XiaohongshuVideoResolver:
    def resolve(self, source_url: str) -> VideoSource:
        normalized_url = self._normalize_url(source_url)
        info = self._extract_info(normalized_url)
        playable = self._pick_playable(info)
        if not playable["video_url"]:
            raise RuntimeError("Could not extract Xiaohongshu playable video URL.")

        return VideoSource(
            source_url=source_url,
            video_id=str(info.get("id") or self._extract_note_id(normalized_url)),
            share_url=str(info.get("webpage_url") or normalized_url),
            playwm_url=playable["video_url"],
            video_url=playable["video_url"],
            author=self._author(info),
            desc=str(info.get("title") or info.get("description") or ""),
            duration_ms=self._parse_duration_ms(info.get("duration")),
            content_type=playable["content_type"],
            size_mb=playable["size_mb"],
            video_url_source=playable["video_url_source"],
        )

    def build_video_data_url(self, video: VideoSource) -> str:
        raise RuntimeError("Xiaohongshu inline data URL is not supported; use yt-dlp download path.")

    @staticmethod
    def _normalize_url(url: str) -> str:
        hostname = (urlparse(url).hostname or "").lower()
        if hostname == "xiaohongshu.com" or hostname.endswith(".xiaohongshu.com"):
            return url
        if hostname == "xhslink.com" or hostname.endswith(".xhslink.com"):
            return url
        raise ValueError(f"Unsupported Xiaohongshu URL: {url}")

    @staticmethod
    def _extract_info(url: str) -> dict[str, Any]:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise RuntimeError("yt-dlp is required to resolve Xiaohongshu videos.") from exc
        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "socket_timeout": 30,
            "retries": 2,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/135.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.xiaohongshu.com/",
            },
        }
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=False)
                break
            except Exception as exc:
                last_error = exc
                if attempt >= 3:
                    raise
                time.sleep(1.5 * attempt)
        else:
            raise RuntimeError("yt-dlp returned no Xiaohongshu metadata.") from last_error
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp returned no Xiaohongshu metadata.")
        return info

    @staticmethod
    def _pick_playable(info: dict[str, Any]) -> dict[str, Any]:
        formats = info.get("formats")
        candidates: list[dict[str, Any]] = []
        if isinstance(formats, list):
            for item in formats:
                if isinstance(item, dict) and item.get("url"):
                    candidates.append(item)
        if isinstance(info.get("url"), str):
            candidates.append(info)

        def score(item: dict[str, Any]) -> tuple[int, int, int, int]:
            ext_score = 1 if str(item.get("ext") or "").lower() == "mp4" else 0
            protocol = str(item.get("protocol") or "")
            http_score = 1 if protocol.startswith("http") or str(item.get("url") or "").startswith("http") else 0
            size = int(item.get("filesize") or item.get("filesize_approx") or 0)
            height = int(item.get("height") or 0)
            return (http_score, ext_score, size, height)

        selected = max(candidates, key=score, default={})
        video_url = str(selected.get("url") or "")
        size = selected.get("filesize") or selected.get("filesize_approx") or info.get("filesize") or info.get("filesize_approx")
        try:
            size_mb = float(size) / 1024 / 1024 if size else None
        except (TypeError, ValueError):
            size_mb = None
        return {
            "video_url": video_url,
            "content_type": "video/mp4" if str(selected.get("ext") or "").lower() == "mp4" else None,
            "size_mb": size_mb,
            "video_url_source": "yt-dlp",
        }

    @staticmethod
    def _parse_duration_ms(value: Any) -> int | None:
        if isinstance(value, (int, float)) and value >= 0:
            return int(float(value) * 1000)
        if isinstance(value, str):
            try:
                parsed = float(value.strip())
            except ValueError:
                return None
            return int(parsed * 1000) if parsed >= 0 else None
        return None

    @staticmethod
    def _extract_note_id(url: str) -> str:
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        for marker in ("item", "explore"):
            if marker in path_parts:
                index = path_parts.index(marker)
                if index + 1 < len(path_parts):
                    return path_parts[index + 1]
        return path_parts[-1] if path_parts else ""

    @staticmethod
    def _author(info: dict[str, Any]) -> str:
        uploader = info.get("uploader") or info.get("channel") or info.get("creator")
        return str(uploader or "")
