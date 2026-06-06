#!/usr/bin/env bash
set -euo pipefail

SERVER_NAME="${OPENCLAW_SAME_ORIGIN_SERVER_NAME:-www.huahuoai.com}"
OPENRESTY_CONTAINER="${OPENRESTY_CONTAINER:-openresty-prod}"
CONFIG_ROOT="${OPENRESTY_CONFIG_ROOT:-/app/config/openresty/conf}"
TARGET_CONF="${OPENCLAW_SAME_ORIGIN_CONF:-$CONFIG_ROOT/conf.d/${SERVER_NAME}.conf}"
BACKUP_ROOT="${OPENCLAW_SAME_ORIGIN_BACKUP_ROOT:-/app/config/openresty/backups/openclaw-lab-same-origin}"
MARKER_BEGIN="# managed-by: openclaw-video install_openclaw_lab_same_origin.sh begin"
MARKER_END="# managed-by: openclaw-video install_openclaw_lab_same_origin.sh end"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

require_command docker
require_command python3
require_command sha256sum

if ! docker ps --format '{{.Names}}' | grep -Fxq "$OPENRESTY_CONTAINER"; then
  echo "OpenResty container is not running: $OPENRESTY_CONTAINER" >&2
  exit 1
fi

if [ ! -r "$TARGET_CONF" ]; then
  echo "target OpenResty server config is not readable: $TARGET_CONF" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d%H%M%S)"
mkdir -p "$BACKUP_ROOT"
backup_path="$BACKUP_ROOT/removed-${SERVER_NAME}.${timestamp}.conf"
cp -a "$TARGET_CONF" "$backup_path"
echo "rollback_backup=$backup_path"
echo "pre_rollback_sha256=$(sha256sum "$TARGET_CONF" | awk '{print $1}')"

python3 - "$TARGET_CONF" "$MARKER_BEGIN" "$MARKER_END" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
marker_begin = sys.argv[2]
marker_end = sys.argv[3]

text = path.read_text(encoding="utf-8")
start = text.find(marker_begin)
if start < 0:
    print("same_origin_block=absent")
    sys.exit(0)
line_start = text.rfind("\n", 0, start)
line_start = 0 if line_start < 0 else line_start
end = text.find(marker_end, start)
if end < 0:
    raise SystemExit("managed same-origin block start exists but end marker is missing")
line_end = text.find("\n", end)
line_end = len(text) if line_end < 0 else line_end + 1
path.write_text(text[:line_start] + text[line_end:], encoding="utf-8")
print("same_origin_block=removed")
PY

echo "post_rollback_sha256=$(sha256sum "$TARGET_CONF" | awk '{print $1}')"

docker exec "$OPENRESTY_CONTAINER" openresty -t
docker exec "$OPENRESTY_CONTAINER" openresty -s reload

echo "same_origin_rollback=PASS"
