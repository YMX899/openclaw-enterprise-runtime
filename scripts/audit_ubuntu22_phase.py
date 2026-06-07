#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_AUDIT_PATH = REPO_ROOT / "scripts" / "audit_production_readiness.py"


@dataclass(frozen=True)
class PhaseCheck:
    check_id: str
    status: str
    evidence: str
    required_for: str = "ubuntu22_phase"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_production_audit():
    spec = importlib.util.spec_from_file_location("audit_production_readiness", PRODUCTION_AUDIT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _from_production_gate(gate) -> PhaseCheck:
    return PhaseCheck(gate.gate_id, gate.status, gate.evidence)


def check_openclaw_security(repo: Path) -> PhaseCheck:
    return _from_production_gate(_load_production_audit().check_openclaw_security(repo))


def check_douyin_artifact(repo: Path) -> PhaseCheck:
    return _from_production_gate(_load_production_audit().check_douyin_artifact(repo))


def check_douyin_current_phase(repo: Path) -> PhaseCheck:
    production_audit = _load_production_audit()
    gate = production_audit.check_video_link_read_mode(repo)
    if gate.status != "PASS":
        return PhaseCheck("douyin_current_phase", gate.status, gate.evidence)
    return PhaseCheck(
        "douyin_current_phase",
        "PASS",
        "video link-read mode is adopted for the Ubuntu 22.04 phase",
    )


def check_phase1_5_exit(repo: Path) -> PhaseCheck:
    return _from_production_gate(_load_production_audit().check_phase1_5_exit(repo))


def check_ubuntu22_dify_baseline(repo: Path) -> PhaseCheck:
    path = repo / "ubuntu22-dify-browser-baseline-20260606.md"
    if not path.exists():
        return PhaseCheck("ubuntu22_dify_authenticated_baseline", "NO_GO", f"missing {path.name}")

    text = _read(path)
    forbidden = [
        r"Authorization:\s*Bearer\s+\S+",
        r"Authorization headers?\s+recorded",
        r"Cookie:\s*\S+=\S+",
        r"CSRF[-_ ]?Token:\s*\S+",
        r"CSRF tokens?\s+recorded",
        r"password\s*[:=]\s*\S+",
        r"secret[_ -]?file[_ -]?contents[_ -]?recorded:\s*true",
    ]
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in forbidden):
        return PhaseCheck(
            "ubuntu22_dify_authenticated_baseline",
            "NO_GO",
            "baseline text appears to record sensitive browser or credential material",
        )

    required = [
        r"Target host:\s*`ubuntu22\.04`",
        r"Base URL:\s*`http://192\.168\.206\.130:8088`",
        r"Authenticated Dify app conversation baseline:\s*PASS",
        r"test account:\s*openclaw-baseline\+ubuntu22@local\.test",
        r"credential file mode:\s*600",
        r"TEMP_SECRET_RESIDUE_CLEARED",
        r"app name:\s*OpenClaw Baseline Fixed Reply",
        r"mode:\s*advanced-chat",
        r"model dependency:\s*none",
        r"published:\s*PASS",
        r"GET /apps after login:",
        r"workspace visible:\s*OpenClaw Ubuntu22 Baseline",
        r"app visible:\s*OpenClaw Baseline Fixed Reply",
        r"Message flow:",
        r"expected reply:\s*OpenClaw baseline reply ping baseline 0606",
        r"reply visible:\s*PASS",
        r"Refresh:",
        r"prior answer visible after refresh:\s*PASS",
        r"Return to /apps:",
        r"app entry visible:\s*PASS",
        r"Logout:",
        r"after logout /apps finalUrl:\s*http://192\.168\.206\.130:8088/signin",
        r"signin page visible:\s*PASS",
        r"new 5xx:\s*NONE",
        r"OpenClaw sidecar containers:\s*none remaining",
        r"Test listeners on 18181/18789/5432:\s*none remaining",
        r"production/root public baseline.*still\s+requires",
    ]
    missing = [pattern for pattern in required if not re.search(pattern, text, re.IGNORECASE)]
    if missing:
        return PhaseCheck(
            "ubuntu22_dify_authenticated_baseline",
            "NO_GO",
            "Ubuntu 22.04 authenticated Dify baseline missing markers: " + ", ".join(missing),
        )

    return PhaseCheck(
        "ubuntu22_dify_authenticated_baseline",
        "PASS",
        "Ubuntu 22.04 authenticated Dify browser baseline passed",
    )


def check_production_route_absent(repo: Path) -> PhaseCheck:
    return _from_production_gate(_load_production_audit().check_production_route_absent(repo))


CHECKS: tuple[Callable[[Path], PhaseCheck], ...] = (
    check_openclaw_security,
    check_douyin_artifact,
    check_douyin_current_phase,
    check_phase1_5_exit,
    check_ubuntu22_dify_baseline,
    check_production_route_absent,
)


def audit(repo: Path) -> dict:
    checks = [check(repo) for check in CHECKS]
    overall = "PASS" if all(check.status == "PASS" for check in checks) else "NO_GO"
    return {
        "schema_version": "openclaw-ubuntu22-phase-readiness.v1",
        "target": "ubuntu22_phase",
        "overall": overall,
        "checks": [asdict(check) for check in checks],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit OpenClaw x Dify Ubuntu 22.04 phase gates.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--fail-on-no-go", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit(Path(args.repo_root).resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_no_go and report["overall"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
