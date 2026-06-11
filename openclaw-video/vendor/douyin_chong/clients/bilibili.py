from __future__ import annotations

import base64
import re
import time
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests

from ..models import VideoSource


BILIBILI_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


class BilibiliVideoResolver:
    bvid_re = re.compile(r"(BV[0-9A-Za-z]+)")

    def __init__(self, *, retries: int = 2, retry_wait: float = 1.5) -> None:
        self.retries = retries
        self.retry_wait = retry_wait
        self.session = requests.Session()

    def resolve(self, source_url: str) -> VideoSource:
        page_url = self._follow_short_link(source_url)
        bvid = self._extract_bvid(page_url) or self._extract_bvid(source_url)
        if not bvid:
            raise ValueError(f"Could not extract Bilibili BV id from URL: {source_url}")

        view_data = self._get_view_data(bvid)
        page_number = self._extract_page_number(page_url) or self._extract_page_number(source_url)
        page = self._select_page(view_data, page_number)
        cid = int(page.get("cid") or view_data.get("cid") or 0)
        if not cid:
            raise RuntimeError(f"Could not determine Bilibili cid for {bvid}.")

        play_data = self._get_play_data(bvid=bvid, cid=cid)
        playable = self._extract_playable_url(play_data)
        video_url = str(playable.get("url") or "")
        if not video_url:
            raise RuntimeError(f"Could not extract Bilibili playable URL for {bvid}.")

        probed = self._probe_media_url(video_url, page_url)
        owner = view_data.get("owner") if isinstance(view_data.get("owner"), dict) else {}
        return VideoSource(
            source_url=source_url,
            video_id=bvid,
            share_url=page_url,
            playwm_url=video_url,
            video_url=probed["video_url"],
            author=str(owner.get("name") or ""),
            desc=str(view_data.get("title") or view_data.get("desc") or ""),
            duration_ms=self._parse_duration_ms(view_data.get("duration")),
            content_type=probed["content_type"] or playable.get("content_type"),
            size_mb=probed["size_mb"],
            video_url_source=probed["video_url_source"],
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
                    timeout=(20, 180),
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
            raise RuntimeError("Failed to download Bilibili video bytes for inline fallback.") from last_error
        raise RuntimeError("No candidate Bilibili video URL was available for inline fallback.")

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

    def _follow_short_link(self, url: str) -> str:
        response = self._http_get(
            url,
            allow_redirects=True,
            timeout=20,
            headers=self._build_page_headers(),
        )
        return response.url or url

    def _extract_bvid(self, url: str) -> str:
        match = self.bvid_re.search(url)
        return match.group(1) if match else ""

    def _get_view_data(self, bvid: str) -> dict[str, Any]:
        response = self._http_get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            timeout=20,
            headers=self._build_api_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("code") or 0) != 0:
            raise RuntimeError(
                f"Bilibili view API failed for {bvid}: {payload.get('message') or payload}"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(f"Bilibili view API returned no data for {bvid}.")
        return data

    def _get_play_data(self, *, bvid: str, cid: int) -> dict[str, Any]:
        response = self._http_get(
            "https://api.bilibili.com/x/player/playurl",
            params={
                "bvid": bvid,
                "cid": cid,
                "platform": "html5",
                "high_quality": 1,
            },
            timeout=20,
            headers=self._build_api_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        if int(payload.get("code") or 0) != 0:
            raise RuntimeError(
                f"Bilibili playurl API failed for {bvid}/{cid}: {payload.get('message') or payload}"
            )
        data = payload.get("data") or payload.get("result")
        if not isinstance(data, dict):
            raise RuntimeError(f"Bilibili playurl API returned no data for {bvid}/{cid}.")
        return data

    @staticmethod
    def _extract_playable_url(play_data: dict[str, Any]) -> dict[str, Any]:
        durl = play_data.get("durl")
        if isinstance(durl, list) and durl:
            first = durl[0]
            if isinstance(first, dict):
                return {
                    "url": str(first.get("url") or ""),
                    "content_type": "video/mp4",
                }

        dash = play_data.get("dash")
        if isinstance(dash, dict):
            videos = dash.get("video")
            if isinstance(videos, list) and videos:
                first = videos[0]
                if isinstance(first, dict):
                    return {
                        "url": str(first.get("baseUrl") or first.get("base_url") or ""),
                        "content_type": str(first.get("mimeType") or "video/mp4"),
                    }
        return {"url": "", "content_type": None}

    def _probe_media_url(self, video_url: str, referer: str) -> dict[str, Any]:
        try:
            response = self._http_get(
                video_url,
                allow_redirects=True,
                stream=True,
                timeout=(10, 30),
                headers=self._build_media_headers(referer),
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
    def _extract_page_number(url: str) -> Optional[int]:
        query = parse_qs(urlparse(url).query)
        values = query.get("p")
        if not values:
            return None
        try:
            page_number = int(values[0])
        except (TypeError, ValueError):
            return None
        return page_number if page_number > 0 else None

    @staticmethod
    def _select_page(view_data: dict[str, Any], page_number: Optional[int]) -> dict[str, Any]:
        pages = view_data.get("pages")
        if not isinstance(pages, list) or not pages:
            return {}
        index = (page_number or 1) - 1
        if 0 <= index < len(pages) and isinstance(pages[index], dict):
            return pages[index]
        first = pages[0]
        return first if isinstance(first, dict) else {}

    @staticmethod
    def _parse_duration_ms(value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value * 1000
        if isinstance(value, float):
            return int(value * 1000)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip()) * 1000
        return None

    @staticmethod
    def _build_page_headers() -> dict[str, str]:
        return {
            "User-Agent": BILIBILI_DESKTOP_UA,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.bilibili.com/",
        }

    @staticmethod
    def _build_api_headers() -> dict[str, str]:
        return {
            "User-Agent": BILIBILI_DESKTOP_UA,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.bilibili.com/",
        }

    @staticmethod
    def _build_media_headers(referer: str) -> dict[str, str]:
        return {
            "User-Agent": BILIBILI_DESKTOP_UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer or "https://www.bilibili.com/",
        }
