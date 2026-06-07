from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from ..models import VideoSource


MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


class DouyinVideoResolver:
    router_assignment_re = re.compile(r"window\._ROUTER_DATA\s*=\s*", re.S)
    router_data_re = re.compile(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)

    def __init__(self, *, retries: int = 2, retry_wait: float = 1.5) -> None:
        self.retries = retries
        self.retry_wait = retry_wait
        self.session = requests.Session()

    def resolve(self, source_url: str) -> VideoSource:
        normalized_url = self._normalize_douyin_video_url(source_url)
        if "iesdouyin.com/share/video/" in normalized_url:
            share_url = normalized_url
        else:
            share_url = self._follow_short_link(normalized_url)

        page_candidates = self._build_page_candidates(
            source_url=source_url,
            normalized_url=normalized_url,
            share_url=share_url,
        )
        header_profiles = (
            self._build_page_headers(MOBILE_UA),
            self._build_page_headers(DESKTOP_UA),
        )

        router_data: Optional[dict[str, Any]] = None
        resolved_page_url = share_url
        last_error: Optional[Exception] = None

        for page_url in page_candidates:
            for headers in header_profiles:
                try:
                    html = self._http_get(
                        page_url,
                        timeout=20,
                        headers=headers,
                    ).text
                    router_data = self._extract_router_data(html)
                    resolved_page_url = page_url
                    break
                except Exception as exc:
                    last_error = exc
            if router_data is not None:
                break

        if router_data is None:
            if last_error is not None:
                raise RuntimeError(str(last_error)) from last_error
            raise RuntimeError("Failed to resolve Douyin router data from any candidate page.")

        try:
            item = router_data["loaderData"]["video_(id)/page"]["videoInfoRes"]["item_list"][0]
            video = item["video"]
            playwm_url = video["play_addr"]["url_list"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Could not extract Douyin video data from router payload.") from exc

        playable = self._resolve_playable_video_url(playwm_url)
        return VideoSource(
            source_url=source_url,
            video_id=self._extract_video_id(source_url),
            share_url=resolved_page_url,
            playwm_url=playwm_url,
            video_url=playable["video_url"],
            author=str(item.get("author", {}).get("nickname", "")),
            desc=str(item.get("desc", "")),
            duration_ms=self._parse_intish(video.get("duration")),
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
                    headers={"User-Agent": "Mozilla/5.0"},
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
            raise RuntimeError("Failed to download video bytes for inline fallback.") from last_error
        raise RuntimeError("No candidate video URL was available for inline fallback.")

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
        patterns = (
            r"/video/(\d+)",
            r"/note/(\d+)",
            r"/share/video/(\d+)",
            r"[?&]modal_id=(\d+)",
            r"[?&]vid=(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ValueError(f"Could not extract video id from URL: {url}")

    def _normalize_douyin_video_url(self, url: str) -> str:
        hostname = urlparse(url).netloc.lower()
        if "v.douyin.com" in hostname:
            return url
        video_id = self._extract_video_id(url)
        return f"https://www.iesdouyin.com/share/video/{video_id}/?from_ssr=1"

    def _follow_short_link(self, url: str) -> str:
        response = self._http_get(
            url,
            allow_redirects=False,
            timeout=20,
            headers=self._build_page_headers(DESKTOP_UA),
        )
        if response.is_redirect and response.headers.get("Location"):
            return response.headers["Location"]
        return url

    def _extract_router_data(self, html: str) -> dict[str, Any]:
        match = self.router_assignment_re.search(html)
        if match:
            try:
                payload = self._extract_balanced_json(html, match.end())
                return json.loads(payload)
            except Exception:
                pass

        regex_match = self.router_data_re.search(html)
        if regex_match:
            try:
                return json.loads(regex_match.group(1))
            except json.JSONDecodeError as exc:
                raise RuntimeError("Failed to decode Douyin router data.") from exc

        raise RuntimeError(self._build_router_error(html))

    def _resolve_playable_video_url(self, playwm_url: str) -> dict[str, Any]:
        try:
            response = self._http_get(
                playwm_url,
                allow_redirects=True,
                stream=True,
                timeout=(10, 30),
                headers={"User-Agent": DESKTOP_UA},
            )
            final_url = response.url
            if response.status_code >= 400:
                response.close()
                return {
                    "video_url": playwm_url,
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
                "video_url": playwm_url,
                "content_type": None,
                "size_mb": None,
                "video_url_source": "request_fallback",
            }

    @staticmethod
    def _parse_intish(value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _build_page_candidates(
        self,
        *,
        source_url: str,
        normalized_url: str,
        share_url: str,
    ) -> list[str]:
        last_error: Exception | None = None
        for candidate_url in (source_url, normalized_url, share_url):
            try:
                video_id = self._extract_video_id(candidate_url)
                break
            except ValueError as exc:
                last_error = exc
        else:
            raise ValueError(f"Could not extract video id from URL: {source_url}") from last_error
        candidates = [
            share_url,
            normalized_url,
            f"https://www.iesdouyin.com/share/video/{video_id}/?from_ssr=1",
            f"https://www.iesdouyin.com/share/video/{video_id}/",
            source_url,
        ]
        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _build_page_headers(user_agent: str) -> dict[str, str]:
        return {
            "User-Agent": user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.douyin.com/",
        }

    @staticmethod
    def _extract_balanced_json(text: str, start_index: int) -> str:
        start = text.find("{", start_index)
        if start < 0:
            raise RuntimeError("Could not find the start of Douyin router JSON.")

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]

        raise RuntimeError("Could not find the end of Douyin router JSON.")

    @staticmethod
    def _build_router_error(html: str) -> str:
        markers: list[str] = []
        lower_html = html.lower()
        for marker in ("window._router_data", "__next_data__", "render_data", "verify", "captcha", "secsdk"):
            if marker in lower_html:
                markers.append(marker)
        marker_text = ",".join(markers) if markers else "none"
        return (
            "Could not find Douyin router data in share page HTML. "
            f"html_len={len(html)}, markers={marker_text}"
        )
