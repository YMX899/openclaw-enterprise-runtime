import unittest

from openclaw_video.redaction import redact_headers, safe_error_message


class RedactionTests(unittest.TestCase):
    def test_redacts_sensitive_headers(self):
        redacted = redact_headers(
            {
                "Authorization": "Bearer secret",
                "Cookie": "a=b",
                "X-CSRF-Token": "csrf",
                "User-Agent": "test",
            }
        )
        self.assertEqual(redacted["Authorization"], "<redacted>")
        self.assertEqual(redacted["Cookie"], "<redacted>")
        self.assertEqual(redacted["X-CSRF-Token"], "<redacted>")
        self.assertEqual(redacted["User-Agent"], "test")

    def test_safe_error_message_hides_tokens(self):
        self.assertEqual(safe_error_message(RuntimeError("failed Bearer abc")), "internal error")


if __name__ == "__main__":
    unittest.main()

