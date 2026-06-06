from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "root_private_sidecar_build.sh"


class RootPrivateSidecarBuildScriptTests(unittest.TestCase):
    def test_build_script_is_private_project_scoped_and_logs_redacted(self):
        script = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('project="openclaw-video"', script)
        self.assertIn('compose_file="docker-compose.openclaw-video.yaml"', script)
        self.assertIn('docker compose --env-file "$env_file" -p "$project" -f "$compose_file" build', script)
        self.assertIn("OPENCLAW_BUILD_TIMEOUT_SECONDS:-900", script)
        self.assertIn("registry.npmmirror.com", script)
        self.assertIn("pypi.tuna.tsinghua.edu.cn", script)
        self.assertIn("mirrors.tuna.tsinghua.edu.cn/debian", script)
        self.assertIn("sed -E", script)
        self.assertIn("ARK_API_KEY", script)
        self.assertNotIn("docker compose down", script)
        self.assertNotIn("docker restart", script)
        self.assertNotIn("openresty -s reload", script)


if __name__ == "__main__":
    unittest.main()
