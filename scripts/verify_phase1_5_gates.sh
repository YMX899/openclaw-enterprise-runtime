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
"$python_cmd" -c 'import cryptography, fastapi, httpx, jsonschema, psycopg, pydantic, requests, websockets; import volcenginesdkarkruntime; from psycopg.types.json import Jsonb'

step "Python tests"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="openclaw-video/src"
"$python_cmd" -m unittest discover openclaw-video/tests -v
"$python_cmd" -m compileall openclaw-video/src openclaw-video/tests

step "vendored douyin_chong source gate"
"$python_cmd" - <<'PY'
from hashlib import sha256
from pathlib import Path

vendor = Path("openclaw-video/vendor/douyin_chong")
hashes = vendor / "SOURCE_SHA256SUMS"
expected_files = {
    "__init__.py",
    "clients/__init__.py",
    "clients/ark_video.py",
    "clients/douyin.py",
    "clients/resolver.py",
    "clients/tiktok.py",
    "config.py",
    "models.py",
    "README.md",
}
entries = {}
for line in hashes.read_text(encoding="utf-8").splitlines():
    digest, relative = line.split("  ", 1)
    entries[relative] = digest
if set(entries) != expected_files:
    raise SystemExit(f"vendor hash manifest mismatch: {sorted(set(entries) ^ expected_files)}")
for relative, expected_digest in entries.items():
    actual = sha256((vendor / relative).read_bytes()).hexdigest()
    if actual != expected_digest:
        raise SystemExit(f"vendor source digest mismatch: {relative}")
for forbidden in [".env", ".env.local", ".douyin_storage_state.json", "douyin_login_state.py", "profile_batch_fashion.py"]:
    if (vendor / forbidden).exists():
        raise SystemExit(f"forbidden vendor file present: {forbidden}")
for path in vendor.rglob("*"):
    text = str(path).lower()
    if "__pycache__" in text or path.suffix in {".pyc", ".log", ".json"} or "storage" in text or "cookie" in text:
        raise SystemExit(f"forbidden vendor runtime artifact present: {path}")
print("vendor source gate: OK")
PY

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
    "DOUYIN_CHONG_BIN: /usr/local/bin/openclaw-douyin-adapter",
    "DOUYIN_CHONG_ENV_FILE: /run/secrets/douyin_chong_env",
    "./secrets/douyin_chong.env:/run/secrets/douyin_chong_env:ro",
    "./vendor/douyin_chong:/app/vendor/douyin_chong:ro",
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
elif "Status: verified" in manifest:
    print("douyin_chong artifact gate: VERIFIED")
elif "Status: minimal candidate source vendored" in manifest:
    print("douyin_chong artifact gate: MINIMAL_SOURCE_NOT_MODEL_VERIFIED")
else:
    print("douyin_chong artifact gate: CANDIDATE_NOT_VERIFIED")
PY

if [[ "$require_douyin_artifact" == "1" ]] && ! grep -q 'Status: verified' artifacts/douyin_chong/ARTIFACT_MANIFEST.md; then
  fail "REQUIRE_DOUYIN_ARTIFACT=1 but douyin_chong artifact is not verified."
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

step "worker image smoke"
worker_image="$(docker compose -f "$compose_file" images -q video-analysis-worker)"
if [[ -z "$worker_image" ]]; then
  fail "could not resolve built video-analysis-worker image id"
fi
docker run --rm "$worker_image" openclaw-douyin-adapter --help >/dev/null
docker run --rm "$worker_image" python -c 'from openclaw_video.douyin_legacy_adapter import _load_legacy_components; print([component.__name__ for component in _load_legacy_components()])'

if [[ "$run_compose_up" == "1" ]]; then
  step "compose up isolated sidecar"
  cleanup() {
    docker compose -f "$compose_file" down --remove-orphans
  }
  trap cleanup EXIT
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
