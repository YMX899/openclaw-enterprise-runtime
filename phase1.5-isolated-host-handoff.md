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

SSH non-production host refresh on 2026-06-06 after tag
`douyin-real-sample-promotion-gate-20260606`:

```text
ubuntu22.04: timed out
myproj: timed out
xcp: timed out
linaro: timed out
run: reachable, Darwin 25.2.0 arm64, no Docker Engine evidence returned
xiaojianping: reachable, Darwin 25.2.0 arm64, no Docker Engine evidence returned
```

Result: no eligible non-production Linux Docker host is currently available
through the configured SSH aliases.

SSH readiness refresh on 2026-06-06 for user-selected host `ubuntu22.04`:

```text
host: xiejuyang-virtual-machine
os: Linux 6.8.0-111-generic x86_64
python3: Python 3.10.12
node: v24.14.1
docker client: Docker Engine - Community 29.4.0
docker compose: Docker Compose version v5.1.3
disk: 50.6GiB free
memory: 15.6GiB total
docker service: active and enabled
current ssh user: xiejuyang
current user docker socket access: NO_GO, permission denied for /var/run/docker.sock
sudo docker: NO_GO, sudo requires password / terminal
```

Result: `ubuntu22.04` is a good non-production Linux x86_64 candidate, but it
cannot run Phase 1.5 Docker gates until Docker access is configured for the SSH
operator, for example by using a docker-group user or non-interactive sudo. No
Docker group change, sudo password entry, service restart, package install or
compose command was performed by Codex.

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

Run the read-only readiness check before copying secrets or running any build:

```bash
python scripts/check_phase1_5_host_readiness.py --fail-on-no-go
```

If the isolated test operator is allowed to use passwordless sudo for Docker,
use an explicit Docker command prefix:

```bash
python scripts/check_phase1_5_host_readiness.py \
  --use-sudo-docker \
  --fail-on-no-go
```

The readiness check must report:

```text
schema_version: phase1.5-host-readiness.v1
target: isolated_linux_docker_host
overall: PASS
```

It only checks local host capabilities. It does not install Docker, start
containers, write secrets, or approve production.

## Repository State To Test

Use a clean checkout at or after:

```text
tag: douyin-real-sample-promotion-gate-20260606
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

Preferred one-command acceptance runner on the isolated Linux host:

```bash
TARGET_LABEL=ubuntu22.04 \
DOCKER_CMD='docker' \
PYTHON=python3 \
scripts/run_phase1_5_acceptance.sh
```

If Docker is granted only through passwordless non-interactive sudo:

```bash
TARGET_LABEL=ubuntu22.04 \
DOCKER_CMD='sudo -n docker' \
PYTHON=python3 \
scripts/run_phase1_5_acceptance.sh
```

The runner refuses to run on the production `AI-01`/`root` path, checks only
that required non-production secret files exist and are non-empty, runs host
readiness, then runs the full Phase 1.5 gate with compose-up. It does not read
or print secret file contents.

No compose-up build/smoke gate:

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
REQUIRE_DOUYIN_ARTIFACT=1 \
PYTHON=/path/to/python scripts/verify_phase1_5_gates.sh
```

Full isolated sidecar boot gate:

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
REQUIRE_DOUYIN_ARTIFACT=1 \
RUN_COMPOSE_UP=1 \
PYTHON=/path/to/python scripts/verify_phase1_5_gates.sh
```

If the isolated test host grants Docker through passwordless non-interactive
sudo instead of direct docker-group access, run the same gate with an explicit
Docker command prefix:

```bash
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
REQUIRE_DOUYIN_ARTIFACT=1 \
RUN_COMPOSE_UP=1 \
DOCKER_CMD='sudo -n docker' \
PYTHON=/path/to/python scripts/verify_phase1_5_gates.sh
```

The script still fails closed if Docker cannot be reached. It does not prompt
for a sudo password and does not install, enable, restart, or reconfigure
Docker.

When the full isolated sidecar boot gate succeeds, the script automatically
writes:

```text
phase1.5-exit-proof.md
```

The proof is generated only after `docker compose up`, Bridge `healthz`, the
host port exposure check, and `docker compose down --remove-orphans` all
succeed. It is not generated when `SKIP_DOCKER=1`, when `RUN_COMPOSE_UP=0`, or
when either `REQUIRE_OPENCLAW_SECURITY_APPROVAL=1` or
`REQUIRE_DOUYIN_ARTIFACT=1` is missing.

The full script must prove:

```text
clean git rollback anchor
Python dependency gate
103 unit tests or more
vendored douyin_chong SOURCE_SHA256SUMS gate
Node syntax gate
static compose safety gates
real douyin_chong artifact and REAL_SAMPLE_EVIDENCE.json verified
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
generated phase1.5-exit-proof.md
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

## Real Sample Evidence Promotion

After a real sample run succeeds, first inspect only the sanitized summary under
`tmp/`. Do not commit raw result JSON, raw URLs, secret env files, stdout/stderr
contents, cookies, headers, browser state or full model output.

Validate without writing:

```bash
PYTHON=/path/to/python
$PYTHON scripts/promote_douyin_real_sample_evidence.py \
  --source tmp/douyin-real-samples/<run-id>/sanitized-run.json \
  --dry-run
```

Promote only the sanitized evidence:

```bash
$PYTHON scripts/promote_douyin_real_sample_evidence.py \
  --source tmp/douyin-real-samples/<run-id>/sanitized-run.json
```

The promotion script writes:

```text
artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json
```

It fails closed if the sample did not succeed, if the explicit runtime env file
was missing, if stdout/stderr contents were recorded, if a raw URL is present,
or if the schema/hash evidence is missing. The generated file is still only one
gate input; it does not approve production by itself.
