import json
import unittest
from types import SimpleNamespace

from openclaw_video.url_guard import UrlRejected
from openclaw_video.video_link_probe import VideoLinkProbeConfig, probe_video_link
from openclaw_video.video_limits import MAX_VIDEO_BYTES


def public_resolver(host, port):
    return ["8.8.8.8"]


def one_hop_redirect(url):
    if url == "https://v.douyin.com/abc":
        return "https://www.douyin.com/video/123?b=2&a=1"
    return None


class FakeResolver:
    def __init__(self, video):
        self.video = video
        self.calls = []

    def resolve(self, url):
        self.calls.append(url)
        return self.video


class VideoLinkProbeTests(unittest.TestCase):
    def test_probe_sanitizes_real_urls_and_does_not_invoke_model(self):
        raw_url = "https://v.douyin.com/abc"
        direct_url = "https://v3-dy-o.zjcdn.com/video/tos/example.mp4?token=secret"
        playwm_url = "https://v26-dy.ixigua.com/video/tos/example.mp4?token=secret"
        fake_video = SimpleNamespace(
            video_url=direct_url,
            playwm_url=playwm_url,
            source_url=raw_url,
            share_url="https://www.douyin.com/video/123?secret=value",
            video_id="123",
            content_type="video/mp4",
            duration_ms=12_345,
            size_mb=2.5,
            video_url_source="direct",
        )
        legacy = FakeResolver(fake_video)

        payload = probe_video_link(
            raw_url,
            resolver=public_resolver,
            redirect_fetcher=one_hop_redirect,
            legacy_resolver=legacy,
        )

        self.assertEqual(payload["schema_version"], "openclaw-video-link-read-check.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(legacy.calls, ["https://www.douyin.com/video/123?a=1&b=2"])
        self.assertEqual(payload["canonical_host"], "www.douyin.com")
        self.assertEqual(payload["redirect_hop_count"], 1)
        self.assertEqual(payload["redirect_chain_hosts"], ["v.douyin.com", "www.douyin.com"])
        self.assertEqual(payload["direct_video_candidate_count"], 2)
        self.assertEqual(payload["direct_video_host"], "v3-dy-o.zjcdn.com")
        self.assertEqual(payload["playwm_host"], "v26-dy.ixigua.com")
        self.assertEqual(payload["duration_seconds"], 12.345)
        self.assertEqual(payload["size_bytes"], 2_621_440)
        self.assertTrue(payload["limits"]["eligible_for_model_analysis"])
        self.assertFalse(payload["raw_url_recorded"])
        self.assertFalse(payload["direct_video_url_recorded"])
        self.assertFalse(payload["cookies_recorded"])
        self.assertFalse(payload["headers_recorded"])
        self.assertFalse(payload["tokens_recorded"])
        self.assertFalse(payload["model_invoked"])

        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(raw_url, serialized)
        self.assertNotIn(direct_url, serialized)
        self.assertNotIn(playwm_url, serialized)
        self.assertNotIn("secret", serialized)
        for key in ("input_url_sha256", "canonical_url_sha256", "source_url_sha256", "share_url_sha256", "video_id_sha256"):
            self.assertRegex(payload[key], r"^[a-f0-9]{64}$")

    def test_probe_does_not_reject_by_duration(self):
        fake_video = SimpleNamespace(
            video_url="https://cdn.douyin.com/video.mp4",
            playwm_url="",
            source_url="",
            share_url="",
            video_id="",
            content_type="video/mp4",
            duration_ms=61_000,
            size_mb=1,
            video_url_source="direct",
        )

        payload = probe_video_link(
            "https://www.douyin.com/video/123",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
            config=VideoLinkProbeConfig(max_duration_seconds=60, max_download_bytes=MAX_VIDEO_BYTES),
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["limits"]["eligible_for_model_analysis"])
        self.assertTrue(payload["limits"]["duration_ok"])
        self.assertTrue(payload["limits"]["size_ok"])
        self.assertFalse(payload["model_invoked"])

    def test_probe_ignores_legacy_model_size_budget_for_files_api(self):
        fake_video = SimpleNamespace(
            video_url="https://cdn.douyin.com/video.mp4",
            playwm_url="",
            source_url="",
            share_url="",
            video_id="",
            content_type="video/mp4",
            duration_ms=45_000,
            size_mb=86,
            video_url_source="direct",
        )

        payload = probe_video_link(
            "https://www.douyin.com/video/123",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["limits"]["max_download_bytes"], 500 * 1024 * 1024)
        self.assertEqual(payload["limits"]["max_model_video_bytes"], 50 * 1024 * 1024)
        self.assertTrue(payload["limits"]["eligible_for_model_analysis"])
        self.assertTrue(payload["limits"]["download_size_ok"])
        self.assertTrue(payload["limits"]["model_size_ok"])
        self.assertTrue(payload["limits"]["fps_adjusted"])
        self.assertAlmostEqual(payload["limits"]["video_understanding_fps"], 1.7442, places=4)

    def test_probe_warns_when_video_exceeds_500mib_download_limit(self):
        fake_video = SimpleNamespace(
            video_url="https://cdn.douyin.com/video.mp4",
            playwm_url="",
            source_url="",
            share_url="",
            video_id="",
            content_type="video/mp4",
            duration_ms=45_000,
            size_mb=1200,
            video_url_source="direct",
        )

        payload = probe_video_link(
            "https://www.douyin.com/video/123",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
            config=VideoLinkProbeConfig(max_download_bytes=500 * 1024 * 1024),
        )

        self.assertEqual(payload["status"], "WARN")
        self.assertFalse(payload["limits"]["eligible_for_model_analysis"])
        self.assertFalse(payload["limits"]["download_size_ok"])
        self.assertFalse(payload["limits"]["size_ok"])

    def test_probe_accepts_videos_up_to_five_minutes_by_default(self):
        fake_video = SimpleNamespace(
            video_url="https://cdn.douyin.com/video.mp4",
            playwm_url="",
            source_url="",
            share_url="",
            video_id="",
            content_type="video/mp4",
            duration_ms=299_000,
            size_mb=10,
            video_url_source="direct",
        )

        payload = probe_video_link(
            "https://www.douyin.com/video/123",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["limits"]["max_duration_seconds"], 0)
        self.assertTrue(payload["limits"]["eligible_for_model_analysis"])
        self.assertTrue(payload["limits"]["duration_ok"])

    def test_probe_accepts_video_longer_than_five_minutes_by_default(self):
        fake_video = SimpleNamespace(
            video_url="https://cdn.douyin.com/video.mp4",
            playwm_url="",
            source_url="",
            share_url="",
            video_id="",
            content_type="video/mp4",
            duration_ms=301_000,
            size_mb=10,
            video_url_source="direct",
        )

        payload = probe_video_link(
            "https://www.douyin.com/video/123",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["limits"]["max_duration_seconds"], 0)
        self.assertTrue(payload["limits"]["eligible_for_model_analysis"])
        self.assertTrue(payload["limits"]["duration_ok"])

    def test_probe_accepts_bilibili_link(self):
        fake_video = SimpleNamespace(
            video_url="https://upos-sz-mirror.example/video.m4s",
            playwm_url="",
            source_url="https://www.bilibili.com/video/BV1xx",
            share_url="https://www.bilibili.com/video/BV1xx",
            video_id="BV1xx",
            content_type="video/mp4",
            duration_ms=30_000,
            size_mb=2,
            video_url_source="direct",
        )

        payload = probe_video_link(
            "https://www.bilibili.com/video/BV1xx",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["canonical_host"], "www.bilibili.com")
        self.assertEqual(payload["video_id_present"], True)

    def test_probe_accepts_tiktok_link(self):
        fake_video = SimpleNamespace(
            video_url="https://v16-webapp-prime.example/video.mp4",
            playwm_url="",
            source_url="https://www.tiktok.com/@demo/video/123",
            share_url="https://www.tiktok.com/@demo/video/123",
            video_id="123",
            content_type="video/mp4",
            duration_ms=30_000,
            size_mb=2,
            video_url_source="direct",
        )

        payload = probe_video_link(
            "https://www.tiktok.com/@demo/video/123",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["canonical_host"], "www.tiktok.com")
        self.assertEqual(payload["video_id_present"], True)

    def test_probe_accepts_xiaohongshu_link(self):
        fake_video = SimpleNamespace(
            video_url="https://sns-video.example/video.mp4",
            playwm_url="",
            source_url="https://www.xiaohongshu.com/explore/abc",
            share_url="https://www.xiaohongshu.com/explore/abc",
            video_id="abc",
            content_type="video/mp4",
            duration_ms=90_000,
            size_mb=5,
            video_url_source="yt-dlp",
        )

        payload = probe_video_link(
            "https://www.xiaohongshu.com/explore/abc",
            resolver=public_resolver,
            redirect_fetcher=lambda url: None,
            legacy_resolver=FakeResolver(fake_video),
        )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["canonical_host"], "www.xiaohongshu.com")
        self.assertEqual(payload["video_url_source"], "yt-dlp")

    def test_probe_reuses_url_guard_rejections(self):
        with self.assertRaises(UrlRejected):
            probe_video_link(
                "https://example.com/video/123",
                resolver=public_resolver,
                redirect_fetcher=lambda url: None,
                legacy_resolver=FakeResolver(SimpleNamespace()),
            )


if __name__ == "__main__":
    unittest.main()
