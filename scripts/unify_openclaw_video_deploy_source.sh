#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${OPENCLAW_SOURCE_ROOT:-/project/Dify}"
APP_ROOT="${OPENCLAW_APP_ROOT:-/app/bin/openclaw-video}"
RELEASES_DIR="${OPENCLAW_RELEASES_DIR:-$APP_ROOT/releases}"
CURRENT_LINK="${OPENCLAW_CURRENT_LINK:-$APP_ROOT/current}"
ENV_FILE="${OPENCLAW_ENV_FILE:-$APP_ROOT/shared/openclaw-video.env}"
SECRETS_DIR="${OPENCLAW_SHARED_SECRETS_DIR:-$APP_ROOT/shared/secrets}"
PROJECT="${OPENCLAW_COMPOSE_PROJECT:-openclaw-video}"
WORKER_REPLICAS="${OPENCLAW_WORKER_REPLICAS:-3}"

cd "$SOURCE_ROOT"

if [ -n "$(git status --short)" ]; then
  echo "source tree is not clean; commit or stash changes before deployment" >&2
  git status --short >&2
  exit 1
fi

COMMIT="$(git rev-parse HEAD)"
SHORT_COMMIT="${COMMIT:0:12}"
RELEASE_DIR="$RELEASES_DIR/$SHORT_COMMIT"
RELEASE_APP_DIR="$RELEASE_DIR/openclaw-video"

mkdir -p "$RELEASES_DIR"
rm -rf "$RELEASE_DIR.tmp"
mkdir -p "$RELEASE_DIR.tmp"

git archive --format=tar "$COMMIT" | tar -x -C "$RELEASE_DIR.tmp"
mv "$RELEASE_DIR.tmp" "$RELEASE_DIR"

if [ ! -f "$RELEASE_APP_DIR/docker-compose.openclaw-video.yaml" ]; then
  echo "release missing openclaw-video compose file: $RELEASE_APP_DIR" >&2
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "runtime env file missing: $ENV_FILE" >&2
  exit 1
fi
if [ ! -d "$SECRETS_DIR" ]; then
  echo "shared secrets directory missing: $SECRETS_DIR" >&2
  exit 1
fi
if [ ! -e "$RELEASE_APP_DIR/secrets" ]; then
  ln -s "$SECRETS_DIR" "$RELEASE_APP_DIR/secrets"
fi

cat > "$RELEASE_DIR/DEPLOY_SOURCE.json" <<EOF
{
  "source_root": "$SOURCE_ROOT",
  "git_commit": "$COMMIT",
  "release_dir": "$RELEASE_DIR",
  "created_at": "$(date -Is)"
}
EOF

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"

OPENCLAW_VIDEO_ROOT="$RELEASE_APP_DIR" \
OPENCLAW_ENV_FILE="$ENV_FILE" \
OPENCLAW_COMPOSE_PROJECT="$PROJECT" \
"$SOURCE_ROOT/scripts/root_rebuild_bridge_fast.sh"

OPENCLAW_VIDEO_ROOT="$RELEASE_APP_DIR" \
OPENCLAW_ENV_FILE="$ENV_FILE" \
OPENCLAW_COMPOSE_PROJECT="$PROJECT" \
OPENCLAW_WORKER_REPLICAS="$WORKER_REPLICAS" \
"$SOURCE_ROOT/scripts/root_rebuild_worker_fast.sh"

if systemctl list-unit-files openclaw-video-worker-autoscaler.service >/dev/null 2>&1; then
  systemctl restart openclaw-video-worker-autoscaler.service
fi

echo "deploy_source_unified=PASS"
echo "git_commit=$COMMIT"
echo "release_dir=$RELEASE_DIR"
