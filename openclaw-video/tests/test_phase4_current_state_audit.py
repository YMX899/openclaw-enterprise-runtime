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


PHASE4_BASE = """
current=/app/bin/openclaw-video/releases/db58a8ba6741
tag: phase4-openclaw-huahuo-login-header-20260607
ai_openclaw_lab=200
openclaw_lab=200
openclaw_api_me_unauth=401
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
    def test_current_repo_reports_known_remaining_gates(self):
        smoke = REPO_ROOT / "tmp" / "playwright-public-browser" / "20260606T195713Z" / "summary.json"
        report = phase4_audit.audit(REPO_ROOT, smoke_summary=smoke, include_git_clean=True)
        statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}

        self.assertEqual(report["overall"], "NO_GO")
        self.assertEqual(statuses["phase4_deployment_evidence"], "PASS")
        self.assertEqual(statuses["chrome_post_login_runner"], "PASS")
        self.assertEqual(statuses["public_smoke_latest"], "PASS")
        self.assertEqual(statuses["authenticated_browser_gate"], "PASS")
        self.assertEqual(statuses["douyin_real_sample"], "NO_GO")

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
                repo / "artifacts/evidence/phase4/openclaw-standalone-login-browser-acceptance-20260607.json",
                json.dumps(STANDALONE_LOGIN_PASS),
            )
            write(
                repo / "artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json",
                json.dumps({"schema_version": "douyin-real-sample-evidence.v1", "status": "succeeded"}),
            )
            smoke = repo / "summary.json"
            smoke.write_text(json.dumps(SMOKE_PASS), encoding="utf-8")

            report = phase4_audit.audit(repo, smoke_summary=smoke)

        self.assertEqual(report["overall"], "PASS")
        self.assertTrue(all(gate["status"] == "PASS" for gate in report["gates"]))

    def test_standalone_login_evidence_passes_authenticated_gate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "artifacts/evidence/phase4/openclaw-standalone-login-browser-acceptance-20260607.json",
                json.dumps(STANDALONE_LOGIN_PASS),
            )

            result = phase4_audit.check_authenticated_browser_gate(repo)

        self.assertEqual(result.status, "PASS")
        self.assertIn("standalone", result.evidence)

    def test_standalone_login_evidence_rejects_sensitive_recording(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = dict(STANDALONE_LOGIN_PASS)
            payload["password_recorded"] = True
            write(
                repo / "artifacts/evidence/phase4/openclaw-standalone-login-browser-acceptance-20260607.json",
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
