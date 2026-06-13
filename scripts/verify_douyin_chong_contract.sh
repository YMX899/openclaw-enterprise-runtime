#!/usr/bin/env bash
set -euo pipefail

: "${DOUYIN_CHONG_BIN:?DOUYIN_CHONG_BIN is required}"
: "${SAMPLE_DOUYIN_URL:?SAMPLE_DOUYIN_URL is required}"
: "${MAX_DOWNLOAD_BYTES:=524288000}"
: "${MAX_VIDEO_DURATION_SECONDS:=0}"
: "${MAX_VIDEO_FRAMES:=0}"

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

result_json="$tmpdir/result.json"

"$DOUYIN_CHONG_BIN" \
  --input-url "$SAMPLE_DOUYIN_URL" \
  --output-json "$result_json" \
  --max-bytes "$MAX_DOWNLOAD_BYTES" \
  --max-duration-seconds "$MAX_VIDEO_DURATION_SECONDS" \
  --max-frames "$MAX_VIDEO_FRAMES" \
  --no-shell

python - "$result_json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
required = ["schema_version", "source", "summary", "signals", "created_at"]
missing = [key for key in required if key not in data]
if missing:
    raise SystemExit(f"missing fields: {missing}")
if data["schema_version"] != "openclaw-video-result.v1":
    raise SystemExit("unexpected schema_version")
if data["source"].get("platform") != "douyin":
    raise SystemExit("unexpected source.platform")
print("douyin_chong contract ok")
PY
