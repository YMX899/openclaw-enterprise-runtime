from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_public_browser_smoke.py"


class PublicBrowserSmokeScriptTests(unittest.TestCase):
    def test_script_uses_playwright_screenshots_and_sanitized_har_summary(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("playwright", text)
        self.assertIn("npx.cmd", text)
        self.assertIn("screenshot", text)
        self.assertIn("--save-har", text)
        self.assertIn("headers_recorded", text)
        self.assertIn("bodies_recorded", text)
        self.assertIn("secrets_recorded", text)
        self.assertNotIn("request-headers", text)
        self.assertNotIn("response-body", text)

    def test_script_checks_openclaw_and_dify_public_baselines(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("https://www.huahuoai.com/ai/openclaw-lab/", text)
        self.assertIn("https://www.huahuoai.com/openclaw-lab/", text)
        self.assertIn("https://www.huahuoai.com/openclaw-api/me", text)
        self.assertIn("https://www.huahuoai.com/ai/?id=4", text)
        self.assertIn(
            "https://ai001.huahuoai.com/app/d44c1add-5043-4b33-b513-1d4f6ec3b4f0/configuration",
            text,
        )
        self.assertIn("gateway_direct_request_count", text)
        self.assertIn("token_url_leak_count", text)


if __name__ == "__main__":
    unittest.main()
