#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = REPO_ROOT / "scripts" / "audit_production_readiness.py"


@dataclass(frozen=True)
class PreflightCheck:
    check_id: str
    status: str
    evidence: str


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_production_readiness", AUDIT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(["git", *args], cwd=repo, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def check_target_host(target_host: str) -> PreflightCheck:
    if target_host != "root":
        return PreflightCheck(
            "target_host",
            "NO_GO",
            "root deployment preflight must target the configured production alias 'root'",
        )
    return PreflightCheck("target_host", "PASS", "target host alias is root")


def check_git_clean(repo: Path) -> PreflightCheck:
    code, stdout, stderr = _git(repo, ["status", "--short"])
    if code != 0:
        return PreflightCheck("git_clean", "NO_GO", stderr or stdout or "git status failed")
    if stdout:
        return PreflightCheck("git_clean", "NO_GO", "git worktree is not clean")
    return PreflightCheck("git_clean", "PASS", "git worktree is clean")


def check_git_tagged_head(repo: Path) -> PreflightCheck:
    code, stdout, stderr = _git(repo, ["tag", "--points-at", "HEAD"])
    if code != 0:
        return PreflightCheck("git_tagged_head", "NO_GO", stderr or stdout or "git tag failed")
    tags = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not tags:
        return PreflightCheck("git_tagged_head", "NO_GO", "HEAD has no version tag")
    return PreflightCheck("git_tagged_head", "PASS", ", ".join(tags))


def check_production_readiness(repo: Path) -> PreflightCheck:
    audit_module = _load_audit_module()
    report = audit_module.audit(repo, include_git_clean=True)
    no_go = [gate["gate_id"] for gate in report["gates"] if gate["status"] != "PASS"]
    if os.environ.get("ALLOW_DOUYIN_SAMPLE_DEFERRED") == "1":
        no_go = [gate_id for gate_id in no_go if gate_id != "douyin_real_sample"]
    if no_go:
        return PreflightCheck("production_readiness", "NO_GO", "NO_GO gates: " + ", ".join(no_go))
    return PreflightCheck("production_readiness", "PASS", "production readiness audit is GO")


def check_phase1_5_proof(repo: Path) -> PreflightCheck:
    path = repo / "phase1.5-exit-proof.md"
    if not path.exists():
        return PreflightCheck("phase1_5_proof_source", "NO_GO", "missing phase1.5-exit-proof.md")
    text = path.read_text(encoding="utf-8")
    forbidden = [
        r"production_host:\s*YES\b",
        r"host_name:\s*AI-01\b",
        r"target_host:\s*root\b",
        r"source:\s*production",
    ]
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in forbidden):
        return PreflightCheck("phase1_5_proof_source", "NO_GO", "proof appears to come from production host")
    required = [
        r"status:\s*PASS\b",
        r"source:\s*isolated-linux-docker-host\b",
        r"production_host:\s*NO\b",
        r"host_os:\s*Linux\b",
        r"RUN_COMPOSE_UP=1",
        r"docker compose up",
        r"docker compose down --remove-orphans --volumes",
        r"no 0\.0\.0\.0 listener",
    ]
    missing = [pattern for pattern in required if not re.search(pattern, text, re.IGNORECASE)]
    if missing:
        return PreflightCheck("phase1_5_proof_source", "NO_GO", "proof missing required isolated-host markers")
    return PreflightCheck("phase1_5_proof_source", "PASS", "isolated non-production Phase 1.5 proof is present")


def preflight(repo: Path, target_host: str) -> dict:
    checks = [
        check_target_host(target_host),
        check_git_clean(repo),
        check_git_tagged_head(repo),
        check_production_readiness(repo),
        check_phase1_5_proof(repo),
    ]
    overall = "GO" if all(check.status == "PASS" for check in checks) else "NO_GO"
    return {
        "schema_version": "openclaw-root-deploy-preflight.v1",
        "target_host": target_host,
        "overall": overall,
        "checks": [asdict(check) for check in checks],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed preflight before deploying OpenClaw sidecar to root.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--target-host", default="root")
    parser.add_argument("--fail-on-no-go", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = preflight(Path(args.repo_root).resolve(), args.target_host)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_no_go and report["overall"] != "GO":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
