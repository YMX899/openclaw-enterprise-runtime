#!/bin/sh
set -eu

APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"
TOKEN_FILE="${OPENCLAW_GATEWAY_TOKEN_FILE:-/run/secrets/openclaw_gateway_token}"

if [ -z "$TOKEN_FILE" ] || [ ! -r "$TOKEN_FILE" ]; then
  echo "required OpenClaw gateway token file is not readable" >&2
  exit 1
fi

umask 077
OPENCLAW_GATEWAY_TOKEN="$(cat "$TOKEN_FILE")"
OPENCLAW_HOME="${OPENCLAW_HOME:-${OPENCLAW_STATE_DIR:-/var/lib/openclaw}}"
HOME="$OPENCLAW_HOME"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$OPENCLAW_HOME/.config}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$OPENCLAW_HOME/.cache}"
XDG_DATA_HOME="${XDG_DATA_HOME:-$OPENCLAW_HOME/.local/share}"

case "$HOME" in
  /var/lib/openclaw|/var/lib/openclaw/*) ;;
  *)
    echo "refusing to use unsafe OpenClaw home directory: $HOME" >&2
    exit 1
    ;;
esac

mkdir -p "$HOME/.openclaw" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"
chown -R "$APP_UID:$APP_GID" "$HOME"
export OPENCLAW_GATEWAY_TOKEN OPENCLAW_HOME HOME XDG_CONFIG_HOME XDG_CACHE_HOME XDG_DATA_HOME

exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
