from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from ..models import VideoSource


TIKTOK_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


class TikTokVideoResolver:
    hydration_script_re = re.compile(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
        re.S,
    )

    def __init__(self, *, retries: int = 2, retry_wait: float = 1.5) -> None:
        self.retries = retries
        self.retry_wait = retry_wait
        self.session = requests.Session()

    def resolve(self, source_url: str) -> VideoSource:
        normalized_url = self._normalize_tiktok_video_url(source_url)
        page_url = self._follow_short_link(normalized_url)
        html = self._http_get(
            page_url,
            timeout=30,
            headers=self._build_page_headers(),
        ).text
        item = self._extract_item_struct(html)

        video_id = str(item.get("id") or self._extract_video_id(page_url))
        video = item.get("video", {})
        author = item.get("author", {})
        play_addr = str(video.get("playAddr") or "").strip()
        download_addr = str(video.get("downloadAddr") or "").strip()
        if not play_addr and not download_addr:
            raise RuntimeError("Could not extract TikTok playable video URL from hydration data.")

        playable = self._resolve_playable_video_url(play_addr or download_addr)
        return VideoSource(
            source_url=source_url,
            video_id=video_id,
            share_url=page_url,
            playwm_url=download_addr or play_addr,
            video_url=playable["video_url"],
            author=str(author.get("nickname") or author.get("uniqueId") or ""),
            desc=str(item.get("desc", "")),
            duration_ms=self._parse_duration_ms(video.get("duration")),
            content_type=playable["content_type"],
            size_mb=playable["size_mb"],
            video_url_source=playable["video_url_source"],
        )

    def build_video_data_url(self, video: VideoSource) -> str:
        candidate_urls = [video.video_url, video.playwm_url]
        last_error: Optional[Exception] = None
        for candidate_url in candidate_urls:
            if not candidate_url:
                continue
            try:
                response = self._http_get(
                    candidate_url,
                    allow_redirects=True,
                    timeout=(20, 120),
                    headers=self._build_media_headers(video.share_url),
                )
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type")
                    or video.content_type
                    or "video/mp4"
                )
                encoded = base64.b64encode(response.content).decode("ascii")
                return f"data:{content_type};base64,{encoded}"
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise RuntimeError("Failed to download TikTok video bytes for inline fallback.") from last_error
        raise RuntimeError("No candidate TikTok video URL was available for inline fallback.")

    def _http_get(self, url: str, **kwargs: Any) -> requests.Response:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 2):
            try:
                return self.session.get(url, **kwargs)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt > self.retries:
                    break
                time.sleep(self.retry_wait)
        assert last_error is not None
        raise last_error

    def _extract_video_id(self, url: str) -> str:
        match = re.search(r"/video/(\d+)", url)
        if match:
            return match.group(1)
        raise ValueError(f"Could not extract TikTok video id from URL: {url}")

    def _normalize_tiktok_video_url(self, url: str) -> str:
        hostname = urlparse(url).netloc.lower()
        if "tiktok.com" in hostname:
            return url
        raise ValueError(f"Unsupported TikTok URL: {url}")

    def _follow_short_link(self, url: str) -> str:
        response = self._http_get(
            url,
            allow_redirects=True,
            timeout=30,
            headers=self._build_page_headers(),
        )
        return response.url

    def _extract_item_struct(self, html: str) -> dict[str, Any]:
        match = self.hydration_script_re.search(html)
        if not match:
            raise RuntimeError(self._build_hydration_error(html))
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise RuntimeError("Failed to decode TikTok hydration JSON.") from exc

        try:
            return data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError("Could not extract TikTok itemStruct from hydration data.") from exc

    def _resolve_playable_video_url(self, video_url: str) -> dict[str, Any]:
        try:
            response = self._http_get(
                video_url,
                allow_redirects=True,
                stream=True,
                timeout=(10, 30),
                headers=self._build_media_headers("https://www.tiktok.com/"),
            )
            final_url = response.url
            if response.status_code >= 400:
                response.close()
                return {
                    "video_url": video_url,
                    "content_type": None,
                    "size_mb": None,
                    "video_url_source": "http_fallback",
                }
            content_type = response.headers.get("content-type")
            content_length = response.headers.get("content-length")
            content_range = response.headers.get("content-range")
            total_bytes = None
            if content_range and "/" in content_range:
                candidate = content_range.rsplit("/", 1)[-1]
                if candidate.isdigit():
                    total_bytes = int(candidate)
            elif content_length and content_length.isdigit():
                total_bytes = int(content_length)
            size_mb = total_bytes / 1024 / 1024 if total_bytes is not None else None
            response.close()
            return {
                "video_url": final_url,
                "content_type": content_type,
                "size_mb": size_mb,
                "video_url_source": "direct",
            }
        except requests.exceptions.RequestException:
            return {
                "video_url": video_url,
                "content_type": None,
                "size_mb": None,
                "video_url_source": "request_fallback",
            }

    @staticmethod
    def _build_page_headers() -> dict[str, str]:
        return {
            "User-Agent": TIKTOK_DESKTOP_UA,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.tiktok.com/",
        }

    @staticmethod
    def _build_media_headers(referer: str) -> dict[str, str]:
        return {
            "User-Agent": TIKTOK_DESKTOP_UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer or "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        }

    @staticmethod
    def _parse_duration_ms(value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value * 1000
        if isinstance(value, float):
            return int(value * 1000)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped) * 1000
        return None

    @staticmethod
    def _build_hydration_error(html: str) -> str:
        markers: list[str] = []
        lower_html = html.lower()
        for marker in ("__universal_data_for_rehydration__", "playaddr", "downloadaddr", "itemstruct", "captcha", "verify"):
            if marker in lower_html:
                markers.append(marker)
        marker_text = ",".join(markers) if markers else "none"
        return (
            "Could not find TikTok hydration data in page HTML. "
            f"html_len={len(html)}, markers={marker_text}"
        )
