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
  chown "$APP_UID:$APP_GID" "$SECRET_TMP_DIR"
  chmod 0700 "$SECRET_TMP_DIR"
  target_path="$SECRET_TMP_DIR/$target_name"
  cp "$source_path" "$target_path"
  chown "$APP_UID:$APP_GID" "$target_path"
  chmod 0400 "$target_path"
  printf '%s\n' "$target_path"
}

umask 077
OPENCLAW_GATEWAY_TOKEN_FILE="$(
  stage_secret "${OPENCLAW_GATEWAY_TOKEN_FILE:-/run/secrets/openclaw_gateway_token}" openclaw_gateway_token
)"
OPENCLAW_GATEWAY_DEVICE_KEY_FILE="$(
  stage_secret "${OPENCLAW_GATEWAY_DEVICE_KEY_FILE:-/run/secrets/openclaw_bridge_device_key.pem}" openclaw_bridge_device_key.pem
)"
export OPENCLAW_GATEWAY_TOKEN_FILE OPENCLAW_GATEWAY_DEVICE_KEY_FILE

if [ -n "${BRIDGE_UPLOAD_DIR:-}" ]; then
  mkdir -p "$BRIDGE_UPLOAD_DIR"
  chown "$APP_UID:$APP_GID" "$BRIDGE_UPLOAD_DIR"
  chmod 0750 "$BRIDGE_UPLOAD_DIR"
fi

exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
