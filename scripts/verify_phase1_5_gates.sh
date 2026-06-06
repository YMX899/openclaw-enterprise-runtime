#!/usr/bin/env bash
set -euo pipefail

compose_file="${COMPOSE_FILE:-openclaw-video/docker-compose.openclaw-video.yaml}"
python_cmd="${PYTHON:-python}"
node_cmd="${NODE:-node}"
docker_cmd="${DOCKER_CMD:-docker}"
skip_docker="${SKIP_DOCKER:-0}"
run_compose_up="${RUN_COMPOSE_UP:-0}"
require_douyin_artifact="${REQUIRE_DOUYIN_ARTIFACT:-0}"
require_openclaw_security_approval="${REQUIRE_OPENCLAW_SECURITY_APPROVAL:-0}"
allow_douyin_sample_deferred="${ALLOW_DOUYIN_SAMPLE_DEFERRED:-0}"
allow_dirty="${ALLOW_DIRTY:-0}"

step() {
  printf '==> %s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

print_version_anchor() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ "$allow_dirty" != "1" ]] && [[ -n "$(git status --short)" ]]; then
      fail "git worktree is not clean; commit or discard unrelated changes before Phase 1.5 exit."
    fi
    printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
    tags="$(git tag --points-at HEAD | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
    printf 'git_tags=%s\n' "${tags:-none}"
    return
  fi

  if [[ ! -f BUILD_INFO ]]; then
    fail "missing git checkout and BUILD_INFO; cannot establish rollback anchor."
  fi

  commit="$(awk -F': ' '/^git_commit:/ {print $2}' BUILD_INFO | head -n 1)"
  refs="$(sed -n 's/^git_refs: //p' BUILD_INFO | head -n 1)"
  if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    fail "BUILD_INFO does not contain a resolved git commit; rebuild the archive with git archive."
  fi

  tags="$(printf '%s\n' "$refs" | tr ',' '\n' | sed -n 's/^[[:space:]]*tag: //p' | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
  printf 'git_commit=%s\n' "$commit"
  printf 'git_tags=%s\n' "${tags:-none}"
}

cd "$(dirname "$0")/.."

step "git rollback anchor"
print_version_anchor
printf 'PYTHON=%s\n' "$python_cmd"
printf 'NODE=%s\n' "$node_cmd"
printf 'DOCKER_CMD=%s\n' "$docker_cmd"

read -r -a docker_cmd_parts <<<"$docker_cmd"
if [[ "${#docker_cmd_parts[@]}" -eq 0 ]]; then
  fail "DOCKER_CMD must not be empty."
fi

step "Python dependency gate"
"$python_cmd" -B -c 'import cryptography, fastapi, httpx, jsonschema, psycopg, pydantic, requests, websockets; import volcenginesdkarkruntime; from psycopg.types.json import Jsonb'

step "Python tests"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="openclaw-video/src"
env -u ALLOW_DOUYIN_SAMPLE_DEFERRED "$python_cmd" -B -m unittest discover openclaw-video/tests -v
"$python_cmd" -B -m compileall openclaw-video/src openclaw-video/tests

step "vendored douyin_chong source gate"
"$python_cmd" -B - <<'PY'
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
"$node_cmd" --check scripts/verify_openclaw_gateway_ws_contract.mjs

step "static phase gates"
"$python_cmd" -B - <<'PY'
import json
from pathlib import Path
import re


def is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
    'cpus: "1.00"',
    "mem_limit: 1024M",
    "mem_reservation: 256M",
    "pids_limit: 128",
    "name: ${DIFY_DOCKER_NETWORK:-docker_default}",
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

sample = Path("artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json")
if not sample.exists():
    print("douyin real sample gate: MISSING")
