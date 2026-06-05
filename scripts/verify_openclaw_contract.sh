#!/usr/bin/env bash
set -euo pipefail

if ! command -v openclaw >/dev/null 2>&1; then
  echo "openclaw binary not found" >&2
  exit 2
fi

echo "== openclaw version =="
openclaw --version

echo "== doctor lint json =="
openclaw doctor --lint --json

echo "== doctor deep =="
openclaw doctor --deep

echo "== gateway status deep =="
openclaw gateway status --deep

echo "== gateway probe =="
openclaw gateway probe

echo "== status deep =="
openclaw status --deep

echo "== devices list =="
openclaw devices list

