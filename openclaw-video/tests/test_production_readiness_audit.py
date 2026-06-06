import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_production_readiness.py"
spec = importlib.util.spec_from_file_location("audit_production_readiness", SCRIPT_PATH)
audit_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = audit_module
spec.loader.exec_module(audit_module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ProductionReadinessAuditTests(unittest.TestCase):
    def test_current_repo_is_no_go(self):
        report = audit_module.audit(Path(__file__).resolve().parents[2])
        self.assertEqual(report["overall"], "NO_GO")
        statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(statuses["openclaw_security"], "NO_GO")
        self.assertEqual(statuses["douyin_artifact"], "NO_GO")

    def test_all_markers_present_is_go(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/openclaw-2026.3.13/SECURITY_DECISION.md",
                """
decision: approve_exception
security_owner: alice
engineering_owner: bob
""",
            )
            write(repo / "artifacts/douyin_chong/ARTIFACT_MANIFEST.md", "Status: verified\n")
            write(
                repo / "phase1.5-exit-proof.md",
                """
status: PASS
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1
RUN_COMPOSE_UP=1
docker compose build --no-cache
docker compose up -d
127.0.0.1:18181
""",
            )
            write(
                repo / "dify-public-baseline.md",
                """
authenticated_baseline: PASS
existing app message: PASS
history: PASS
""",
            )
            write(repo / "openresty-route-map-redacted.md", "no OpenClaw route present\n")

            report = audit_module.audit(repo)

        self.assertEqual(report["overall"], "GO")
        self.assertTrue(all(gate["status"] == "PASS" for gate in report["gates"]))


if __name__ == "__main__":
    unittest.main()
