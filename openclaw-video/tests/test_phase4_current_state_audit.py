import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_phase4_current_state.py"
spec = importlib.util.spec_from_file_location("audit_phase4_current_state", SCRIPT_PATH)
phase4_audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = phase4_audit
spec.loader.exec_module(phase4_audit)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SMOKE_PASS = {
    "schema": "openclaw-public-browser-smoke.v1",
    "status": "PASS",
    "targets": [
        {
            "name": "openclaw-standalone-lab",
            "http_5xx_count": 0,
            "gateway_direct_request_count": 0,
            "token_url_leak_count": 0,
        },
        {"name": "openclaw-lab", "http_5xx_count": 0, "gateway_direct_request_count": 0, "token_url_leak_count": 0},
        {
            "name": "openclaw-api-me-unauthenticated",
            "http_5xx_count": 0,
            "gateway_direct_request_count": 0,
            "token_url_leak_count": 0,
        },
        {"name": "huahuo-user-web", "http_5xx_count": 0, "gateway_direct_request_count": 0, "token_url_leak_count": 0},
        {
            "name": "huahuo-admin-configuration",
            "http_5xx_count": 0,
            "gateway_direct_request_count": 0,
            "token_url_leak_count": 0,
        },
    ],
    "secrets_recorded": False,
    "headers_recorded": False,
    "bodies_recorded": False,
}


DIFY_CORE_PASS = {
    "api": {
        "id": "1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631",
        "started_at": "2026-01-05T11:17:20.555976179Z",
        "status": "running",
    },
    "web": {
        "id": "62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36",
        "started_at": "2026-01-05T11:17:19.85303869Z",
        "status": "running",
    },
    "nginx": {
        "id": "8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe",
        "started_at": "2026-01-05T11:17:20.937420886Z",
        "status": "running",
    },
}

PRODUCTIZED_UI_ROOT_PASS = {
    "schema": "openclaw-productized-ui-root-deployment-evidence.v1",
    "deployed_commit": "c9aaaa8c6655",
    "deployed_release": "/app/bin/openclaw-video/releases/c9aaaa8c6655",
    "previous_release": "/app/bin/openclaw-video/releases/94fdd79b29a0",
    "root_runtime": {
        "current_release": "/app/bin/openclaw-video/releases/c9aaaa8c6655",
        "previous_release": "/app/bin/openclaw-video/releases/94fdd79b29a0",
        "dify_core": DIFY_CORE_PASS,
        "public_routes": {
            "dify_root": 200,
            "openclaw_lab": 200,
            "openclaw_api_me_unauth": 401,
            "bridge_healthz": 200,
        },
    },
    "ui_acceptance": {
        "schema": "openclaw-ui-productized-root-acceptance.v1",
        "assertions": {
            "page_loaded": True,
            "workflow_present": True,
            "source_tabs_present": True,
            "result_cards_present": True,
            "diagnostics_available": True,
            "raw_json_secondary": True,
            "desktop_no_horizontal_overflow": True,
            "mobile_no_horizontal_overflow": True,
            "required_ids_present": True,
            "login_authenticated": True,
            "session_created": True,
            "post_login_acceptance_all_pass": True,
        },
        "login": {
            "authenticated": True,
            "passwordCleared": True,
            "accountRecorded": False,
        },
        "session": {
            "created": True,
            "idLength": 36,
        },
        "post_login_acceptance": {
            "overall": "PASS",
            "checkCount": 16,
            "allPass": True,
        },
    },
    "policy": {
        "local_test_loop_used": False,
        "authoritative_environment": "root",
        "ui_debug_completed_before_root_testing": True,
        "dify_core_restarted": False,
        "dify_core_rebuilt": False,
        "secrets_recorded": False,
        "account_recorded": False,
        "password_recorded": False,
        "cookies_recorded": False,
        "headers_recorded": False,
    },
}

