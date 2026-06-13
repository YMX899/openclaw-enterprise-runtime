from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .ark_files_client import DEFAULT_ARK_API_BASE, DEFAULT_ARK_RESPONSES_MODEL, ArkFilesClient
from .result_schema import RESULT_SCHEMA_VERSION, validate_result_payload
from .url_guard import UrlRejected, validate_video_url_with_redirects
from .video_limits import (
    MAX_VIDEO_BYTES,
    DEFAULT_MAX_MODEL_VIDEO_BYTES,
    DEFAULT_MAX_VIDEO_DURATION_SECONDS,
    DEFAULT_MAX_VIDEO_FRAMES,
    DEFAULT_VIDEO_UNDERSTANDING_FPS,
    MAX_VIDEO_UNDERSTANDING_FPS,
    MIN_VIDEO_UNDERSTANDING_FPS,
)


class LegacyAdapterError(RuntimeError):
    pass


MODEL_INLINE_TARGET_BYTES = 45 * 1024 * 1024
VIDEO_CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_VIDEO_CACHE_DIR = "/tmp/openclaw-video/cache"
FILES_API_MODE = "files_api"
INLINE_LEGACY_MODE = "inline_legacy"

LEGACY_CONFIG_ENV_KEYS = (
    "ARK_API_KEY",
    "MEDIAKIT_API_KEY",
    "MODEL",
    "ARK_MODEL",
    "ARK_BASE_URL",
    "MEDIAKIT_BASE_URL",
)


@dataclass(frozen=True)
class LegacyVideoLimits:
    max_download_bytes: int
    max_model_video_bytes: int
    max_duration_seconds: int
    max_frames: int
    fps: float
    min_fps: float = MIN_VIDEO_UNDERSTANDING_FPS
    max_fps: float = MAX_VIDEO_UNDERSTANDING_FPS

    def with_fps(self, fps: float) -> "LegacyVideoLimits":
        return LegacyVideoLimits(
            max_download_bytes=self.max_download_bytes,
            max_model_video_bytes=self.max_model_video_bytes,
            max_duration_seconds=self.max_duration_seconds,
            max_frames=self.max_frames,
            fps=fps,
            min_fps=self.min_fps,
            max_fps=self.max_fps,
        )


@dataclass(frozen=True)
class PreparedModelVideo:
    path: Path
    size_bytes: int
    fps: float
    compressed: bool
    downloaded: bool = False
    cache_hit: bool = False
    download_tool: str = ""
    cache_key: str = ""


def _positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise LegacyAdapterError(f"{name} must be positive")
    return value


def _nonnegative_int(value: int, name: str) -> int:
    if value < 0:
        raise LegacyAdapterError(f"{name} must be zero or positive")
    return value


def _positive_float(value: float, name: str) -> float:
    if value <= 0:
        raise LegacyAdapterError(f"{name} must be positive")
    return value


def _fps_in_range(value: float, name: str) -> float:
    value = _positive_float(value, name)
    if value < MIN_VIDEO_UNDERSTANDING_FPS or value > MAX_VIDEO_UNDERSTANDING_FPS:
        raise LegacyAdapterError(
            f"{name} must be between {MIN_VIDEO_UNDERSTANDING_FPS} and {MAX_VIDEO_UNDERSTANDING_FPS}"
        )
    return value


def _ensure_legacy_pythonpath() -> None:
    raw_paths = os.environ.get("DOUYIN_CHONG_PYTHONPATH", "")
    for raw_path in raw_paths.split(os.pathsep):
        path = raw_path.strip()
        if path and path not in sys.path:
            sys.path.insert(0, path)


def _load_legacy_components() -> tuple[type, type, type]:
    _ensure_legacy_pythonpath()
    try:
        from douyin_chong.clients.ark_video import ArkVideoClient
        from douyin_chong.clients.resolver import UniversalVideoResolver
        from douyin_chong.config import AppConfig
    except ImportError as exc:
        raise LegacyAdapterError("douyin_chong package is not importable") from exc
    return AppConfig, UniversalVideoResolver, ArkVideoClient


def _duration_seconds(video: Any) -> float | None:
    duration_ms = getattr(video, "duration_ms", None)
    if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
        return float(duration_ms) / 1000.0
    return None


def _size_bytes(video: Any) -> int | None:
    size_mb = getattr(video, "size_mb", None)
    if isinstance(size_mb, (int, float)) and size_mb >= 0:
        return int(float(size_mb) * 1024 * 1024)
    return None


def _canonicalize_input_for_resolver(input_url: str) -> str:
    try:
        return validate_video_url_with_redirects(input_url).canonical
    except UrlRejected as exc:
        raise LegacyAdapterError("video URL failed redirect validation") from exc


def _platform_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "b23.tv" or host.endswith(".b23.tv") or host == "bilibili.com" or host.endswith(".bilibili.com"):
        return "bilibili"
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "tiktok"
    if (
        host == "xiaohongshu.com"
        or host.endswith(".xiaohongshu.com")
        or host == "xhslink.com"
        or host.endswith(".xhslink.com")
    ):
        return "xiaohongshu"
    return "douyin"


def _referer_for_url(url: str) -> str:
    platform = _platform_from_url(url)
    if platform == "bilibili":
        return "https://www.bilibili.com/"
    if platform == "tiktok":
        return "https://www.tiktok.com/"
    if platform == "xiaohongshu":
        return "https://www.xiaohongshu.com/"
    return "https://www.douyin.com/"


