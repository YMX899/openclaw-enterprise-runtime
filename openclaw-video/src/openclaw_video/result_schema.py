from __future__ import annotations

from datetime import UTC, datetime


RESULT_SCHEMA_VERSION = "openclaw-video-result.v1"


class ResultSchemaError(ValueError):
    pass


def validate_result_payload(payload: dict) -> dict:
    """Validate the minimum result contract without external dependencies."""

    if not isinstance(payload, dict):
        raise ResultSchemaError("result payload must be an object")
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ResultSchemaError("invalid schema_version")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ResultSchemaError("source is required")
    if source.get("platform") not in {"bilibili", "douyin", "tiktok", "xiaohongshu", "upload"}:
        raise ResultSchemaError("source.platform must be bilibili, douyin, tiktok, xiaohongshu, or upload")
    if not source.get("video_url_canonical"):
        raise ResultSchemaError("source.video_url_canonical is required")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        raise ResultSchemaError("summary is required")
    if "analysis_detail" in payload and (
        not isinstance(payload["analysis_detail"], str) or not payload["analysis_detail"].strip()
    ):
        raise ResultSchemaError("analysis_detail must be a non-empty string")
    if not isinstance(payload.get("signals"), dict):
        raise ResultSchemaError("signals object is required")
    if not payload.get("created_at"):
        payload = {**payload, "created_at": datetime.now(UTC).isoformat()}
    return payload
