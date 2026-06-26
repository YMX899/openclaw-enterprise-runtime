from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "root_rebuild_bridge_fast.sh"
WORKER_SCRIPT = REPO_ROOT / "scripts" / "root_rebuild_worker_fast.sh"
UNIFY_SCRIPT = REPO_ROOT / "scripts" / "unify_openclaw_video_deploy_source.sh"
COMPOSE = REPO_ROOT / "openclaw-video" / "docker-compose.openclaw-video.yaml"
BRIDGE_FAST_DOCKERFILE = REPO_ROOT / "openclaw-video" / "docker" / "bridge" / "Fast.Dockerfile"
WORKER_FAST_DOCKERFILE = REPO_ROOT / "openclaw-video" / "docker" / "worker" / "Fast.Dockerfile"


class RootBridgeFastRebuildTests(unittest.TestCase):
    def test_fast_rebuild_reuses_existing_bridge_image_and_skips_dependency_resolution(self):
        text = SCRIPT.read_text(encoding="utf-8")
        dockerfile = BRIDGE_FAST_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("OPENCLAW_BRIDGE_BASE_IMAGE:-openclaw-video-openclaw-bridge", text)
        self.assertIn("OPENCLAW_BRIDGE_FAST_IMAGE:-openclaw-video-openclaw-bridge:fast", text)
        self.assertIn("OPENCLAW_BRIDGE_FAST_DOCKERFILE:-docker/bridge/Fast.Dockerfile", text)
        self.assertIn("COPY vendor/douyin_chong /app/vendor/douyin_chong", dockerfile)
        self.assertIn("pip install --no-cache-dir --no-deps /app", dockerfile)
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

    def test_worker_fast_rebuild_uses_versioned_template_and_scales_worker_only(self):
        text = WORKER_SCRIPT.read_text(encoding="utf-8")
        dockerfile = WORKER_FAST_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("OPENCLAW_WORKER_BASE_IMAGE:-openclaw-video-video-analysis-worker", text)
        self.assertIn("OPENCLAW_WORKER_FAST_DOCKERFILE:-docker/worker/Fast.Dockerfile", text)
        self.assertIn("COPY vendor/douyin_chong /app/vendor/douyin_chong", dockerfile)
        self.assertIn("pip install --no-cache-dir --no-deps /app", dockerfile)
        self.assertIn("--scale \"video-analysis-worker=${WORKER_REPLICAS}\" video-analysis-worker", text)
        self.assertIn("worker_fast_rebuild=PASS", text)
        self.assertNotIn("openclaw-bridge", text.split("docker compose", 1)[-1])

    def test_unified_deploy_uses_project_git_commit_as_only_source(self):
        text = UNIFY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("SOURCE_ROOT=\"${OPENCLAW_SOURCE_ROOT:-/project/Dify}\"", text)
        self.assertIn("git status --short", text)
        self.assertIn("COMMIT=\"$(git rev-parse HEAD)\"", text)
        self.assertIn("git archive --format=tar \"$COMMIT\"", text)
        self.assertIn("ln -sfn \"$RELEASE_DIR\" \"$CURRENT_LINK\"", text)
        self.assertIn("root_rebuild_bridge_fast.sh", text)
        self.assertIn("root_rebuild_worker_fast.sh", text)
        self.assertIn("systemctl restart openclaw-video-worker-autoscaler.service", text)
        self.assertNotIn("/tmp/openclaw-video-deploy", text)

    def test_autoscaler_start_script_defaults_to_current_release(self):
        text = (REPO_ROOT / "scripts" / "start_openclaw_video_worker_autoscaler.sh").read_text(encoding="utf-8")

        self.assertIn(
            'WORKDIR="${OPENCLAW_VIDEO_WORKDIR:-/app/bin/openclaw-video/current/openclaw-video}"',
            text,
        )
        self.assertNotIn("/tmp/openclaw-video-deploy", text)

    def test_compose_bridge_image_can_be_overridden_for_fast_rebuild(self):
        text = COMPOSE.read_text(encoding="utf-8")

        self.assertIn("image: ${OPENCLAW_BRIDGE_IMAGE:-openclaw-video-openclaw-bridge}", text)
        self.assertIn("BRIDGE_ENABLE_TEST_IDENTITY_HEADERS: ${BRIDGE_ENABLE_TEST_IDENTITY_HEADERS:-0}", text)
        self.assertIn("BRIDGE_TEST_IDENTITY_SECRET: ${BRIDGE_TEST_IDENTITY_SECRET:-}", text)
        self.assertIn('MAX_DOWNLOAD_BYTES: "524288000"', text)
        self.assertIn('MAX_VIDEO_DURATION_SECONDS: "0"', text)
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
