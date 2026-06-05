import unittest

from openclaw_video.dify_client import identity_headers


class DifyClientTests(unittest.TestCase):
    def test_identity_headers_only_forward_dify_login_material(self):
        selected = identity_headers(
            {
                "Authorization": "Bearer dify",
                "Cookie": "session=1",
                "X-CSRF-Token": "csrf",
                "User-Agent": "browser",
                "OpenClaw-Gateway-Token": "gateway-secret",
            }
        )
        self.assertEqual(selected["Authorization"], "Bearer dify")
        self.assertEqual(selected["Cookie"], "session=1")
        self.assertEqual(selected["X-CSRF-Token"], "csrf")
        self.assertNotIn("User-Agent", selected)
        self.assertNotIn("OpenClaw-Gateway-Token", selected)


if __name__ == "__main__":
    unittest.main()