else:
    evidence = json.loads(sample.read_text(encoding="utf-8"))
    if evidence.get("schema_version") != "douyin-real-sample-evidence.v1":
        raise SystemExit("unexpected real sample evidence schema version")
    if evidence.get("status") != "succeeded":
        raise SystemExit("real sample did not succeed")
    if evidence.get("secret_file_contents_recorded") is not False:
        raise SystemExit("real sample evidence may record secret file contents")
    if evidence.get("env_file_present") is not True:
        raise SystemExit("real sample did not use an explicit runtime env file")
    if not is_sha256(evidence.get("input_url_sha256")):
        raise SystemExit("real sample evidence is missing input URL hash")
    if "https://" in json_text(evidence):
        raise SystemExit("real sample evidence contains a raw URL")
    process = evidence.get("process") or {}
    if process.get("returncode") != 0:
        raise SystemExit("real sample adapter return code was not zero")
    if not isinstance(process.get("elapsed_seconds"), (int, float)) or process["elapsed_seconds"] <= 0:
        raise SystemExit("real sample elapsed time is missing")
    if process.get("stdout_recorded") is not False or process.get("stderr_recorded") is not False:
        raise SystemExit("real sample stdout/stderr contents must not be recorded")
    result = evidence.get("result") or {}
    if result.get("schema_version") != "openclaw-video-result.v1":
        raise SystemExit("real sample result schema was not validated")
    if result.get("platform") != "douyin":
        raise SystemExit("real sample platform is not douyin")
    if not is_sha256(result.get("result_json_sha256")):
        raise SystemExit("real sample result hash is missing")
    if not isinstance(result.get("result_json_bytes"), int) or result["result_json_bytes"] <= 0:
        raise SystemExit("real sample result size is missing")
    print("douyin real sample gate: VERIFIED")
PY

step "OpenClaw 2026.3.13 security decision"
"$python_cmd" -B - <<'PY'
from pathlib import Path

decision = Path("artifacts/openclaw-2026.3.13/SECURITY_DECISION.md").read_text(encoding="utf-8").lower()
if "decision: reject_fixed_version_for_production_currently" in decision:
    print("openclaw security gate: REJECTED_FOR_PRODUCTION")
elif "decision: approve_exception" in decision or "decision: vendor_patch" in decision or "decision: upgrade_strategy" in decision:
    if "security_owner: not assigned" in decision or "engineering_owner: codex draft" in decision:
        raise SystemExit("openclaw security decision is present but not human-approved")
    print("openclaw security gate: APPROVED")
else:
    raise SystemExit("openclaw security decision is missing or unrecognized")
PY

if [[ "$require_douyin_artifact" == "1" ]] && ! grep -q 'Status: verified' artifacts/douyin_chong/ARTIFACT_MANIFEST.md; then
  fail "REQUIRE_DOUYIN_ARTIFACT=1 but douyin_chong artifact is not verified."
fi

if [[ "$require_douyin_artifact" == "1" && ! -f artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json && "$allow_douyin_sample_deferred" != "1" ]]; then
  fail "REQUIRE_DOUYIN_ARTIFACT=1 but REAL_SAMPLE_EVIDENCE.json is missing."
fi

douyin_real_sample_status="VERIFIED"
if [[ "$require_douyin_artifact" == "1" && ! -f artifacts/douyin_chong/REAL_SAMPLE_EVIDENCE.json && "$allow_douyin_sample_deferred" == "1" ]]; then
  printf 'REAL_SAMPLE_EVIDENCE.json deferred by operator. This is not final production evidence.\n'
  douyin_real_sample_status="DEFERRED_BY_OPERATOR_FOR_CURRENT_PHASE"
fi

if [[ "$require_openclaw_security_approval" == "1" ]] && ! grep -Eq 'decision: (approve_exception|vendor_patch|upgrade_strategy)' artifacts/openclaw-2026.3.13/SECURITY_DECISION.md; then
  fail "REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 but OpenClaw 2026.3.13 is not approved for production."
fi

if [[ "$run_compose_up" == "1" && "$require_douyin_artifact" != "1" ]]; then
  fail "RUN_COMPOSE_UP=1 requires REQUIRE_DOUYIN_ARTIFACT=1 for Phase 1.5 exit proof."
fi

if [[ "$run_compose_up" == "1" && "$require_openclaw_security_approval" != "1" ]]; then
  fail "RUN_COMPOSE_UP=1 requires REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 for Phase 1.5 exit proof."
