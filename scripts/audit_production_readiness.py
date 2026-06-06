#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    evidence: str
    required_for: str = "production_phase2"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def check_openclaw_security(repo: Path) -> GateResult:
    path = repo / "artifacts" / "openclaw-2026.3.13" / "SECURITY_DECISION.md"
    triage_path = repo / "artifacts" / "openclaw-2026.3.13" / "SECURITY_TRIAGE.md"
    if not path.exists():
        return GateResult("openclaw_security", "NO_GO", f"missing {path}")
    text = _read(path)
    lower = text.lower()
    if "decision: reject_fixed_version_for_production_currently" in lower:
        return GateResult(
            "openclaw_security",
            "NO_GO",
            "OpenClaw 2026.3.13 is currently rejected for production",
        )
    approved = re.search(r"decision:\s*(approve_exception|vendor_patch|upgrade_strategy)\b", lower)
    if not approved:
        return GateResult("openclaw_security", "NO_GO", "no approved OpenClaw security decision")
    if "security_owner: not assigned" in lower or "engineering_owner: codex draft" in lower:
        return GateResult("openclaw_security", "NO_GO", "security decision is not human-approved")
    if not triage_path.exists():
        return GateResult("openclaw_security", "NO_GO", f"missing {triage_path.name}")
    triage = _read(triage_path)
    triage_lower = triage.lower()
    if re.search(r"template_pending|<[^>\n]+>|\btodo\b|\btbd\b", triage, re.IGNORECASE):
        return GateResult("openclaw_security", "NO_GO", "security triage still contains template placeholders")
    required_triage = [
        r"openclaw_version:\s*2026\.3\.13",
        r"npm_audit_command:\s*npm audit --omit=dev --json",
        r"runtime_scope:\s*private OpenClaw Gateway behind Bridge only",
        r"browser_exposure:\s*Gateway token never sent to browser",
        r"bridge_scopes:\s*operator\.read,\s*operator\.write",
        r"operator_admin:\s*forbidden",
        r"approved_by_security_owner:\s*\S+",
        r"approved_by_engineering_owner:\s*\S+",
        r"approval_date:\s*\d{4}-\d{2}-\d{2}",
    ]
    missing_triage = [pattern for pattern in required_triage if not re.search(pattern, triage, re.IGNORECASE)]
    if missing_triage:
        return GateResult("openclaw_security", "NO_GO", "security triage missing required approval markers")
    packages = [
        "openclaw",
        "@buape/carbon",
        "@hono/node-server",
        "@larksuiteoapi/node-sdk",
        "axios",
        "hono",
        "ws",
    ]
    missing_packages = [package for package in packages if package.lower() not in triage_lower]
    if missing_packages:
        return GateResult(
            "openclaw_security",
            "NO_GO",
            f"security triage missing package rows: {', '.join(missing_packages)}",
        )
    if re.search(r"severity:\s*critical[\s\S]{0,240}reachable:\s*(yes|unknown)", triage, re.IGNORECASE):
        return GateResult("openclaw_security", "NO_GO", "critical reachable or unknown advisory not closed")
    if re.search(r"severity:\s*high[\s\S]{0,240}reachable:\s*(yes|unknown)", triage, re.IGNORECASE):
        return GateResult("openclaw_security", "NO_GO", "high reachable or unknown advisory not closed")
    return GateResult("openclaw_security", "PASS", f"approved decision: {approved.group(1)}")


def check_douyin_artifact(repo: Path) -> GateResult:
    path = repo / "artifacts" / "douyin_chong" / "ARTIFACT_MANIFEST.md"
    if not path.exists():
        return GateResult("douyin_artifact", "NO_GO", f"missing {path}")
    text = _read(path)
    if re.search(r"^Status:\s*verified\b", text, re.IGNORECASE | re.MULTILINE):
        return GateResult("douyin_artifact", "PASS", "douyin_chong artifact manifest is verified")
    return GateResult("douyin_artifact", "NO_GO", "douyin_chong artifact is not verified")