REAL_VIDEO_ANALYSIS_PASS = {
    "schema_version": "openclaw-real-video-analysis-root-evidence.v1",
    "status": "PASS",
    "scope": {
        "page_url": "https://www.huahuoai.com/ai/openclaw-lab/",
        "dify_web_login_required": False,
        "douyin_account_login_required": False,
        "real_model_analysis_invoked": True,
    },
    "runtime_secret_status": {
        "secret_values_recorded": False,
        "keys_present_in_worker_container": {
            "ARK_API_KEY": True,
            "MEDIAKIT_API_KEY": True,
            "ARK_BASE_URL": True,
            "MODEL": True,
            "ARK_MODEL": True,
            "MEDIAKIT_BASE_URL": True,
        },
    },
    "root_release": {
        "current_release": "/app/bin/openclaw-video/releases/c9aaaa8c6655",
        "worker_status": "running",
        "bridge_status": "running",
    },
    "input": {
        "input_url_sha256": "a" * 64,
        "raw_input_url_recorded": False,
        "direct_video_url_recorded": False,
    },
    "openclaw_page_flow": {
        "session_created": True,
        "read_check_http_status": 200,
        "read_check_status": "PASS",
        "read_check_model_invoked": False,
        "submit_job_http_status": 202,
    },
    "job": {
        "status": "succeeded",
        "attempt_count": 1,
        "error_code": None,
        "created_at_present": True,
        "started_at_present": True,
        "finished_at_present": True,
        "result_schema_version": "openclaw-video-result.v1",
        "result_location_present": True,
    },
    "result_meta": {
        "schema_version": "openclaw-video-result.v1",
        "platform": "douyin",
        "duration_seconds_present": True,
        "summary_chars": 220,
        "signals_keys": ["audience", "hook", "risk_notes", "structure", "topic", "visual_notes"],
        "raw_tool_result_keys": ["request_id", "usage"],
        "request_id_present": True,
        "usage_present": True,
        "model_output_recorded": False,
        "result_json_bytes": 2381,
        "result_json_sha256": "b" * 64,
    },
    "public_routes": {
        "dify_root": 200,
        "openclaw_lab": 200,
        "openclaw_api_me_unauth": 401,
        "bridge_healthz": 200,
    },
    "dify_core_container_invariant": {
        "api": {
            "container_id": "1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631",
            "started_at": "2026-01-05T11:17:20.555976179Z",
            "status": "running",
        },
        "web": {
            "container_id": "62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36",
            "started_at": "2026-01-05T11:17:19.85303869Z",
            "status": "running",
        },
        "nginx": {
            "container_id": "8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe",
            "started_at": "2026-01-05T11:17:20.937420886Z",
            "status": "running",
        },
    },
    "sanitization": {
        "raw_url_recorded": False,
        "account_recorded": False,
        "password_recorded": False,
        "cookies_recorded": False,
        "headers_recorded": False,
        "tokens_recorded": False,
        "secret_file_contents_recorded": False,
        "model_key_recorded": False,
        "model_output_recorded": False,
        "database_url_recorded": False,
    },
}

RUNNER = """
export async function runHuahuoPostLoginAcceptance(browser, options = {}) {
  await browser.tabs.new();
}
export async function runOpenClawProductizedLoginAcceptance(browser, options = {}) {
  await browser.tabs.new();
}
openclaw-ui-productized-root-acceptance.v1
Post-Login Acceptance
PENDING_CREDENTIALS
secrets_recorded: false
headers_recorded: false
local_storage_values_recorded: false
account_recorded: false
password_recorded: false
"""


