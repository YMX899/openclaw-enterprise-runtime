# Phase 1.5 Isolated Host Handoff

Status: required before production Phase 2. This is a handoff/runbook for a
non-production Linux Docker host. Do not run this gate on the production Dify
server `AI-01`.

## Why This Exists

Local workstation status:

```text
Docker CLI: unavailable
Phase 1.5 local gate: passes only with -SkipDocker
Phase 1.5 exit proof: not available locally
```

SSH non-production host probe on 2026-06-06:

```text
ubuntu22.04: connection timeout
myproj: connection timeout
ubuntu: invalid alias, missing password/key_file
prod-web-01: invalid alias, missing password/key_file
```

Production Dify host `root` / `AI-01` is intentionally excluded from this gate
because Phase 1.5 must be isolated from Dify.

## Required Host

```text
OS: Linux x86_64
Docker: installed and running
Docker Compose: v2 plugin installed
Network: can pull base images and Python/npm dependencies
Ports: 18181, 18789, 5432 free on the host
Disk: at least 20G free
Memory: at least 8G preferred
```

The host must not run production Dify containers. It may be disposable.

## Repository State To Test

Use a clean checkout at or after:

```text
commit: 937ce36
tag: phase1-5-docker-gates-loader-smoke
```

The test must run from a clean worktree:

```bash
git status --short
git tag --points-at HEAD
```

The gate uses `PYTHON` and `NODE` from the environment. On a normal Linux host
`NODE` can be omitted if `node` is in `PATH`.

## Secret Files For Build/Smoke

The Docker build and no-up smoke gate need secret files to exist because compose
declares read-only mounts. Use non-production dummy values unless explicitly
running a real model-backed video sample.

Create only on the isolated host:

```bash
mkdir -p openclaw-video/secrets
printf 'dummy-gateway-token\n' > openclaw-video/secrets/openclaw_gateway_token
openssl genpkey -algorithm ED25519 -out openclaw-video/secrets/openclaw_bridge_device_key.pem
cat > openclaw-video/secrets/douyin_chong.env <<'EOF'
ARK_API_KEY=dummy-not-production
MODEL=doubao-seed-2-0-pro
EOF
chmod 600 openclaw-video/secrets/*
```

Do not commit or upload these files. They are ignored by git.

## Required Commands

No compose-up build/smoke gate:

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
PYTHON=/path/to/python scripts/verify_phase1_5_gates.sh
```

Full isolated sidecar boot gate:

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
RUN_COMPOSE_UP=1 \
PYTHON=/path/to/python scripts/verify_phase1_5_gates.sh
```

The full script must prove:

```text
clean git rollback anchor
Python dependency gate
92 unit tests
vendored douyin_chong SOURCE_SHA256SUMS gate
Node syntax gate
static compose safety gates
OpenClaw 2026.3.13 security decision approved, not rejected/unapproved
docker compose config render
docker compose build --no-cache
worker image smoke:
  openclaw-douyin-adapter --help
  adapter loader imports vendored AppConfig/ArkVideoClient/UniversalVideoResolver
optional compose up:
  Bridge health at http://127.0.0.1:18181/healthz
  no 0.0.0.0 listener for 18181, 18789, 5432
  docker compose down --remove-orphans cleanup
```

## Not Sufficient For Production

Passing this gate still does not approve production Phase 2 unless the following
are also completed:

```text
real model-backed single-video sample through openclaw-douyin-adapter
result JSON schema evidence
worker timeout and cleanup evidence
resource profile: CPU, memory, disk, duration
OpenClaw 2026.3.13 security/audit decision
authenticated real-browser Dify baseline
server rollback runbook for future sidecar deployment
```

## Evidence To Bring Back

Capture:

```text
host name and date
docker version
docker compose version
git commit and tag
full command line used
summary of successful gates
docker compose ps output if RUN_COMPOSE_UP=1
ss -lntp filtered output for 18181/18789/5432
worker image id/digest if available
```

Do not capture or share:

```text
real API keys
cookies
CSRF tokens
authorization headers
full .env files
TLS private keys
OpenClaw gateway tokens
```
