#!/usr/bin/env bash
set -euo pipefail

compose_file="${COMPOSE_FILE:-openclaw-video/docker-compose.openclaw-video.yaml}"
python_cmd="${PYTHON:-python}"
skip_docker="${SKIP_DOCKER:-0}"
run_compose_up="${RUN_COMPOSE_UP:-0}"
require_douyin_artifact="${REQUIRE_DOUYIN_ARTIFACT:-0}"
allow_dirty="${ALLOW_DIRTY:-0}"

step() {
  printf '==> %s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

cd "$(dirname "$0")/.."

step "git rollback anchor"
if [[ "$allow_dirty" != "1" ]] && [[ -n "$(git status --short)" ]]; then
  fail "git worktree is not clean; commit or discard unrelated changes before Phase 1.5 exit."
fi
git rev-parse HEAD
git tag --points-at HEAD
printf 'PYTHON=%s\n' "$python_cmd"

step "Python dependency gate"
"$python_cmd" -c 'import cryptography, fastapi, httpx, jsonschema, psycopg, pydantic, websockets; from psycopg.types.json import Jsonb'

step "Python tests"
export PYTHONPATH="openclaw-video/src"
"$python_cmd" -m unittest discover openclaw-video/tests -v
"$python_cmd" -m compileall openclaw-video/src openclaw-video/tests

step "Node syntax"
node --check scripts/verify_openclaw_gateway_ws_contract.mjs

step "static phase gates"
"$python_cmd" - <<'PY'
from pathlib import Path

compose = Path("openclaw-video/docker-compose.openclaw-video.yaml").read_text(encoding="utf-8")
required = [
    "127.0.0.1:18181:3000",
    "OPENCLAW_GATEWAY_URL: ws://openclaw-gateway:18789",
    "OPENCLAW_GATEWAY_TOKEN_FILE: /run/secrets/openclaw_gateway_token",
    "OPENCLAW_GATEWAY_DEVICE_KEY_FILE: /run/secrets/openclaw_bridge_device_key.pem",
    'WORKER_CONCURRENCY: "1"',
    'MAX_DOWNLOAD_BYTES: "536870912"',
    'MAX_VIDEO_DURATION_SECONDS: "60"',
    'MAX_VIDEO_FRAMES: "1200"',
    "./vendor/douyin_chong:/opt/douyin_chong:ro",
    "read_only: true",
    "/tmp:size=1024m,nosuid,nodev",
    "pids_limit: 128",
]
for needle in required:
    if needle not in compose:
        raise SystemExit(f"missing compose gate: {needle}")
for forbidden in [
    "0.0.0.0:18789",
    "0.0.0.0:5432",
    "/var/run/docker.sock",
    "OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN",
    "OPENCLAW_GATEWAY_TOKEN:",
    "internal: true",
]:
    if forbidden in compose:
        raise SystemExit(f"forbidden compose surface: {forbidden}")

manifest = Path("artifacts/douyin_chong/ARTIFACT_MANIFEST.md").read_text(encoding="utf-8")
if "Status: missing" in manifest:
    print("douyin_chong artifact gate: MISSING")
else:
    print("douyin_chong artifact gate: present")
PY

if [[ "$require_douyin_artifact" == "1" ]] && grep -q 'Status: missing' artifacts/douyin_chong/ARTIFACT_MANIFEST.md; then
  fail "REQUIRE_DOUYIN_ARTIFACT=1 but douyin_chong artifact is still missing."
fi

if [[ "$skip_docker" == "1" ]]; then
  printf 'Docker gates skipped by operator request. This is not a Phase 1.5 exit proof.\n'
  exit 0
fi

step "Docker availability"
command -v docker >/dev/null 2>&1 || fail "docker command is unavailable. Phase 1.5 cannot exit and production Phase 2 remains NO-GO."

step "compose render"
rendered="${TMPDIR:-/tmp}/openclaw-video-compose.phase1_5.rendered.yaml"
docker compose -f "$compose_file" config >"$rendered"
if grep -E '0\.0\.0\.0:18789|0\.0\.0\.0:5432|/var/run/docker\.sock|internal: true|--token' "$rendered"; then
  fail "compose render exposes forbidden Gateway/Postgres/Docker socket/token surface"
fi
grep -q '127.0.0.1:18181:3000' "$rendered"
grep -q 'ws://openclaw-gateway:18789' "$rendered"

step "compose build"
docker compose -f "$compose_file" build --no-cache

if [[ "$run_compose_up" == "1" ]]; then
  step "compose up isolated sidecar"
  docker compose -f "$compose_file" up -d
  docker compose -f "$compose_file" ps

  step "localhost health"
  curl -fsS http://127.0.0.1:18181/healthz >/dev/null

  step "port exposure check"
  if ss -lntp | grep -E '0\.0\.0\.0:18181|0\.0\.0\.0:18789|0\.0\.0\.0:5432'; then
    fail "forbidden public listener detected"
  fi
else
  printf 'Compose up skipped. Use RUN_COMPOSE_UP=1 only in an isolated Docker/Linux validation host.\n'
fi

printf 'Phase 1.5 gate checks completed for this environment.\n'
