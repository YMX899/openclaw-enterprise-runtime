#!/usr/bin/env bash
set -euo pipefail

PORT="${OPENCLAW_PUBLIC_PORT:-18443}"
OPENRESTY_CONTAINER="${OPENRESTY_CONTAINER:-openresty-prod}"
CONFIG_ROOT="${OPENRESTY_CONFIG_ROOT:-/app/config/openresty/conf}"
TARGET_CONF="${OPENCLAW_PUBLIC_CONF:-$CONFIG_ROOT/conf.d/openclaw-lab-public-${PORT}.conf}"
BACKUP_ROOT="${OPENCLAW_PUBLIC_BACKUP_ROOT:-/app/config/openresty/backups/openclaw-lab-public}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

require_command docker
require_command sha256sum

if ! docker ps --format '{{.Names}}' | grep -Fxq "$OPENRESTY_CONTAINER"; then
  echo "OpenResty container is not running: $OPENRESTY_CONTAINER" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d%H%M%S)"
mkdir -p "$BACKUP_ROOT"

if [ -f "$TARGET_CONF" ]; then
  if ! grep -q 'managed-by: openclaw-video install_openclaw_lab_public_port.sh' "$TARGET_CONF"; then
    echo "target config exists but is not managed by the OpenClaw public-port script: $TARGET_CONF" >&2
    exit 1
  fi
  backup_path="$BACKUP_ROOT/removed-openclaw-lab-public-${PORT}.${timestamp}.conf"
  cp -a "$TARGET_CONF" "$backup_path"
  echo "removed_config_backup=$backup_path"
  echo "removed_config_sha256=$(sha256sum "$TARGET_CONF" | awk '{print $1}')"
  rm -f "$TARGET_CONF"
else
  echo "target_config_absent=$TARGET_CONF"
fi

docker exec "$OPENRESTY_CONTAINER" openresty -t
docker exec "$OPENRESTY_CONTAINER" openresty -s reload

echo "public_port_rollback=PASS"
