from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install_openclaw_lab_public_port.sh"
ROLLBACK_SCRIPT = REPO_ROOT / "scripts" / "rollback_openclaw_lab_public_port.sh"
RUNBOOK = REPO_ROOT / "openclaw-lab-public-port-runbook.md"


class PublicPortScriptTests(unittest.TestCase):
    def test_install_script_uses_independent_tls_port_and_bridge_backend(self):
        text = INSTALL_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('OPENCLAW_PUBLIC_PORT:-18443', text)
        self.assertIn('OPENCLAW_BRIDGE_BACKEND:-http://127.0.0.1:18181', text)
        self.assertIn('openclaw-lab-public-${PORT}.conf', text)
        self.assertIn('listen       ${PORT} ssl;', text)
        self.assertIn('location ^~ /openclaw-lab/', text)
        self.assertIn('location ^~ /openclaw-api/', text)
        self.assertIn('proxy_pass ${BACKEND};', text)
        self.assertIn('openresty -t', text)
        self.assertIn('openresty -s reload', text)
        self.assertIn('local_https_me=401', text)

    def test_install_script_does_not_publish_gateway_postgres_or_touch_dify(self):
        text = INSTALL_SCRIPT.read_text(encoding="utf-8").lower()

        self.assertNotIn("docker compose -p docker", text)
        self.assertNotIn("docker restart docker-", text)
        self.assertNotIn("docker compose down", text)
        self.assertNotIn(":18789", text)
        self.assertNotIn(":5432", text)

    def test_rollback_removes_only_managed_public_port_config(self):
        text = ROLLBACK_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('openclaw-lab-public-${PORT}.conf', text)
        self.assertIn('managed-by: openclaw-video install_openclaw_lab_public_port.sh', text)
        self.assertIn('rm -f "$TARGET_CONF"', text)
        self.assertIn('openresty -t', text)
        self.assertIn('openresty -s reload', text)
        self.assertNotIn("docker compose -p docker", text)

    def test_runbook_records_public_port_gate_and_dify_baseline(self):
        text = RUNBOOK.read_text(encoding="utf-8")

        self.assertIn("https://ai001.huahuoai.com:18443/openclaw-lab/", text)
        self.assertIn("https://ai001.huahuoai.com:18443/openclaw-api/", text)
        self.assertIn("https://ai001.huahuoai.com/signin -> 200", text)
        self.assertIn("rollback", text.lower())
        self.assertIn("does not change Dify compose", text)


if __name__ == "__main__":
    unittest.main()
