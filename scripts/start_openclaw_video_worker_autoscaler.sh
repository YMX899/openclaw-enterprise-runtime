#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${OPENCLAW_VIDEO_ENV_FILE:-/app/bin/openclaw-video/shared/openclaw-video.env}"
WORKDIR="${OPENCLAW_VIDEO_WORKDIR:-/tmp/openclaw-video-deploy-995df1c}"
COMPOSE_FILE="${OPENCLAW_VIDEO_COMPOSE_FILE:-docker-compose.openclaw-video.yaml}"
PYTHON_BIN="${OPENCLAW_VIDEO_AUTOSCALER_PYTHON:-/project/Dify/openclaw-video/.venv/bin/python}"
AUTOSCALER="${OPENCLAW_VIDEO_AUTOSCALER_SCRIPT:-/project/Dify/scripts/openclaw_video_worker_autoscaler.py}"
POSTGRES_CONTAINER="${OPENCLAW_VIDEO_POSTGRES_CONTAINER:-openclaw-video-bridge-postgres-1}"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

POSTGRES_IP="$(
  docker inspect "$POSTGRES_CONTAINER" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
)"
if [ -z "$POSTGRES_IP" ]; then
  echo "failed to resolve ${POSTGRES_CONTAINER} IP" >&2
  exit 1
fi

export DATABASE_URL="postgresql://bridge:${BRIDGE_POSTGRES_PASSWORD}@${POSTGRES_IP}:5432/bridge"

exec "$PYTHON_BIN" "$AUTOSCALER" \
  --workdir "$WORKDIR" \
  --compose-file "$COMPOSE_FILE" \
  --env-file "$ENV_FILE" \
  --min-workers "${VIDEO_WORKER_MIN_REPLICAS:-3}" \
  --target-idle "${VIDEO_WORKER_TARGET_IDLE:-2}" \
  --max-workers "${VIDEO_WORKER_MAX_REPLICAS:-30}" \
  --interval "${VIDEO_WORKER_AUTOSCALE_INTERVAL_SECONDS:-20}"
