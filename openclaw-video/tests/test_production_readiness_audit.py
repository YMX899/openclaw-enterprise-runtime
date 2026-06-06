import importlib.util
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "audit_production_readiness.py"
spec = importlib.util.spec_from_file_location("audit_production_readiness", SCRIPT_PATH)
audit_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = audit_module
spec.loader.exec_module(audit_module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SECURITY_TRIAGE_PASS = """
status: reviewed
openclaw_version: 2026.3.13
production_decision: approve_exception
npm_audit_command: npm audit --omit=dev --json
npm_audit_total: 7
npm_audit_critical: 1
npm_audit_high: 4
runtime_scope: private OpenClaw Gateway behind Bridge only
browser_exposure: Gateway token never sent to browser
bridge_scopes: operator.read, operator.write
operator_admin: forbidden
approved_by_security_owner: alice
approved_by_engineering_owner: bob
approval_date: 2026-06-06

package: openclaw
severity: critical
reachable: no
mitigation: private gateway plus vendor analysis
decision: approve_exception

package: @buape/carbon
severity: high
reachable: no
mitigation: not used by Bridge path
decision: approve_exception

package: @hono/node-server
severity: high
reachable: no
mitigation: gateway not browser exposed
decision: approve_exception

package: @larksuiteoapi/node-sdk
severity: high
reachable: no
mitigation: larksuite integration disabled
decision: approve_exception

package: axios
severity: high
reachable: no
mitigation: larksuite integration disabled
decision: approve_exception

package: hono
severity: moderate
reachable: no
mitigation: private gateway only
decision: approve_exception

package: ws
severity: moderate
reachable: no
mitigation: Bridge-only authenticated channel
decision: approve_exception
"""


class ProductionReadinessAuditTests(unittest.TestCase):
    def test_current_repo_is_no_go(self):
        report = audit_module.audit(Path(__file__).resolve().parents[2])
        self.assertEqual(report["overall"], "NO_GO")
        statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(statuses["openclaw_security"], "PASS")
        self.assertEqual(statuses["douyin_artifact"], "PASS")
        self.assertEqual(statuses["douyin_real_sample"], "NO_GO")
        self.assertEqual(statuses["phase1_5_exit_proof"], "PASS")
        self.assertEqual(statuses["authenticated_dify_baseline"], "NO_GO")

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
            write(repo / "artifacts/openclaw-2026.3.13/SECURITY_TRIAGE.md", SECURITY_TRIAGE_PASS)
            write(repo / "artifacts/douyin_chong/ARTIFACT_MANIFEST.md", "Status: verified\n")
            write(
                repo / "artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json",
                """
{
  "schema_version": "douyin-real-sample-evidence.v1",
  "status": "succeeded",
  "input_url_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "input_url_host": "www.douyin.com",
  "env_file_present": true,
  "secret_file_contents_recorded": false,
  "process": {
    "returncode": 0,
    "elapsed_seconds": 12.3,
    "stdout_recorded": false,
    "stderr_recorded": false
  },
  "result": {
    "schema_version": "openclaw-video-result.v1",
    "platform": "douyin",
    "result_json_bytes": 1234,
    "result_json_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
""",
            )
            write(
                repo / "phase1.5-exit-proof.md",
                """
status: PASS
source: isolated-linux-docker-host
production_host: NO
host_os: Linux
SKIP_DOCKER=0
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1
REQUIRE_DOUYIN_ARTIFACT=1
RUN_COMPOSE_UP=1
scripts/verify_phase1_5_gates.sh
docker version
docker compose version
docker compose config
docker compose build --no-cache
docker compose up -d
healthz
port exposure check
127.0.0.1:18181
docker compose down --remove-orphans --volumes
no 0.0.0.0 listener
worker image
""",
            )
            write(
                repo / "dify-public-baseline.md",
                """
authenticated_baseline: PASS
existing app message: PASS
streaming reply: PASS
refresh: PASS
history: PASS
logout: PASS
profile 401: PASS
new 5xx: NONE
""",
            )
            write(repo / "openresty-route-map-redacted.md", "no OpenClaw route present\n")

            report = audit_module.audit(repo)

        self.assertEqual(report["overall"], "GO")
        self.assertTrue(all(gate["status"] == "PASS" for gate in report["gates"]))

    def test_verified_manifest_alone_does_not_pass_without_sample_evidence(self):
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
            write(repo / "artifacts/openclaw-2026.3.13/SECURITY_TRIAGE.md", SECURITY_TRIAGE_PASS)
            write(repo / "artifacts/douyin_chong/ARTIFACT_MANIFEST.md", "Status: verified\n")
            write(
                repo / "phase1.5-exit-proof.md",
                """
status: PASS
source: isolated-linux-docker-host
production_host: NO
host_os: Linux
SKIP_DOCKER=0
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1
REQUIRE_DOUYIN_ARTIFACT=1
RUN_COMPOSE_UP=1
scripts/verify_phase1_5_gates.sh
docker version
docker compose version
docker compose config
docker compose build --no-cache
docker compose up -d
healthz
port exposure check
127.0.0.1:18181
docker compose down --remove-orphans --volumes
no 0.0.0.0 listener
worker image
""",
            )
            write(
                repo / "dify-public-baseline.md",
                """
authenticated_baseline: PASS
existing app message: PASS
streaming reply: PASS
refresh: PASS
history: PASS
logout: PASS
profile 401: PASS
new 5xx: NONE
""",
            )
            write(repo / "openresty-route-map-redacted.md", "no OpenClaw route present\n")

            report = audit_module.audit(repo)

        statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(report["overall"], "NO_GO")
        self.assertEqual(statuses["douyin_artifact"], "PASS")
        self.assertEqual(statuses["douyin_real_sample"], "NO_GO")

    def test_real_sample_can_be_explicitly_deferred_for_current_phase(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with mock.patch.dict(os.environ, {"ALLOW_DOUYIN_SAMPLE_DEFERRED": "1"}):
                result = audit_module.check_douyin_real_sample(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("deferred", result.evidence)

    def test_openclaw_security_requires_triage_when_decision_approved(self):
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

            result = audit_module.check_openclaw_security(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("SECURITY_TRIAGE.md", result.evidence)

    def test_openclaw_security_rejects_triage_placeholders(self):
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
            write(
                repo / "artifacts/openclaw-2026.3.13/SECURITY_TRIAGE.md",
                SECURITY_TRIAGE_PASS + "\nreviewer: <fill-me>\n",
            )

            result = audit_module.check_openclaw_security(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("template placeholders", result.evidence)

    def test_openclaw_security_rejects_reachable_critical(self):
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
            write(
                repo / "artifacts/openclaw-2026.3.13/SECURITY_TRIAGE.md",
                SECURITY_TRIAGE_PASS.replace("reachable: no", "reachable: unknown", 1),
            )

            result = audit_module.check_openclaw_security(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("critical", result.evidence)

    def test_real_sample_evidence_rejects_raw_url_leak(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json",
                """
{
  "schema_version": "douyin-real-sample-evidence.v1",
  "status": "succeeded",
  "input_url_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "raw_url": "https://www.douyin.com/video/123",
  "env_file_present": true,
  "secret_file_contents_recorded": false,
  "process": {
    "returncode": 0,
    "elapsed_seconds": 12.3,
    "stdout_recorded": false,
    "stderr_recorded": false
  },
  "result": {
    "schema_version": "openclaw-video-result.v1",
    "platform": "douyin",
    "result_json_bytes": 1234,
    "result_json_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
""",
            )

            result = audit_module.check_douyin_real_sample(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("raw URL", result.evidence)

    def test_phase1_5_exit_rejects_template_placeholders(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "phase1.5-exit-proof.md",
                """
status: PASS
source: isolated-linux-docker-host
production_host: NO
host_os: Linux
SKIP_DOCKER=0
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1
REQUIRE_DOUYIN_ARTIFACT=1
RUN_COMPOSE_UP=1
scripts/verify_phase1_5_gates.sh
docker version
docker compose version
docker compose config
docker compose build --no-cache
docker compose up -d
healthz
port exposure check
127.0.0.1:18181
docker compose down --remove-orphans --volumes
no 0.0.0.0 listener
worker image
operator: <fill-me>
""",
            )

            result = audit_module.check_phase1_5_exit(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("template placeholders", result.evidence)

    def test_real_sample_evidence_rejects_http_raw_url_leak(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json",
                """
{
  "schema_version": "douyin-real-sample-evidence.v1",
  "status": "succeeded",
  "input_url_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "raw_url": "http://www.douyin.com/video/123",
  "env_file_present": true,
  "secret_file_contents_recorded": false,
  "process": {
    "returncode": 0,
    "elapsed_seconds": 12.3,
    "stdout_recorded": false,
    "stderr_recorded": false
  },
  "result": {
    "schema_version": "openclaw-video-result.v1",
    "platform": "douyin",
    "result_json_bytes": 1234,
    "result_json_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
""",
            )

            result = audit_module.check_douyin_real_sample(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("raw URL", result.evidence)


if __name__ == "__main__":
    unittest.main()
