import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_ubuntu22_phase.py"
spec = importlib.util.spec_from_file_location("audit_ubuntu22_phase", SCRIPT_PATH)
audit_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = audit_module
spec.loader.exec_module(audit_module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


UBUNTU_BASELINE_PASS = """
# Ubuntu 22.04 Dify Browser Baseline
Target host: `ubuntu22.04`
Base URL: `http://192.168.206.130:8088`
Authenticated Dify app conversation baseline: PASS
test account: openclaw-baseline+ubuntu22@local.test
credential file mode: 600
TEMP_SECRET_RESIDUE_CLEARED
app name: OpenClaw Baseline Fixed Reply
mode: advanced-chat
model dependency: none
published: PASS
GET /apps after login:
workspace visible: OpenClaw Ubuntu22 Baseline
app visible: OpenClaw Baseline Fixed Reply
Message flow:
expected reply: OpenClaw baseline reply ping baseline 0606
reply visible: PASS
Refresh:
prior answer visible after refresh: PASS
Return to /apps:
app entry visible: PASS
Logout:
after logout /apps finalUrl: http://192.168.206.130:8088/signin
signin page visible: PASS
new 5xx: NONE
OpenClaw sidecar containers: none remaining
Test listeners on 18181/18789/5432: none remaining
The production/root public baseline still requires its own authenticated run.
"""


class Ubuntu22PhaseAuditTests(unittest.TestCase):
    def test_current_repo_ubuntu22_phase_is_pass(self):
        report = audit_module.audit(Path(__file__).resolve().parents[2])

        self.assertEqual(report["overall"], "PASS")
        self.assertTrue(all(check["status"] == "PASS" for check in report["checks"]))

    def test_rejects_missing_authenticated_baseline_markers(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "ubuntu22-dify-browser-baseline-20260606.md", "Target host: `ubuntu22.04`\n")

            result = audit_module.check_ubuntu22_dify_baseline(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("missing markers", result.evidence)

    def test_rejects_sensitive_baseline_recording(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "ubuntu22-dify-browser-baseline-20260606.md",
                UBUNTU_BASELINE_PASS + "\nAuthorization header recorded\n",
            )

            result = audit_module.check_ubuntu22_dify_baseline(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("sensitive", result.evidence)

    def test_douyin_phase_deferral_requires_explicit_manifest(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "artifacts/douyin_chong/ARTIFACT_MANIFEST.md", "Status: verified\n")

            result = audit_module.check_douyin_current_phase(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("deferral", result.evidence)

    def test_douyin_phase_accepts_documented_current_phase_deferral(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/douyin_chong/ARTIFACT_MANIFEST.md",
                """
The operator has explicitly deferred `REAL_SAMPLE_EVIDENCE.json` for the
current Ubuntu 22.04 validation phase. The deployment gates still keep this
deferral explicit through `ALLOW_DOUYIN_SAMPLE_DEFERRED=1`; final production
can require the sanitized real sample evidence again by omitting that flag.
""",
            )

            result = audit_module.check_douyin_current_phase(repo)

        self.assertEqual(result.status, "PASS")


if __name__ == "__main__":
    unittest.main()
