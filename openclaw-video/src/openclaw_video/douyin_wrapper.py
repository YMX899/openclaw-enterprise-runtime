from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class DouyinWrapperError(RuntimeError):
    pass


@dataclass(frozen=True)
class DouyinAnalysisResult:
    payload: dict
    stdout: str
    stderr: str


def run_douyin_chong(
    *,
    video_url: str,
    output_dir: Path,
    binary: str | None = None,
    timeout_seconds: int = 900,
) -> DouyinAnalysisResult:
    """Run douyin_chong through a fixed-argument, no-shell wrapper.

    The real binary is not present in this repository. This function documents
    the only allowed invocation pattern and prevents arbitrary shell assembly.
    """

    executable = binary or os.environ.get("DOUYIN_CHONG_BIN")
    if not executable:
        raise DouyinWrapperError("DOUYIN_CHONG_BIN is not configured")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = output_dir / "result.json"
    cmd = [
        executable,
        "--input-url",
        video_url,
        "--output-json",
        str(output_json),
        "--no-shell",
    ]
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise DouyinWrapperError(f"douyin_chong failed with exit code {completed.returncode}")
    if output_json.exists():
        payload = json.loads(output_json.read_text(encoding="utf-8"))
    else:
        payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise DouyinWrapperError("douyin_chong result must be a JSON object")
    return DouyinAnalysisResult(payload=payload, stdout=completed.stdout, stderr=completed.stderr)

