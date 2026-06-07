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
STANDALONE_LOGIN_EVIDENCE_CANDIDATES = (
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-standalone-login-browser-acceptance-root-20260607.json",
    REPO_ROOT / "artifacts" / "evidence" / "phase4" / "openclaw-standalone-login-browser-acceptance-20260607.json",
)


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
    path = repo / PHASE4_EVIDENCE.relative_to(REPO_ROOT)
    if not path.exists():
        return GateResult("phase4_deployment_evidence", "NO_GO", f"missing {path.name}")
    text = _read(path)
    required = [
        r"current=/app/bin/openclaw-video/releases/14722e96e130",
        r"tag:\s*phase4-relaxed-root-testing-baseline-20260607",
        r"ai_openclaw_lab=200",
        r"openclaw_lab=200",
        r"openclaw_api_me_unauth=401",
        r"huahuo_ai=200",
        r"docker-api-1\s+.*2026-01-05T11:17:20\.555976179Z\s+running",
        r"docker-web-1\s+.*2026-01-05T11:17:19\.85303869Z\s+running",
        r"docker-nginx-1\s+.*2026-01-05T11:17:20\.937420886Z\s+running",
    ]
    missing = [pattern for pattern in required if not re.search(pattern, text, re.IGNORECASE)]
    if missing:
        return GateResult("phase4_deployment_evidence", "NO_GO", "phase4 deployment evidence is incomplete")
    return GateResult("phase4_deployment_evidence", "PASS", "same-origin Lab deployment and Dify container invariants recorded")


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
