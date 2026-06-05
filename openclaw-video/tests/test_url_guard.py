import unittest

from openclaw_video.url_guard import UrlRejected, validate_video_url


def resolver(*addresses):
    return lambda _host, _port: list(addresses)


class UrlGuardTests(unittest.TestCase):
    def test_accepts_public_douyin_https(self):
        result = validate_video_url("https://v.douyin.com/abc?b=2&a=1", resolver("110.242.68.66"))
        self.assertEqual(result.host, "v.douyin.com")
        self.assertIn("a=1&b=2", result.canonical)

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


if __name__ == "__main__":
    unittest.main()

