#!/usr/bin/env bash
set -euo pipefail

python_cmd="${PYTHON:-python3}"
docker_cmd="${DOCKER_CMD:-docker}"
target_label="${TARGET_LABEL:-ubuntu22.04}"
require_secrets="${REQUIRE_SECRETS:-1}"

step() {
  printf '==> %s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

cd "$(dirname "$0")/.."

host_name="$(hostname 2>/dev/null || true)"
if [[ "$host_name" == "AI-01" || "$target_label" == "root" ]]; then
  fail "Phase 1.5 acceptance must run on a non-production Linux Docker host, not $target_label/$host_name."
fi

if [[ -f /app/bin/dify/dify-1.11.2/docker/docker-compose.yaml ]]; then
  fail "Dify production compose path detected; do not run Phase 1.5 acceptance on the production host."
fi

step "acceptance identity"
date -Is
printf 'host_name=%s\n' "$host_name"
printf 'target_label=%s\n' "$target_label"
printf 'PYTHON=%s\n' "$python_cmd"
printf 'DOCKER_CMD=%s\n' "$docker_cmd"
git rev-parse HEAD
git tag --points-at HEAD

if [[ "$require_secrets" == "1" ]]; then
  step "secret file presence"
  for path in \
    openclaw-video/secrets/openclaw_gateway_token \
    openclaw-video/secrets/openclaw_bridge_device_key.pem \
    openclaw-video/secrets/douyin_chong.env
  do
    [[ -f "$path" ]] || fail "required non-production secret file is missing: $path"
    [[ -s "$path" ]] || fail "required non-production secret file is empty: $path"
    printf 'present: %s\n' "$path"
  done
else
  printf 'Secret file presence check skipped by REQUIRE_SECRETS=0. This cannot produce Phase 1.5 exit proof.\n'
fi

step "host readiness"
read -r -a docker_cmd_parts <<<"$docker_cmd"
if [[ "${#docker_cmd_parts[@]}" -eq 0 ]]; then
  fail "DOCKER_CMD must not be empty."
fi
"$python_cmd" scripts/check_phase1_5_host_readiness.py \
  --docker-cmd "${docker_cmd_parts[@]}" \
  --fail-on-no-go

if [[ "$require_secrets" != "1" ]]; then
  fail "REQUIRE_SECRETS=0 cannot continue to full Phase 1.5 acceptance."
fi

step "full Phase 1.5 gate"
REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
REQUIRE_DOUYIN_ARTIFACT=1 \
RUN_COMPOSE_UP=1 \
DOCKER_CMD="$docker_cmd" \
PYTHON="$python_cmd" \
scripts/verify_phase1_5_gates.sh

step "exit proof present"
[[ -f phase1.5-exit-proof.md ]] || fail "phase1.5-exit-proof.md was not generated."
grep -q 'status: PASS' phase1.5-exit-proof.md
grep -q 'source: isolated-linux-docker-host' phase1.5-exit-proof.md
grep -q 'production_host: NO' phase1.5-exit-proof.md
printf 'Phase 1.5 acceptance completed successfully.\n'
