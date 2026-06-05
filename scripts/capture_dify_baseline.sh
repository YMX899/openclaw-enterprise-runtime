#!/usr/bin/env bash
set -euo pipefail

base_url="${1:?usage: capture_dify_baseline.sh <base-url>}"
timestamp="$(date -Is)"

echo "timestamp=$timestamp"
for path in /signin /apps /console/api/account/profile; do
  code="$(curl -sk -o /dev/null -w '%{http_code}' "$base_url$path")"
  echo "$path code=$code"
done

echo "note=authenticated browser baseline must be captured separately without storing cookies or tokens"

