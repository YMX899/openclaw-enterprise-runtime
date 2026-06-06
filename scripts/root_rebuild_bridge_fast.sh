#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENCLAW_VIDEO_ROOT:-/app/bin/openclaw-video/current/openclaw-video}"
PROJECT="${OPENCLAW_COMPOSE_PROJECT:-openclaw-video}"
ENV_FILE="${OPENCLAW_ENV_FILE:-/app/bin/openclaw-video/shared/openclaw-video.env}"
BASE_IMAGE="${OPENCLAW_BRIDGE_BASE_IMAGE:-openclaw-video-openclaw-bridge}"
FAST_IMAGE="${OPENCLAW_BRIDGE_FAST_IMAGE:-openclaw-video-openclaw-bridge:fast}"
TMP_DOCKERFILE="${ROOT}/.bridge-fast.Dockerfile"

cd "$ROOT"

if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  echo "base bridge image not found: $BASE_IMAGE" >&2
  exit 1
fi

cat > "$TMP_DOCKERFILE" <<'EOF'
ARG BASE_IMAGE=openclaw-video-openclaw-bridge
FROM ${BASE_IMAGE}
USER root
WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir --no-deps /app
EOF

trap 'rm -f "$TMP_DOCKERFILE"' EXIT

docker build \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  -f "$TMP_DOCKERFILE" \
  -t "$FAST_IMAGE" \
  .

OPENCLAW_BRIDGE_IMAGE="$FAST_IMAGE" docker compose \
  --env-file "$ENV_FILE" \
  -p "$PROJECT" \
  -f docker-compose.openclaw-video.yaml \
  up -d --no-deps --force-recreate openclaw-bridge

sleep 5
docker compose \
  --env-file "$ENV_FILE" \
  -p "$PROJECT" \
  -f docker-compose.openclaw-video.yaml \
  ps openclaw-bridge

curl -fsS http://127.0.0.1:18181/healthz >/dev/null
curl -fsS http://127.0.0.1:18181/openclaw-lab/ >/dev/null

echo "bridge_fast_rebuild=PASS"
