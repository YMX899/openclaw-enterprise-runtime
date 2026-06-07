#!/bin/sh
set -eu

APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"
TOKEN_FILE="${OPENCLAW_GATEWAY_TOKEN_FILE:-/run/secrets/openclaw_gateway_token}"
DOUYIN_CHONG_ENV_FILE="${DOUYIN_CHONG_ENV_FILE:-/run/secrets/douyin_chong_env}"

read_dotenv_key() {
  awk -v key="$1" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      quote = substr(value, 1, 1)
      if ((quote == "\"" || quote == "'\''") && substr(value, length(value), 1) == quote) {
        value = substr(value, 2, length(value) - 2)
      }
      print value
      exit
    }
  ' "$2"
}

if [ -z "$TOKEN_FILE" ] || [ ! -r "$TOKEN_FILE" ]; then
  echo "required OpenClaw gateway token file is not readable" >&2
  exit 1
fi

umask 077
OPENCLAW_GATEWAY_TOKEN="$(cat "$TOKEN_FILE")"
VOLCANO_ENGINE_API_KEY="${VOLCANO_ENGINE_API_KEY:-}"
if [ -z "$VOLCANO_ENGINE_API_KEY" ] && [ -r "$DOUYIN_CHONG_ENV_FILE" ]; then
  VOLCANO_ENGINE_API_KEY="$(read_dotenv_key ARK_API_KEY "$DOUYIN_CHONG_ENV_FILE")"
fi
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
export OPENCLAW_GATEWAY_TOKEN VOLCANO_ENGINE_API_KEY DOUYIN_CHONG_ENV_FILE
export OPENCLAW_HOME HOME XDG_CONFIG_HOME XDG_CACHE_HOME XDG_DATA_HOME

exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
