from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .result_schema import RESULT_SCHEMA_VERSION, validate_result_payload
from .url_guard import UrlRejected, validate_video_url_with_redirects
from .video_limits import DEFAULT_MAX_VIDEO_DURATION_SECONDS, DEFAULT_MAX_VIDEO_FRAMES


class LegacyAdapterError(RuntimeError):
    pass


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
    max_duration_seconds: int
    max_frames: int
    fps: float


def _positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise LegacyAdapterError(f"{name} must be positive")
    return value


def _positive_float(value: float, name: str) -> float:
    if value <= 0:
        raise LegacyAdapterError(f"{name} must be positive")
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
    return "douyin"


def _referer_for_url(url: str) -> str:
    platform = _platform_from_url(url)
    if platform == "bilibili":
        return "https://www.bilibili.com/"
    if platform == "tiktok":
        return "https://www.tiktok.com/"
    return "https://www.douyin.com/"


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
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            "Referer": referer,
        },
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


def _enforce_limits(video: Any, limits: LegacyVideoLimits) -> None:
    duration = _duration_seconds(video)
    if duration is None:
        raise LegacyAdapterError("video duration is unavailable")
    if duration > limits.max_duration_seconds:
        raise LegacyAdapterError("video duration exceeds limit")
    estimated_frames = duration * limits.fps
    if estimated_frames > limits.max_frames:
        raise LegacyAdapterError("video frame budget exceeds limit")
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


