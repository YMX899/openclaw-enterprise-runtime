from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.openclaw-video.yaml"


class ComposeContractTests(unittest.TestCase):
    def test_knowledge_base_is_mounted_read_only(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        expected_mount = "../artifacts/knowledge-base-short-video/2026.06.06:/knowledge/short-video:ro"
        self.assertIn(expected_mount, compose)
        self.assertIn("KNOWLEDGE_BASE_DIR: /knowledge/short-video", compose)
        self.assertIn("KNOWLEDGE_BASE_VERSION_FILE: /knowledge/short-video/VERSION", compose)
        self.assertNotIn(":/knowledge/short-video:rw", compose)
        self.assertNotIn(":/knowledge/short-video\n", compose)

    def test_sidecar_forbidden_public_surfaces_are_not_declared(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for forbidden in [
            "0.0.0.0:18789",
            "0.0.0.0:5432",
            "/var/run/docker.sock",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, compose)


if __name__ == "__main__":
    unittest.main()
