#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "tmp" / "playwright-public-browser"


TARGETS = {
    "openclaw-lab": {
        "url": "https://www.huahuoai.com/openclaw-lab/",
        "wait_ms": "1500",
        "expected_statuses": {
            "GET https://www.huahuoai.com/openclaw-lab/": 200,
        },
    },
    "openclaw-api-me-unauthenticated": {
        "url": "https://www.huahuoai.com/openclaw-api/me",
        "wait_ms": "500",
        "expected_statuses": {
            "GET https://www.huahuoai.com/openclaw-api/me": 401,
        },
    },
    "huahuo-user-web": {
        "url": "https://www.huahuoai.com/ai/?id=4",
        "wait_ms": "1000",
        "expected_statuses": {
            "GET https://www.huahuoai.com/ai/": 200,
        },
    },
    "huahuo-admin-configuration": {
        "url": "https://ai001.huahuoai.com/app/d44c1add-5043-4b33-b513-1d4f6ec3b4f0/configuration",
        "wait_ms": "1000",
        "expected_statuses": {
            "GET https://ai001.huahuoai.com/app/d44c1add-5043-4b33-b513-1d4f6ec3b4f0/configuration": 200,
        },
    },
}

TOKEN_PATTERNS = (
    "gateway_token",
    "openclaw_gateway_token",
    "authorization=",
    "access_token=",
)


def _safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _command_key(method: str | None, safe_url: str) -> str:
    return f"{method or ''} {safe_url}".strip()


def _run(cmd: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout)


def _npx_command() -> str:
    return "npx.cmd" if os.name == "nt" else "npx"


def _capture_target(name: str, target: dict, output_dir: Path, timeout: int) -> dict:
    screenshot = output_dir / f"{name}.png"
    har = output_dir / f"{name}.har"
    cmd = [
        _npx_command(),
        "--yes",
        "playwright",
        "screenshot",
        "--ignore-https-errors",
        "--full-page",
        "--viewport-size",
        "1280,720",
        "--wait-for-timeout",
        str(target["wait_ms"]),
        "--save-har",
        str(har),
        str(target["url"]),
        str(screenshot),
    ]
    completed = _run(cmd, cwd=REPO_ROOT, timeout=timeout)
    result = {
        "name": name,
        "url": target["url"],
        "screenshot": str(screenshot.relative_to(REPO_ROOT)),
        "har": str(har.relative_to(REPO_ROOT)),
        "playwright_returncode": completed.returncode,
        "playwright_stdout_chars": len(completed.stdout or ""),
        "playwright_stderr_chars": len(completed.stderr or ""),
        "headers_recorded_in_summary": False,
        "bodies_recorded_in_summary": False,
    }
    if completed.returncode != 0:
        result["status"] = "failed"
        result["error_code"] = "playwright_nonzero_exit"
        return result
    result.update(_summarize_har(har, target["expected_statuses"]))
    result["status"] = "passed" if result["ok"] else "failed"
    return result


def _summarize_har(har_path: Path, expected_statuses: dict[str, int]) -> dict:
    data = json.loads(har_path.read_text(encoding="utf-8"))
    entries = data.get("log", {}).get("entries", [])
    rows = []
    http_5xx = []
    gateway_hits = []
    token_url_hits = []
    expected_hits: dict[str, int | None] = {key: None for key in expected_statuses}
    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})
        method = request.get("method")
        raw_url = request.get("url", "")
        safe_url = _safe_url(raw_url)
        status = response.get("status")
        row = {"method": method, "url": safe_url, "status": status}
        rows.append(row)
        key = _command_key(method, safe_url)
        if key in expected_hits:
            expected_hits[key] = status
        if isinstance(status, int) and status >= 500:
            http_5xx.append(row)
        lower_url = raw_url.lower()
        if "18789" in lower_url or "openclaw-gateway" in lower_url:
            gateway_hits.append(row)
        if any(pattern in lower_url for pattern in TOKEN_PATTERNS):
            token_url_hits.append(row)
    expectation_results = [
        {
            "request": key,
            "expected_status": expected,
            "actual_status": expected_hits.get(key),
            "ok": expected_hits.get(key) == expected,
        }
        for key, expected in expected_statuses.items()
    ]
    return {
        "request_count": len(rows),
        "statuses": rows,
        "http_5xx_count": len(http_5xx),
        "gateway_direct_request_count": len(gateway_hits),
        "token_url_leak_count": len(token_url_hits),
        "expectations": expectation_results,
        "ok": (
            all(item["ok"] for item in expectation_results)
            and not http_5xx
            and not gateway_hits
            and not token_url_hits
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run public browser smoke checks with sanitized HAR summaries.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timeout-seconds", type=int, default=60)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results = [_capture_target(name, target, run_dir, args.timeout_seconds) for name, target in TARGETS.items()]
    report = {
        "schema": "openclaw-public-browser-smoke.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(item.get("status") == "passed" for item in results) else "FAIL",
        "run_dir": str(run_dir.relative_to(REPO_ROOT)),
        "targets": results,
        "secrets_recorded": False,
        "headers_recorded": False,
        "bodies_recorded": False,
    }
    report_path = run_dir / "summary.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
