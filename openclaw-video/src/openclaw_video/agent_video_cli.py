from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .douyin_legacy_adapter import LegacyAdapterError, run_adapter
from .video_limits import DEFAULT_MAX_DOWNLOAD_BYTES, DEFAULT_MAX_VIDEO_DURATION_SECONDS, DEFAULT_MAX_VIDEO_FRAMES


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _error_code(message: str) -> str:
    lowered = message.lower()
    if "duration" in lowered and "exceeds" in lowered:
        return "video_duration_exceeds_limit"
    if "frame budget" in lowered:
        return "video_frame_budget_exceeds_limit"
    if "size" in lowered and "exceeds" in lowered:
        return "video_size_exceeds_limit"
    if "size is unavailable" in lowered:
        return "video_size_unavailable"
    if "resolver" in lowered or "extract video id" in lowered or "router data" in lowered:
        return "douyin_resolver_failed"
    if "no analysis output" in lowered:
        return "model_analysis_failed"
    if "env-file" in lowered or "ark_api_key" in lowered:
        return "runtime_secret_unavailable"
    return "video_analysis_failed"


def _sanitize_error_message(message: str, input_url: str) -> str:
    text = str(message or "")
    if input_url:
        text = text.replace(input_url, "[redacted-url]")
    text = re.sub(r"https?://[^\s)]+", "[redacted-url]", text)
    return text[:240]


def _summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    raw = payload.get("raw_tool_result") if isinstance(payload.get("raw_tool_result"), dict) else {}
    signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
    summary = str(payload.get("summary") or "")
    return {
        "schema_version": payload.get("schema_version"),
        "source": {
            "platform": source.get("platform"),
            "duration_seconds": source.get("duration_seconds"),
        },
        "summary": summary,
        "signals": signals,
        "tool_meta": {
            "adapter": raw.get("adapter"),
            "content_type": raw.get("content_type"),
            "size_bytes": raw.get("size_bytes"),
            "video_url_source": raw.get("video_url_source"),
            "request_id_present": bool(raw.get("request_id")),
            "usage_present": raw.get("usage") is not None,
            "limits": raw.get("limits") if isinstance(raw.get("limits"), dict) else {},
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OpenClaw agent-safe Douyin video analyzer. Outputs sanitized JSON only."
    )
    parser.add_argument("--input-url", required=True)
    parser.add_argument("--env-file", default=os.environ.get("DOUYIN_CHONG_ENV_FILE", "/run/secrets/douyin_chong_env"))
    parser.add_argument("--max-bytes", type=int, default=int(os.environ.get("MAX_DOWNLOAD_BYTES", str(DEFAULT_MAX_DOWNLOAD_BYTES))))
    parser.add_argument("--max-duration-seconds", type=int, default=int(os.environ.get("MAX_VIDEO_DURATION_SECONDS", str(DEFAULT_MAX_VIDEO_DURATION_SECONDS))))
    parser.add_argument("--max-frames", type=int, default=int(os.environ.get("MAX_VIDEO_FRAMES", str(DEFAULT_MAX_VIDEO_FRAMES))))
    parser.add_argument("--output-json", default="")
    parser.add_argument("--pretty", action="store_true")
    return parser


def run_cli(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    args = build_parser().parse_args(argv)
    output_path = Path(args.output_json) if args.output_json else None
    with TemporaryDirectory(prefix="openclaw-agent-video-") as tmp:
        adapter_output = output_path or (Path(tmp) / "result.json")
        try:
            payload = run_adapter(
                [
                    "--input-url",
                    args.input_url,
                    "--output-json",
                    str(adapter_output),
                    "--max-bytes",
                    str(args.max_bytes),
                    "--max-duration-seconds",
                    str(args.max_duration_seconds),
                    "--max-frames",
                    str(args.max_frames),
                    "--env-file",
                    str(args.env_file),
                    "--no-shell",
                ]
            )
        except (LegacyAdapterError, TimeoutError, ValueError) as exc:
            message = str(exc)
            return 2, {
                "schema_version": "openclaw-agent-video-analysis.v1",
                "created_at": datetime.now(UTC).isoformat(),
                "status": "FAIL",
                "error_code": _error_code(message),
                "error_message": _sanitize_error_message(message, args.input_url),
                "input": {
                    "input_url_sha256": _sha256_text(args.input_url),
                    "raw_input_url_recorded": False,
                },
                "sanitization": {
                    "raw_url_recorded": False,
                    "direct_video_url_recorded": False,
                    "cookies_recorded": False,
                    "headers_recorded": False,
                    "tokens_recorded": False,
                    "secret_file_contents_recorded": False,
                },
            }
    return 0, {
        "schema_version": "openclaw-agent-video-analysis.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "input": {
            "input_url_sha256": _sha256_text(args.input_url),
            "raw_input_url_recorded": False,
        },
        "analysis": _summarize_payload(payload),
        "sanitization": {
            "raw_url_recorded": False,
            "direct_video_url_recorded": False,
            "cookies_recorded": False,
            "headers_recorded": False,
            "tokens_recorded": False,
            "secret_file_contents_recorded": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    code, payload = run_cli(argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if "--pretty" in (argv or []) else None))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
