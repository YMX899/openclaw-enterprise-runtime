#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENCLAW_VIDEO_ROOT:-/app/bin/openclaw-video/current/openclaw-video}"
PROJECT="${OPENCLAW_COMPOSE_PROJECT:-openclaw-video}"
ENV_FILE="${OPENCLAW_ENV_FILE:-/app/bin/openclaw-video/shared/openclaw-video.env}"
BASE_IMAGE="${OPENCLAW_BRIDGE_BASE_IMAGE:-openclaw-video-openclaw-bridge}"
FAST_IMAGE="${OPENCLAW_BRIDGE_FAST_IMAGE:-openclaw-video-openclaw-bridge:fast}"
FAST_DOCKERFILE="${OPENCLAW_BRIDGE_FAST_DOCKERFILE:-docker/bridge/Fast.Dockerfile}"
TEST_IDENTITY_HEADERS="${BRIDGE_ENABLE_TEST_IDENTITY_HEADERS:-0}"
TEST_IDENTITY_SECRET="${BRIDGE_TEST_IDENTITY_SECRET:-}"
SHARED_SECRETS_DIR="${OPENCLAW_SHARED_SECRETS_DIR:-/app/bin/openclaw-video/shared/secrets}"
DIFY_API_CONTAINER="${DIFY_API_CONTAINER:-docker-api-1}"

cd "$ROOT"

if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  echo "base bridge image not found: $BASE_IMAGE" >&2
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

if [ ! -f "$FAST_DOCKERFILE" ]; then
  echo "fast bridge Dockerfile not found: $ROOT/$FAST_DOCKERFILE" >&2
  exit 1
fi

docker build \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  -f "$FAST_DOCKERFILE" \
  -t "$FAST_IMAGE" \
  .

DIFY_AUTH_DB_HOST_VALUE="${DIFY_AUTH_DB_HOST:-}"
DIFY_AUTH_DB_PORT_VALUE="${DIFY_AUTH_DB_PORT:-}"
DIFY_AUTH_DB_NAME_VALUE="${DIFY_AUTH_DB_NAME:-}"
DIFY_AUTH_DB_USER_VALUE="${DIFY_AUTH_DB_USER:-}"
DIFY_AUTH_DB_PASSWORD_VALUE="${DIFY_AUTH_DB_PASSWORD:-}"
if [ -z "${DIFY_AUTH_DATABASE_URL:-}" ] && docker inspect "$DIFY_API_CONTAINER" >/dev/null 2>&1; then
  dify_db_env="$(docker exec "$DIFY_API_CONTAINER" sh -lc 'printf "%s\n%s\n%s\n%s\n%s\n" "${DB_HOST:-}" "${DB_PORT:-}" "${DB_DATABASE:-}" "${DB_USERNAME:-}" "${DB_PASSWORD:-}"' 2>/dev/null || true)"
  if [ -n "$dify_db_env" ]; then
    DIFY_AUTH_DB_HOST_VALUE="${DIFY_AUTH_DB_HOST_VALUE:-$(printf '%s\n' "$dify_db_env" | sed -n '1p')}"
    DIFY_AUTH_DB_PORT_VALUE="${DIFY_AUTH_DB_PORT_VALUE:-$(printf '%s\n' "$dify_db_env" | sed -n '2p')}"
    DIFY_AUTH_DB_NAME_VALUE="${DIFY_AUTH_DB_NAME_VALUE:-$(printf '%s\n' "$dify_db_env" | sed -n '3p')}"
    DIFY_AUTH_DB_USER_VALUE="${DIFY_AUTH_DB_USER_VALUE:-$(printf '%s\n' "$dify_db_env" | sed -n '4p')}"
    DIFY_AUTH_DB_PASSWORD_VALUE="${DIFY_AUTH_DB_PASSWORD_VALUE:-$(printf '%s\n' "$dify_db_env" | sed -n '5p')}"
  fi
fi

OPENCLAW_BRIDGE_IMAGE="$FAST_IMAGE" \
BRIDGE_ENABLE_TEST_IDENTITY_HEADERS="$TEST_IDENTITY_HEADERS" \
BRIDGE_TEST_IDENTITY_SECRET="$TEST_IDENTITY_SECRET" \
DIFY_AUTH_DB_HOST="$DIFY_AUTH_DB_HOST_VALUE" \
DIFY_AUTH_DB_PORT="$DIFY_AUTH_DB_PORT_VALUE" \
DIFY_AUTH_DB_NAME="$DIFY_AUTH_DB_NAME_VALUE" \
DIFY_AUTH_DB_USER="$DIFY_AUTH_DB_USER_VALUE" \
DIFY_AUTH_DB_PASSWORD="$DIFY_AUTH_DB_PASSWORD_VALUE" \
OPENCLAW_ENABLE_HUAHUO_PASSWORD_LOGIN="1" \
OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY="0" \
docker compose \
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
curl -fsS http://127.0.0.1:18181/ai/agent/ >/dev/null

echo "bridge_fast_rebuild=PASS"
