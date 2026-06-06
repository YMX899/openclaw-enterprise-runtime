#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    evidence: str
    required_for: str = "production_phase2"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _missing(path: Path) -> GateResult:
    return GateResult(path.name, "NO_GO", f"missing required evidence file: {path}")


def check_openclaw_security(repo: Path) -> GateResult:
    path = repo / "artifacts" / "openclaw-2026.3.13" / "SECURITY_DECISION.md"
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
    return GateResult("openclaw_security", "PASS", f"approved decision: {approved.group(1)}")


def check_douyin_artifact(repo: Path) -> GateResult:
    path = repo / "artifacts" / "douyin_chong" / "ARTIFACT_MANIFEST.md"
    if not path.exists():
        return GateResult("douyin_artifact", "NO_GO", f"missing {path}")
    text = _read(path)
    if re.search(r"^Status:\s*verified\b", text, re.IGNORECASE | re.MULTILINE):
        return GateResult("douyin_artifact", "PASS", "douyin_chong artifact manifest is verified")
    return GateResult("douyin_artifact", "NO_GO", "douyin_chong artifact is not verified")


def check_phase1_5_exit(repo: Path) -> GateResult:
    path = repo / "phase1.5-exit-proof.md"
    if not path.exists():
        return GateResult("phase1_5_exit_proof", "NO_GO", f"missing {path.name}")
    text = _read(path)
    required = [
        r"status:\s*PASS\b",
        r"REQUIRE_OPENCLAW_SECURITY_APPROVAL=1",
        r"RUN_COMPOSE_UP=1",
        r"docker compose build",
        r"docker compose up",
        r"127\.0\.0\.1:18181",
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
        r"history:\s*PASS\b",
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
