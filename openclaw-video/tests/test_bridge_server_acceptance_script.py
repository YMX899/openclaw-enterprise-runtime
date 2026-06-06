from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_bridge_server_acceptance.py"


class BridgeServerAcceptanceScriptTests(unittest.TestCase):
    def test_acceptance_script_uses_guarded_test_identity_secret(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--test-secret", text)
        self.assertIn("BRIDGE_TEST_IDENTITY_SECRET", text)
        self.assertIn("x-openclaw-test-identity-secret", text)
        self.assertIn("test_identity_secret_present", text)
        self.assertIn("missing --test-secret or BRIDGE_TEST_IDENTITY_SECRET", text)

    def test_acceptance_script_covers_owner_isolation_and_invalid_url_worker_path(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("unauthenticated_me", text)
        self.assertIn("diagnostics_authenticated", text)
        self.assertIn("cross_user_session_404", text)
        self.assertIn("cross_user_job_404", text)
        self.assertIn("https://example.com/not-douyin", text)
        self.assertIn("invalid_url_job_rejected", text)
        self.assertIn("url_rejected", text)


if __name__ == "__main__":
    unittest.main()
