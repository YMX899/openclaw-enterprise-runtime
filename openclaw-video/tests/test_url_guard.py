import unittest

from openclaw_video.url_guard import UrlRejected, validate_video_url, validate_video_url_with_redirects


def resolver(*addresses):
    return lambda _host, _port: list(addresses)


def resolver_by_host(mapping):
    def resolve(host, _port):
        return list(mapping[host])

    return resolve


def redirect_map(mapping):
    return lambda url: mapping.get(url)


class UrlGuardTests(unittest.TestCase):
    def test_accepts_public_douyin_https(self):
        result = validate_video_url("https://v.douyin.com/abc?b=2&a=1", resolver("110.242.68.66"))
        self.assertEqual(result.host, "v.douyin.com")
        self.assertIn("a=1&b=2", result.canonical)

    def test_accepts_public_tiktok_https(self):
        result = validate_video_url("https://www.tiktok.com/@demo/video/123", resolver("8.8.8.8"))
        self.assertEqual(result.host, "www.tiktok.com")

    def test_accepts_public_bilibili_https(self):
        result = validate_video_url("https://www.bilibili.com/video/BV1xx?p=2", resolver("8.8.8.8"))
        self.assertEqual(result.host, "www.bilibili.com")

    def test_accepts_bilibili_short_redirect_target(self):
        result = validate_video_url_with_redirects(
            "https://b23.tv/abc",
            resolver=resolver_by_host({"b23.tv": ["8.8.8.8"], "www.bilibili.com": ["8.8.8.8"]}),
            redirect_fetcher=redirect_map({"https://b23.tv/abc": "https://www.bilibili.com/video/BV1xx"}),
        )
        self.assertEqual(result.canonical, "https://www.bilibili.com/video/BV1xx")

    def test_rejects_non_douyin_domain(self):
        with self.assertRaises(UrlRejected):
            validate_video_url("https://example.com/video", resolver("93.184.216.34"))

    def test_rejects_localhost(self):
        with self.assertRaises(UrlRejected):
            validate_video_url("https://v.douyin.com/abc", resolver("127.0.0.1"))

    def test_rejects_private_network(self):
        with self.assertRaises(UrlRejected):
            validate_video_url("https://www.douyin.com/video/1", resolver("10.0.0.1"))

    def test_rejects_metadata_ip(self):
        with self.assertRaises(UrlRejected):
            validate_video_url("https://www.douyin.com/video/1", resolver("169.254.169.254"))

    def test_rejects_userinfo(self):
        with self.assertRaises(UrlRejected):
            validate_video_url("https://user:pass@v.douyin.com/abc", resolver("110.242.68.66"))

    def test_revalidates_allowed_redirect_target(self):
        result = validate_video_url_with_redirects(
            "https://v.douyin.com/abc",
            resolver=resolver_by_host({"v.douyin.com": ["110.242.68.66"], "www.douyin.com": ["110.242.68.66"]}),
            redirect_fetcher=redirect_map({"https://v.douyin.com/abc": "https://www.douyin.com/video/1"}),
        )
        self.assertEqual(result.canonical, "https://www.douyin.com/video/1")
        self.assertEqual(result.redirect_chain, ("https://v.douyin.com/abc", "https://www.douyin.com/video/1"))

    def test_rejects_redirect_to_non_allowlisted_domain(self):
        with self.assertRaises(UrlRejected):
            validate_video_url_with_redirects(
                "https://v.douyin.com/abc",
                resolver=resolver_by_host({"v.douyin.com": ["110.242.68.66"], "example.com": ["93.184.216.34"]}),
                redirect_fetcher=redirect_map({"https://v.douyin.com/abc": "https://example.com/video"}),
            )

    def test_rejects_redirect_to_private_ip_resolution(self):
        with self.assertRaises(UrlRejected):
            validate_video_url_with_redirects(
                "https://v.douyin.com/abc",
                resolver=resolver_by_host({"v.douyin.com": ["110.242.68.66"], "www.douyin.com": ["10.0.0.1"]}),
                redirect_fetcher=redirect_map({"https://v.douyin.com/abc": "https://www.douyin.com/video/1"}),
            )

    def test_rejects_redirect_loop(self):
        with self.assertRaises(UrlRejected):
            validate_video_url_with_redirects(
                "https://v.douyin.com/abc",
                resolver=resolver("110.242.68.66"),
                redirect_fetcher=redirect_map({"https://v.douyin.com/abc": "https://v.douyin.com/abc"}),
            )

    def test_rejects_too_many_redirects(self):
        with self.assertRaises(UrlRejected):
            validate_video_url_with_redirects(
                "https://v.douyin.com/1",
                resolver=resolver("110.242.68.66"),
                redirect_fetcher=redirect_map(
                    {
                        "https://v.douyin.com/1": "https://v.douyin.com/2",
                        "https://v.douyin.com/2": "https://v.douyin.com/3",
                    }
                ),
                max_redirects=1,
            )


if __name__ == "__main__":
    unittest.main()
