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


CURRENT_ROOT_CHROME_PASS = {
    "schema": "openclaw-current-root-chrome-evidence.v1",
    "status": "PASS",
    "root_runtime": {
        "current_release": "/app/bin/openclaw-video/releases/f1ba8273e7b6",
        "previous_release": "/app/bin/openclaw-video/releases/bea6534980dc",
        "release_has_video_link_probe": True,
        "release_has_douyin_chong_vendor": True,
        "gateway_version": "OpenClaw 2026.3.13 (61d171a)",
        "dify_core": {
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
        },
        "openclaw_ports": {
            "bridge": "3000/tcp -> 127.0.0.1:18181",
            "gateway": "",
            "postgres": "",
            "worker": "",
        },
        "public_routes": {
            "ai_openclaw_lab": 200,
            "openclaw_api_me_unauth": 401,
            "huahuo_ai": 200,
        },
    },
    "chrome_visible_acceptance": {
        "status": "PASS",
        "lab_has_login_form": True,
        "lab_has_workbench": True,
        "lab_has_acceptance_button": True,
        "me_status": 200,
        "me_authenticated": True,
        "post_login_acceptance": {
            "overall": "PASS",
            "step_count": 16,
            "failed_steps": [],
        },
        "console_error_count": 0,
        "account_recorded": False,
        "password_recorded": False,
        "cookies_recorded": False,
        "headers_recorded": False,
        "secrets_recorded": False,
        "local_storage_values_recorded": False,
    },
    "public_smoke": {
        "status": "PASS",
        "secrets_recorded": False,
        "headers_recorded": False,
        "bodies_recorded": False,
    },
    "video_link_read_check": {
        "schema": "openclaw-video-link-read-check-root-chrome-evidence.v1",
        "api_status": 200,
        "auth_status": "Authenticated",
        "auth_metric": "Authenticated",
        "read_link_button_present": True,
        "schema_version": "openclaw-video-link-read-check.v1",
        "status": "PASS",
        "canonical_host": "www.douyin.com",
        "redirect_hop_count": 0,
        "redirect_chain_hosts": ["www.douyin.com"],
        "resolved_ip_count": 18,
        "resolver": "douyin_chong.UniversalVideoResolver",
        "video_id_present": True,
        "direct_video_candidate_count": 2,
        "direct_video_host_present": True,
        "playwm_host_present": True,
        "content_type_present": True,
        "duration_seconds_present": True,
        "size_bytes_present": True,
        "video_url_source": "direct",
        "eligible_for_model_analysis": True,
        "raw_url_recorded": False,
        "direct_video_url_recorded": False,
        "cookies_recorded": False,
        "headers_recorded": False,
        "tokens_recorded": False,
        "model_invoked": False,
        "raw_input_url_leaked": False,
        "test_account_leaked": False,
        "password_leaked": False,
        "direct_mp4_or_m3u8_leaked": False,
        "cookie_value_recorded": False,
        "authorization_word_in_output": False,
    },
    "video_link_read_scope": {
        "mode": "ADOPTED",
        "douyin_login_required": False,
        "real_sample_evidence_required": False,
        "runtime_path_verified_by_tests": True,
        "latest_read_check": "PASS",
        "raw_url_recorded": False,
        "secret_file_contents_recorded": False,
        "headers_recorded": False,
        "cookies_recorded": False,
        "tokens_recorded": False,
    },
}


PHASE4_BASE = """
current=/app/bin/openclaw-video/releases/f1ba8273e7b6
tag: phase4-openclaw-ui-workbench-20260607
tag: phase4-video-link-read-check-20260607
ai_openclaw_lab=200
openclaw_lab=200
openclaw_api_me_unauth=401
read_check_unauth_status=401
video link read check PASS
huahuo_ai=200
/docker-api-1   1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631  2026-01-05T11:17:20.555976179Z  running
/docker-web-1   62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36  2026-01-05T11:17:19.85303869Z   running
/docker-nginx-1 8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe  2026-01-05T11:17:20.937420886Z  running
"""


