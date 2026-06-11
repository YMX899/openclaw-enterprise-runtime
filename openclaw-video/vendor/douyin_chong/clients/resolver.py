from __future__ import annotations

from urllib.parse import urlparse

from .bilibili import BilibiliVideoResolver
from .douyin import DouyinVideoResolver
from .tiktok import TikTokVideoResolver


class UniversalVideoResolver:
    def __init__(self) -> None:
        self.bilibili = BilibiliVideoResolver()
        self.douyin = DouyinVideoResolver()
        self.tiktok = TikTokVideoResolver()

    def resolve(self, source_url: str):
        return self._pick_resolver(source_url).resolve(source_url)

    def build_video_data_url(self, video):
        return self._pick_resolver(video.source_url).build_video_data_url(video)

    def _pick_resolver(self, source_url: str):
        hostname = urlparse(source_url).netloc.lower()
        if any(domain in hostname for domain in ("bilibili.com", "b23.tv")):
            return self.bilibili
        if any(domain in hostname for domain in ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com")):
            return self.tiktok
        return self.douyin
