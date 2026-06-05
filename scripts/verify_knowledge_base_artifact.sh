#!/usr/bin/env bash
set -euo pipefail

artifact_dir="${KNOWLEDGE_BASE_ARTIFACT_DIR:-artifacts/knowledge-base-short-video/2026.06.06}"

if [[ ! -f "$artifact_dir/VERSION" ]]; then
  echo "VERSION not found: $artifact_dir/VERSION" >&2
  exit 1
fi

if [[ ! -f "$artifact_dir/SHA256SUMS" ]]; then
  echo "SHA256SUMS not found: $artifact_dir/SHA256SUMS" >&2
  exit 1
fi

(
  cd "$artifact_dir"
  sha256sum -c SHA256SUMS
)

echo "knowledge-base artifact ok: $artifact_dir"
