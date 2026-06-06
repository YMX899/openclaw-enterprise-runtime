#!/usr/bin/env bash
set -euo pipefail

compose_file="${1:-openclaw-video/docker-compose.openclaw-video.yaml}"
rendered="$(mktemp "${TMPDIR:-/tmp}/openclaw-video-compose.XXXXXX.yaml")"
cleanup() {
  rm -f "$rendered"
}
trap cleanup EXIT

docker compose -f "$compose_file" config --no-interpolate >"$rendered"

if grep -E '0\.0\.0\.0:18789|0\.0\.0\.0:5432|/var/run/docker\.sock|internal: true|--token|phase15-|secret-32bytes|sk-[[:alnum:]_-]+' "$rendered"; then
  echo "compose render exposes forbidden Gateway/Postgres/Docker socket/secret surface" >&2
  exit 1
fi

if ! grep -q '127.0.0.1:18181:3000' "$rendered"; then
  grep -q 'host_ip: 127.0.0.1' "$rendered"
  grep -q 'published: "18181"' "$rendered"
  grep -q 'target: 3000' "$rendered"
fi
grep -q 'ws://openclaw-gateway:18789' "$rendered"
echo "compose render ok"
