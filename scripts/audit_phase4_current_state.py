#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PHASE4_EVIDENCE = REPO_ROOT / "phase4-same-origin-openclaw-lab-deployment-evidence-20260607.md"
RUNNER = REPO_ROOT / "scripts" / "huahuo_post_login_acceptance_runner.mjs"
REAL_SAMPLE = REPO_ROOT / "artifacts" / "douyin_chong" / "REAL_SAMPLE_EVIDENCE.json"
PRODUCTION_AUDIT = REPO_ROOT / "scripts" / "audit_production_readiness.py"
CURRENT_ROOT_CHROME_EVIDENCE_CANDIDATES = (
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-productized-ui-root-deployment-evidence-20260607.json",
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-current-root-chrome-evidence-20260607.json",
)
STANDALONE_LOGIN_EVIDENCE_CANDIDATES = (
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-ui-productized-root-acceptance-20260607.json",
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-ui-workbench-login-acceptance-root-20260607.json",
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-standalone-login-browser-acceptance-root-20260607.json",
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-standalone-login-browser-acceptance-20260607.json",
)

EXPECTED_DIFY_CORE = {
    "api": ("1eec6380496cebc40172a2e26e1a117f87dc480b5e917b8de4688a7f9afb7631", "2026-01-05T11:17:20.555976179Z"),
    "web": ("62c08605b5487328edea52d6d7b41e417d9b76c9114c826d0700f571d4871f36", "2026-01-05T11:17:19.85303869Z"),
    "nginx": ("8bf3a9282c091194130ddcdfbffe50b52d27cb48727322c50679493308b70dbe", "2026-01-05T11:17:20.937420886Z"),
}
EXPECTED_CURRENT_RELEASE = "/app/bin/openclaw-video/releases/94fdd79b29a0"
EXPECTED_PREVIOUS_RELEASE = "/app/bin/openclaw-video/releases/f1ba8273e7b6"


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    evidence: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_production_audit():
    spec = importlib.util.spec_from_file_location("audit_production_readiness", PRODUCTION_AUDIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _first_existing(repo: Path, candidates: tuple[Path, ...]) -> Path | None:
    for path in candidates:
        candidate = repo / path.relative_to(REPO_ROOT)
        if candidate.exists():
            return candidate
    return None


def _git(repo: Path, args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(["git", *args], cwd=repo, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def check_git_clean(repo: Path) -> GateResult:
    code, stdout, stderr = _git(repo, ["status", "--short"])
    if code != 0:
        return GateResult("git_clean", "NO_GO", stderr or stdout or "git status failed")
    if stdout:
        return GateResult("git_clean", "NO_GO", "git worktree is not clean")
    return GateResult("git_clean", "PASS", "git worktree is clean")


def check_phase4_deployment_evidence(repo: Path) -> GateResult:
    productized_path = repo / CURRENT_ROOT_CHROME_EVIDENCE_CANDIDATES[0].relative_to(REPO_ROOT)
    if productized_path.exists():
        try:
            payload = json.loads(_read(productized_path))
        except json.JSONDecodeError:
            return GateResult("phase4_deployment_evidence", "NO_GO", "productized root evidence is not valid JSON")
        root = payload.get("root_runtime") or {}
        public_routes = root.get("public_routes") or {}
        policy = payload.get("policy") or {}
        dify_core = root.get("dify_core") or {}
        dify_ok = True
        for name, (expected_id, expected_started_at) in EXPECTED_DIFY_CORE.items():
            current = dify_core.get(name) or {}
            dify_ok = dify_ok and current.get("id") == expected_id
            dify_ok = dify_ok and current.get("started_at") == expected_started_at
            dify_ok = dify_ok and current.get("status") == "running"
        checks = [
            payload.get("schema") == "openclaw-productized-ui-root-deployment-evidence.v1",
            payload.get("deployed_release") == EXPECTED_CURRENT_RELEASE,
            payload.get("previous_release") == EXPECTED_PREVIOUS_RELEASE,
            public_routes.get("dify_root") == 200,
            public_routes.get("openclaw_lab") == 200,
            public_routes.get("openclaw_api_me_unauth") == 401,
            public_routes.get("bridge_healthz") == 200,
            dify_ok,
            policy.get("local_test_loop_used") is False,
            policy.get("authoritative_environment") == "root",
            policy.get("ui_debug_completed_before_root_testing") is True,
            policy.get("dify_core_restarted") is False,
            policy.get("dify_core_rebuilt") is False,
            policy.get("secrets_recorded") is False,
            policy.get("account_recorded") is False,
            policy.get("password_recorded") is False,
            policy.get("cookies_recorded") is False,
            policy.get("headers_recorded") is False,
        ]
        if all(checks):
            return GateResult("phase4_deployment_evidence", "PASS", "productized UI root deployment evidence is current and sanitized")
        return GateResult("phase4_deployment_evidence", "NO_GO", "productized UI root deployment evidence failed required checks")

    path = repo / PHASE4_EVIDENCE.relative_to(REPO_ROOT)
    if not path.exists():
        return GateResult("phase4_deployment_evidence", "NO_GO", f"missing {path.name}")
    text = _read(path)
    required = [
        rf"current={re.escape(EXPECTED_CURRENT_RELEASE)}",
        r"tag:\s*phase4-openclaw-ui-workbench-20260607",
        r"tag:\s*phase4-video-link-read-check-20260607",
        r"ai_openclaw_lab=200",
        r"openclaw_lab=200",
        r"openclaw_api_me_unauth=401",
        r"read_check_unauth_status=401",
        r"video link read check PASS",
        r"huahuo_ai=200",
        r"docker-api-1\s+.*2026-01-05T11:17:20\.555976179Z\s+running",
        r"docker-web-1\s+.*2026-01-05T11:17:19\.85303869Z\s+running",
        r"docker-nginx-1\s+.*2026-01-05T11:17:20\.937420886Z\s+running",
    ]
    missing = [pattern for pattern in required if not re.search(pattern, text, re.IGNORECASE)]
    if missing:
        return GateResult("phase4_deployment_evidence", "NO_GO", "phase4 deployment evidence is incomplete")
    return GateResult("phase4_deployment_evidence", "PASS", "same-origin Lab deployment and Dify container invariants recorded")


def check_current_root_chrome_evidence(repo: Path) -> GateResult:
    path = _first_existing(repo, CURRENT_ROOT_CHROME_EVIDENCE_CANDIDATES)
    if path is None:
        return GateResult("current_root_chrome_evidence", "NO_GO", "missing current root/Chrome evidence")
    try:
        payload = json.loads(_read(path))
    except json.JSONDecodeError:
        return GateResult("current_root_chrome_evidence", "NO_GO", "current root/Chrome evidence is not valid JSON")
    if payload.get("schema") == "openclaw-productized-ui-root-deployment-evidence.v1":
        root = payload.get("root_runtime") or {}
        ui = payload.get("ui_acceptance") or {}
        assertions = ui.get("assertions") or {}
        acceptance = ui.get("post_login_acceptance") or {}
        login = ui.get("login") or {}
        session = ui.get("session") or {}
        public_routes = root.get("public_routes") or {}
        dify_core = root.get("dify_core") or {}
        policy = payload.get("policy") or {}
        dify_ok = True
        for name, (expected_id, expected_started_at) in EXPECTED_DIFY_CORE.items():
            current = dify_core.get(name) or {}
            dify_ok = dify_ok and current.get("id") == expected_id
            dify_ok = dify_ok and current.get("started_at") == expected_started_at
            dify_ok = dify_ok and current.get("status") == "running"
        safe_flags = (
            policy.get("secrets_recorded") is False
            and policy.get("account_recorded") is False
            and policy.get("password_recorded") is False
            and policy.get("cookies_recorded") is False
            and policy.get("headers_recorded") is False
            and login.get("accountRecorded") is False
        )
        checks = [
            payload.get("deployed_release") == EXPECTED_CURRENT_RELEASE,
            payload.get("previous_release") == EXPECTED_PREVIOUS_RELEASE,
            root.get("current_release") == EXPECTED_CURRENT_RELEASE,
            public_routes.get("dify_root") == 200,
            public_routes.get("openclaw_lab") == 200,
            public_routes.get("openclaw_api_me_unauth") == 401,
            public_routes.get("bridge_healthz") == 200,
            dify_ok,
            assertions.get("page_loaded") is True,
            assertions.get("workflow_present") is True,
            assertions.get("source_tabs_present") is True,
            assertions.get("result_cards_present") is True,
            assertions.get("diagnostics_available") is True,
            assertions.get("raw_json_secondary") is True,
            assertions.get("desktop_no_horizontal_overflow") is True,
            assertions.get("mobile_no_horizontal_overflow") is True,
            assertions.get("required_ids_present") is True,
            assertions.get("login_authenticated") is True,
            assertions.get("session_created") is True,
            assertions.get("post_login_acceptance_all_pass") is True,
            acceptance.get("overall") == "PASS",
            acceptance.get("checkCount") == 16,
            acceptance.get("allPass") is True,
            login.get("authenticated") is True,
            login.get("passwordCleared") is True,
            session.get("created") is True,
            session.get("idLength") == 36,
            safe_flags,
        ]
        if not all(checks):
            return GateResult("current_root_chrome_evidence", "NO_GO", "productized root UI evidence failed required checks")
        return GateResult(
            "current_root_chrome_evidence",
            "PASS",
            "root runtime proves productized OpenClaw UI, standalone login, Dify invariants and sanitized acceptance",
        )

    root = payload.get("root_runtime") or {}
    chrome = payload.get("chrome_visible_acceptance") or {}
    acceptance = chrome.get("post_login_acceptance") or {}
    public_routes = root.get("public_routes") or {}
    ports = root.get("openclaw_ports") or {}
    dify_core = root.get("dify_core") or {}
    smoke = payload.get("public_smoke") or {}
    video_scope = payload.get("video_link_read_scope") or {}
    read_check = payload.get("video_link_read_check") or {}

    dify_ok = True
    for name, (expected_id, expected_started_at) in EXPECTED_DIFY_CORE.items():
        current = dify_core.get(name) or {}
        dify_ok = dify_ok and current.get("id") == expected_id
        dify_ok = dify_ok and current.get("started_at") == expected_started_at
        dify_ok = dify_ok and current.get("status") == "running"

    safe_flags = (
        chrome.get("account_recorded") is False
        and chrome.get("password_recorded") is False
        and chrome.get("cookies_recorded") is False
        and chrome.get("headers_recorded") is False
        and chrome.get("secrets_recorded") is False
        and chrome.get("local_storage_values_recorded") is False
        and smoke.get("secrets_recorded") is False
        and smoke.get("headers_recorded") is False
        and smoke.get("bodies_recorded") is False
        and video_scope.get("raw_url_recorded") is False
        and video_scope.get("secret_file_contents_recorded") is False
        and video_scope.get("headers_recorded") is False
        and video_scope.get("cookies_recorded") is False
        and video_scope.get("tokens_recorded") is False
        and read_check.get("raw_url_recorded") is False
        and read_check.get("direct_video_url_recorded") is False
        and read_check.get("cookies_recorded") is False
        and read_check.get("headers_recorded") is False
        and read_check.get("tokens_recorded") is False
        and read_check.get("model_invoked") is False
        and read_check.get("raw_input_url_leaked") is False
        and read_check.get("test_account_leaked") is False
        and read_check.get("password_leaked") is False
        and read_check.get("direct_mp4_or_m3u8_leaked") is False
        and read_check.get("cookie_value_recorded") is False
        and read_check.get("authorization_word_in_output") is False
    )

    checks = [
        payload.get("schema") == "openclaw-current-root-chrome-evidence.v1",
        payload.get("status") == "PASS",
        root.get("current_release") == EXPECTED_CURRENT_RELEASE,
        root.get("previous_release") == "/app/bin/openclaw-video/releases/bea6534980dc",
        root.get("release_has_video_link_probe") is True,
        root.get("release_has_douyin_chong_vendor") is True,
        root.get("gateway_version") == "OpenClaw 2026.3.13 (61d171a)",
        dify_ok,
        "127.0.0.1:18181" in str(ports.get("bridge", "")),
        ports.get("gateway") == "",
        ports.get("postgres") == "",
        ports.get("worker") == "",
        public_routes.get("ai_openclaw_lab") == 200,
        public_routes.get("openclaw_api_me_unauth") == 401,
        public_routes.get("huahuo_ai") == 200,
        chrome.get("status") == "PASS",
        chrome.get("lab_has_login_form") is True,
        chrome.get("lab_has_workbench") is True,
        chrome.get("lab_has_acceptance_button") is True,
        chrome.get("me_status") == 200,
        chrome.get("me_authenticated") is True,
        acceptance.get("overall") == "PASS",
        acceptance.get("step_count") == 16,
        acceptance.get("failed_steps") == [],
        chrome.get("console_error_count") == 0,
        smoke.get("status") == "PASS",
        video_scope.get("mode") == "ADOPTED",
        video_scope.get("douyin_login_required") is False,
        video_scope.get("real_sample_evidence_required") is False,
        video_scope.get("runtime_path_verified_by_tests") is True,
        video_scope.get("latest_read_check") == "PASS",
        read_check.get("schema") == "openclaw-video-link-read-check-root-chrome-evidence.v1",
        read_check.get("api_status") == 200,
        read_check.get("auth_status") == "Authenticated",
        read_check.get("read_link_button_present") is True,
        read_check.get("schema_version") == "openclaw-video-link-read-check.v1",
        read_check.get("status") == "PASS",
        read_check.get("canonical_host") == "www.douyin.com",
        read_check.get("direct_video_candidate_count", 0) >= 1,
        read_check.get("direct_video_host_present") is True,
        read_check.get("playwm_host_present") is True,
        read_check.get("content_type_present") is True,
        read_check.get("duration_seconds_present") is True,
        read_check.get("size_bytes_present") is True,
        read_check.get("eligible_for_model_analysis") is True,
        safe_flags,
    ]
    if not all(checks):
        return GateResult("current_root_chrome_evidence", "NO_GO", "current root/Chrome evidence failed required checks")
    return GateResult(
        "current_root_chrome_evidence",
        "PASS",
        "root runtime proves OpenClaw 2026.3.13, private sidecar ports, Dify invariants, and Chrome acceptance",
    )


def check_chrome_runner_ready(repo: Path) -> GateResult:
    path = repo / RUNNER.relative_to(REPO_ROOT)
    if not path.exists():
        return GateResult("chrome_post_login_runner", "NO_GO", f"missing {path.name}")
    text = _read(path)
    required = [
        "openclaw-chrome-post-login-acceptance.v1",
        "openclaw-standalone-login-browser-acceptance.v1",
        "runHuahuoPostLoginAcceptance",
        "runOpenClawStandaloneLoginAcceptance",
        "Post-Login Acceptance",
        "PENDING_LOGIN",
        "secrets_recorded: false",
        "headers_recorded: false",
        "local_storage_values_recorded: false",
    ]
    missing = [item for item in required if item not in text]
    forbidden = [
        "document.cookie",
        "localStorage",
        "storageState",
        "request.headers",
        "setupBrowserRuntime",
        "agent.browsers.get",
        "chromium.launch",
    ]
    found_forbidden = [item for item in forbidden if item in text]
    if missing:
        return GateResult("chrome_post_login_runner", "NO_GO", "runner missing required sanitized markers")
    if found_forbidden:
        return GateResult("chrome_post_login_runner", "NO_GO", "runner contains forbidden browser/session access")
    return GateResult("chrome_post_login_runner", "PASS", "Chrome helper is present and sanitized")


def _json_has_safe_flags(payload: dict[str, Any]) -> bool:
    return (
        payload.get("secrets_recorded") is False
        and payload.get("headers_recorded") is False
        and payload.get("cookies_recorded") is False
        and payload.get("local_storage_values_recorded") is False
        and payload.get("account_recorded") is False
        and payload.get("password_recorded") is False
    )


def check_public_smoke_summary(path: Path | None) -> GateResult:
    if path is None:
        return GateResult("public_smoke_latest", "WARN", "no smoke summary path supplied")
    if not path.exists():
        return GateResult("public_smoke_latest", "NO_GO", f"missing smoke summary: {path}")
    try:
        payload = json.loads(_read(path))
    except json.JSONDecodeError:
        return GateResult("public_smoke_latest", "NO_GO", "smoke summary is not valid JSON")
    target_names = {target.get("name") for target in payload.get("targets") or []}
    required_targets = {
        "openclaw-standalone-lab",
        "openclaw-lab",
        "openclaw-api-me-unauthenticated",
        "huahuo-user-web",
        "huahuo-admin-configuration",
    }
    if payload.get("status") != "PASS":
        return GateResult("public_smoke_latest", "NO_GO", "public smoke did not pass")
    if not required_targets.issubset(target_names):
        return GateResult("public_smoke_latest", "NO_GO", "public smoke missing expected targets")
    unsafe_flags = [
        payload.get("secrets_recorded") is not False,
        payload.get("headers_recorded") is not False,
        payload.get("bodies_recorded") is not False,
    ]
    if any(unsafe_flags):
        return GateResult("public_smoke_latest", "NO_GO", "public smoke summary recorded unsafe material")
    for target in payload.get("targets") or []:
        if target.get("http_5xx_count") != 0:
            return GateResult("public_smoke_latest", "NO_GO", "public smoke saw HTTP 5xx")
        if target.get("gateway_direct_request_count") != 0:
            return GateResult("public_smoke_latest", "NO_GO", "browser directly reached Gateway")
        if target.get("token_url_leak_count") != 0:
            return GateResult("public_smoke_latest", "NO_GO", "token-like material appeared in URL")
    return GateResult("public_smoke_latest", "PASS", "latest public smoke summary passed with sanitized metadata")


def check_authenticated_browser_gate(repo: Path) -> GateResult:
    standalone_path = next(
        (
            repo / path.relative_to(REPO_ROOT)
            for path in STANDALONE_LOGIN_EVIDENCE_CANDIDATES
            if (repo / path.relative_to(REPO_ROOT)).exists()
        ),
        None,
    )
    if standalone_path is not None and standalone_path.exists():
        try:
            payload = json.loads(_read(standalone_path))
        except json.JSONDecodeError:
            return GateResult("authenticated_browser_gate", "NO_GO", "standalone login evidence is not valid JSON")
        if payload.get("schema") == "openclaw-ui-productized-root-acceptance.v1":
            assertions = payload.get("assertions") or {}
            acceptance = payload.get("post_login_acceptance") or {}
            login = payload.get("login") or {}
            if (
                assertions.get("login_authenticated") is True
                and assertions.get("session_created") is True
                and assertions.get("post_login_acceptance_all_pass") is True
                and acceptance.get("overall") == "PASS"
                and acceptance.get("checkCount") == 16
                and acceptance.get("allPass") is True
                and login.get("authenticated") is True
                and login.get("passwordCleared") is True
                and login.get("accountRecorded") is False
            ):
                return GateResult(
                    "authenticated_browser_gate",
                    "PASS",
                    "OpenClaw productized UI standalone login and post-login acceptance passed on root",
                )
            return GateResult("authenticated_browser_gate", "NO_GO", "productized UI login evidence did not pass required checks")
        diagnostics = payload.get("diagnostics") or {}
        acceptance = payload.get("post_login_acceptance") or {}
        if (
            payload.get("schema") == "openclaw-standalone-login-browser-acceptance.v1"
            and payload.get("status") == "PASS"
            and payload.get("login_status") == 200
            and payload.get("login_authenticated") is True
            and payload.get("login_principal_len") == 64
            and diagnostics.get("authenticated") is True
            and diagnostics.get("openclaw_session_present") is True
            and diagnostics.get("auth_mode") == "openclaw_session"
            and diagnostics.get("huahuo_access_token_present") is False
            and diagnostics.get("huahuo_app_uuid_present") is False
            and diagnostics.get("profile_ok") is True
            and diagnostics.get("workspace_ok") is True
            and diagnostics.get("access_ok") is True
            and diagnostics.get("provider_probe_present") is False
            and acceptance.get("overall") == "PASS"
            and acceptance.get("step_count") == 16
            and acceptance.get("failed_steps") == []
            and payload.get("console_error_count") == 0
            and _json_has_safe_flags(payload)
        ):
            return GateResult(
                "authenticated_browser_gate",
                "PASS",
                "OpenClaw standalone password login and post-login Chrome acceptance passed",
            )
        return GateResult("authenticated_browser_gate", "NO_GO", "standalone login evidence did not pass required checks")

    path = repo / PHASE4_EVIDENCE.relative_to(REPO_ROOT)
    if not path.exists():
        return GateResult("authenticated_browser_gate", "NO_GO", f"missing {path.name}")
    text = _read(path)
    if (
        "openclaw-chrome-post-login-acceptance.v1" in text
        and re.search(r'"status":\s*"PASS"', text)
    ):
        return GateResult("authenticated_browser_gate", "PASS", "post-login Chrome acceptance has passed")
    if "PENDING_LOGIN" in text and "user_looks_logged_out" in text:
        return GateResult("authenticated_browser_gate", "PENDING_LOGIN", "Huahuo user web login is still absent in Chrome")
    return GateResult("authenticated_browser_gate", "NO_GO", "post-login Chrome acceptance evidence is missing")


def check_real_douyin_sample(repo: Path) -> GateResult:
    path = repo / REAL_SAMPLE.relative_to(REPO_ROOT)
    if not path.exists():
        return GateResult("douyin_real_sample", "NO_GO", f"missing {path.name}")
    try:
        payload = json.loads(_read(path))
    except json.JSONDecodeError:
        return GateResult("douyin_real_sample", "NO_GO", "real sample evidence is not valid JSON")
    if payload.get("schema_version") != "douyin-real-sample-evidence.v1" or payload.get("status") != "succeeded":
        return GateResult("douyin_real_sample", "NO_GO", "real sample evidence did not succeed")
    return GateResult("douyin_real_sample", "PASS", "real douyin sample evidence is present")


def check_video_link_read_mode(repo: Path) -> GateResult:
    gate = _load_production_audit().check_video_link_read_mode(repo)
    return GateResult(gate.gate_id, gate.status, gate.evidence)


def audit(repo: Path, *, smoke_summary: Path | None = None, include_git_clean: bool = False) -> dict[str, Any]:
    gates = [
        check_phase4_deployment_evidence(repo),
        check_current_root_chrome_evidence(repo),
        check_chrome_runner_ready(repo),
        check_public_smoke_summary(smoke_summary),
        check_authenticated_browser_gate(repo),
        check_video_link_read_mode(repo),
    ]
    if include_git_clean:
        gates.append(check_git_clean(repo))
    statuses = {gate.status for gate in gates}
    if "NO_GO" in statuses:
        overall = "NO_GO"
    elif "PENDING_LOGIN" in statuses:
        overall = "PENDING_LOGIN"
    elif "WARN" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"
    return {
        "schema_version": "openclaw-phase4-current-state.v1",
        "overall": overall,
        "gates": [asdict(gate) for gate in gates],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit the current Phase 4 sidecar state without claiming full production GO.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--smoke-summary")
    parser.add_argument("--include-git-clean", action="store_true")
    parser.add_argument("--fail-on-no-go", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    smoke_summary = Path(args.smoke_summary).resolve() if args.smoke_summary else None
    report = audit(Path(args.repo_root).resolve(), smoke_summary=smoke_summary, include_git_clean=args.include_git_clean)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_no_go and report["overall"] == "NO_GO":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