def _default_prompt() -> str:
    return (
        "Analyze this short video from the supported platform and write the final answer in Simplified Chinese. "
        "Cover topic, opening hook, structure, visuals, actions, audience, risks, and improvement suggestions. "
        "Use Markdown format: `##` section headings, short bullet lists, and bold key phrases. "
        "Keep paragraphs compact and do not wrap the whole answer in a code block. "
        "Do not include links, secrets, request headers, cookies, or internal paths."
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


def _build_payload(
    *,
    input_url: str,
    video: Any,
    completion: Any,
    limits: LegacyVideoLimits,
) -> dict[str, Any]:
    output_text = _safe_text(getattr(completion, "output_text", ""))
    if not output_text:
        detail = (
            getattr(completion, "api_error_message", "")
            or getattr(completion, "error_message", "")
            or "empty analysis output"
        )
        raise LegacyAdapterError(f"legacy tool returned no analysis output: {detail}")

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
        "limits": {
            "max_download_bytes": limits.max_download_bytes,
            "max_duration_seconds": limits.max_duration_seconds,
            "max_frames": limits.max_frames,
            "fps": limits.fps,
        },
    }
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "source": {
            "video_url_canonical": input_url,
            "platform": platform,
            "duration_seconds": duration,
        },
        "summary": output_text,
        "signals": {
            "hook": None,
            "topic": None,
            "audience": None,
            "structure": None,
            "visual_notes": output_text,
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
    return (
        "请分析这条短视频，用简体中文回答：主题、开头 3 秒钩子、内容结构与信息密度、"
        "画面与动作设计、目标人群、风险点，并给出可执行的改进建议（开头改法、脚本改法、复拍要点）。"
        "必须使用 Markdown 格式：用 `##` 小标题、短列表、**加粗关键词**，段落保持紧凑，"
        "不要把整段回复包在代码块里。"
        "不要输出任何链接、密钥、请求头、cookie 或内部路径。"
    )


def _build_upload_payload(
    *,
    source_label: str | None,
    filename: str,
    size_bytes: int,
    completion: Any,
) -> dict[str, Any]:
    output_text = _safe_text(getattr(completion, "output_text", ""))
    if not output_text:
        detail = (
            getattr(completion, "api_error_message", "")
            or getattr(completion, "error_message", "")
            or "empty analysis output"
        )
        raise LegacyAdapterError(f"legacy tool returned no analysis output: {detail}")
    raw_tool_result: dict[str, Any] = {
        "tool": "openclaw-upload-analyzer",
        "adapter": "openclaw_video.douyin_legacy_adapter",
        "mode": "inline-base64",
        "filename": filename,
        "size_bytes": size_bytes,
        "request_id": str(getattr(completion, "request_id", "") or ""),
        "usage": getattr(completion, "usage", None),
    }
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "source": {
            "video_url_canonical": source_label or filename,
            "platform": "upload",
            "duration_seconds": None,
        },
        "summary": output_text,
        "signals": {
            "hook": None,
            "topic": None,
            "audience": None,
            "structure": None,
            "visual_notes": output_text,
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
    content_type = _UPLOAD_CONTENT_TYPES.get(path.suffix.lower(), "video/mp4")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    data_url = f"data:{content_type};base64,{encoded}"
    completion = ark_video_client(config).analyze(video_urls=[data_url], prompt=_upload_prompt())
    return _build_upload_payload(
        source_label=source_label,
        filename=path.name,
        size_bytes=size_bytes,
        completion=completion,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw-safe adapter for the legacy douyin_chong package.")
    parser.add_argument("--input-url", default=None, help="Douyin video link (URL mode).")
    parser.add_argument("--input-file", default=None, help="Local video file path (upload inline-base64 mode).")
    parser.add_argument("--source-label", default=None, help="Traceable source label (e.g. upload:// URI) for the result payload.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--max-duration-seconds", type=int, default=int(os.environ.get("MAX_VIDEO_DURATION_SECONDS", str(DEFAULT_MAX_VIDEO_DURATION_SECONDS))))
    parser.add_argument("--max-frames", type=int, default=int(os.environ.get("MAX_VIDEO_FRAMES", str(DEFAULT_MAX_VIDEO_FRAMES))))
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--no-shell", action="store_true", required=True)
    parser.add_argument("--fps", type=float, default=float(os.environ.get("DOUYIN_CHONG_FPS", "4.0")))
    parser.add_argument("--max-tokens", type=int, default=int(os.environ.get("DOUYIN_CHONG_MAX_TOKENS", "12000")))
    parser.add_argument("--connect-timeout", type=float, default=float(os.environ.get("DOUYIN_CHONG_CONNECT_TIMEOUT", "60")))
    parser.add_argument("--read-timeout", type=float, default=float(os.environ.get("DOUYIN_CHONG_READ_TIMEOUT", "900")))
    parser.add_argument("--retries", type=int, default=int(os.environ.get("DOUYIN_CHONG_RETRIES", "1")))
    return parser


def run_adapter(
    argv: list[str] | None = None,
    *,
    component_loader: Callable[[], tuple[type, type, type]] = _load_legacy_components,
) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if not args.no_shell:
        raise LegacyAdapterError("--no-shell is required")
    env_file = Path(args.env_file)
    if not env_file.is_file():
        raise LegacyAdapterError("--env-file must point to an existing file")

    limits = LegacyVideoLimits(
        max_download_bytes=_positive_int(args.max_bytes, "max_bytes"),
        max_duration_seconds=_positive_int(args.max_duration_seconds, "max_duration_seconds"),
        max_frames=_positive_int(args.max_frames, "max_frames"),
        fps=_positive_float(args.fps, "fps"),
    )
    AppConfig, UniversalVideoResolver, ArkVideoClient = component_loader()
    config = _load_config_from_explicit_env_file(
        AppConfig,
        env_file=env_file.resolve(),
        limits=limits,
        max_tokens=args.max_tokens,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        retries=args.retries,
    )
    if bool(args.input_file) == bool(args.input_url):
        raise LegacyAdapterError("exactly one of --input-url or --input-file is required")
    if args.input_file:
        payload = _analyze_uploaded_file(
            config,
            ArkVideoClient,
            file_path=args.input_file,
            source_label=args.source_label,
            max_bytes=limits.max_download_bytes,
        )
    else:
        resolver_input_url = _canonicalize_input_for_resolver(args.input_url)
        video = UniversalVideoResolver().resolve(resolver_input_url)
        _enforce_limits(video, limits)
        video_urls = [
            url
            for url in (
                getattr(video, "video_url", ""),
                getattr(video, "playwm_url", ""),
            )
            if url
        ]
        completion = ArkVideoClient(config).analyze(video_urls=video_urls, prompt=_default_prompt())
        payload = _build_payload(
            input_url=args.input_url,
            video=video,
            completion=completion,
            limits=limits,
        )
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
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
