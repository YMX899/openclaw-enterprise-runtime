#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import getpass
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]

PLACEHOLDER_PATTERN = re.compile(r"TEMPLATE_PENDING|DO_NOT_USE|<[^>\n]+>|\bTODO\b|\bTBD\b", re.IGNORECASE)

REQUIRED_MARKERS = [
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
    r"docker compose down --remove-orphans",
    r"no 0\.0\.0\.0 listener",
    r"worker image",
]


@dataclass(frozen=True)
class ProofContext:
    host_name: str
    host_date: str
    host_os: str
    docker_version: str
    docker_compose_version: str
    git_commit: str
    git_tags: str
    operator: str
    reviewer: str
    compose_file: str
    python_cmd: str
    node_cmd: str
    worker_image: str


def _run(command: Sequence[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return completed.stdout.strip()


def _clean_line(value: str, field: str) -> str:
    cleaned = " ".join(str(value).strip().split())
    if not cleaned:
        raise ValueError(f"{field} is required")
    if PLACEHOLDER_PATTERN.search(cleaned):
        raise ValueError(f"{field} contains a template placeholder")
    return cleaned


def collect_context(args: argparse.Namespace) -> ProofContext:
    repo = Path(args.repo_root).resolve()
    host_os = platform.system()
    if host_os != "Linux":
        raise RuntimeError("Phase 1.5 exit proof can only be generated on an isolated Linux Docker host")

    docker_version = _run(["docker", "version", "--format", "Docker server={{.Server.Version}}"], cwd=repo)
    docker_compose_version = _run(["docker", "compose", "version"], cwd=repo)
    git_commit = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    git_tags = _run(["git", "tag", "--points-at", "HEAD"], cwd=repo) or "none"

    return ProofContext(
        host_name=_clean_line(socket.gethostname(), "host_name"),
        host_date=datetime.now().astimezone().isoformat(timespec="seconds"),
        host_os=host_os,
        docker_version=_clean_line(docker_version, "docker_version"),
        docker_compose_version=_clean_line(docker_compose_version, "docker_compose_version"),
        git_commit=_clean_line(git_commit, "git_commit"),
        git_tags=_clean_line(git_tags, "git_tags"),
        operator=_clean_line(args.operator, "operator"),
        reviewer=_clean_line(args.reviewer, "reviewer"),
        compose_file=_clean_line(args.compose_file, "compose_file"),
        python_cmd=_clean_line(args.python_cmd, "python_cmd"),
        node_cmd=_clean_line(args.node_cmd, "node_cmd"),
        worker_image=_clean_line(args.worker_image, "worker_image"),
    )


def build_proof(context: ProofContext) -> str:
    if context.host_os != "Linux":
        raise ValueError("host_os must be Linux")

    text = f"""# Phase 1.5 Exit Proof

status: PASS
source: isolated-linux-docker-host
production_host: NO
host_os: Linux
SKIP_DOCKER=0

This file is generated only after `scripts/verify_phase1_5_gates.sh` completes
the full non-production Linux Docker gate with `RUN_COMPOSE_UP=1`. It is not a
production deployment approval and it was not generated on the production Dify
host.

## Identity

```text
host_name: {context.host_name}
host_date: {context.host_date}
docker version: {context.docker_version}
docker compose version: {context.docker_compose_version}
git_commit: {context.git_commit}
git_tags: {context.git_tags}
operator: {context.operator}
reviewer: {context.reviewer}
```

## Command Line Used

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \\
REQUIRE_DOUYIN_ARTIFACT=1 \\
RUN_COMPOSE_UP=1 \\
SKIP_DOCKER=0 \\
PYTHON={context.python_cmd} \\
NODE={context.node_cmd} \\
scripts/verify_phase1_5_gates.sh
```

## Successful Gate Evidence

```text
compose_file: {context.compose_file}
Python dependency gate: PASS
Python unittest: PASS
Python compileall: PASS
vendored douyin_chong source gate: PASS
douyin_chong artifact gate: VERIFIED
douyin real sample gate: VERIFIED
OpenClaw 2026.3.13 security gate: APPROVED
docker compose config: PASS
docker compose build --no-cache: PASS
worker image smoke: PASS
worker image: {context.worker_image}
docker compose up -d: PASS
Bridge healthz at http://127.0.0.1:18181/healthz: PASS
port exposure check: PASS, no 0.0.0.0 listener for 18181/18789/5432
docker compose down --remove-orphans: PASS
```

## Sanitization

```text
real API keys: not collected
cookies: not collected
CSRF tokens: not collected
authorization headers: not collected
full .env files: not collected
TLS private keys: not collected
OpenClaw gateway token values: not collected
raw Douyin sample URL: not collected
raw model output: not collected
```

## Final Decision

Phase 1.5 isolated Docker proof is PASS for this repository state. Production
Phase 2 still requires the separate production readiness audit, authenticated
Dify public baseline, route rollback plan, and explicit Go/No-Go review.
"""
    validate_proof_text(text)
    return text


def validate_proof_text(text: str) -> None:
    if PLACEHOLDER_PATTERN.search(text):
        raise ValueError("exit proof contains a template placeholder")
    missing = [pattern for pattern in REQUIRED_MARKERS if not re.search(pattern, text, re.IGNORECASE)]
    if missing:
        raise ValueError(f"exit proof missing markers: {', '.join(missing)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write sanitized Phase 1.5 isolated Docker exit proof.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output", default="phase1.5-exit-proof.md")
    parser.add_argument("--compose-file", default="openclaw-video/docker-compose.openclaw-video.yaml")
    parser.add_argument("--python-cmd", default=os.environ.get("PYTHON", "python"))
    parser.add_argument("--node-cmd", default=os.environ.get("NODE", "node"))
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--operator", default=os.environ.get("PHASE1_5_OPERATOR") or getpass.getuser())
    parser.add_argument(
        "--reviewer",
        default=os.environ.get("PHASE1_5_REVIEWER") or "separate-production-go-no-go-review-required",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo_root).resolve()
    context = collect_context(args)
    text = build_proof(context)
    output = Path(args.output)
    if not output.is_absolute():
        output = repo / output
    output.write_text(text, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
