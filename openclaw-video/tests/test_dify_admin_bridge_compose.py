from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "openclaw-video" / "docker-compose.dify-admin-bridge.yaml"
SCRIPT = REPO_ROOT / "scripts" / "root_rebuild_dify_admin_bridge_fast.sh"


class DifyAdminBridgeComposeTests(unittest.TestCase):
    def test_admin_bridge_is_private_dify_identity_sidecar(self):
        text = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("dify-openclaw-bridge:", text)
        self.assertIn("BRIDGE_IDENTITY_PROVIDER: dify", text)
        self.assertIn("DIFY_API_BASE: ${DIFY_ADMIN_API_BASE:-http://nginx:8081}", text)
        self.assertIn('"127.0.0.1:18182:3000"', text)
        self.assertIn("BRIDGE_ENABLE_TEST_IDENTITY_HEADERS: \"0\"", text)
        self.assertIn("BRIDGE_TEST_IDENTITY_SECRET: \"\"", text)
        self.assertIn("name: openclaw_video_internal", text)
        self.assertIn("name: ${DIFY_DOCKER_NETWORK:-docker_default}", text)
        self.assertNotIn("0.0.0.0:18182", text)
        self.assertNotIn("0.0.0.0:18789", text)
        self.assertNotIn("/var/run/docker.sock", text)

    def test_admin_bridge_rebuild_script_only_recreates_admin_bridge(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("docker-compose.dify-admin-bridge.yaml", text)
        self.assertIn("dify-openclaw-bridge", text)
        self.assertIn("http://127.0.0.1:18182/healthz", text)
        self.assertIn("http://127.0.0.1:18182/openclaw-lab/", text)
        self.assertIn("dify_admin_bridge_fast_rebuild=PASS", text)
        self.assertNotIn("docker compose down", text)
        self.assertNotIn("docker restart docker-", text)


if __name__ == "__main__":
    unittest.main()
