#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENCLAW_VIDEO_ROOT:-/app/bin/openclaw-video/current/openclaw-video}"
PROJECT="${OPENCLAW_COMPOSE_PROJECT:-openclaw-video}"
ENV_FILE="${OPENCLAW_ENV_FILE:-/app/bin/openclaw-video/shared/openclaw-video.env}"
FAST_IMAGE="${OPENCLAW_BRIDGE_FAST_IMAGE:-openclaw-video-openclaw-bridge:fast}"
SHARED_SECRETS_DIR="${OPENCLAW_SHARED_SECRETS_DIR:-/app/bin/openclaw-video/shared/secrets}"

cd "$ROOT"

if ! docker image inspect "$FAST_IMAGE" >/dev/null 2>&1; then
  echo "fast bridge image not found: $FAST_IMAGE" >&2
  exit 1
fi

if [ ! -d "$SHARED_SECRETS_DIR" ]; then
  echo "shared secrets directory not found: $SHARED_SECRETS_DIR" >&2
  exit 1
fi
if [ -L secrets ]; then
  :
elif [ -d secrets ]; then
  if find secrets -mindepth 1 ! -type d | grep -q .; then
    echo "release secrets directory contains non-placeholder entries: $ROOT/secrets" >&2
    exit 1
  fi
  find secrets -mindepth 1 -depth -type d -empty -exec rmdir {} +
  rmdir secrets
elif [ ! -e secrets ]; then
  :
else
  echo "unexpected secrets path under release: $ROOT/secrets" >&2
  exit 1
fi
if [ ! -e secrets ]; then
  ln -s "$SHARED_SECRETS_DIR" secrets
fi

OPENCLAW_BRIDGE_IMAGE="$FAST_IMAGE" docker compose \
  --env-file "$ENV_FILE" \
  -p "$PROJECT" \
  -f docker-compose.dify-admin-bridge.yaml \
  up -d --force-recreate dify-openclaw-bridge

sleep 5
docker compose \
  --env-file "$ENV_FILE" \
  -p "$PROJECT" \
  -f docker-compose.dify-admin-bridge.yaml \
  ps dify-openclaw-bridge

curl -fsS http://127.0.0.1:18182/healthz >/dev/null
curl -fsS http://127.0.0.1:18182/openclaw-lab/ >/dev/null
status="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:18182/openclaw-api/me)"
if [ "$status" != "401" ]; then
  echo "expected unauthenticated /openclaw-api/me to return 401, got $status" >&2
  exit 1
fi

echo "dify_admin_bridge_fast_rebuild=PASS"
