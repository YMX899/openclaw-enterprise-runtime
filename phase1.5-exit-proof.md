# Phase 1.5 Exit Proof

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
host_name: xiejuyang-virtual-machine
host_date: 2026-06-06T19:09:46+08:00
docker version: Docker server=29.4.0
docker compose version: Docker Compose version v5.1.3
docker_command: docker
git_commit: e63b9229cbf59578aa439e513f3a910bc72512c5
git_tags: phase1-5-bridge-healthz-20260606
operator: xiejuyang
reviewer: separate-production-go-no-go-review-required
```

## Command Line Used

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
REQUIRE_DOUYIN_ARTIFACT=1 \
RUN_COMPOSE_UP=1 \
SKIP_DOCKER=0 \
PYTHON=/tmp/openclaw-dify-phase1.5-e63b922/.phase1.5-venv/bin/python \
NODE=node \
DOCKER_CMD=docker \
scripts/verify_phase1_5_gates.sh
```

## Successful Gate Evidence

```text
compose_file: openclaw-video/docker-compose.openclaw-video.yaml
docker version command: docker version --format 'Docker server={{.Server.Version}}'
docker compose version command: docker compose version
Python dependency gate: PASS
Python unittest: PASS
Python compileall: PASS
vendored douyin_chong source gate: PASS
douyin_chong artifact gate: VERIFIED
video link-read mode gate: ADOPTED
OpenClaw 2026.3.13 security gate: APPROVED
docker compose config: PASS
docker compose build --no-cache: PASS
worker image smoke: PASS
worker image: sha256:f317f6077422536a7acdf8cf88e3352203dbff528e02ef8a41082808905b0fbf
docker compose up -d: PASS
Bridge healthz at http://127.0.0.1:18181/healthz: PASS
port exposure check: PASS, no 0.0.0.0 listener for 18181/18789/5432
docker compose down --remove-orphans --volumes: PASS
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
Douyin browser login state: not collected
```

## Final Decision

Phase 1.5 isolated Docker proof is PASS for this repository state. Production
Phase 2 still requires the separate production readiness audit, route rollback
plan, and explicit Go/No-Go review.
