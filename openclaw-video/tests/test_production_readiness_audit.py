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


LINK_READ_DECISION_PASS = """
link_read_mode: ADOPTED
REAL_SAMPLE_EVIDENCE.json: NOT_REQUIRED
douyin_account_login: NOT_REQUIRED
browser_storage_state: NOT_REQUIRED
runtime_path: url_guard -> worker_service -> douyin_legacy_adapter -> UniversalVideoResolver
allowlisted_douyin_hosts: PASS
redirect_revalidation: PASS
private_ip_blocking: PASS
no_browser_login_state: PASS
"""


def write_link_read_runtime(repo: Path) -> None:
    source_root = Path(__file__).resolve().parents[2] / "openclaw-video" / "src" / "openclaw_video"
    for name in ("url_guard.py", "worker_service.py", "douyin_legacy_adapter.py"):
        write(
            repo / "openclaw-video" / "src" / "openclaw_video" / name,
            (source_root / name).read_text(encoding="utf-8"),
        )


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


OPENCLAW_PRODUCTIZED_UI_PASS = """
{
  "schema": "openclaw-ui-productized-root-acceptance.v1",
  "target_url": "https://www.huahuoai.com/ai/openclaw-lab/",
  "assertions": {
    "login_authenticated": true,
    "session_created": true,
    "post_login_acceptance_all_pass": true
  },
  "login": {
    "authenticated": true,
    "passwordCleared": true,
    "accountRecorded": false
  },
  "session": {
    "created": true,
    "idLength": 36
  },
  "post_login_acceptance": {
    "overall": "PASS",
    "checkCount": 16,
    "allPass": true
  }
}
"""

OPENCLAW_PRODUCTIZED_ROUTE_PASS = """
{
  "schema": "openclaw-productized-ui-root-deployment-evidence.v1",
  "root_runtime": {
    "public_routes": {
      "dify_root": 200,
      "openclaw_lab": 200,
      "openclaw_api_me_unauth": 401,
      "bridge_healthz": 200
    }
  },
  "policy": {
    "dify_core_restarted": false,
    "dify_core_rebuilt": false
  }
}
"""

REAL_VIDEO_ANALYSIS_PASS = """
{
  "schema_version": "openclaw-real-video-analysis-root-evidence.v1",
  "status": "PASS",
  "scope": {
    "page_url": "https://www.huahuoai.com/ai/openclaw-lab/",
    "dify_web_login_required": false,
    "douyin_account_login_required": false,
    "real_model_analysis_invoked": true
  },
  "runtime_secret_status": {
    "secret_values_recorded": false,
    "keys_present_in_worker_container": {
      "ARK_API_KEY": true,
      "MEDIAKIT_API_KEY": true,
      "ARK_BASE_URL": true,
      "MODEL": true,
      "ARK_MODEL": true,
      "MEDIAKIT_BASE_URL": true
    }
  },
  "root_release": {
    "current_release": "/app/bin/openclaw-video/releases/c9aaaa8c6655",
    "worker_status": "running",
    "bridge_status": "running"
  },
  "input": {
    "input_url_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "raw_input_url_recorded": false,
    "direct_video_url_recorded": false
  },
  "openclaw_page_flow": {
    "session_created": true,
    "read_check_http_status": 200,
    "read_check_status": "PASS",
    "read_check_model_invoked": false,
    "submit_job_http_status": 202
  },
  "job": {
    "status": "succeeded",
    "attempt_count": 1,
    "error_code": null,
    "created_at_present": true,
    "started_at_present": true,
    "finished_at_present": true,
    "result_schema_version": "openclaw-video-result.v1",
    "result_location_present": true
  },
  "result_meta": {
    "schema_version": "openclaw-video-result.v1",
    "platform": "douyin",
    "duration_seconds_present": true,
    "summary_chars": 220,
    "signals_keys": ["audience", "hook", "risk_notes", "structure", "topic", "visual_notes"],
    "raw_tool_result_keys": ["request_id", "usage"],
    "request_id_present": true,
    "usage_present": true,
    "model_output_recorded": false,
    "result_json_bytes": 2381,
    "result_json_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "public_routes": {
    "dify_root": 200,
    "openclaw_lab": 200,
    "openclaw_api_me_unauth": 401,
    "bridge_healthz": 200
  },
  "dify_core_container_invariant": {
    "api": {
      "container_id": "1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631",
      "started_at": "2026-01-05T11:17:20.555976179Z",
      "status": "running"
    },
    "web": {
      "container_id": "62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36",
      "started_at": "2026-01-05T11:17:19.85303869Z",
      "status": "running"
    },
    "nginx": {
      "container_id": "8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe",
      "started_at": "2026-01-05T11:17:20.937420886Z",
      "status": "running"
    }
  },
  "sanitization": {
    "raw_url_recorded": false,
    "account_recorded": false,
    "password_recorded": false,
    "cookies_recorded": false,
    "headers_recorded": false,
    "tokens_recorded": false,
    "secret_file_contents_recorded": false,
    "model_key_recorded": false,
    "model_output_recorded": false,
    "database_url_recorded": false
  }
}
"""


LEGACY_BROWSER_LOGIN_BASELINE_PASS = """
{
  "schema": "legacy-browser-login-baseline.v1",
  "status": "PASS",
  "authenticated_baseline": true,
  "existing_app_message": true,
  "streaming_reply": true,
  "refresh": true,
  "history": true,
  "logout": true,
  "profile_401": true,
  "new_5xx_none": true,
  "cookies_recorded": false,
  "headers_recorded": false,
  "local_storage_values_recorded": false,
  "session_storage_values_recorded": false,
  "tokens_recorded": false,
  "passwords_recorded": false
}
"""


