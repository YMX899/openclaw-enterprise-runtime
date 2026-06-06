#!/usr/bin/env bash
set -euo pipefail

PORT="${OPENCLAW_PUBLIC_PORT:-18443}"
SERVER_NAME="${OPENCLAW_PUBLIC_SERVER_NAME:-ai001.huahuoai.com}"
BACKEND="${OPENCLAW_BRIDGE_BACKEND:-http://127.0.0.1:18181}"
OPENRESTY_CONTAINER="${OPENRESTY_CONTAINER:-openresty-prod}"
CONFIG_ROOT="${OPENRESTY_CONFIG_ROOT:-/app/config/openresty/conf}"
SOURCE_TLS_CONF="${OPENRESTY_SOURCE_TLS_CONF:-$CONFIG_ROOT/conf.d/ai001.huahuoai.com.conf}"
TARGET_CONF="${OPENCLAW_PUBLIC_CONF:-$CONFIG_ROOT/conf.d/openclaw-lab-public-${PORT}.conf}"
BACKUP_ROOT="${OPENCLAW_PUBLIC_BACKUP_ROOT:-/app/config/openresty/backups/openclaw-lab-public}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

redact_config_summary() {
  grep -nE 'listen|server_name|ssl_certificate|proxy_pass|location|add_header' "$TARGET_CONF" \
    | sed -E 's#ssl_certificate_key[[:space:]]+[^;]+;#ssl_certificate_key <redacted>;#Ig; s#ssl_certificate[[:space:]]+[^;]+;#ssl_certificate <redacted>;#Ig'
}

require_command docker
require_command curl
require_command awk
require_command sha256sum
require_command ss

if ! docker ps --format '{{.Names}}' | grep -Fxq "$OPENRESTY_CONTAINER"; then
  echo "OpenResty container is not running: $OPENRESTY_CONTAINER" >&2
  exit 1
fi

if [ ! -r "$SOURCE_TLS_CONF" ]; then
  echo "source TLS config is not readable: $SOURCE_TLS_CONF" >&2
  exit 1
fi

if ss -ltnp | grep -Eq ":${PORT}[[:space:]]" && [ ! -f "$TARGET_CONF" ]; then
  echo "port $PORT is already in use and target config does not exist" >&2
  exit 1
fi

curl -fsS "$BACKEND/healthz" >/dev/null
curl -fsS "$BACKEND/openclaw-lab/" >/dev/null

TLS_LINES="$(
  awk '
    /^[[:space:]]*ssl_certificate[[:space:]]+/ ||
    /^[[:space:]]*ssl_certificate_key[[:space:]]+/ ||
    /^[[:space:]]*ssl_session_cache[[:space:]]+/ ||
    /^[[:space:]]*ssl_session_timeout[[:space:]]+/ ||
    /^[[:space:]]*ssl_protocols[[:space:]]+/ ||
    /^[[:space:]]*ssl_ciphers[[:space:]]+/ ||
    /^[[:space:]]*ssl_prefer_server_ciphers[[:space:]]+/ {
      print
    }
  ' "$SOURCE_TLS_CONF"
)"

printf '%s\n' "$TLS_LINES" | grep -Eq '^[[:space:]]*ssl_certificate[[:space:]]+' || {
  echo "source TLS config did not provide ssl_certificate" >&2
  exit 1
}
printf '%s\n' "$TLS_LINES" | grep -Eq '^[[:space:]]*ssl_certificate_key[[:space:]]+' || {
  echo "source TLS config did not provide ssl_certificate_key" >&2
  exit 1
}

timestamp="$(date +%Y%m%d%H%M%S)"
mkdir -p "$BACKUP_ROOT"
if [ -f "$TARGET_CONF" ]; then
  if ! grep -q 'managed-by: openclaw-video install_openclaw_lab_public_port.sh' "$TARGET_CONF"; then
    echo "target config exists but is not managed by this script: $TARGET_CONF" >&2
    exit 1
  fi
  cp -a "$TARGET_CONF" "$BACKUP_ROOT/openclaw-lab-public-${PORT}.${timestamp}.conf"
fi

tmp_conf="${TARGET_CONF}.tmp.${timestamp}"
cat > "$tmp_conf" <<EOF
# managed-by: openclaw-video install_openclaw_lab_public_port.sh
# purpose: expose OpenClaw Lab on an independent public TLS port without changing Dify routes
server {
    listen       ${PORT} ssl;
    server_name  ${SERVER_NAME};

${TLS_LINES}

    access_log /app/logs/openresty/openclaw_lab_${PORT}_access.log main;
    error_log  /app/logs/openresty/openclaw_lab_${PORT}_error.log warn;

    client_max_body_size 20m;
    proxy_buffering off;

    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "same-origin" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location = / {
        return 302 /openclaw-lab/;
    }

    location = /openclaw-lab {
        return 308 /openclaw-lab/;
    }

    location = /openclaw-api {
        return 308 /openclaw-api/;
    }

    location ^~ /openclaw-lab/ {
        proxy_http_version 1.1;
        proxy_set_header Host \$host:\$server_port;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host:\$server_port;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass ${BACKEND};
    }

    location ^~ /openclaw-api/ {
        proxy_http_version 1.1;
        proxy_set_header Host \$host:\$server_port;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host:\$server_port;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass ${BACKEND};
    }

    location / {
        return 404;
    }
}
EOF

mv "$tmp_conf" "$TARGET_CONF"
chmod 0644 "$TARGET_CONF"

echo "target_config=$TARGET_CONF"
echo "target_sha256=$(sha256sum "$TARGET_CONF" | awk '{print $1}')"
echo "redacted_config_summary"
redact_config_summary

docker exec "$OPENRESTY_CONTAINER" openresty -t
docker exec "$OPENRESTY_CONTAINER" openresty -s reload

lab_ready=0
for _ in 1 2 3 4 5; do
  if curl -kfsS --resolve "${SERVER_NAME}:${PORT}:127.0.0.1" "https://${SERVER_NAME}:${PORT}/openclaw-lab/" >/dev/null; then
    lab_ready=1
    break
  fi
  sleep 1
done
if [ "$lab_ready" != "1" ]; then
  echo "OpenClaw public port did not become reachable on $PORT" >&2
  exit 1
fi

me_status=""
for _ in 1 2 3 4 5; do
  me_status="$(curl -ksS --resolve "${SERVER_NAME}:${PORT}:127.0.0.1" -o /tmp/openclaw-public-port-me -w '%{http_code}' "https://${SERVER_NAME}:${PORT}/openclaw-api/me" || true)"
  if [ "$me_status" = "401" ]; then
    break
  fi
  sleep 1
done
if [ "$me_status" != "401" ]; then
  echo "expected unauthenticated /openclaw-api/me to return 401, got $me_status" >&2
  exit 1
fi

echo "public_port_install=PASS"
echo "local_https_lab=200"
echo "local_https_me=401"