class Phase4CurrentStateAuditTests(unittest.TestCase):
    def test_current_repo_reports_current_gates_pass(self):
        smoke = REPO_ROOT / "tmp" / "playwright-public-browser" / "20260607T061801Z" / "summary.json"
        report = phase4_audit.audit(REPO_ROOT, smoke_summary=smoke, include_git_clean=True)
        statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}

        self.assertEqual(statuses["phase4_deployment_evidence"], "PASS")
        self.assertEqual(statuses["current_root_chrome_evidence"], "PASS")
        self.assertEqual(statuses["chrome_post_login_runner"], "PASS")
        self.assertEqual(statuses["public_smoke_latest"], "PASS")
        self.assertEqual(statuses["authenticated_browser_gate"], "PASS")
        self.assertEqual(statuses["video_link_read_mode"], "PASS")
        self.assertIn(statuses["git_clean"], {"PASS", "NO_GO"})
        self.assertEqual(report["overall"], "PASS" if statuses["git_clean"] == "PASS" else "NO_GO")

    def test_all_phase4_current_state_markers_can_pass(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "scripts/huahuo_post_login_acceptance_runner.mjs", RUNNER)
            write(
                repo / "artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json",
                json.dumps(PRODUCTIZED_UI_ROOT_PASS),
            )
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json",
                json.dumps(PRODUCTIZED_UI_ROOT_PASS["ui_acceptance"]),
            )
            write(
                repo / "artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json",
                json.dumps(REAL_VIDEO_ANALYSIS_PASS),
            )
            write(
                repo / "artifacts/douyin_chong/LINK_READ_DECISION.md",
                """
link_read_mode: ADOPTED
REAL_SAMPLE_EVIDENCE.json: NOT_REQUIRED
douyin_account_login: NOT_REQUIRED
browser_storage_state: NOT_REQUIRED
runtime_path: url_guard -> worker_service -> douyin_legacy_adapter -> UniversalVideoResolver
allowlisted_douyin_hosts: PASS
redirect_revalidation: PASS
private_ip_blocking: PASS
no_browser_login_state: PASS
""",
            )
            source_root = REPO_ROOT / "openclaw-video" / "src" / "openclaw_video"
            for name in ("url_guard.py", "worker_service.py", "douyin_legacy_adapter.py"):
                write(repo / "openclaw-video/src/openclaw_video" / name, (source_root / name).read_text(encoding="utf-8"))
            smoke = repo / "summary.json"
            smoke.write_text(json.dumps(SMOKE_PASS), encoding="utf-8")

            report = phase4_audit.audit(repo, smoke_summary=smoke)

        self.assertEqual(report["overall"], "PASS")
        self.assertTrue(all(gate["status"] == "PASS" for gate in report["gates"]))

    def test_productized_login_evidence_passes_authenticated_gate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json",
                json.dumps(PRODUCTIZED_UI_ROOT_PASS["ui_acceptance"]),
            )

            result = phase4_audit.check_authenticated_browser_gate(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("productized", result.evidence)

    def test_real_video_analysis_root_evidence_passes(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-real-video-analysis-root-evidence-20260607.json",
                json.dumps(REAL_VIDEO_ANALYSIS_PASS),
            )

            result = phase4_audit.check_real_video_analysis_root_evidence(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("model-backed", result.evidence)

    def test_current_root_chrome_evidence_passes(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json",
                json.dumps(PRODUCTIZED_UI_ROOT_PASS),
            )

            result = phase4_audit.check_current_root_chrome_evidence(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("productized", result.evidence)

    def test_current_root_chrome_evidence_rejects_public_gateway_port(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = json.loads(json.dumps(PRODUCTIZED_UI_ROOT_PASS))
            payload["ui_acceptance"]["assertions"]["mobile_no_horizontal_overflow"] = False
            write(
                repo / "artifacts/evidence/phase4/openclaw-productized-ui-root-deployment-evidence-20260607.json",
                json.dumps(payload),
            )

            result = phase4_audit.check_current_root_chrome_evidence(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("productized", result.evidence)

    def test_productized_login_evidence_rejects_sensitive_recording(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = json.loads(json.dumps(PRODUCTIZED_UI_ROOT_PASS["ui_acceptance"]))
            payload["login"]["accountRecorded"] = True
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-productized-root-acceptance-20260607.json",
                json.dumps(payload),
            )

            result = phase4_audit.check_authenticated_browser_gate(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("productized", result.evidence)

    def test_runner_gate_rejects_storage_or_header_access(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "scripts/huahuo_post_login_acceptance_runner.mjs", RUNNER + "\ndocument.cookie\n")

            result = phase4_audit.check_chrome_runner_ready(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("forbidden", result.evidence)

    def test_public_smoke_rejects_gateway_hits(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            payload = dict(SMOKE_PASS)
            payload["targets"] = [dict(item) for item in SMOKE_PASS["targets"]]
            payload["targets"][0]["gateway_direct_request_count"] = 1
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = phase4_audit.check_public_smoke_summary(path)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("Gateway", result.evidence)


if __name__ == "__main__":
    unittest.main()
