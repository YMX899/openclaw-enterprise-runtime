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


REPO_ROOT = Path(__file__).resolve().parents[1]
UBUNTU22_AUDIT_PATH = REPO_ROOT / "scripts" / "audit_ubuntu22_phase.py"


@dataclass(frozen=True)
class PrivatePreflightCheck:
    check_id: str
    status: str
    evidence: str


def _load_ubuntu22_audit():
    spec = importlib.util.spec_from_file_location("audit_ubuntu22_phase", UBUNTU22_AUDIT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(["git", *args], cwd=repo, check=False, capture_output=True, text=True)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def check_target_host(target_host: str) -> PrivatePreflightCheck:
    if target_host != "root":
        return PrivatePreflightCheck(
            "target_host",
            "NO_GO",
            "private sidecar deployment must target the configured production alias 'root'",
        )
    return PrivatePreflightCheck("target_host", "PASS", "target host alias is root")


def check_git_clean(repo: Path) -> PrivatePreflightCheck:
    code, stdout, stderr = _git(repo, ["status", "--short"])
    if code != 0:
        return PrivatePreflightCheck("git_clean", "NO_GO", stderr or stdout or "git status failed")
    if stdout:
        return PrivatePreflightCheck("git_clean", "NO_GO", "git worktree is not clean")
    return PrivatePreflightCheck("git_clean", "PASS", "git worktree is clean")


def check_git_tagged_head(repo: Path) -> PrivatePreflightCheck:
    code, stdout, stderr = _git(repo, ["tag", "--points-at", "HEAD"])
    if code != 0:
        return PrivatePreflightCheck("git_tagged_head", "NO_GO", stderr or stdout or "git tag failed")
    tags = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not tags:
        return PrivatePreflightCheck("git_tagged_head", "NO_GO", "HEAD has no version tag")
    return PrivatePreflightCheck("git_tagged_head", "PASS", ", ".join(tags))


def check_ubuntu22_phase(repo: Path) -> PrivatePreflightCheck:
    audit_module = _load_ubuntu22_audit()
    report = audit_module.audit(repo)
    if report["overall"] != "PASS":
        no_go = [check["check_id"] for check in report["checks"] if check["status"] != "PASS"]
        return PrivatePreflightCheck("ubuntu22_phase", "NO_GO", "NO_GO checks: " + ", ".join(no_go))
    return PrivatePreflightCheck("ubuntu22_phase", "PASS", "Ubuntu 22.04 phase audit is PASS")


def _service_block(compose: str, service_name: str) -> str:
    match = re.search(rf"(?m)^  {re.escape(service_name)}:\s*$", compose)
    if not match:
        return ""
    start = match.start()
    rest = compose[match.end() :]
    next_service = re.search(r"(?m)^  [a-zA-Z0-9_-]+:\s*$", rest)
    end = match.end() + next_service.start() if next_service else len(compose)
    return compose[start:end]


def check_private_compose_contract(repo: Path) -> PrivatePreflightCheck:
    compose_path = repo / "openclaw-video" / "docker-compose.openclaw-video.yaml"
    if not compose_path.exists():
        return PrivatePreflightCheck("private_compose_contract", "NO_GO", f"missing {compose_path}")
    compose = compose_path.read_text(encoding="utf-8")
    gateway_config_path = repo / "openclaw-video" / "openclaw" / "config" / "config.yaml"
    if not gateway_config_path.exists():
        return PrivatePreflightCheck("private_compose_contract", "NO_GO", f"missing {gateway_config_path}")
    gateway_config = gateway_config_path.read_text(encoding="utf-8")

    forbidden = [
        "0.0.0.0:18181",
        "0.0.0.0:18789",
        "0.0.0.0:5432",
        "0.0.0.0:6379",
        "/var/run/docker.sock",
        "OPENCLAW_GATEWAY_TOKEN:",
        "ARK_API_KEY:",
        "MEDIAKIT_API_KEY:",
    ]
    found = [item for item in forbidden if item in compose]
    if found:
        return PrivatePreflightCheck(
            "private_compose_contract",
            "NO_GO",
            "compose exposes forbidden private deployment surfaces: " + ", ".join(found),
        )

    forbidden_config = [
        "dangerouslyAllowHostHeaderOriginFallback",
        "dangerouslyDisableDeviceAuth",
        "allowInsecureAuth",
        'allowedOrigins: ["*"]',
        "token:",
        "password:",
    ]
    found_config = [item for item in forbidden_config if item in gateway_config]
    if found_config:
        return PrivatePreflightCheck(
            "private_compose_contract",
            "NO_GO",
            "gateway config contains forbidden private deployment settings: " + ", ".join(found_config),
        )

    required_config = [
        'mode: "local"',
        'bind: "lan"',
        'port: 18789',
        'mode: "token"',
        'controlUi:',
        'enabled: false',
    ]
    missing_config = [item for item in required_config if item not in gateway_config]
    if missing_config:
        return PrivatePreflightCheck(
            "private_compose_contract",
            "NO_GO",
            "gateway config missing private deployment markers: " + ", ".join(missing_config),
        )

    required = [
        'name: openclaw-video',
        '127.0.0.1:18181:3000',
        'OPENCLAW_GATEWAY_URL: ws://openclaw-gateway:18789',
        'OPENCLAW_GATEWAY_TOKEN_FILE: /run/secrets/openclaw_gateway_token',
        'OPENCLAW_GATEWAY_DEVICE_KEY_FILE: /run/secrets/openclaw_bridge_device_key.pem',
        'DOUYIN_CHONG_ENV_FILE: /run/secrets/douyin_chong_env',
        'WORKER_CONCURRENCY: "1"',
        'image: postgres:15-alpine',
        'name: ${DIFY_DOCKER_NETWORK:-docker_default}',
        '../artifacts/knowledge-base-short-video/2026.06.06:/knowledge/short-video:ro',
    ]
    missing = [item for item in required if item not in compose]
    if missing:
        return PrivatePreflightCheck(
            "private_compose_contract",
            "NO_GO",
            "compose missing private deployment markers: " + ", ".join(missing),
        )

    bridge = _service_block(compose, "openclaw-bridge")
    gateway = _service_block(compose, "openclaw-gateway")
    worker = _service_block(compose, "video-analysis-worker")
    postgres = _service_block(compose, "bridge-postgres")
    if "- dify-default" not in bridge:
        return PrivatePreflightCheck("private_compose_contract", "NO_GO", "bridge must join Dify network")
    for name, block in {
        "openclaw-gateway": gateway,
        "video-analysis-worker": worker,
        "bridge-postgres": postgres,
    }.items():
        if "- dify-default" in block:
            return PrivatePreflightCheck("private_compose_contract", "NO_GO", f"{name} must not join Dify network")
    if 'ports: []' not in gateway or 'ports: []' not in postgres:
        return PrivatePreflightCheck(
            "private_compose_contract",
            "NO_GO",
            "gateway and postgres must not publish host ports",
        )

    return PrivatePreflightCheck(
        "private_compose_contract",
        "PASS",
        "compose is private sidecar only and binds bridge to 127.0.0.1:18181",
    )


def check_public_route_absent(repo: Path) -> PrivatePreflightCheck:
    route_map = repo / "openresty-route-map-redacted.md"
    if not route_map.exists():
        return PrivatePreflightCheck("public_route_absent", "NO_GO", f"missing {route_map.name}")
    text = route_map.read_text(encoding="utf-8").lower()
    if "no openclaw route present" not in text:
        return PrivatePreflightCheck("public_route_absent", "NO_GO", "OpenClaw public route is not proven absent")
    return PrivatePreflightCheck("public_route_absent", "PASS", "no OpenClaw public route is present")


def preflight(repo: Path, target_host: str) -> dict:
    checks = [
        check_target_host(target_host),
        check_git_clean(repo),
        check_git_tagged_head(repo),
        check_ubuntu22_phase(repo),
        check_private_compose_contract(repo),
        check_public_route_absent(repo),
    ]
    overall = "GO" if all(check.status == "PASS" for check in checks) else "NO_GO"
    return {
        "schema_version": "openclaw-root-private-sidecar-preflight.v1",
        "target_host": target_host,
        "scope": "private-sidecar-no-public-route",
        "overall": overall,
        "checks": [asdict(check) for check in checks],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed preflight before deploying the private OpenClaw sidecar to root."
    )
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
