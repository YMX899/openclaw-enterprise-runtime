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
HOME="${HOME:-/home/node}"
export OPENCLAW_GATEWAY_TOKEN HOME

exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
