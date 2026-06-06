#!/bin/sh
set -eu

APP_UID="${APP_UID:-65532}"
APP_GID="${APP_GID:-65532}"
SECRET_TMP_DIR="${SECRET_TMP_DIR:-/tmp/openclaw-secrets}"

stage_secret() {
  source_path="$1"
  target_name="$2"
  if [ -z "$source_path" ] || [ ! -r "$source_path" ]; then
    echo "required secret file is not readable: $target_name" >&2
    exit 1
  fi
  mkdir -p "$SECRET_TMP_DIR"
  target_path="$SECRET_TMP_DIR/$target_name"
  cp "$source_path" "$target_path"
  chown "$APP_UID:$APP_GID" "$target_path"
  chmod 0400 "$target_path"
  printf '%s\n' "$target_path"
}

umask 077
mkdir -p /tmp/openclaw-video
chown "$APP_UID:$APP_GID" /tmp/openclaw-video
DOUYIN_CHONG_ENV_FILE="$(
  stage_secret "${DOUYIN_CHONG_ENV_FILE:-/run/secrets/douyin_chong_env}" douyin_chong.env
)"
export DOUYIN_CHONG_ENV_FILE

exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
