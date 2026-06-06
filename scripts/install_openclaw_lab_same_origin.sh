#!/usr/bin/env bash
set -euo pipefail

SERVER_NAME="${OPENCLAW_SAME_ORIGIN_SERVER_NAME:-www.huahuoai.com}"
BACKEND="${OPENCLAW_BRIDGE_BACKEND:-http://127.0.0.1:18181}"
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
require_command curl
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

if ! grep -Eq "server_name([[:space:]]+[^;]*)?${SERVER_NAME}" "$TARGET_CONF"; then
  echo "target config does not appear to serve $SERVER_NAME: $TARGET_CONF" >&2
  exit 1
fi

curl -fsS "$BACKEND/healthz" >/dev/null
curl -fsS "$BACKEND/openclaw-lab/" >/dev/null

timestamp="$(date +%Y%m%d%H%M%S)"
mkdir -p "$BACKUP_ROOT"
backup_path="$BACKUP_ROOT/${SERVER_NAME}.${timestamp}.conf"
cp -a "$TARGET_CONF" "$backup_path"

python3 - "$TARGET_CONF" "$MARKER_BEGIN" "$MARKER_END" "$BACKEND" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
marker_begin = sys.argv[2]
marker_end = sys.argv[3]
backend = sys.argv[4]

text = path.read_text(encoding="utf-8")
if marker_begin in text:
    print("same_origin_block=already_present")
    sys.exit(0)

block = f"""
    {marker_begin}
    location = /openclaw-lab {{
        return 308 /openclaw-lab/;
    }}

    location = /openclaw-api {{
        return 308 /openclaw-api/;
    }}

    location ^~ /openclaw-lab/ {{
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass {backend};
    }}

    location ^~ /openclaw-api/ {{
        client_max_body_size 512m;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass {backend};
    }}
    {marker_end}
"""

insert_at = text.rfind("\n}")
if insert_at < 0:
    raise SystemExit("could not find final server block closing brace")

path.write_text(text[:insert_at] + block + text[insert_at:], encoding="utf-8")
print("same_origin_block=inserted")
PY

chmod 0644 "$TARGET_CONF"
echo "target_config=$TARGET_CONF"
echo "backup_path=$backup_path"
echo "target_sha256=$(sha256sum "$TARGET_CONF" | awk '{print $1}')"
echo "redacted_config_summary"
grep -nE 'managed-by|server_name|listen|location|proxy_pass|client_max_body_size' "$TARGET_CONF" \
  | sed -E 's#ssl_certificate_key[[:space:]]+[^;]+;#ssl_certificate_key <redacted>;#Ig; s#ssl_certificate[[:space:]]+[^;]+;#ssl_certificate <redacted>;#Ig'

docker exec "$OPENRESTY_CONTAINER" openresty -t
docker exec "$OPENRESTY_CONTAINER" openresty -s reload

lab_status="$(curl -ksS --resolve "${SERVER_NAME}:443:127.0.0.1" -o /tmp/openclaw-same-origin-lab -w '%{http_code}' "https://${SERVER_NAME}/openclaw-lab/" || true)"
if [ "$lab_status" != "200" ]; then
  echo "expected same-origin lab status 200, got $lab_status" >&2
  exit 1
fi

me_status="$(curl -ksS --resolve "${SERVER_NAME}:443:127.0.0.1" -o /tmp/openclaw-same-origin-me -w '%{http_code}' "https://${SERVER_NAME}/openclaw-api/me" || true)"
if [ "$me_status" != "401" ]; then
  echo "expected unauthenticated same-origin /openclaw-api/me to return 401, got $me_status" >&2
  exit 1
fi

echo "same_origin_install=PASS"
echo "same_origin_lab=200"
echo "same_origin_me=401"
