from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "run_phase1_5_acceptance.sh"


class Phase15AcceptanceRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNNER.read_text(encoding="utf-8")

    def test_rejects_production_host_markers(self):
        self.assertIn('host_name" == "AI-01"', self.text)
        self.assertIn('target_label" == "root"', self.text)
        self.assertIn("/app/bin/dify/dify-1.11.2/docker/docker-compose.yaml", self.text)

    def test_supports_archive_build_info_anchor(self):
        self.assertIn("print_version_anchor", self.text)
        self.assertIn("BUILD_INFO", self.text)
        self.assertIn("git_commit=", self.text)
        self.assertIn("git_tags=", self.text)
        self.assertIn("rebuild the archive with git archive", self.text)

    def test_requires_non_production_secret_files_without_printing_contents(self):
        for path in [
            "openclaw-video/secrets/openclaw_gateway_token",
            "openclaw-video/secrets/openclaw_bridge_device_key.pem",
            "openclaw-video/secrets/douyin_chong.env",
        ]:
            self.assertIn(path, self.text)
        self.assertNotIn("cat openclaw-video/secrets", self.text)
        self.assertNotIn("cat $path", self.text)

    def test_runs_readiness_before_full_gate(self):
        readiness_index = self.text.index("scripts/check_phase1_5_host_readiness.py")
        full_gate_index = self.text.index("scripts/verify_phase1_5_gates.sh")

        self.assertLess(readiness_index, full_gate_index)
        self.assertIn("--fail-on-no-go", self.text)

    def test_full_gate_requires_hard_gates_and_compose_up(self):
        self.assertIn("REQUIRE_OPENCLAW_SECURITY_APPROVAL=1", self.text)
        self.assertIn("REQUIRE_DOUYIN_ARTIFACT=1", self.text)
        self.assertIn("RUN_COMPOSE_UP=1", self.text)
        self.assertIn("DOCKER_CMD=\"$docker_cmd\"", self.text)

    def test_secret_skip_cannot_produce_exit_proof(self):
        self.assertIn("REQUIRE_SECRETS=0 cannot continue to full Phase 1.5 acceptance", self.text)
        self.assertIn("This cannot produce Phase 1.5 exit proof", self.text)


if __name__ == "__main__":
    unittest.main()
