#!/usr/bin/env bash
set -euo pipefail

release_dir="${1:-/app/bin/openclaw-video/current/openclaw-video}"
env_file="${2:-/app/bin/openclaw-video/shared/openclaw-video.env}"
log_dir="${3:-/app/bin/openclaw-video/shared/logs}"
project="openclaw-video"
compose_file="docker-compose.openclaw-video.yaml"

if [[ ! -f "$release_dir/$compose_file" ]]; then
  echo "missing compose file under release dir: $release_dir" >&2
  exit 2
fi
if [[ ! -f "$env_file" ]]; then
  echo "missing runtime env file: $env_file" >&2
  exit 2
fi

mkdir -p "$log_dir"
chmod 700 "$log_dir"
log_file="$log_dir/build-$(date +%Y%m%d%H%M%S).log"

cd "$release_dir"
printf 'build_log=%s\n' "$log_file"
printf 'build_start=%s\n' "$(date -Is)"

export PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-python:3.12-slim}"
export NODE_BASE_IMAGE="${NODE_BASE_IMAGE:-node:22.18-slim}"
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"
export APT_DEBIAN_MIRROR="${APT_DEBIAN_MIRROR:-http://mirrors.tuna.tsinghua.edu.cn/debian}"
export APT_SECURITY_MIRROR="${APT_SECURITY_MIRROR:-http://mirrors.tuna.tsinghua.edu.cn/debian-security}"

set +e
timeout "${OPENCLAW_BUILD_TIMEOUT_SECONDS:-900}" \
  docker compose --env-file "$env_file" -p "$project" -f "$compose_file" build \
  >"$log_file" 2>&1
code=$?
set -e

printf 'build_exit=%s\n' "$code"
printf 'build_end=%s\n' "$(date -Is)"
printf 'build_log_tail\n'
tail -n 120 "$log_file" \
  | sed -E 's/(token|password|secret|key|ARK_API_KEY|MEDIAKIT_API_KEY)[^[:space:]]*/\1=<redacted>/Ig'
printf 'images\n'
docker compose --env-file "$env_file" -p "$project" -f "$compose_file" images || true

exit "$code"