def check_douyin_real_sample(repo: Path) -> GateResult:
    path = repo / "artifacts" / "douyin_chong" / "REAL_SAMPLE_EVIDENCE.json"
    if not path.exists():
        if os.environ.get("ALLOW_DOUYIN_SAMPLE_DEFERRED") == "1":
            return GateResult(
                "douyin_real_sample",
                "PASS",
                "real sample evidence deferred by operator for current phase",
            )
        return GateResult("douyin_real_sample", "NO_GO", f"missing {path}")
    try:
        evidence = json.loads(_read(path))
    except json.JSONDecodeError:
        return GateResult("douyin_real_sample", "NO_GO", "real sample evidence is not valid JSON")

    if evidence.get("schema_version") != "douyin-real-sample-evidence.v1":
        return GateResult("douyin_real_sample", "NO_GO", "unexpected real sample evidence schema version")
    if evidence.get("status") != "succeeded":
        return GateResult("douyin_real_sample", "NO_GO", "real sample did not succeed")
    if evidence.get("secret_file_contents_recorded") is not False:
        return GateResult("douyin_real_sample", "NO_GO", "real sample evidence may record secret file contents")
    if evidence.get("env_file_present") is not True:
        return GateResult("douyin_real_sample", "NO_GO", "real sample did not use an explicit runtime env file")
    if not _is_sha256(evidence.get("input_url_sha256")):
        return GateResult("douyin_real_sample", "NO_GO", "real sample evidence is missing input URL hash")
    if re.search(r"https?://", _json_text(evidence), re.IGNORECASE):
        return GateResult("douyin_real_sample", "NO_GO", "real sample evidence contains a raw URL")

    process = evidence.get("process") or {}
    if process.get("returncode") != 0:
        return GateResult("douyin_real_sample", "NO_GO", "real sample adapter return code was not zero")
    if not isinstance(process.get("elapsed_seconds"), (int, float)) or process["elapsed_seconds"] <= 0:
        return GateResult("douyin_real_sample", "NO_GO", "real sample elapsed time is missing")
    if process.get("stdout_recorded") is not False or process.get("stderr_recorded") is not False:
        return GateResult("douyin_real_sample", "NO_GO", "real sample stdout/stderr contents must not be recorded")

    result = evidence.get("result") or {}
    if result.get("schema_version") != "openclaw-video-result.v1":
        return GateResult("douyin_real_sample", "NO_GO", "real sample result schema was not validated")
    if result.get("platform") != "douyin":
        return GateResult("douyin_real_sample", "NO_GO", "real sample platform is not douyin")
    if not _is_sha256(result.get("result_json_sha256")):
        return GateResult("douyin_real_sample", "NO_GO", "real sample result hash is missing")
    if not isinstance(result.get("result_json_bytes"), int) or result["result_json_bytes"] <= 0:
        return GateResult("douyin_real_sample", "NO_GO", "real sample result size is missing")
    return GateResult("douyin_real_sample", "PASS", "sanitized real model-backed sample evidence is present")