def _best_download_url_for_platform(input_url: str, video: Any) -> str:
    platform = _platform_from_url(input_url or str(getattr(video, "source_url", "") or ""))
    if platform in {"bilibili", "xiaohongshu"}:
        return input_url
    return str(getattr(video, "video_url", "") or "") or input_url


def _request_headers(*, referer: str = "https://www.douyin.com/") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
    }


def _model_inline_target_bytes(limits: LegacyVideoLimits) -> int:
    return min(MODEL_INLINE_TARGET_BYTES, max(1, int(limits.max_model_video_bytes * 0.90)))


def _cache_root() -> Path:
    return Path(os.environ.get("OPENCLAW_VIDEO_CACHE_DIR", DEFAULT_VIDEO_CACHE_DIR))


def _cache_key_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _cache_key_for_video(input_url: str, video: Any) -> str:
    platform = _platform_from_url(input_url or str(getattr(video, "source_url", "") or ""))
    video_id = str(getattr(video, "video_id", "") or "").strip()
    if video_id:
        return _cache_key_for_url(f"{platform}:{video_id}")
    return _cache_key_for_url(input_url)


def _cleanup_video_cache(cache_root: Path, *, now: float | None = None, ttl_seconds: int = VIDEO_CACHE_TTL_SECONDS) -> None:
    now = time.time() if now is None else now
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for path in cache_root.iterdir():
        try:
            if now - path.stat().st_mtime <= ttl_seconds:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            continue


def _cached_video_path(cache_root: Path, key: str) -> Path | None:
    entry_dir = cache_root / key
    if not entry_dir.is_dir():
        return None
    for candidate in sorted(entry_dir.iterdir()):
        if candidate.is_file() and candidate.stat().st_size > 0:
            try:
                os.utime(entry_dir, None)
                os.utime(candidate, None)
            except OSError:
                pass
            return candidate
    return None


def _probe_stream_size_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float = 30.0,
    referer: str = "https://www.douyin.com/",
) -> int:
    if not url:
        raise LegacyAdapterError("video size is unavailable")
    request = Request(
        url,
        headers=_request_headers(referer=referer),
    )
    total = 0
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise LegacyAdapterError("video size exceeds limit")
    except LegacyAdapterError:
        raise
    except Exception as exc:
        raise LegacyAdapterError("video size is unavailable") from exc
    if total <= 0:
        raise LegacyAdapterError("video size is unavailable")
    return total


def _download_video_to_file(
    url: str,
    *,
    output_path: Path,
    max_bytes: int,
    referer: str,
    timeout_seconds: float = 120.0,
) -> int:
    if not url:
        raise LegacyAdapterError("video URL is unavailable")
    request = Request(url, headers=_request_headers(referer=referer))
    total = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(request, timeout=timeout_seconds) as response, output_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise LegacyAdapterError("video size exceeds download limit")
                handle.write(chunk)
    except LegacyAdapterError:
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        raise
    except Exception as exc:
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        raise LegacyAdapterError("video download failed") from exc
    if total <= 0:
        raise LegacyAdapterError("video download was empty")
    return total


