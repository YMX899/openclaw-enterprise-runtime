from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.openclaw-video.yaml"
GATEWAY_DOCKERFILE = ROOT / "docker" / "openclaw-gateway" / "Dockerfile"


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
            "OPENCLAW_GATEWAY_URL: http://",
            "OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN",
            "OPENCLAW_GATEWAY_TOKEN:",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, compose)

    def test_bridge_gateway_contract_uses_ws_and_read_only_secret_files(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for required in [
            "OPENCLAW_GATEWAY_URL: ws://openclaw-gateway:18789",
            "OPENCLAW_GATEWAY_TOKEN_FILE: /run/secrets/openclaw_gateway_token",
            "OPENCLAW_GATEWAY_DEVICE_KEY_FILE: /run/secrets/openclaw_bridge_device_key.pem",
            "./secrets/openclaw_gateway_token:/run/secrets/openclaw_gateway_token:ro",
            "./secrets/openclaw_bridge_device_key.pem:/run/secrets/openclaw_bridge_device_key.pem:ro",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, compose)

    def test_gateway_entrypoint_does_not_expand_token_into_process_args(self):
        dockerfile = GATEWAY_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("--auth token", dockerfile)
        self.assertNotIn("--token", dockerfile)
        self.assertIn("/run/secrets/openclaw_gateway_token", dockerfile)

    def test_sidecar_private_network_allows_required_egress(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("name: openclaw_video_internal", compose)
        self.assertNotIn("internal: true", compose)

    def test_worker_resource_and_filesystem_limits_are_declared(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for required in [
            "WORKER_CONCURRENCY: \"1\"",
            "JOB_TIMEOUT_SECONDS: \"900\"",
            "MAX_DOWNLOAD_BYTES: \"536870912\"",
            "MAX_VIDEO_DURATION_SECONDS: \"60\"",
            "MAX_VIDEO_FRAMES: \"1200\"",
            "./vendor/douyin_chong:/opt/douyin_chong:ro",
            "- worker-tmp:/tmp/openclaw-video",
            "read_only: true",
            "/tmp:size=1024m,nosuid,nodev",
            "pids_limit: 128",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, compose)

    def test_only_bridge_joins_dify_network(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        bridge_block = compose.split("  bridge-postgres:", 1)[0]
        gateway_block = compose.split("  openclaw-gateway:", 1)[1].split("  video-analysis-worker:", 1)[0]
        worker_block = compose.split("  video-analysis-worker:", 1)[1].split("volumes:", 1)[0]
        postgres_block = compose.split("  bridge-postgres:", 1)[1].split("  openclaw-gateway:", 1)[0]
        self.assertIn("- dify-default", bridge_block)
        self.assertNotIn("- dify-default", gateway_block)
        self.assertNotIn("- dify-default", worker_block)
        self.assertNotIn("- dify-default", postgres_block)


if __name__ == "__main__":
    unittest.main()
