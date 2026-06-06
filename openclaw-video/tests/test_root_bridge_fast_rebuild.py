from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "root_rebuild_bridge_fast.sh"
COMPOSE = REPO_ROOT / "openclaw-video" / "docker-compose.openclaw-video.yaml"


class RootBridgeFastRebuildTests(unittest.TestCase):
    def test_fast_rebuild_reuses_existing_bridge_image_and_skips_dependency_resolution(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("OPENCLAW_BRIDGE_BASE_IMAGE:-openclaw-video-openclaw-bridge", text)
        self.assertIn("OPENCLAW_BRIDGE_FAST_IMAGE:-openclaw-video-openclaw-bridge:fast", text)
        self.assertIn("pip install --no-cache-dir --no-deps /app", text)
        self.assertIn("up -d --no-deps --force-recreate openclaw-bridge", text)
        self.assertIn("bridge_fast_rebuild=PASS", text)
        self.assertNotIn("video-analysis-worker", text)
        self.assertNotIn("docker compose -p docker", text)

    def test_compose_bridge_image_can_be_overridden_for_fast_rebuild(self):
        text = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("image: ${OPENCLAW_BRIDGE_IMAGE:-openclaw-video-openclaw-bridge}", text)
        self.assertIn("openclaw-bridge:", text)


if __name__ == "__main__":
    unittest.main()