RUNNER = """
export async function runHuahuoPostLoginAcceptance(browser, options = {}) {
  await browser.tabs.new();
}
export async function runOpenClawStandaloneLoginAcceptance(browser, options = {}) {
  await browser.tabs.new();
}
openclaw-chrome-post-login-acceptance.v1
openclaw-standalone-login-browser-acceptance.v1
Post-Login Acceptance
PENDING_LOGIN
secrets_recorded: false
headers_recorded: false
local_storage_values_recorded: false
"""


STANDALONE_LOGIN_PASS = {
    "schema": "openclaw-standalone-login-browser-acceptance.v1",
    "status": "PASS",
    "login_status": 200,
    "login_authenticated": True,
    "login_principal_len": 64,
    "diagnostics": {
        "authenticated": True,
        "openclaw_session_present": True,
        "auth_mode": "openclaw_session",
        "huahuo_access_token_present": False,
        "huahuo_app_uuid_present": False,
        "profile_ok": True,
        "workspace_ok": True,
        "access_ok": True,
        "provider_probe_present": False,
    },
    "post_login_acceptance": {
        "overall": "PASS",
        "step_count": 16,
        "failed_steps": [],
    },
    "console_error_count": 0,
    "account_recorded": False,
    "secrets_recorded": False,
    "headers_recorded": False,
    "cookies_recorded": False,
    "local_storage_values_recorded": False,
    "password_recorded": False,
}


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
            write(repo / "phase4-same-origin-openclaw-lab-deployment-evidence-20260607.md", PHASE4_BASE)
            write(
                repo / "phase4-same-origin-openclaw-lab-deployment-evidence-20260607.md",
                PHASE4_BASE
                + '\n"schema": "openclaw-chrome-post-login-acceptance.v1"\n'
                + '\n"status": "PASS"\n',
            )
            write(repo / "scripts/huahuo_post_login_acceptance_runner.mjs", RUNNER)
            write(
                repo / "artifacts/evidence/phase4/openclaw-current-root-chrome-evidence-20260607.json",
                json.dumps(CURRENT_ROOT_CHROME_PASS),
            )
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-workbench-login-acceptance-root-20260607.json",
                json.dumps(STANDALONE_LOGIN_PASS),
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

    def test_standalone_login_evidence_passes_authenticated_gate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-workbench-login-acceptance-root-20260607.json",
                json.dumps(STANDALONE_LOGIN_PASS),
            )

            result = phase4_audit.check_authenticated_browser_gate(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("standalone", result.evidence)

    def test_current_root_chrome_evidence_passes(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-current-root-chrome-evidence-20260607.json",
                json.dumps(CURRENT_ROOT_CHROME_PASS),
            )

            result = phase4_audit.check_current_root_chrome_evidence(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("2026.3.13", result.evidence)

    def test_current_root_chrome_evidence_rejects_public_gateway_port(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = json.loads(json.dumps(CURRENT_ROOT_CHROME_PASS))
            payload["root_runtime"]["openclaw_ports"]["gateway"] = "18789/tcp -> 0.0.0.0:18789"
            write(
                repo / "artifacts/evidence/phase4/openclaw-current-root-chrome-evidence-20260607.json",
                json.dumps(payload),
            )

            result = phase4_audit.check_current_root_chrome_evidence(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("root/Chrome", result.evidence)

    def test_standalone_login_evidence_rejects_sensitive_recording(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = dict(STANDALONE_LOGIN_PASS)
            payload["password_recorded"] = True
            write(
                repo / "artifacts/evidence/phase4/openclaw-ui-workbench-login-acceptance-root-20260607.json",
                json.dumps(payload),
            )

            result = phase4_audit.check_authenticated_browser_gate(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("standalone", result.evidence)

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
