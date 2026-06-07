#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlparse

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "openclaw-video" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from openclaw_video.result_schema import ResultSchemaError, validate_result_payload  # noqa: E402


FAILURE_CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("duration exceeds", "duration_limit"),
    ("size exceeds", "size_limit"),
    ("router data", "douyin_router_data"),
    ("could not extract", "douyin_extract"),
    ("arkauthentication", "ark_authentication"),
    ("authentication", "authentication"),
    ("empty analysis", "empty_analysis"),
    ("timed out", "timeout"),
    ("403", "http_403"),
    ("401", "http_401"),
    ("captcha", "captcha"),
    ("verify", "verify"),
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one real douyin_chong adapter sample and write a sanitized evidence "
            "summary. The runner never reads or prints the secret env file."
        )
    )
    parser.add_argument("--input-url", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--adapter-bin", default="openclaw-douyin-adapter")
    parser.add_argument("--output-dir")
    parser.add_argument("--legacy-pythonpath")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--max-duration-seconds", type=int, default=60)
    parser.add_argument("--max-frames", type=int, default=1200)
    parser.add_argument("--evidence-json", default="sanitized-run.json")
    return parser


def _default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "tmp" / "douyin-real-samples" / stamp


def _adapter_command(adapter_bin: str) -> list[str]:
    adapter_path = Path(adapter_bin)
    if adapter_path.suffix == ".py":
        return [sys.executable, "-B", str(adapter_path)]
    return [adapter_bin]


def _rusage_snapshot() -> dict[str, int | None]:
    if resource is None:
        return {"max_rss_kb": None}
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"max_rss_kb": int(getattr(usage, "ru_maxrss", 0))}


def classify_adapter_failure(*, stdout: str, stderr: str) -> list[str]:
    combined = f"{stderr or ''}\n{stdout or ''}".lower()
    categories = {
        label
        for marker, label in FAILURE_CATEGORY_PATTERNS
        if marker in combined
    }
    return sorted(categories)


def _build_summary_base(args: argparse.Namespace, output_dir: Path, result_json: Path) -> dict:
    parsed = urlparse(args.input_url)
    return {
        "schema_version": "douyin-real-sample-evidence.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "unknown",
        "input_url_sha256": sha256_text(args.input_url),
        "input_url_host": parsed.hostname or "",
        "env_file_present": Path(args.env_file).is_file(),
        "secret_file_contents_recorded": False,
        "adapter_bin_name": Path(args.adapter_bin).name,
        "output_dir": str(output_dir),
        "result_json": str(result_json),
        "limits": {
            "timeout_seconds": args.timeout_seconds,
            "max_bytes": args.max_bytes,
            "max_duration_seconds": args.max_duration_seconds,
            "max_frames": args.max_frames,
        },
        "process": {},
        "result": {},
    }


def run(args: argparse.Namespace) -> tuple[int, dict]:
    env_file = Path(args.env_file)
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_json = output_dir / "result.json"
    evidence_json = output_dir / args.evidence_json
    summary = _build_summary_base(args, output_dir, result_json)

    if not env_file.is_file():
        summary["status"] = "failed"
        summary["error_code"] = "env_file_missing"
        evidence_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2, summary

    env = os.environ.copy()
    env["DOUYIN_CHONG_PYTHONPATH"] = args.legacy_pythonpath or env.get(
        "DOUYIN_CHONG_PYTHONPATH",
        str(REPO_ROOT / "openclaw-video" / "vendor"),
    )
    cmd = [
        *_adapter_command(args.adapter_bin),
        "--input-url",
        args.input_url,
        "--output-json",
        str(result_json),
        "--max-bytes",
        str(args.max_bytes),
        "--max-duration-seconds",
        str(args.max_duration_seconds),
        "--max-frames",
        str(args.max_frames),
        "--env-file",
        str(env_file),
        "--no-shell",
    ]

    start = time.monotonic()
    before_rusage = _rusage_snapshot()
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        summary["status"] = "timed_out"
        summary["error_code"] = "adapter_timeout"
        summary["process"] = {
            "elapsed_seconds": round(elapsed, 3),
            "timeout_seconds": args.timeout_seconds,
            "max_rss_kb_before": before_rusage["max_rss_kb"],
            "max_rss_kb_after": _rusage_snapshot()["max_rss_kb"],
        }
        evidence_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 124, summary

    elapsed = time.monotonic() - start
    after_rusage = _rusage_snapshot()
    summary["process"] = {
        "returncode": completed.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "stdout_chars": len(completed.stdout or ""),
        "stderr_chars": len(completed.stderr or ""),
        "stdout_recorded": False,
        "stderr_recorded": False,
        "max_rss_kb_before": before_rusage["max_rss_kb"],
        "max_rss_kb_after": after_rusage["max_rss_kb"],
    }

    if completed.returncode != 0:
        summary["status"] = "failed"
        summary["error_code"] = "adapter_nonzero_exit"
        summary["error_categories"] = classify_adapter_failure(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        evidence_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return completed.returncode or 1, summary

    try:
        payload = json.loads(result_json.read_text(encoding="utf-8"))
        payload = validate_result_payload(payload)
    except (OSError, json.JSONDecodeError, ResultSchemaError) as exc:
        summary["status"] = "failed"
        summary["error_code"] = "result_schema_invalid"
        summary["result"]["validation_error"] = type(exc).__name__
        evidence_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 3, summary

    summary["status"] = "succeeded"
    summary["result"] = {
        "schema_version": payload.get("schema_version"),
        "platform": payload.get("source", {}).get("platform"),
        "duration_seconds": payload.get("source", {}).get("duration_seconds"),
        "summary_chars": len(payload.get("summary", "")),
        "signals_keys": sorted((payload.get("signals") or {}).keys()),
        "result_json_bytes": result_json.stat().st_size,
        "result_json_sha256": sha256_file(result_json),
        "raw_tool_result_keys": sorted((payload.get("raw_tool_result") or {}).keys()),
    }
    evidence_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0, summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code, summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