def check_phase1_5_exit(repo: Path) -> GateResult:
    path = repo / "phase1.5-exit-proof.md"
    if not path.exists():
        return GateResult("phase1_5_exit_proof", "NO_GO", f"missing {path.name}")
    text = _read(path)
    placeholder_patterns = [
        r"TEMPLATE_PENDING",
        r"DO_NOT_USE",
        r"<[^>\n]+>",
        r"\bTODO\b",
        r"\bTBD\b",
    ]
    placeholders = [pattern for pattern in placeholder_patterns if re.search(pattern, text, re.IGNORECASE)]
    if placeholders:
        return GateResult("phase1_5_exit_proof", "NO_GO", "exit proof still contains template placeholders")
    required = [
        r"status:\s*PASS\b",
        r"source:\s*isolated-linux-docker-host\b",
        r"production_host:\s*NO\b",
        r"host_os:\s*Linux\b",
        r"SKIP_DOCKER=0",
        r"REQUIRE_OPENCLAW_SECURITY_APPROVAL=1",
        r"REQUIRE_DOUYIN_ARTIFACT=1",
        r"RUN_COMPOSE_UP=1",
        r"scripts/verify_phase1_5_gates\.sh",
        r"docker version",
        r"docker compose version",
        r"docker compose config",
        r"docker compose build",
        r"docker compose up",
        r"healthz",
        r"port exposure check",
        r"127\.0\.0\.1:18181",
        r"docker compose down --remove-orphans --volumes",
        r"no 0\.0\.0\.0 listener",
        r"worker image",
    ]
    missing = [pattern for pattern in required if not re.search(pattern, text, re.IGNORECASE)]
    if missing:
        return GateResult("phase1_5_exit_proof", "NO_GO", f"exit proof missing markers: {', '.join(missing)}")
    return GateResult("phase1_5_exit_proof", "PASS", "isolated Linux Docker exit proof markers present")


def check_authenticated_dify_baseline(repo: Path) -> GateResult:
    path = repo / "dify-public-baseline.md"
    if not path.exists():
        return GateResult("authenticated_dify_baseline", "NO_GO", f"missing {path}")
    text = _read(path)
    pass_markers = [
        r"authenticated[_ -]?baseline:\s*PASS\b",
        r"existing app message:\s*PASS\b",
        r"streaming reply:\s*PASS\b",
        r"refresh:\s*PASS\b",
        r"history:\s*PASS\b",
        r"logout:\s*PASS\b",
        r"profile 401:\s*PASS\b",
        r"new 5xx:\s*NONE\b",
    ]
    missing = [pattern for pattern in pass_markers if not re.search(pattern, text, re.IGNORECASE)]
    if missing:
        return GateResult(
            "authenticated_dify_baseline",
            "NO_GO",
            "authenticated public Dify baseline has not passed",
        )
    return GateResult("authenticated_dify_baseline", "PASS", "authenticated public Dify baseline passed")


def check_production_route_absent(repo: Path) -> GateResult:
    path = repo / "openresty-route-map-redacted.md"
    if not path.exists():
        return GateResult("openresty_no_route_change", "NO_GO", f"missing {path}")
    text = _read(path).lower()
    if "no openclaw route present" in text:
        return GateResult("openresty_no_route_change", "PASS", "no OpenClaw public route is present")
    return GateResult("openresty_no_route_change", "NO_GO", "route state is unclear; do not proceed")


def check_git_clean(repo: Path) -> GateResult:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return GateResult("git_clean", "NO_GO", "git status failed")
    if completed.stdout.strip():
        return GateResult("git_clean", "NO_GO", "git worktree is not clean")
    return GateResult("git_clean", "PASS", "git worktree is clean")


GATES: tuple[Callable[[Path], GateResult], ...] = (
    check_openclaw_security,
    check_douyin_artifact,
    check_douyin_real_sample,
    check_phase1_5_exit,
    check_authenticated_dify_baseline,
    check_production_route_absent,
)


def audit(repo: Path, *, include_git_clean: bool = False) -> dict:
    results = [gate(repo) for gate in GATES]
    if include_git_clean:
        results.append(check_git_clean(repo))
    overall = "GO" if all(result.status == "PASS" for result in results) else "NO_GO"
    return {
        "schema_version": "openclaw-production-readiness.v1",
        "target": "production_phase2",
        "overall": overall,
        "gates": [asdict(result) for result in results],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit OpenClaw x Dify production readiness gates.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--include-git-clean", action="store_true")
    parser.add_argument("--fail-on-no-go", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit(Path(args.repo_root), include_git_clean=args.include_git_clean)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_no_go and report["overall"] != "GO":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
