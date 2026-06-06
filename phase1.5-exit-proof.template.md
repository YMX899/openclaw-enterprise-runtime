# Phase 1.5 Exit Proof Template

status: TEMPLATE_PENDING
source: isolated-linux-docker-host
production_host: NO
host_os: Linux
SKIP_DOCKER=0

Do not rename this template to `phase1.5-exit-proof.md` until every command
below has actually succeeded on a non-production Linux Docker host. The
production Dify host `AI-01` must not be used for this proof.

## Identity

```text
host_name: <non-production-hostname>
host_date: <ISO-8601 timestamp>
docker_version: <docker version output>
docker_compose_version: <docker compose version output>
git_commit: <commit sha>
git_tags: <tags at commit>
operator: <person or process>
reviewer: <person>
```

## Command Line Used

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
REQUIRE_DOUYIN_ARTIFACT=1 \
RUN_COMPOSE_UP=1 \
PYTHON=/path/to/python \
scripts/verify_phase1_5_gates.sh
```

## Required Successful Markers

The final `phase1.5-exit-proof.md` must contain exact evidence for all of these
markers:

```text
status: PASS
source: isolated-linux-docker-host
production_host: NO
host_os: Linux
SKIP_DOCKER=0
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1
REQUIRE_DOUYIN_ARTIFACT=1
RUN_COMPOSE_UP=1
scripts/verify_phase1_5_gates.sh
docker version
docker compose version
docker compose config
docker compose build
docker compose up
healthz
port exposure check
127.0.0.1:18181
docker compose down --remove-orphans --volumes
no 0.0.0.0 listener
worker image
```

## Evidence Summary

```text
Python dependency gate: PASS
Python unittest: PASS
Python compileall: PASS
vendored douyin_chong source gate: PASS
douyin_chong artifact gate: VERIFIED
douyin real sample gate: VERIFIED
OpenClaw 2026.3.13 security gate: APPROVED
docker compose config: PASS
docker compose build: PASS
worker image smoke: PASS
docker compose up: PASS
Bridge healthz at http://127.0.0.1:18181/healthz: PASS
port exposure check: PASS, no 0.0.0.0 listener for 18181/18789/5432
docker compose down --remove-orphans --volumes: PASS
```

## Sanitization

Do not include:

```text
real API keys
cookies
CSRF tokens
authorization headers
full .env files
TLS private keys
OpenClaw gateway token values
raw Douyin sample URL
raw model output
full stdout/stderr if it contains sensitive values
```

## Final Decision

Only after replacing all placeholders with real evidence and setting
`status: PASS` may this file be copied to:

```text
phase1.5-exit-proof.md
```

Passing Phase 1.5 still does not deploy production. It only permits the next
production Go/No-Go review.
