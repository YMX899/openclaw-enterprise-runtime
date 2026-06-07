from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "huahuo_post_login_acceptance_runner.mjs"


class HuahuoPostLoginAcceptanceRunnerTests(unittest.TestCase):
    def test_runner_is_chrome_skill_helper_not_standalone_browser_controller(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("runHuahuoPostLoginAcceptance", text)
        self.assertIn("export async function runHuahuoPostLoginAcceptance", text)
        self.assertIn("export async function runDifyAuthenticatedBaseline", text)
        self.assertIn("browser.tabs.new", text)
        self.assertIn("Post-Login Acceptance", text)
        self.assertIn("openclaw-chrome-post-login-acceptance.v1", text)
        self.assertIn("dify-authenticated-baseline-browser-acceptance.v1", text)
        self.assertIn("PENDING_LOGIN", text)
        self.assertIn("https://www.huahuoai.com/openclaw-lab/", text)
        self.assertIn("https://www.huahuoai.com/ai/?id=4", text)
        self.assertIn("https://ai001.huahuoai.com/apps", text)
        self.assertNotIn("setupBrowserRuntime", text)
        self.assertNotIn("agent.browsers.get", text)
        self.assertNotIn("chromium.launch", text)
        self.assertNotIn("playwright.chromium", text)

    def test_runner_records_only_sanitized_visible_evidence(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("secrets_recorded: false", text)
        self.assertIn("headers_recorded: false", text)
        self.assertIn("local_storage_values_recorded: false", text)
        self.assertIn("session_storage_values_recorded: false", text)
        self.assertIn("tokens_recorded: false", text)
        self.assertIn("passwords_recorded: false", text)
        self.assertIn("locator(\"body\").innerText", text)
        self.assertIn("locator(\"#output\").innerText", text)
        self.assertNotIn("document.cookie", text)
        self.assertNotIn("localStorage.getItem", text)
        self.assertNotIn("localStorage", text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("request.headers", text)
        self.assertNotIn("storageState", text)


if __name__ == "__main__":
    unittest.main()
