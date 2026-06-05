#!/usr/bin/env bash
set -euo pipefail

compose_file="${1:-openclaw-video/docker-compose.openclaw-video.yaml}"

docker compose -f "$compose_file" config >/tmp/openclaw-video-compose.rendered.yaml

if grep -E '0\.0\.0\.0:18789|0\.0\.0\.0:5432|/var/run/docker\.sock' /tmp/openclaw-video-compose.rendered.yaml; then
  echo "compose render exposes forbidden Gateway/Postgres/Docker socket surface" >&2
  exit 1
fi

grep -q '127.0.0.1:18181:3000' /tmp/openclaw-video-compose.rendered.yaml
echo "compose render ok"

