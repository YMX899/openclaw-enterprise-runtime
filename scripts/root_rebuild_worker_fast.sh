#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENCLAW_VIDEO_ROOT:-/app/bin/openclaw-video/current/openclaw-video}"
PROJECT="${OPENCLAW_COMPOSE_PROJECT:-openclaw-video}"
ENV_FILE="${OPENCLAW_ENV_FILE:-/app/bin/openclaw-video/shared/openclaw-video.env}"
BASE_IMAGE="${OPENCLAW_WORKER_BASE_IMAGE:-openclaw-video-video-analysis-worker}"
FAST_IMAGE="${OPENCLAW_WORKER_FAST_IMAGE:-openclaw-video-video-analysis-worker}"
FAST_DOCKERFILE="${OPENCLAW_WORKER_FAST_DOCKERFILE:-docker/worker/Fast.Dockerfile}"
WORKER_REPLICAS="${OPENCLAW_WORKER_REPLICAS:-3}"

cd "$ROOT"

if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  echo "base worker image not found: $BASE_IMAGE" >&2
  exit 1
fi
if [ ! -f "$FAST_DOCKERFILE" ]; then
  echo "fast worker Dockerfile not found: $ROOT/$FAST_DOCKERFILE" >&2
  exit 1
fi

docker build \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  -f "$FAST_DOCKERFILE" \
  -t "$FAST_IMAGE" \
  .

docker compose \
  --env-file "$ENV_FILE" \
  -p "$PROJECT" \
  -f docker-compose.openclaw-video.yaml \
  up -d --no-build --no-deps --force-recreate --scale "video-analysis-worker=${WORKER_REPLICAS}" video-analysis-worker

sleep 5
docker compose \
  --env-file "$ENV_FILE" \
  -p "$PROJECT" \
  -f docker-compose.openclaw-video.yaml \
  ps video-analysis-worker

echo "worker_fast_rebuild=PASS"
