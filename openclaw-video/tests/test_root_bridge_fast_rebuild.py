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
        self.assertIn("COPY vendor/douyin_chong /app/vendor/douyin_chong", text)
        self.assertIn("pip install --no-cache-dir --no-deps /app", text)
        self.assertIn("BRIDGE_ENABLE_TEST_IDENTITY_HEADERS", text)
        self.assertIn("BRIDGE_TEST_IDENTITY_SECRET", text)
        self.assertIn("DIFY_API_CONTAINER", text)
        self.assertIn("DIFY_AUTH_DB_HOST", text)
        self.assertIn("DIFY_AUTH_DB_PASSWORD", text)
        self.assertIn("DB_PASSWORD", text)
        self.assertIn('OPENCLAW_ENABLE_HUAHUO_PASSWORD_LOGIN="1"', text)
        self.assertIn('OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY="0"', text)
        self.assertIn("OPENCLAW_SHARED_SECRETS_DIR:-/app/bin/openclaw-video/shared/secrets", text)
        self.assertIn("release secrets directory contains non-placeholder entries", text)
        self.assertIn("find secrets -mindepth 1 -depth -type d -empty -exec rmdir {} +", text)
        self.assertIn("elif [ ! -e secrets ]; then", text)
        self.assertIn("ln -s \"$SHARED_SECRETS_DIR\" secrets", text)
        self.assertIn("up -d --no-deps --force-recreate openclaw-bridge", text)
        self.assertIn("bridge_fast_rebuild=PASS", text)
        self.assertNotIn("video-analysis-worker", text)
        self.assertNotIn("docker compose -p docker", text)

    def test_compose_bridge_image_can_be_overridden_for_fast_rebuild(self):
        text = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("image: ${OPENCLAW_BRIDGE_IMAGE:-openclaw-video-openclaw-bridge}", text)
        self.assertIn("BRIDGE_ENABLE_TEST_IDENTITY_HEADERS: ${BRIDGE_ENABLE_TEST_IDENTITY_HEADERS:-0}", text)
        self.assertIn("BRIDGE_TEST_IDENTITY_SECRET: ${BRIDGE_TEST_IDENTITY_SECRET:-}", text)
        self.assertIn('MAX_DOWNLOAD_BYTES: "536870912"', text)
        self.assertIn('MAX_VIDEO_DURATION_SECONDS: "300"', text)
        self.assertIn("DIFY_AUTH_DB_HOST: ${DIFY_AUTH_DB_HOST:-}", text)
        self.assertIn("DIFY_AUTH_DB_PASSWORD: ${DIFY_AUTH_DB_PASSWORD:-}", text)
        self.assertIn('OPENCLAW_ENABLE_HUAHUO_PASSWORD_LOGIN: "1"', text)
        self.assertNotIn("OPENCLAW_ENABLE_HUAHUO_PASSWORD_LOGIN: ${OPENCLAW_ENABLE_HUAHUO_PASSWORD_LOGIN:-1}", text)
        self.assertIn('OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY: "0"', text)
        self.assertIn("OPENCLAW_LOGIN_ACCOUNT_ALIASES: ${OPENCLAW_LOGIN_ACCOUNT_ALIASES:-}", text)
        self.assertIn("OPENCLAW_SESSION_TTL_SECONDS: ${OPENCLAW_SESSION_TTL_SECONDS:-604800}", text)
        self.assertIn("openclaw-bridge:", text)


if __name__ == "__main__":
    unittest.main()