class ProductionReadinessAuditTests(unittest.TestCase):
    def test_current_repo_is_go(self):
        report = audit_module.audit(Path(__file__).resolve().parents[2])
        self.assertEqual(report["overall"], "GO")
        statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(statuses["openclaw_security"], "PASS")
        self.assertEqual(statuses["douyin_artifact"], "PASS")
        self.assertEqual(statuses["video_link_read_mode"], "PASS")
        self.assertEqual(statuses["real_video_analysis_root_evidence"], "PASS")
        self.assertEqual(statuses["openclaw_owned_login"], "PASS")

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
            write(repo / "artifacts/douyin_chong/LINK_READ_DECISION.md", LINK_READ_DECISION_PASS)
            write_link_read_runtime(repo)
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json",
                OPENCLAW_PRODUCTIZED_UI_PASS,
            )
            write(
                repo / "artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json",
                OPENCLAW_PRODUCTIZED_ROUTE_PASS,
            )
            write(
                repo / "artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json",
                REAL_VIDEO_ANALYSIS_PASS,
            )

            report = audit_module.audit(repo)

        self.assertEqual(report["overall"], "GO")
        self.assertTrue(all(gate["status"] == "PASS" for gate in report["gates"]))

    def test_verified_manifest_alone_does_not_pass_without_link_read_decision(self):
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
                repo / "artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json",
                OPENCLAW_PRODUCTIZED_UI_PASS,
            )
            write(
                repo / "artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json",
                OPENCLAW_PRODUCTIZED_ROUTE_PASS,
            )

            report = audit_module.audit(repo)

        statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(report["overall"], "NO_GO")
        self.assertEqual(statuses["douyin_artifact"], "PASS")
        self.assertEqual(statuses["video_link_read_mode"], "NO_GO")

    def test_video_link_read_mode_rejects_missing_decision(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)

            result = audit_module.check_video_link_read_mode(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("LINK_READ_DECISION", result.evidence)

    def test_video_link_read_mode_can_pass_without_real_sample_evidence(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "artifacts/douyin_chong/LINK_READ_DECISION.md", LINK_READ_DECISION_PASS)
            write_link_read_runtime(repo)

            result = audit_module.check_video_link_read_mode(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("link-read mode", result.evidence)

    def test_real_video_analysis_evidence_requires_current_release(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json",
                REAL_VIDEO_ANALYSIS_PASS.replace(
                    "/app/bin/openclaw-video/releases/c9aaaa8c6655",
                    "/app/bin/openclaw-video/releases/f1ba8273e7b6",
                ),
            )

            result = audit_module.check_real_video_analysis_root_evidence(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("current-release", result.evidence)

    def test_real_video_analysis_evidence_passes_current_release(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json",
                REAL_VIDEO_ANALYSIS_PASS,
            )

            result = audit_module.check_real_video_analysis_root_evidence(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("model-backed", result.evidence)

    def test_legacy_console_attempt_no_longer_satisfies_login_gate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "legacy-public-baseline.md", "authenticated_baseline: BLOCKED\n")
            write(
                repo / "artifacts/evidence/phase4/legacy-console-baseline-attempt-20260607.json",
                """
{
  "schema": "legacy-console-baseline-attempt.v1",
  "status": "blocked",
  "reason": "The current Chrome profile is not authenticated.",
  "final_url": "https://example.invalid/signin"
}
""",
            )

            result = audit_module.check_openclaw_owned_login(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("productized UI acceptance", result.evidence)
        self.assertIn("legacy console", result.evidence)

    def test_openclaw_standalone_login_evidence_no_longer_passes(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-standalone-login-browser-acceptance-20260607.json",
                """
{
  "schema": "openclaw-standalone-login-browser-acceptance.v1",
  "status": "PASS",
  "page_url": "https://www.huahuoai.com/ai/openclaw-lab/",
  "login_status": 200,
  "login_authenticated": true,
  "post_login_acceptance": {
    "overall": "PASS",
    "step_count": 16,
    "failed_steps": []
  },
  "account_recorded": false,
  "password_recorded": false,
  "secrets_recorded": false,
  "headers_recorded": false,
  "cookies_recorded": false
}
""",
            )

            result = audit_module.check_openclaw_owned_login(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("pre-productized evidence no longer satisfy", result.evidence)

    def test_openclaw_productized_ui_evidence_can_pass_login_gate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json",
                OPENCLAW_PRODUCTIZED_UI_PASS,
            )

            result = audit_module.check_openclaw_owned_login(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("productized UI", result.evidence)

    def test_openclaw_productized_ui_evidence_rejects_sensitive_recording(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = OPENCLAW_PRODUCTIZED_UI_PASS.replace('"accountRecorded": false', '"accountRecorded": true')
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json",
                payload,
            )

            result = audit_module.check_openclaw_owned_login(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("productized UI evidence did not pass", result.evidence)

    def test_legacy_browser_evidence_no_longer_passes_gate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/legacy-browser-login-baseline-20260607.json",
                LEGACY_BROWSER_LOGIN_BASELINE_PASS,
            )

            result = audit_module.check_openclaw_owned_login(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("legacy console", result.evidence)

    def test_productized_route_evidence_allows_current_openclaw_route(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json",
                OPENCLAW_PRODUCTIZED_ROUTE_PASS,
            )

            result = audit_module.check_production_route_absent(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("public route is present through Bridge", result.evidence)

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


if __name__ == "__main__":
    unittest.main()