def _download_video_with_ytdlp(
    url: str,
    *,
    output_dir: Path,
    max_bytes: int,
    referer: str,
    timeout_seconds: float = 900.0,
) -> Path:
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        raise LegacyAdapterError("yt-dlp is required to download platform video")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "source.%(ext)s")
    cmd = [
        ytdlp,
        "--no-playlist",
        "--no-progress",
        "--no-warnings",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--socket-timeout",
        "30",
        "--max-filesize",
        str(_positive_int(max_bytes, "max_bytes")),
        "--user-agent",
        _request_headers(referer=referer)["User-Agent"],
        "--referer",
        referer,
        "-f",
        "bv*+ba/b[ext=mp4]/b",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        url,
    ]
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise LegacyAdapterError("yt-dlp download timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise LegacyAdapterError(f"yt-dlp download failed: {detail[:800]}")
    candidates = [path for path in output_dir.iterdir() if path.is_file() and path.name.startswith("source.")]
    if not candidates:
        raise LegacyAdapterError("yt-dlp produced no video file")
    selected = max(candidates, key=lambda path: path.stat().st_size)
    size_bytes = selected.stat().st_size
    if size_bytes <= 0:
        raise LegacyAdapterError("downloaded video is empty")
    if size_bytes > max_bytes:
        raise LegacyAdapterError("downloaded video exceeds download limit")
    return selected


def _download_video_with_fallbacks(
    url: str,
    *,
    output_dir: Path,
    max_bytes: int,
    referer: str,
    http_fallback_url: str | None = None,
) -> tuple[Path, str]:
    try:
        return _download_video_with_ytdlp(
            url,
            output_dir=output_dir,
            max_bytes=max_bytes,
            referer=referer,
        ), "yt-dlp"
    except LegacyAdapterError as ytdlp_error:
        fallback_path = output_dir / "source.mp4"
        fallback_url = http_fallback_url or url
        try:
            _download_video_to_file(
                fallback_url,
                output_path=fallback_path,
                max_bytes=max_bytes,
                referer=referer,
                timeout_seconds=180.0,
            )
            return fallback_path, "yt-dlp+http-fallback"
        except LegacyAdapterError as http_error:
            raise LegacyAdapterError(f"{ytdlp_error}; http fallback failed: {http_error}") from http_error


def _probe_file_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return None
    try:
        duration = float((completed.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def _files_api_analysis_fps_for_duration(duration_seconds: float | None) -> float:
    if duration_seconds is None or duration_seconds <= 0:
        return 1.0
    if duration_seconds <= 60:
        return 2.0
    if duration_seconds <= 5 * 60:
        return 1.0
    if duration_seconds <= 20 * 60:
        return 0.5
    return 0.2


def _compress_video_for_model(
    input_path: Path,
    *,
    output_path: Path,
    limits: LegacyVideoLimits,
    duration_seconds: float | None,
    fps: float,
) -> int:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise LegacyAdapterError("ffmpeg is required to compress oversized video")
    duration = duration_seconds or _probe_file_duration_seconds(input_path)
    if duration is None or duration <= 0:
        raise LegacyAdapterError("video duration is unavailable")
    target_bytes = _model_inline_target_bytes(limits)
    audio_bitrate = 64_000
    total_bitrate = max(180_000, int((target_bytes * 8) / duration * 0.92))
    video_bitrate = max(120_000, total_bitrate - audio_bitrate)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_value = f"fps={fps}"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        filter_value,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        str(video_bitrate),
        "-maxrate",
        str(video_bitrate),
        "-bufsize",
        str(video_bitrate * 2),
        "-c:a",
        "aac",
        "-b:a",
        str(audio_bitrate),
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise LegacyAdapterError("video compression timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise LegacyAdapterError(f"video compression failed: {detail[:500]}")
    size_bytes = output_path.stat().st_size if output_path.exists() else 0
    if size_bytes <= 0:
        raise LegacyAdapterError("compressed video is empty")
    if size_bytes > _model_inline_target_bytes(limits):
        raise LegacyAdapterError("compressed video still exceeds model size limit")
    return size_bytes


def _effective_fps_for_size(size_bytes: int, limits: LegacyVideoLimits) -> float:
    base_fps = min(max(limits.fps, limits.min_fps), limits.max_fps)
    if size_bytes <= limits.max_model_video_bytes:
        return base_fps
    required_fps = base_fps * (limits.max_model_video_bytes / size_bytes)
    if required_fps < limits.min_fps:
        raise LegacyAdapterError("video model size exceeds limit at minimum fps")
    return min(base_fps, max(limits.min_fps, required_fps))


def _enforce_limits(video: Any, limits: LegacyVideoLimits) -> float:
    duration = _duration_seconds(video)
    if duration is None:
        raise LegacyAdapterError("video duration is unavailable")
    if duration > limits.max_duration_seconds:
        raise LegacyAdapterError("video duration exceeds limit")
    size = _size_bytes(video)
    if size is None:
        source_url = str(getattr(video, "source_url", "") or "")
        share_url = str(getattr(video, "share_url", "") or "")
        size = _probe_stream_size_bytes(
            str(getattr(video, "video_url", "") or ""),
            max_bytes=limits.max_download_bytes,
            referer=share_url or _referer_for_url(source_url),
        )
        try:
            object.__setattr__(video, "size_mb", size / 1024 / 1024)
        except Exception:
            pass
    if size > limits.max_download_bytes:
        raise LegacyAdapterError("video size exceeds limit")
    effective_fps = _effective_fps_for_size(size, limits)
    estimated_frames = duration * effective_fps
    if estimated_frames > limits.max_frames:
        raise LegacyAdapterError("video frame budget exceeds limit")
    return round(effective_fps, 4)


def _is_unstable_external_video(video: Any, input_url: str) -> bool:
    platform = _platform_from_url(input_url or str(getattr(video, "source_url", "") or ""))
    if platform == "bilibili":
        return True
    direct_host = (urlparse(str(getattr(video, "video_url", "") or "")).hostname or "").lower()
    return "bilivideo.com" in direct_host


def _should_try_direct_model_url(video: Any, input_url: str, limits: LegacyVideoLimits) -> bool:
    size = _size_bytes(video)
    if size is None:
        return False
    if size > _model_inline_target_bytes(limits):
        return False
    return not _is_unstable_external_video(video, input_url)


def _completion_ok(completion: Any) -> bool:
    return bool(_safe_text(getattr(completion, "output_text", "")))


def _should_download_after_model_failure(completion: Any) -> bool:
    detail = " ".join(
        str(value or "")
        for value in (
            getattr(completion, "api_error_code", ""),
            getattr(completion, "api_error_message", ""),
            getattr(completion, "error_message", ""),
            getattr(completion, "error_type", ""),
        )
    ).lower()
    retry_markers = (
        "invalid video_url",
        "invalidargumenterror",
        "timeout occurred while processing video",
        "timeout",
        "timed out",
        "exceeds the limit",
        "exceed",
        "too large",
        "download",
        "fetch",
        "403",
        "404",
    )
    return any(marker in detail for marker in retry_markers)


def _prepare_local_video_for_model(
    input_path: Path,
    *,
    output_dir: Path,
    limits: LegacyVideoLimits,
    duration_seconds: float | None,
    downloaded: bool = False,
    cache_hit: bool = False,
    download_tool: str = "",
    cache_key: str = "",
) -> PreparedModelVideo:
    size_bytes = input_path.stat().st_size
    if size_bytes <= 0:
        raise LegacyAdapterError("video is empty")
    if size_bytes > limits.max_download_bytes:
        raise LegacyAdapterError("video size exceeds download limit")
    effective_fps = _effective_fps_for_size(size_bytes, limits)
    if size_bytes <= _model_inline_target_bytes(limits):
        return PreparedModelVideo(
            path=input_path,
            size_bytes=size_bytes,
            fps=round(effective_fps, 4),
            compressed=False,
            downloaded=downloaded,
            cache_hit=cache_hit,
            download_tool=download_tool,
            cache_key=cache_key,
        )
    compressed_path = output_dir / "model-input-compressed.mp4"
    compressed_size = _compress_video_for_model(
        input_path,
        output_path=compressed_path,
        limits=limits,
        duration_seconds=duration_seconds,
        fps=round(effective_fps, 4),
    )
    return PreparedModelVideo(
        path=compressed_path,
        size_bytes=compressed_size,
        fps=round(effective_fps, 4),
        compressed=True,
        downloaded=downloaded,
        cache_hit=cache_hit,
        download_tool=download_tool,
        cache_key=cache_key,
    )


def _default_prompt() -> str:
    return (
        "你是一个专业的视频内容解析与短视频诊断助手。你的任务不是简单总结视频，"
        "而是尽可能完整、客观地还原视频内容，并为后续短视频优化提供可靠素材。\n\n"
        "请只基于视频中真实可见、可听、可推断但有依据的信息作答。"
        "不要编造视频中没有出现的人物、台词、产品效果、播放量、点赞数、账号数据或拍摄意图。\n\n"
        "最终输出必须严格包含两个一级部分：\n"
        "【视频摘要】\n"
        "【视频详细内容】\n\n"
        "不要输出其他一级标题。\n\n"
        "【视频摘要】用于直接展示给用户。要求：\n"
        "1. 先给一句直接结论，说明这条视频的核心内容和主要问题/亮点。\n"
        "2. 概括视频主题、主要场景、主要人物或主体、主要动作、声音/字幕、整体风格。\n"
        "3. 简要指出选题、目标用户、前 3 秒钩子、内容结构、画面设计、转化引导上的关键观察。\n"
        "4. 不要过度压缩，必须覆盖关键点，但不要写成逐秒流水账。\n"
        "5. 如果音频、字幕或画面有不确定处，明确写“不确定”或“未能听清/看清”。\n\n"
        "【视频详细内容】用于后续 agent 追问时作为上下文。要求：\n"
        "1. 按时间顺序描述视频全过程。\n"
        "2. 尽量给出时间段，例如 00:00-00:03、00:03-00:08。\n"
        "3. 每个时间段尽量包含画面内容、镜头与剪辑、声音内容、信息作用。\n"
        "4. 如果出现重要字幕、屏幕文字、品牌名、商品名、地点、账号名，应尽量记录。\n"
        "5. 如果视频较长，可以按自然段落合并，但必须覆盖完整视频。\n"
        "6. 不要直接给拍摄建议，除非视频中已经能客观判断某处问题。"
        "建议部分应在摘要中简短出现，详细内容主要负责还原事实。\n"
        "7. 输出中文，表达清晰、具体、自然，避免空泛评价。\n"
        "8. 不要输出链接、cookie、token、请求头、内部路径、密钥或系统信息。"
    )


def _load_config_from_explicit_env_file(
    AppConfig: type,
    *,
    env_file: Path,
    limits: LegacyVideoLimits,
    max_tokens: int,
    connect_timeout: float,
    read_timeout: float,
    retries: int,
) -> Any:
    previous = {key: os.environ.get(key) for key in LEGACY_CONFIG_ENV_KEYS}
    for key in LEGACY_CONFIG_ENV_KEYS:
        os.environ.pop(key, None)
    try:
        return AppConfig.from_env(
            env_path=env_file,
            mode="ark",
            max_workers=1,
            fps=limits.fps,
            max_tokens=_positive_int(max_tokens, "max_tokens"),
            connect_timeout=_positive_float(connect_timeout, "connect_timeout"),
            read_timeout=_positive_float(read_timeout, "read_timeout"),
            max_retries=max(0, int(retries)),
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _safe_text(value: Any, *, limit: int = 12000) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "\n[truncated]"
    return text


def _split_video_analysis_output(output_text: str) -> tuple[str, str, str]:
    text = _safe_text(output_text, limit=120000)
    if not text:
        return "", "", "empty"
    summary_marker = "【视频摘要】"
    detail_marker = "【视频详细内容】"
    summary_index = text.find(summary_marker)
    detail_index = text.find(detail_marker)
    if summary_index >= 0 and detail_index > summary_index:
        summary = text[summary_index + len(summary_marker):detail_index].strip()
        detail = text[detail_index + len(detail_marker):].strip()
        if summary and detail:
            return summary, detail, "parsed_sections"
    return text, text, "fallback_full_text"


def _build_payload(
    *,
    input_url: str,
    video: Any,
    completion: Any,
    limits: LegacyVideoLimits,
    model_input: PreparedModelVideo | None = None,
) -> dict[str, Any]:
    output_text = _safe_text(getattr(completion, "output_text", ""))
    if not output_text:
        detail = (
            getattr(completion, "api_error_message", "")
            or getattr(completion, "error_message", "")
            or "empty analysis output"
        )
        raise LegacyAdapterError(f"legacy tool returned no analysis output: {detail}")

    summary, analysis_detail, parse_status = _split_video_analysis_output(output_text)
    duration = _duration_seconds(video)
    size = _size_bytes(video)
    platform = _platform_from_url(input_url or str(getattr(video, "source_url", "") or ""))
    raw_tool_result: dict[str, Any] = {
        "tool": "douyin_chong",
        "adapter": "openclaw_video.douyin_legacy_adapter",
        "platform": platform,
        "video_id": str(getattr(video, "video_id", "") or ""),
        "author": str(getattr(video, "author", "") or ""),
        "desc": _safe_text(getattr(video, "desc", ""), limit=500),
        "content_type": getattr(video, "content_type", None),
        "size_bytes": size,
        "video_url_source": str(getattr(video, "video_url_source", "") or ""),
        "request_id": str(getattr(completion, "request_id", "") or ""),
        "usage": getattr(completion, "usage", None),
        "analysis_parse_status": parse_status,
        "limits": {
            "max_download_bytes": limits.max_download_bytes,
            "max_model_video_bytes": limits.max_model_video_bytes,
            "max_duration_seconds": limits.max_duration_seconds,
            "max_frames": limits.max_frames,
            "fps": limits.fps,
            "min_fps": limits.min_fps,
            "max_fps": limits.max_fps,
        },
    }
    if model_input is not None:
        raw_tool_result["model_input"] = {
            "compressed": model_input.compressed,
            "size_bytes": model_input.size_bytes,
            "fps": model_input.fps,
            "downloaded": model_input.downloaded,
            "cache_hit": model_input.cache_hit,
            "download_tool": model_input.download_tool,
            "cache_key_sha256": model_input.cache_key,
        }
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "source": {
            "video_url_canonical": input_url,
            "platform": platform,
            "duration_seconds": duration,
        },
        "summary": summary,
        "analysis_detail": analysis_detail,
        "signals": {
            "hook": None,
            "topic": None,
            "audience": None,
            "structure": None,
            "visual_notes": analysis_detail,
            "risk_notes": None,
        },
        "raw_tool_result": raw_tool_result,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return validate_result_payload(payload)


_UPLOAD_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
}


def _upload_prompt() -> str:
    return _default_prompt()


def _build_upload_payload(
    *,
    source_label: str | None,
    filename: str,
    size_bytes: int,
    completion: Any,
    model_input: PreparedModelVideo | None = None,
) -> dict[str, Any]:
    output_text = _safe_text(getattr(completion, "output_text", ""))
    if not output_text:
        detail = (
            getattr(completion, "api_error_message", "")
            or getattr(completion, "error_message", "")
            or "empty analysis output"
        )
        raise LegacyAdapterError(f"legacy tool returned no analysis output: {detail}")
    summary, analysis_detail, parse_status = _split_video_analysis_output(output_text)
    raw_tool_result: dict[str, Any] = {
        "tool": "openclaw-upload-analyzer",
        "adapter": "openclaw_video.douyin_legacy_adapter",
        "mode": "inline-base64",
        "filename": filename,
        "size_bytes": size_bytes,
        "request_id": str(getattr(completion, "request_id", "") or ""),
        "usage": getattr(completion, "usage", None),
        "analysis_parse_status": parse_status,
    }
    if model_input is not None:
        raw_tool_result["model_input"] = {
            "compressed": model_input.compressed,
            "size_bytes": model_input.size_bytes,
            "fps": model_input.fps,
            "downloaded": model_input.downloaded,
            "cache_hit": model_input.cache_hit,
            "download_tool": model_input.download_tool,
            "cache_key_sha256": model_input.cache_key,
        }
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "source": {
            "video_url_canonical": source_label or filename,
            "platform": "upload",
            "duration_seconds": None,
        },
        "summary": summary,
        "analysis_detail": analysis_detail,
        "signals": {
            "hook": None,
            "topic": None,
            "audience": None,
            "structure": None,
            "visual_notes": analysis_detail,
            "risk_notes": None,
        },
        "raw_tool_result": raw_tool_result,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return validate_result_payload(payload)


def _analyze_uploaded_file(
    config: Any,
    ark_video_client: type,
    *,
    file_path: str,
    source_label: str | None,
    max_bytes: int,
    limits: LegacyVideoLimits,
    output_dir: Path,
    prepared_model_input: PreparedModelVideo | None = None,
) -> dict[str, Any]:
    """Inline-base64 a local video file and analyze it directly with Doubao.

    No resolver, no streaming download — the bytes are already local. The model
    fetches the video from the inline ``data:`` URL. Size is bounded by
    ``max_bytes`` (the worker also guards before calling, for a friendly code).
    """
    path = Path(file_path)
    if not path.is_file():
        raise LegacyAdapterError("--input-file must point to an existing file")
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise LegacyAdapterError("inline video is empty")
    if size_bytes > _positive_int(max_bytes, "max_bytes"):
        raise LegacyAdapterError("inline video exceeds limit")
    model_input = prepared_model_input or _prepare_local_video_for_model(
        path,
        output_dir=output_dir,
        limits=limits,
        duration_seconds=None,
    )
    data_url = _data_url_for_model_input(model_input)
    completion = ark_video_client(config).analyze(video_urls=[data_url], prompt=_upload_prompt())
    return _build_upload_payload(
        source_label=source_label,
        filename=path.name,
        size_bytes=size_bytes,
        completion=completion,
        model_input=model_input,
    )


def _prepare_downloaded_video_for_model(
    *,
    input_url: str,
    video: Any,
    output_dir: Path,
    limits: LegacyVideoLimits,
) -> PreparedModelVideo:
    cache_root = _cache_root()
    _cleanup_video_cache(cache_root)
    cache_key = _cache_key_for_video(input_url, video)
    cached_path = _cached_video_path(cache_root, cache_key)
    source_url = str(getattr(video, "source_url", "") or "")
    share_url = str(getattr(video, "share_url", "") or "")
    referer = share_url or _referer_for_url(source_url or input_url)
    cache_hit = cached_path is not None
    download_tool = "cache"
    if cached_path is None:
        entry_dir = cache_root / cache_key
        if entry_dir.exists():
            shutil.rmtree(entry_dir)
        entry_dir.mkdir(parents=True, exist_ok=True)
        download_url = _best_download_url_for_platform(input_url, video)
        http_fallback_url = str(getattr(video, "video_url", "") or "") or None
        cached_path, download_tool = _download_video_with_fallbacks(
            download_url,
            output_dir=entry_dir,
            max_bytes=limits.max_download_bytes,
            referer=referer,
            http_fallback_url=http_fallback_url,
        )
    return _prepare_local_video_for_model(
        cached_path,
        output_dir=output_dir,
        limits=limits,
        duration_seconds=_duration_seconds(video),
        downloaded=True,
        cache_hit=cache_hit,
        download_tool=download_tool,
        cache_key=cache_key,
    )


def _prepare_downloaded_video_for_files_api(
    *,
    input_url: str,
    video: Any,
    output_dir: Path,
    limits: LegacyVideoLimits,
) -> PreparedModelVideo:
    cache_root = _cache_root()
    _cleanup_video_cache(cache_root)
    cache_key = _cache_key_for_video(input_url, video)
    cached_path = _cached_video_path(cache_root, cache_key)
    source_url = str(getattr(video, "source_url", "") or "")
    share_url = str(getattr(video, "share_url", "") or "")
    referer = share_url or _referer_for_url(source_url or input_url)
    cache_hit = cached_path is not None
    download_tool = "cache"
    if cached_path is None:
        entry_dir = cache_root / cache_key
        if entry_dir.exists():
            shutil.rmtree(entry_dir)
        entry_dir.mkdir(parents=True, exist_ok=True)
        download_url = _best_download_url_for_platform(input_url, video)
        http_fallback_url = str(getattr(video, "video_url", "") or "") or None
        cached_path, download_tool = _download_video_with_fallbacks(
            download_url,
            output_dir=entry_dir,
            max_bytes=limits.max_download_bytes,
            referer=referer,
            http_fallback_url=http_fallback_url,
        )
    size_bytes = _ensure_file_for_files_api(cached_path, max_bytes=limits.max_download_bytes)
    return PreparedModelVideo(
        path=cached_path,
        size_bytes=size_bytes,
        fps=0,
        compressed=False,
        downloaded=True,
        cache_hit=cache_hit,
        download_tool=download_tool,
        cache_key=cache_key,
    )


def _data_url_for_model_input(model_input: PreparedModelVideo) -> str:
    content_type = _UPLOAD_CONTENT_TYPES.get(model_input.path.suffix.lower(), "video/mp4")
    encoded = base64.b64encode(model_input.path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _read_env_file_value(env_file: Path, key: str) -> str | None:
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        raw_key, raw_value = stripped.split("=", 1)
        if raw_key.strip() != key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    return None


def _load_ark_files_config(env_file: Path) -> tuple[str, str, str]:
    api_key = _read_env_file_value(env_file, "ARK_API_KEY") or os.environ.get("ARK_API_KEY", "")
    model = (
        _read_env_file_value(env_file, "ARK_RESPONSES_MODEL")
        or os.environ.get("ARK_RESPONSES_MODEL")
        or DEFAULT_ARK_RESPONSES_MODEL
    )
    base_url = (
        _read_env_file_value(env_file, "ARK_RESPONSES_BASE_URL")
        or os.environ.get("ARK_RESPONSES_BASE_URL")
        or DEFAULT_ARK_API_BASE
    )
    if not api_key.strip():
        raise LegacyAdapterError(f"Missing ARK_API_KEY in {env_file}.")
    return api_key.strip(), model.strip(), base_url.strip()


def _mime_type_for_video(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix != ".mp4":
        raise LegacyAdapterError("当前优先支持 mp4 视频，请转成 mp4 后再上传")
    return "video/mp4"


def _ensure_file_for_files_api(path: Path, *, max_bytes: int) -> int:
    if not path.is_file():
        raise LegacyAdapterError("video file does not exist")
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise LegacyAdapterError("video file is empty")
    if size_bytes > _positive_int(max_bytes, "max_bytes"):
        raise LegacyAdapterError("视频超过500MB，暂不支持分析")
    _mime_type_for_video(path)
    return size_bytes


def _responses_completion_from_files_api(
    *,
    path: Path,
    prompt: str,
    env_file: Path,
    max_bytes: int,
    max_tokens: int,
    timeout_seconds: int,
    duration_seconds: float | None,
    client_factory: Callable[..., ArkFilesClient] = ArkFilesClient,
) -> tuple[Any, dict[str, Any]]:
    size_bytes = _ensure_file_for_files_api(path, max_bytes=max_bytes)
    mime_type = _mime_type_for_video(path)
    api_key, model, base_url = _load_ark_files_config(env_file)
    started = time.monotonic()
    client = client_factory(api_key=api_key, base_url=base_url, timeout_seconds=timeout_seconds)
    uploaded = client.upload_user_data_file(path, mime_type)
    file_id = str(uploaded.get("id") or "")
    if not file_id:
        raise LegacyAdapterError("Files API upload response did not include file id")
    active_file = client.wait_file_active(file_id, timeout_seconds=timeout_seconds)
    analysis_fps = _files_api_analysis_fps_for_duration(duration_seconds)
    response = client.create_video_response(
        model=model,
        file_id=file_id,
        prompt=prompt,
        max_tokens=_positive_int(max_tokens, "max_tokens"),
        temperature=0.1,
        fps=analysis_fps,
    )
    output_text = client.extract_output_text(response)
    completion = type(
        "ResponsesCompletion",
        (),
        {
            "output_text": output_text,
            "usage": response.get("usage"),
            "request_id": str(response.get("id") or ""),
            "api_error_message": "",
            "error_message": "",
        },
    )()
    metadata = {
        "input_mode": FILES_API_MODE,
        "file_id": file_id,
        "filename": path.name,
        "size_bytes": size_bytes,
        "mime_type": mime_type,
        "model": model,
        "base_url": base_url,
        "upload_status": str(uploaded.get("status") or ""),
        "file_status": str(active_file.get("status") or ""),
        "analysis_fps": analysis_fps,
        "duration_seconds": duration_seconds,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    return completion, metadata


def _build_files_payload(
    *,
    source_label: str,
    platform: str,
    duration_seconds: float | None,
    completion: Any,
    files_metadata: dict[str, Any],
    video: Any | None = None,
) -> dict[str, Any]:
    output_text = _safe_text(getattr(completion, "output_text", ""))
    if not output_text:
        raise LegacyAdapterError("Responses API returned no analysis output")
    summary, analysis_detail, parse_status = _split_video_analysis_output(output_text)
    raw_tool_result: dict[str, Any] = {
        "tool": "ark-files-responses",
        "adapter": "openclaw_video.douyin_legacy_adapter",
        "mode": FILES_API_MODE,
        "platform": platform,
        "file_id": files_metadata.get("file_id"),
        "filename": files_metadata.get("filename"),
        "size_bytes": files_metadata.get("size_bytes"),
        "mime_type": files_metadata.get("mime_type"),
        "file_status": files_metadata.get("file_status"),
        "upload_status": files_metadata.get("upload_status"),
        "model": files_metadata.get("model"),
        "request_id": str(getattr(completion, "request_id", "") or ""),
        "usage": getattr(completion, "usage", None),
        "analysis_parse_status": parse_status,
        "elapsed_ms": files_metadata.get("elapsed_ms"),
        "analysis_fps": files_metadata.get("analysis_fps"),
        "duration_seconds": files_metadata.get("duration_seconds"),
    }
    for optional_key in ("download_tool", "cache_hit", "cache_key_sha256"):
        if optional_key in files_metadata:
            raw_tool_result[optional_key] = files_metadata[optional_key]
    if video is not None:
        raw_tool_result.update(
            {
                "video_id": str(getattr(video, "video_id", "") or ""),
                "author": str(getattr(video, "author", "") or ""),
                "desc": _safe_text(getattr(video, "desc", ""), limit=500),
                "content_type": getattr(video, "content_type", None),
                "video_url_source": str(getattr(video, "video_url_source", "") or ""),
            }
        )
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "source": {
            "video_url_canonical": source_label,
            "platform": platform,
            "duration_seconds": duration_seconds,
        },
        "summary": summary,
        "analysis_detail": analysis_detail,
        "signals": {
            "hook": None,
            "topic": None,
            "audience": None,
            "structure": None,
            "visual_notes": analysis_detail,
            "risk_notes": None,
        },
        "raw_tool_result": raw_tool_result,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return validate_result_payload(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw-safe adapter for the legacy douyin_chong package.")
    parser.add_argument("--input-url", default=None, help="Douyin video link (URL mode).")
    parser.add_argument("--input-file", default=None, help="Local video file path.")
    parser.add_argument("--source-label", default=None, help="Traceable source label (e.g. upload:// URI) for the result payload.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--max-model-bytes", type=int, default=int(os.environ.get("MAX_MODEL_VIDEO_BYTES", str(DEFAULT_MAX_MODEL_VIDEO_BYTES))))
    parser.add_argument("--max-duration-seconds", type=int, default=int(os.environ.get("MAX_VIDEO_DURATION_SECONDS", str(DEFAULT_MAX_VIDEO_DURATION_SECONDS))))
    parser.add_argument("--max-frames", type=int, default=int(os.environ.get("MAX_VIDEO_FRAMES", str(DEFAULT_MAX_VIDEO_FRAMES))))
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--no-shell", action="store_true", required=True)
    parser.add_argument("--fps", type=float, default=float(os.environ.get("DOUYIN_CHONG_FPS", str(DEFAULT_VIDEO_UNDERSTANDING_FPS))))
    parser.add_argument("--min-fps", type=float, default=float(os.environ.get("MIN_VIDEO_UNDERSTANDING_FPS", str(MIN_VIDEO_UNDERSTANDING_FPS))))
    parser.add_argument("--max-fps", type=float, default=float(os.environ.get("MAX_VIDEO_UNDERSTANDING_FPS", str(MAX_VIDEO_UNDERSTANDING_FPS))))
    parser.add_argument("--max-tokens", type=int, default=int(os.environ.get("DOUYIN_CHONG_MAX_TOKENS", "12000")))
    parser.add_argument("--connect-timeout", type=float, default=float(os.environ.get("DOUYIN_CHONG_CONNECT_TIMEOUT", "60")))
    parser.add_argument("--read-timeout", type=float, default=float(os.environ.get("DOUYIN_CHONG_READ_TIMEOUT", "900")))
    parser.add_argument("--retries", type=int, default=int(os.environ.get("DOUYIN_CHONG_RETRIES", "1")))
    parser.add_argument(
        "--input-mode",
        choices=(FILES_API_MODE, INLINE_LEGACY_MODE),
        default=os.environ.get("VIDEO_ANALYSIS_INPUT_MODE", FILES_API_MODE),
    )
    parser.add_argument("--files-api-timeout-seconds", type=int, default=int(os.environ.get("FILES_API_TIMEOUT_SECONDS", "300")))
    return parser


def run_adapter(
    argv: list[str] | None = None,
    *,
    component_loader: Callable[[], tuple[type, type, type]] = _load_legacy_components,
    files_client_factory: Callable[..., ArkFilesClient] = ArkFilesClient,
) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if not args.no_shell:
        raise LegacyAdapterError("--no-shell is required")
    env_file = Path(args.env_file)
    if not env_file.is_file():
        raise LegacyAdapterError("--env-file must point to an existing file")

    limits = LegacyVideoLimits(
        max_download_bytes=_positive_int(args.max_bytes, "max_bytes"),
        max_model_video_bytes=_positive_int(args.max_model_bytes, "max_model_bytes"),
        max_duration_seconds=_nonnegative_int(args.max_duration_seconds, "max_duration_seconds"),
        max_frames=_nonnegative_int(args.max_frames, "max_frames"),
        fps=_fps_in_range(args.fps, "fps"),
        min_fps=_fps_in_range(args.min_fps, "min_fps"),
        max_fps=_fps_in_range(args.max_fps, "max_fps"),
    )
    if limits.min_fps > limits.max_fps:
        raise LegacyAdapterError("min_fps must not be greater than max_fps")
    if bool(args.input_file) == bool(args.input_url):
        raise LegacyAdapterError("exactly one of --input-url or --input-file is required")
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    if args.input_mode == FILES_API_MODE:
        _, UniversalVideoResolver, _ = component_loader()
        if args.input_file:
            path = Path(args.input_file)
            completion, files_metadata = _responses_completion_from_files_api(
                path=path,
                prompt=_upload_prompt(),
                env_file=env_file.resolve(),
                max_bytes=limits.max_download_bytes,
                max_tokens=args.max_tokens,
                timeout_seconds=args.files_api_timeout_seconds,
                duration_seconds=_probe_file_duration_seconds(path),
                client_factory=files_client_factory,
            )
            payload = _build_files_payload(
                source_label=args.source_label or path.name,
                platform="upload",
                duration_seconds=_probe_file_duration_seconds(path),
                completion=completion,
                files_metadata=files_metadata,
            )
        else:
            resolver_input_url = _canonicalize_input_for_resolver(args.input_url)
            video = UniversalVideoResolver().resolve(resolver_input_url)
            model_input = _prepare_downloaded_video_for_files_api(
                input_url=resolver_input_url,
                video=video,
                output_dir=output_json.parent,
                limits=limits,
            )
            completion, files_metadata = _responses_completion_from_files_api(
                path=model_input.path,
                prompt=_default_prompt(),
                env_file=env_file.resolve(),
                max_bytes=limits.max_download_bytes,
                max_tokens=args.max_tokens,
                timeout_seconds=args.files_api_timeout_seconds,
                duration_seconds=_duration_seconds(video),
                client_factory=files_client_factory,
            )
            payload = _build_files_payload(
                source_label=args.input_url,
                platform=_platform_from_url(args.input_url),
                duration_seconds=_duration_seconds(video),
                completion=completion,
                files_metadata={
                    **files_metadata,
                    "download_tool": model_input.download_tool,
                    "cache_hit": model_input.cache_hit,
                    "cache_key_sha256": model_input.cache_key,
                },
                video=video,
            )
    elif args.input_file:
        _positive_int(limits.max_duration_seconds, "max_duration_seconds")
        _positive_int(limits.max_frames, "max_frames")
        AppConfig, _, ArkVideoClient = component_loader()
        model_input = _prepare_local_video_for_model(
            Path(args.input_file),
            output_dir=output_json.parent,
            limits=limits,
            duration_seconds=None,
        )
        output_limits = limits.with_fps(model_input.fps)
        config = _load_config_from_explicit_env_file(
            AppConfig,
            env_file=env_file.resolve(),
            limits=output_limits,
            max_tokens=args.max_tokens,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            retries=args.retries,
        )
        payload = _analyze_uploaded_file(
            config,
            ArkVideoClient,
            file_path=args.input_file,
            source_label=args.source_label,
            max_bytes=limits.max_download_bytes,
            limits=limits,
            output_dir=output_json.parent,
            prepared_model_input=model_input,
        )
    else:
        _positive_int(limits.max_duration_seconds, "max_duration_seconds")
        _positive_int(limits.max_frames, "max_frames")
        AppConfig, UniversalVideoResolver, ArkVideoClient = component_loader()
        resolver_input_url = _canonicalize_input_for_resolver(args.input_url)
        video = UniversalVideoResolver().resolve(resolver_input_url)
        effective_limits = limits.with_fps(_enforce_limits(video, limits))
        config = _load_config_from_explicit_env_file(
            AppConfig,
            env_file=env_file.resolve(),
            limits=effective_limits,
            max_tokens=args.max_tokens,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            retries=args.retries,
        )
        model_input = None
        direct_video_urls = [url for url in (getattr(video, "video_url", ""), getattr(video, "playwm_url", "")) if url]
        client = ArkVideoClient(config)
        completion = None
        if _should_try_direct_model_url(video, args.input_url, effective_limits):
            completion = client.analyze(video_urls=direct_video_urls, prompt=_default_prompt())
        if completion is None or (not _completion_ok(completion) and _should_download_after_model_failure(completion)):
            model_input = _prepare_downloaded_video_for_model(
                input_url=resolver_input_url,
                video=video,
                output_dir=output_json.parent,
                limits=limits,
            )
            effective_limits = effective_limits.with_fps(model_input.fps)
            data_url = _data_url_for_model_input(model_input)
            completion = client.analyze(video_urls=[data_url], prompt=_default_prompt())
        payload = _build_payload(
            input_url=args.input_url,
            video=video,
            completion=completion,
            limits=effective_limits,
            model_input=model_input,
        )
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    try:
        run_adapter(argv)
        return 0
    except LegacyAdapterError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