fi

if [[ "$skip_docker" == "1" ]]; then
  printf 'Docker gates skipped by operator request. This is not a Phase 1.5 exit proof.\n'
  exit 0
fi

step "Docker availability"
command -v "${docker_cmd_parts[0]}" >/dev/null 2>&1 || fail "${docker_cmd_parts[0]} command is unavailable. Phase 1.5 cannot exit and production Phase 2 remains NO-GO."
"${docker_cmd_parts[@]}" version --format 'Docker server={{.Server.Version}}' >/dev/null

step "compose render"
rendered="$(mktemp "${TMPDIR:-/tmp}/openclaw-video-compose.phase1_5.XXXXXX.yaml")"
cleanup_rendered() {
  rm -f "$rendered"
}
trap cleanup_rendered EXIT
"${docker_cmd_parts[@]}" compose -f "$compose_file" config --no-interpolate >"$rendered"
if grep -E '0\.0\.0\.0:18789|0\.0\.0\.0:5432|/var/run/docker\.sock|internal: true|--token|phase15-|secret-32bytes|sk-[[:alnum:]_-]+' "$rendered"; then
  fail "compose render exposes forbidden Gateway/Postgres/Docker socket/token/secret surface"
fi
if ! grep -q '127.0.0.1:18181:3000' "$rendered"; then
  grep -q 'host_ip: 127.0.0.1' "$rendered"
  grep -q 'published: "18181"' "$rendered"
  grep -q 'target: 3000' "$rendered"
fi
grep -q 'ws://openclaw-gateway:18789' "$rendered"
cleanup_rendered
trap - EXIT

step "compose build"
"${docker_cmd_parts[@]}" compose -f "$compose_file" build --no-cache

step "worker image smoke"
worker_image="$("${docker_cmd_parts[@]}" compose -f "$compose_file" images -q video-analysis-worker)"
if [[ -z "$worker_image" ]]; then
  worker_image="$("${docker_cmd_parts[@]}" image inspect openclaw-video-video-analysis-worker:latest --format '{{.Id}}' 2>/dev/null || true)"
fi
if [[ -z "$worker_image" ]]; then
  fail "could not resolve built video-analysis-worker image id"
fi
"${docker_cmd_parts[@]}" run --rm "$worker_image" openclaw-douyin-adapter --help >/dev/null
"${docker_cmd_parts[@]}" run --rm "$worker_image" python -c 'from openclaw_video.douyin_legacy_adapter import _load_legacy_components; print([component.__name__ for component in _load_legacy_components()])'

if [[ "$run_compose_up" == "1" ]]; then
  step "compose up isolated sidecar"
  cleanup() {
    "${docker_cmd_parts[@]}" compose -f "$compose_file" down --remove-orphans
  }
  trap cleanup EXIT
  "${docker_cmd_parts[@]}" compose -f "$compose_file" up -d
  "${docker_cmd_parts[@]}" compose -f "$compose_file" ps

  step "localhost health"
  curl -fsS http://127.0.0.1:18181/healthz >/dev/null

  step "port exposure check"
  if ss -lntp | grep -E '0\.0\.0\.0:18181|0\.0\.0\.0:18789|0\.0\.0\.0:5432'; then
    fail "forbidden public listener detected"
  fi

  step "compose down isolated sidecar"
  cleanup
  trap - EXIT

  step "write Phase 1.5 exit proof"
  "$python_cmd" -B scripts/write_phase1_5_exit_proof.py \
    --compose-file "$compose_file" \
    --python-cmd "$python_cmd" \
    --node-cmd "$node_cmd" \
    --docker-cmd "$docker_cmd" \
    --worker-image "$worker_image" \
    --douyin-real-sample-status "$douyin_real_sample_status"
else
  printf 'Compose up skipped. Use RUN_COMPOSE_UP=1 only in an isolated Docker/Linux validation host.\n'
fi

printf 'Phase 1.5 gate checks completed for this environment.\n'
