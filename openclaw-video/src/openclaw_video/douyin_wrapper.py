from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .result_schema import validate_result_payload
from .video_limits import (
    DEFAULT_MAX_DOWNLOAD_BYTES,
    DEFAULT_MAX_MODEL_VIDEO_BYTES,
    DEFAULT_MAX_VIDEO_DURATION_SECONDS,
    DEFAULT_MAX_VIDEO_FRAMES,
    DEFAULT_VIDEO_UNDERSTANDING_FPS,
    MAX_VIDEO_UNDERSTANDING_FPS,
    MIN_VIDEO_UNDERSTANDING_FPS,
)


class DouyinWrapperError(RuntimeError):
    pass


class VideoTooLargeForModelError(DouyinWrapperError):
    pass


@dataclass(frozen=True)
class DouyinAnalysisResult:
    payload: dict
    stdout: str
    stderr: str


def _positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise DouyinWrapperError(f"{name} must be positive")
    return value


def _nonnegative_int(value: int, name: str) -> int:
    if value < 0:
        raise DouyinWrapperError(f"{name} must be non-negative")
    return value


def _positive_float(value: float, name: str) -> float:
    if value <= 0:
        raise DouyinWrapperError(f"{name} must be positive")
    return value


def _raise_for_adapter_failure(prefix: str, completed: subprocess.CompletedProcess) -> None:
    detail = "\n".join(
        part for part in (str(getattr(completed, "stderr", "") or ""), str(getattr(completed, "stdout", "") or "")) if part
    )
    lowered = detail.lower()
    if "input video" in lowered and "exceeds the limit" in lowered:
        raise VideoTooLargeForModelError(f"{prefix} rejected the video because it exceeds the model input size limit")
    if "视频超过500mb" in lowered or "video exceeds 500mb" in lowered:
        raise VideoTooLargeForModelError(f"{prefix} rejected the video because it exceeds the 500MB size limit")
    if "compressed video still exceeds model size limit" in lowered:
        raise VideoTooLargeForModelError(f"{prefix} rejected the video because compression did not fit the model limit")
    if "video model size exceeds limit at minimum fps" in lowered:
        raise VideoTooLargeForModelError(f"{prefix} rejected the video because minimum fps still exceeds the model limit")
    if "serveroverloaded" in lowered or "too many requests" in lowered or "status_code=429" in lowered:
        raise TimeoutError(f"{prefix} model service is overloaded; retry later")
    safe_detail = " ".join(detail.split())
    if safe_detail:
        raise DouyinWrapperError(f"{prefix} failed with exit code {completed.returncode}: {safe_detail[:800]}")
    raise DouyinWrapperError(f"{prefix} failed with exit code {completed.returncode}")


def run_douyin_chong(
    *,
    video_url: str,
    output_dir: Path,
    binary: str | None = None,
    timeout_seconds: int = 900,
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    max_model_video_bytes: int = DEFAULT_MAX_MODEL_VIDEO_BYTES,
    max_duration_seconds: int = DEFAULT_MAX_VIDEO_DURATION_SECONDS,
    max_frames: int = DEFAULT_MAX_VIDEO_FRAMES,
    video_understanding_fps: float = DEFAULT_VIDEO_UNDERSTANDING_FPS,
    min_video_understanding_fps: float = MIN_VIDEO_UNDERSTANDING_FPS,
    max_video_understanding_fps: float = MAX_VIDEO_UNDERSTANDING_FPS,
) -> DouyinAnalysisResult:
    """Run douyin_chong through a fixed-argument, no-shell wrapper.

    The real binary is not present in this repository. This function documents
    the only allowed invocation pattern and prevents arbitrary shell assembly.
    """

    executable = binary or os.environ.get("DOUYIN_CHONG_BIN")
    if not executable:
        raise DouyinWrapperError("DOUYIN_CHONG_BIN is not configured")
    max_download_bytes = _positive_int(max_download_bytes, "max_download_bytes")
    max_model_video_bytes = _positive_int(max_model_video_bytes, "max_model_video_bytes")
    max_duration_seconds = _nonnegative_int(max_duration_seconds, "max_duration_seconds")
    max_frames = _nonnegative_int(max_frames, "max_frames")
    video_understanding_fps = _positive_float(video_understanding_fps, "video_understanding_fps")
    min_video_understanding_fps = _positive_float(min_video_understanding_fps, "min_video_understanding_fps")
    max_video_understanding_fps = _positive_float(max_video_understanding_fps, "max_video_understanding_fps")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = output_dir / "result.json"
    cmd = [
        executable,
        "--input-url",
        video_url,
        "--output-json",
        str(output_json),
        "--max-bytes",
        str(max_download_bytes),
        "--max-model-bytes",
        str(max_model_video_bytes),
        "--max-duration-seconds",
        str(max_duration_seconds),
        "--max-frames",
        str(max_frames),
        "--fps",
        str(video_understanding_fps),
        "--min-fps",
        str(min_video_understanding_fps),
        "--max-fps",
        str(max_video_understanding_fps),
    ]
    env_file = os.environ.get("DOUYIN_CHONG_ENV_FILE")
    if env_file:
        cmd.extend(["--env-file", env_file])
    cmd.append("--no-shell")
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("douyin_chong timed out") from exc
    except FileNotFoundError as exc:
        raise DouyinWrapperError("douyin_chong binary was not found") from exc
    if completed.returncode != 0:
        _raise_for_adapter_failure("douyin_chong", completed)
    if output_json.exists():
        payload = json.loads(output_json.read_text(encoding="utf-8"))
    else:
        payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise DouyinWrapperError("douyin_chong result must be a JSON object")
    payload = validate_result_payload(payload)
    return DouyinAnalysisResult(payload=payload, stdout=completed.stdout, stderr=completed.stderr)


def run_upload_video_analysis(
    *,
    file_path: str,
    output_dir: Path,
    source_label: str,
    binary: str | None = None,
    env_file: str | None = None,
    timeout_seconds: int = 900,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
) -> DouyinAnalysisResult:
    """Analyze a locally-uploaded video via the adapter's configured mode.

    The production mode is Files API: the adapter uploads the local mp4, waits
    until it is active, and calls Responses with input_video + file_id. The
    legacy inline/base64 path remains available only through
    VIDEO_ANALYSIS_INPUT_MODE=inline_legacy.
    """
    executable = binary or os.environ.get("DOUYIN_CHONG_BIN")
    if not executable:
        raise DouyinWrapperError("DOUYIN_CHONG_BIN is not configured")
    resolved_env_file = env_file or os.environ.get("DOUYIN_CHONG_ENV_FILE")
    if not resolved_env_file:
        raise DouyinWrapperError("DOUYIN_CHONG_ENV_FILE is not configured")
    max_bytes = _positive_int(max_bytes, "max_bytes")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = output_dir / "result.json"
    cmd = [
        executable,
        "--input-file",
        file_path,
        "--source-label",
        source_label,
        "--output-json",
        str(output_json),
        "--max-bytes",
        str(max_bytes),
        "--env-file",
        resolved_env_file,
        "--no-shell",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("upload analysis timed out") from exc
    except FileNotFoundError as exc:
        raise DouyinWrapperError("upload analyzer binary was not found") from exc
    if completed.returncode != 0:
        _raise_for_adapter_failure("upload analyzer", completed)
    if output_json.exists():
        payload = json.loads(output_json.read_text(encoding="utf-8"))
    else:
        payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise DouyinWrapperError("upload analyzer result must be a JSON object")
    payload = validate_result_payload(payload)
    return DouyinAnalysisResult(payload=payload, stdout=completed.stdout, stderr=completed.stderr)
