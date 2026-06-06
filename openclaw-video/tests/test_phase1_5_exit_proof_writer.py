import importlib.util
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_PATH = REPO_ROOT / "scripts" / "write_phase1_5_exit_proof.py"
AUDIT_PATH = REPO_ROOT / "scripts" / "audit_production_readiness.py"

writer_spec = importlib.util.spec_from_file_location("write_phase1_5_exit_proof", WRITER_PATH)
writer = importlib.util.module_from_spec(writer_spec)
assert writer_spec.loader is not None
sys.modules[writer_spec.name] = writer
writer_spec.loader.exec_module(writer)

audit_spec = importlib.util.spec_from_file_location("audit_production_readiness_for_exit_writer", AUDIT_PATH)
audit = importlib.util.module_from_spec(audit_spec)
assert audit_spec.loader is not None
sys.modules[audit_spec.name] = audit
audit_spec.loader.exec_module(audit)


class Phase15ExitProofWriterTests(unittest.TestCase):
    def context(self):
        return writer.ProofContext(
            host_name="isolated-linux-test",
            host_date="2026-06-06T12:34:56+08:00",
            host_os="Linux",
            docker_version="Docker server=29.4.0",
            docker_compose_version="Docker Compose version v5.1.3",
            git_commit="a" * 40,
            git_tags="phase1-5-test-tag",
            operator="codex",
            reviewer="separate-production-go-no-go-review-required",
            compose_file="openclaw-video/docker-compose.openclaw-video.yaml",
            python_cmd="/opt/venv/bin/python",
            node_cmd="node",
            worker_image="sha256:" + "b" * 64,
        )

    def test_generated_proof_satisfies_production_audit_exit_gate(self):
        proof = writer.build_proof(self.context())

        writer.validate_proof_text(proof)
        self.assertNotRegex(proof, writer.PLACEHOLDER_PATTERN)

        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "phase1.5-exit-proof.md").write_text(proof, encoding="utf-8")

            result = audit.check_phase1_5_exit(repo)

        self.assertEqual(result.status, "PASS")

    def test_rejects_non_linux_context(self):
        context = self.context()
        bad_context = writer.ProofContext(**{**context.__dict__, "host_os": "Darwin"})

        with self.assertRaisesRegex(ValueError, "host_os must be Linux"):
            writer.build_proof(bad_context)

    def test_validate_rejects_template_placeholder(self):
        proof = writer.build_proof(self.context()) + "\nreviewer: <fill-me>\n"

        with self.assertRaisesRegex(ValueError, "template placeholder"):
            writer.validate_proof_text(proof)

    def test_generated_proof_records_cleanup_before_pass(self):
        proof = writer.build_proof(self.context())

        self.assertIn("docker compose down --remove-orphans: PASS", proof)
        self.assertIn("port exposure check: PASS, no 0.0.0.0 listener", proof)
        self.assertIn("Bridge healthz at http://127.0.0.1:18181/healthz: PASS", proof)


if __name__ == "__main__":
    unittest.main()
