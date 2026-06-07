from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
except ImportError as exc:  # pragma: no cover - import checked in container image
    raise RuntimeError("fastapi is required for openclaw-bridge") from exc

from .redaction import safe_error_message
from .dify_client import DifyClient, HuahuoFrontClient
from .identity import (
    DifyPrincipal,
    IdentityError,
    current_workspace_count,
    derive_openclaw_routing_user,
    derive_principal,
    hmac_sha256_hex,
)
from .job_state import TERMINAL_STATUSES
from .job_store import InMemoryJobStore, JobNotFound, JobOwnershipError, VideoJob
from .openclaw_gateway import (
    DisabledGatewayClient,
    GatewayChatRequest,
    GatewayError,
    GatewayNotConfigured,
    OpenClawGatewayWsClient,
)
from .openclaw_auth import (
    OpenClawAuthenticationError,
    default_openclaw_authenticator,
)
from .phase4_controls import (
    Phase4Config,
    Phase4ConfigError,
    SlidingWindowRateLimiter,
    load_phase4_config,
    positive_int_from_env,
)
from .result_schema import RESULT_SCHEMA_VERSION
from .session_store import (
    BridgeMessage,
    BridgeSession,
    InMemorySessionStore,
    MessageValidationError,
    SessionNotFound,
    SessionOwnershipError,
)
from .upload_store import UploadStoreError, delete_upload_uri, store_upload_fileobj
from .url_guard import UrlRejected
from .video_link_probe import VideoLinkProbeConfig, VideoLinkProbeError, probe_video_link


def _serialize_dt(value: Any) -> str | None:
    return value.isoformat() if value else None


def _serialize_session(session: BridgeSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title,
        "created_at": _serialize_dt(session.created_at),
        "updated_at": _serialize_dt(session.updated_at),
    }


def _serialize_message(message: BridgeMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "video_url": message.video_url,
        "job_id": message.job_id,
        "created_at": _serialize_dt(message.created_at),
    }


def _serialize_job(job: VideoJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "session_id": job.bridge_session_id,
        "status": job.status.value,
        "video_url_canonical": job.video_url_canonical,
        "created_at": _serialize_dt(job.created_at),
        "started_at": _serialize_dt(job.started_at),
        "finished_at": _serialize_dt(job.finished_at),
        "attempt_count": job.attempt_count,
        "error_code": job.error_code,
        "result_schema_version": job.result_schema_version,
        "result_location": job.result_location,
    }


def _serialize_result(result: Any) -> dict[str, Any]:
    return {
        "job_id": result.job_id,
        "schema_version": result.schema_version,
        "result": result.result,
        "created_at": _serialize_dt(result.created_at),
    }


def _is_form_upload(value: Any) -> bool:
    return bool(
        value is not None
        and getattr(value, "filename", None)
        and hasattr(value, "file")
        and hasattr(value, "close")
        and hasattr(value, "seek")
    )


def _sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    return f"event: {event}\ndata: {payload}\n\n"


def _has_dify_login_material(headers: Any) -> bool:
    names = {key.lower() for key in headers.keys()}
    return bool(names & {"authorization", "cookie", "x-csrf-token", "x-xsrf-token", "x-huahuo-access-token"})


def _has_header(headers: Any, name: str) -> bool:
    lowered = name.lower()
    return any(key.lower() == lowered and bool(value) for key, value in headers.items())


def _test_identity_headers_allowed(request: Request, enabled: bool, secret: str) -> bool:
    if not enabled or not secret:
        return False
    provided = request.headers.get("x-openclaw-test-identity-secret", "")
    return hmac.compare_digest(provided, secret) and bool(request.headers.get("x-test-account"))


def _principal_hashes(identity_secret: str, principal: DifyPrincipal) -> tuple[str, str]:
    return (
        hmac_sha256_hex(identity_secret, f"tenant:{principal.tenant_id}"),
        hmac_sha256_hex(identity_secret, f"account:{principal.account_id}"),
    )


OPENCLAW_SESSION_COOKIE_NAME = "openclaw_session"


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _session_signature(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("ascii"), sha256).hexdigest()


def _issue_openclaw_session_cookie(
    identity_secret: str,
    principal: DifyPrincipal,
    tenant_hash: str,
    account_hash: str,
    *,
    now: datetime | None = None,
    ttl_seconds: int = 7 * 24 * 60 * 60,
) -> tuple[str, datetime]:
    if ttl_seconds <= 0:
        ttl_seconds = 7 * 24 * 60 * 60
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    payload = {
        "principal_id": principal.principal_id,
        "tenant_hash": tenant_hash,
        "account_hash": account_hash,
        "exp": int(expires_at.timestamp()),
    }
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _session_signature(identity_secret, encoded_payload)
    return encoded_payload + "." + signature, expires_at


def _principal_from_openclaw_session_cookie(
    identity_secret: str,
    cookie_value: str,
    *,
    now: datetime | None = None,
) -> tuple[DifyPrincipal, str, str] | None:
    if not identity_secret or not cookie_value or "." not in cookie_value:
        return None
    encoded_payload, signature = cookie_value.rsplit(".", 1)
    expected = _session_signature(identity_secret, encoded_payload)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        expires_at = int(payload.get("exp"))
    except (TypeError, ValueError):
        return None
    reference = now or datetime.now(UTC)
    if expires_at <= int(reference.timestamp()):
        return None
    principal_id = payload.get("principal_id")
    tenant_hash = payload.get("tenant_hash")
    account_hash = payload.get("account_hash")
    if not all(isinstance(item, str) and len(item) == 64 for item in (principal_id, tenant_hash, account_hash)):
        return None
    principal = DifyPrincipal(account_id=account_hash, tenant_id=tenant_hash, principal_id=principal_id)
    return principal, tenant_hash, account_hash


def _request_is_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


LAB_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenClaw 短视频智能分析</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f4f6f8;
      color: #111827;
      --page: #f4f6f8;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --surface-raised: #fbfcfe;
      --border: #d6dde8;
      --border-strong: #b9c4d3;
      --text: #111827;
      --muted: #5e6a7d;
      --faint: #eef2f7;
      --primary: #1f5eff;
      --primary-strong: #174bd4;
      --analysis: #0f766e;
      --ink: #172033;
      --success: #147a4b;
      --success-bg: #e5f8ef;
      --danger: #b42318;
      --danger-bg: #ffe8e5;
      --warning: #9a5b00;
      --warning-bg: #fff3d7;
      --info: #076678;
      --info-bg: #e1f5f8;
    }
    * { box-sizing: border-box; }
    html { min-height: 100%; background: var(--page); }
    body {
      margin: 0;
      min-height: 100vh;
      overflow-x: hidden;
      background:
        linear-gradient(180deg, #fbfcfe 0, var(--page) 240px, #edf2f7 100%);
      color: var(--text);
    }
    main.shell { width: min(1260px, calc(100% - 32px)); margin: 0 auto; padding: 22px 0 34px; }
    header.topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }
    .brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .brand-copy { min-width: 0; }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 44px;
      height: 44px;
      flex: 0 0 auto;
      border-radius: 8px;
      background: var(--ink);
      color: #ffffff;
      font-weight: 800;
      box-shadow: 0 12px 30px rgba(23, 32, 51, .16);
    }
    .eyebrow { margin: 0 0 3px; color: var(--muted); font-size: 13px; font-weight: 650; }
    .brand-subtitle {
      margin: 5px 0 0;
      max-width: 620px;
      color: #526176;
      font-size: 14px;
      line-height: 1.38;
    }
    h1 { font-size: 30px; line-height: 1.08; margin: 0; font-weight: 760; }
    h2 { font-size: 16px; line-height: 1.25; margin: 0; font-weight: 760; }
    h3 { font-size: 15px; line-height: 1.25; margin: 0; font-weight: 730; }
    .top-status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .flow-steps {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin: 0 0 16px;
    }
    .flow-step {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      min-height: 36px;
      padding: 0 8px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(255, 255, 255, .82);
      color: #526176;
      font-size: 12px;
      font-weight: 760;
      box-shadow: 0 8px 18px rgba(18, 31, 52, .04);
    }
    .flow-step::before {
      content: attr(data-step);
      display: grid;
      place-items: center;
      width: 20px;
      height: 20px;
      border-radius: 999px;
      background: #e8eef7;
      color: #42526a;
      font-size: 11px;
    }
    .flow-step.active {
      border-color: #b8cdfd;
      background: #eef4ff;
      color: #1d4ed8;
    }
    .flow-step.active::before {
      background: var(--primary);
      color: #fff;
    }
    .flow-step.done {
      border-color: #c4e7d4;
      background: #f1fbf6;
      color: var(--success);
    }
    .flow-step.done::before {
      background: var(--success);
      color: #fff;
    }
    .flow-step.locked {
      color: #8290a3;
      background: #f8fafc;
      box-shadow: none;
    }
    .status,
    .run-state,
    .panel-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      border-radius: 8px;
      padding: 7px 10px;
      border: 1px solid transparent;
      background: var(--faint);
      color: #334155;
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }
    .status::before,
    .run-state::before {
      content: "";
      width: 7px;
      height: 7px;
      margin-right: 7px;
      border-radius: 50%;
      background: currentColor;
    }
    .status.ok,
    .run-state.ok { background: var(--success-bg); color: var(--success); border-color: #bdebd2; }
    .status.fail,
    .run-state.fail { background: var(--danger-bg); color: var(--danger); border-color: #ffc9c3; }
    .status.todo,
    .run-state.todo { background: #eef2f7; color: #42526a; border-color: #d6dde8; }
    .run-state.busy { background: var(--info-bg); color: var(--info); border-color: #b9e8ef; }
    .run-state.warn { background: var(--warning-bg); color: var(--warning); border-color: #f4d18f; }
    .panel-badge { background: #f2f6fb; border-color: var(--border); color: #445166; }
    .panel {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(255, 255, 255, .96);
      padding: 16px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, .04), 0 18px 40px rgba(15, 23, 42, .06);
    }
    .panel + .panel { margin-top: 12px; }
    .section-heading {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 12px;
    }
    .step-title {
      display: flex;
      align-items: center;
      gap: 9px;
    }
    .step-index {
      display: inline-grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border-radius: 999px;
      background: #eef4ff;
      color: var(--primary);
      font-size: 12px;
      font-weight: 820;
      flex: 0 0 auto;
    }
    .section-note { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.45; max-width: 640px; }
    label { display: block; font-size: 13px; color: #475569; margin: 10px 0 6px; font-weight: 650; }
    input, textarea {
      width: 100%;
      border: 1px solid var(--border-strong);
      border-radius: 7px;
      min-height: 40px;
      padding: 9px 11px;
      font: inherit;
      color: var(--text);
      background: #fbfcfe;
      box-shadow: inset 0 1px 0 rgba(17, 24, 39, .03);
    }
    input::placeholder, textarea::placeholder { color: #8a96a8; }
    input:focus-visible,
    textarea:focus-visible,
    button:focus-visible {
      outline: 3px solid rgba(31, 94, 255, .18);
      outline-offset: 2px;
      border-color: var(--primary);
    }
    textarea { min-height: 96px; resize: vertical; }
    input[type="file"] { padding: 8px; background: var(--surface); }
    input[type="file"]::file-selector-button {
      min-height: 32px;
      margin-right: 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0 10px;
      background: #eef4ff;
      color: #1d4ed8;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    button {
      border: 1px solid transparent;
      border-radius: 6px;
      min-height: 40px;
      padding: 0 15px;
      font: inherit;
      font-weight: 760;
      color: #fff;
      background: var(--primary);
      cursor: pointer;
      box-shadow: 0 10px 20px rgba(31, 94, 255, .16);
      transition: transform .14s ease, box-shadow .14s ease, background .14s ease, border-color .14s ease;
    }
    button:hover { background: var(--primary-strong); transform: translateY(-1px); box-shadow: 0 14px 24px rgba(31, 94, 255, .2); }
    button.secondary {
      color: #243044;
      background: #f6f8fb;
      border-color: var(--border);
      box-shadow: none;
    }
    button.secondary:hover { background: #edf2f8; border-color: #c6d1df; box-shadow: none; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    button:disabled:hover { transform: none; }
    button.primary-flow {
      min-width: 148px;
      background: #eef4ff;
      color: #1d4ed8;
      border-color: #cad9ff;
      box-shadow: none;
    }
    button.primary-flow:hover { background: #e4edff; box-shadow: none; }
    button.primary-flow.primary-active {
      background: var(--primary);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 10px 20px rgba(31, 94, 255, .16);
    }
    button.primary-flow.primary-active:hover { background: var(--primary-strong); box-shadow: 0 14px 24px rgba(31, 94, 255, .2); }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .field-row { display: grid; grid-template-columns: minmax(190px, .72fr) minmax(0, 1fr); gap: 14px; }
    .quick-pair { grid-template-columns: minmax(0, .9fr) minmax(0, 1fr); align-items: end; }
    .panel.locked {
      background: rgba(255, 255, 255, .78);
      box-shadow: none;
    }
    .panel.locked .section-note::after {
      content: " 请先完成上一步。";
      color: #64748b;
      font-weight: 700;
    }
    .session-layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      align-items: end;
    }
    .session-actions {
      align-self: end;
      min-width: 360px;
    }
    .session-actions .actions { margin-top: 0; }
    .session-actions .validation-actions {
      padding-top: 8px;
      margin-top: 8px;
    }
    .diagnostics-panel {
      background: #fbfcfe;
      margin-top: 12px;
      box-shadow: none;
    }
    .diagnostics-panel summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      cursor: pointer;
      list-style: none;
      font-weight: 780;
      color: var(--ink);
    }
    .diagnostics-panel summary::-webkit-details-marker { display: none; }
    .diagnostics-panel summary::after {
      content: "展开";
      min-width: 56px;
      text-align: center;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 4px 9px;
      color: #526176;
      background: #f6f8fb;
      font-size: 12px;
      font-weight: 760;
    }
    .diagnostics-panel[open] summary::after { content: "收起"; }
    .summary-note {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    .operator-actions {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--faint);
    }
    .workbench {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(380px, .86fr);
      gap: 16px;
      align-items: start;
      margin-top: 14px;
    }
    .control-stack { display: grid; gap: 12px; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 11px; }
    .validation-actions {
      padding-top: 10px;
      margin-top: 10px;
      border-top: 1px solid var(--faint);
    }
    .field-help { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.4; }
    .divider { height: 1px; background: var(--faint); margin: 16px 0; }
    .source-tabs {
      display: inline-grid;
      grid-template-columns: repeat(2, minmax(92px, 1fr));
      gap: 4px;
      min-height: 40px;
      margin: 10px 0 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 4px;
      background: #eef2f7;
    }
    .source-tab {
      min-height: 30px;
      padding: 0 12px;
      border-radius: 6px;
      background: transparent;
      color: #42526a;
      border-color: transparent;
      box-shadow: none;
    }
    .source-tab:hover { background: #fff; color: var(--ink); box-shadow: none; transform: none; }
    .source-tab.active {
      background: #fff;
      color: var(--primary);
      border-color: #d8e3ff;
      box-shadow: 0 6px 14px rgba(18, 31, 52, .08);
    }
    .source-panel[hidden] { display: none; }
    .source-panel {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      background: var(--surface-raised);
    }
    .source-panel .actions { margin-top: 12px; }
    .conversation {
      display: grid;
      gap: 8px;
      min-height: 112px;
      max-height: 230px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      background: linear-gradient(180deg, #fbfdff, #f6f9fc);
    }
    .message {
      width: fit-content;
      max-width: min(100%, 620px);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 9px 11px;
      background: var(--surface);
      color: var(--ink);
      font-size: 13px;
      line-height: 1.45;
      box-shadow: 0 8px 18px rgba(18, 31, 52, .05);
    }
    .message.user {
      justify-self: end;
      border-color: #bfd0ff;
      background: #eef4ff;
    }
    .message.assistant {
      justify-self: start;
      border-color: #c8e6d8;
      background: #f0faf5;
    }
    .composer-actions {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: 8px;
      align-items: end;
      margin-top: 10px;
    }
    .composer-actions label { margin-top: 0; }
    .next-action {
      margin: 0 0 12px;
      border: 1px solid #bfd0ff;
      border-left: 4px solid var(--primary);
      border-radius: 8px;
      padding: 11px 12px;
      background: #eef4ff;
      color: #1e3a8a;
      font-size: 13px;
      line-height: 1.45;
      font-weight: 720;
    }
    .next-action span {
      display: block;
      margin-bottom: 3px;
      color: #475569;
      font-size: 11px;
      font-weight: 780;
      text-transform: uppercase;
    }
    .output-panel {
      position: sticky;
      top: 14px;
      overflow: hidden;
    }
    .result-overview {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 2px 0 12px;
    }
    .result-card {
      min-width: 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 11px;
      background: linear-gradient(180deg, #ffffff, #f8fafc);
      box-shadow: 0 8px 18px rgba(18, 31, 52, .045);
    }
    .result-card span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
      margin-bottom: 5px;
    }
    .result-card strong {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--ink);
      font-size: 14px;
    }
    .result-card p {
      margin: 5px 0 0;
      color: #64748b;
      font-size: 12px;
      line-height: 1.35;
    }
    .status-strip {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1px;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--border);
      margin: 4px 0 12px;
    }
    .status-strip div { min-width: 0; padding: 10px; background: var(--surface-soft); }
    .metric-label { display: block; color: var(--muted); font-size: 11px; font-weight: 720; margin-bottom: 4px; }
    .status-strip strong {
      display: block;
      overflow: hidden;
      color: var(--ink);
      font-size: 13px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .output-summary {
      min-height: 40px;
      display: flex;
      align-items: center;
      margin-bottom: 10px;
      border: 1px solid var(--border);
      border-left: 4px solid #8aa2c5;
      border-radius: 8px;
      padding: 9px 11px;
      background: #f8fafc;
      color: #334155;
      font-size: 13px;
      line-height: 1.4;
    }
    .output-summary.ok { border-left-color: var(--success); background: var(--success-bg); color: var(--success); }
    .output-summary.fail { border-left-color: var(--danger); background: var(--danger-bg); color: var(--danger); }
    .output-summary.warn { border-left-color: #d68a00; background: var(--warning-bg); color: var(--warning); }
    pre {
      min-height: 220px;
      max-height: 360px;
      overflow: auto;
      margin: 0;
      padding: 14px;
      border-radius: 8px;
      border: 1px solid #0f172a;
      background: #121a2b;
      color: #e8f0fb;
      font-size: 12.5px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, .04);
    }
    .raw-response {
      margin-top: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #f8fafc;
      overflow: hidden;
    }
    .raw-response summary {
      cursor: pointer;
      padding: 10px 12px;
      color: #334155;
      font-size: 13px;
      font-weight: 760;
      list-style: none;
    }
    .raw-response summary::-webkit-details-marker { display: none; }
    .raw-response summary::after {
      content: "展开";
      float: right;
      color: var(--muted);
      font-size: 12px;
    }
    .raw-response[open] summary::after { content: "收起"; }
    .raw-response pre {
      border-radius: 0;
      border-left: 0;
      border-right: 0;
      border-bottom: 0;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    [hidden] { display: none !important; }
    .landing-page {
      min-height: 100vh;
      padding: 22px clamp(18px, 4vw, 52px) 44px;
      background:
        linear-gradient(135deg, rgba(245, 248, 252, .96), rgba(232, 238, 246, .92)),
        radial-gradient(circle at 80% 12%, rgba(31, 94, 255, .13), transparent 32%);
    }
    .landing-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      max-width: 1200px;
      margin: 0 auto;
    }
    .landing-header .brand-copy h1 {
      max-width: 560px;
      font-size: 22px;
    }
    .login-entry {
      min-width: 84px;
      color: var(--ink);
      background: #ffffff;
      border-color: var(--border);
      box-shadow: 0 10px 24px rgba(18, 31, 52, .08);
    }
    .login-entry:hover {
      color: #ffffff;
      background: var(--ink);
      border-color: var(--ink);
      box-shadow: 0 14px 28px rgba(18, 31, 52, .18);
    }
    .landing-main {
      max-width: 1200px;
      margin: 0 auto;
    }
    .hero-section {
      min-height: min(680px, calc(100vh - 184px));
      display: grid;
      grid-template-columns: minmax(0, 1.02fr) minmax(360px, .72fr);
      gap: clamp(28px, 5vw, 70px);
      align-items: center;
      padding: clamp(42px, 8vh, 88px) 0 32px;
    }
    .hero-kicker {
      margin: 0 0 14px;
      color: #31526f;
      font-size: 14px;
      font-weight: 780;
    }
    .hero-copy h2 {
      max-width: 760px;
      font-size: clamp(38px, 6vw, 72px);
      line-height: .98;
      letter-spacing: 0;
      color: var(--ink);
    }
    .hero-text {
      max-width: 720px;
      margin: 22px 0 0;
      color: #3f5068;
      font-size: 18px;
      line-height: 1.72;
    }
    .hero-preview {
      border: 1px solid rgba(214, 221, 232, .92);
      border-radius: 8px;
      padding: 18px;
      background: rgba(255, 255, 255, .86);
      box-shadow: 0 24px 70px rgba(23, 32, 51, .13);
    }
    .preview-topline {
      width: 100%;
      height: 8px;
      margin-bottom: 22px;
      border-radius: 999px;
      background: linear-gradient(90deg, #1f5eff 0 38%, #14b8a6 38% 68%, #f59e0b 68% 100%);
    }
    .preview-message {
      width: fit-content;
      max-width: 88%;
      margin: 10px 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 13px;
      color: var(--ink);
      font-size: 14px;
      line-height: 1.55;
      background: #ffffff;
    }
    .preview-message.user {
      margin-left: auto;
      border-color: #bfd0ff;
      background: #edf4ff;
    }
    .preview-message.assistant {
      border-color: #bfe8dc;
      background: #eefbf7;
    }
    .preview-metrics {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px 14px;
      margin-top: 22px;
      padding-top: 16px;
      border-top: 1px solid var(--faint);
      color: #5e6a7d;
      font-size: 13px;
    }
    .preview-metrics strong { color: var(--success); }
    .capability-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: -2px;
    }
    .capability-grid article {
      min-height: 170px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
      background: rgba(255, 255, 255, .78);
      box-shadow: 0 12px 32px rgba(23, 32, 51, .06);
    }
    .capability-grid span {
      color: var(--primary);
      font-size: 12px;
      font-weight: 860;
    }
    .capability-grid h3 { margin-top: 12px; font-size: 18px; }
    .capability-grid p {
      margin: 10px 0 0;
      color: #536176;
      font-size: 14px;
      line-height: 1.58;
    }
    .login-modal {
      position: fixed;
      inset: 0;
      z-index: 10;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(15, 23, 42, .38);
      backdrop-filter: blur(14px);
    }
    .login-card {
      position: relative;
      width: min(560px, 100%);
      border: 1px solid rgba(214, 221, 232, .96);
      border-radius: 8px;
      padding: 24px;
      background: #ffffff;
      box-shadow: 0 32px 80px rgba(15, 23, 42, .24);
    }
    .icon-button {
      position: absolute;
      top: 14px;
      right: 14px;
      min-width: 36px;
      width: 36px;
      min-height: 36px;
      padding: 0;
      border-radius: 999px;
      color: #445166;
      background: #f5f7fa;
      border-color: var(--border);
      box-shadow: none;
      font-size: 22px;
      line-height: 1;
    }
    .icon-button:hover {
      color: var(--ink);
      background: #e9eef5;
      box-shadow: none;
    }
    .login-actions {
      display: grid;
      grid-template-columns: 1fr;
    }
    .login-feedback {
      min-height: 22px;
      margin-top: 10px;
      color: var(--danger);
      font-size: 13px;
      font-weight: 700;
    }
    .chat-app {
      min-height: 100vh;
    }
    .chat-app .workbench {
      grid-template-columns: 280px minmax(0, 1fr) 360px;
      align-items: stretch;
    }
    .tool-stack {
      display: grid;
      gap: 12px;
      align-content: start;
    }
    .session-sidebar,
    .chat-main,
    .tool-stack .panel {
      min-width: 0;
    }
    .sidebar-heading,
    .chat-heading {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .sidebar-heading button {
      min-width: 104px;
    }
    .technical-label,
    .technical-field {
      position: absolute;
      width: 1px;
      height: 1px;
      margin: -1px;
      padding: 0;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .session-list {
      display: grid;
      gap: 7px;
      margin-top: 14px;
      max-height: calc(100vh - 310px);
      overflow: auto;
    }
    .session-item {
      width: 100%;
      min-height: 44px;
      justify-content: flex-start;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      color: #243044;
      background: #ffffff;
      box-shadow: none;
      text-align: left;
    }
    .session-item:hover {
      color: var(--primary);
      background: #f4f7ff;
      border-color: #cbd9ff;
      box-shadow: none;
      transform: none;
    }
    .session-item.active {
      color: #174bd4;
      background: #eef4ff;
      border-color: #b8cdfd;
    }
    .session-item.empty {
      color: #7a8798;
      background: #f8fafc;
      cursor: default;
    }
    .session-item strong,
    .session-item span {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .session-item span {
      margin-top: 2px;
      color: #7a8798;
      font-size: 11px;
      font-weight: 650;
    }
    .chat-main {
      display: grid;
      grid-template-rows: auto minmax(280px, 1fr) auto;
    }
    .chat-main .conversation {
      min-height: calc(100vh - 330px);
      max-height: none;
      align-content: start;
      padding: 16px;
    }
    .chat-main textarea {
      min-height: 78px;
    }
    @media (max-width: 960px) {
      .workbench { grid-template-columns: 1fr; }
      .chat-app .workbench { grid-template-columns: 1fr; }
      .hero-section { grid-template-columns: 1fr; }
      .hero-preview { max-width: 620px; }
      .capability-grid { grid-template-columns: 1fr; }
      .session-list { max-height: 260px; }
      .output-panel { position: static; }
      pre { min-height: 320px; }
      .composer-actions { grid-template-columns: 1fr; }
      .composer-actions button { width: 100%; }
    }
    @media (max-width: 760px) {
      main.shell { width: min(100% - 20px, 1180px); padding-top: 18px; }
      header.topbar { align-items: flex-start; flex-direction: column; }
      .landing-header { align-items: flex-start; }
      .landing-header .brand-copy h1 { font-size: 19px; }
      .hero-copy h2 { font-size: 38px; }
      .hero-text { font-size: 16px; }
      .brand-subtitle { display: none; }
      .top-status { width: 100%; justify-content: stretch; }
      .status, .run-state { flex: 1 1 auto; }
      .grid { grid-template-columns: 1fr; }
      .quick-pair { grid-template-columns: 1fr; }
      .field-row { grid-template-columns: 1fr; }
      .session-layout { grid-template-columns: 1fr; }
      .session-actions { min-width: 0; }
      .session-actions .actions { margin-top: 11px; }
      .status-strip { grid-template-columns: 1fr; }
      .flow-steps {
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 4px;
      }
      .flow-step {
        min-height: 32px;
        gap: 4px;
        padding: 0 4px;
        font-size: 10px;
      }
      .flow-step::before {
        width: 18px;
        height: 18px;
        font-size: 10px;
      }
      .result-overview { grid-template-columns: 1fr; }
      .source-tabs { width: 100%; }
    }
    @media (max-width: 560px) {
      .brand-mark { width: 40px; height: 40px; }
      h1 { font-size: 26px; }
      .panel { padding: 15px; }
      .section-heading { flex-direction: column; }
      .actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .actions button { width: 100%; min-width: 0; }
      .actions button.primary-flow { grid-column: 1 / -1; }
      .top-status { display: grid; grid-template-columns: 1fr; gap: 6px; }
      .landing-page { padding: 16px 14px 28px; }
      .landing-header .brand { gap: 9px; }
      .landing-header .brand-copy h1 { display: none; }
      .hero-section { padding-top: 36px; }
      .hero-copy h2 { font-size: 33px; }
      .login-card { padding: 22px 16px 18px; }
    }
  </style>
</head>
<body>
  <section id="landingPage" class="landing-page" aria-label="OpenClaw 产品介绍">
    <header class="landing-header">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">OC</div>
        <div class="brand-copy">
          <p class="eyebrow">OpenClaw 短视频智能分析</p>
          <h1>让短视频链接直接进入可追踪的分析对话</h1>
        </div>
      </div>
      <button id="openLogin" class="login-entry" type="button">登录</button>
    </header>
    <main class="landing-main">
      <section class="hero-section">
        <div class="hero-copy">
          <p class="hero-kicker">独立登录 · 视频链接读取 · 模型分析 · 历史对话</p>
          <h2>把一个视频链接变成清晰、可复查、可继续追问的分析结果。</h2>
          <p class="hero-text">OpenClaw 面向短视频运营、内容研究和业务分析场景，用户只需要在本站登录，提交视频链接或上传文件，就可以在同一个中文聊天界面里查看分析进度、结果摘要和历史会话。</p>
        </div>
        <div class="hero-preview" aria-hidden="true">
          <div class="preview-topline"></div>
          <div class="preview-message user">这个视频的核心卖点是什么？</div>
          <div class="preview-message assistant">已识别视频来源，正在提取画面、动作与话术线索。</div>
          <div class="preview-metrics">
            <span>链接读取</span>
            <strong>PASS</strong>
            <span>会话历史</span>
            <strong>已同步</strong>
          </div>
        </div>
      </section>
      <section class="capability-grid" aria-label="核心能力">
        <article>
          <span>01</span>
          <h3>视频链接读取</h3>
          <p>对分享链接进行服务端校验、重定向复核和直连候选解析，减少对浏览器登录状态的依赖。</p>
        </article>
        <article>
          <span>02</span>
          <h3>模型驱动分析</h3>
          <p>围绕画面、动作、话术、场景和内容结构生成结构化结果，便于后续复盘。</p>
        </article>
        <article>
          <span>03</span>
          <h3>中文聊天工作台</h3>
          <p>登录后进入对话界面，可新建会话、查看历史、继续追问并关联视频分析任务。</p>
        </article>
      </section>
    </main>
  </section>

  <section id="loginPanel" class="login-modal" aria-labelledby="loginHeading" hidden>
    <div class="login-card" role="dialog" aria-modal="true">
      <button id="closeLogin" class="icon-button" type="button" aria-label="关闭登录">×</button>
      <div class="section-heading">
        <div>
          <p class="eyebrow">OpenClaw 账号</p>
          <h2 id="loginHeading">登录后进入分析对话</h2>
          <p class="section-note">这里使用 OpenClaw 自己的登录界面；无需再登录 Dify 网页。</p>
        </div>
      </div>
      <div class="grid">
        <div>
          <label for="loginAccount">账号</label>
          <input id="loginAccount" autocomplete="username" inputmode="text" placeholder="请输入账号">
        </div>
        <div>
          <label for="loginPassword">密码</label>
          <input id="loginPassword" type="password" autocomplete="current-password" placeholder="请输入密码">
        </div>
      </div>
      <div id="loginFeedback" class="login-feedback" aria-live="polite"></div>
      <div class="actions login-actions">
        <button id="loginButton" class="primary-flow">登录</button>
      </div>
    </div>
  </section>

  <main id="chatApp" class="shell chat-app" hidden>
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">OC</div>
        <div class="brand-copy">
          <p class="eyebrow">OpenClaw 分析工作台</p>
          <h1>短视频分析对话</h1>
          <p class="brand-subtitle">新建对话、读取视频链接、查看历史记录，并在同一个界面里追踪分析结果。</p>
        </div>
      </div>
      <div class="top-status" aria-label="OpenClaw 运行状态">
        <div id="runState" class="run-state todo">等待登录</div>
        <div id="authStatus" class="status todo">未登录</div>
        <button id="refreshMe" class="secondary">刷新状态</button>
        <button id="logoutButton" class="secondary">退出</button>
      </div>
    </header>

    <nav class="flow-steps" aria-label="分析流程">
      <div id="flowLogin" class="flow-step active" data-step="1">登录</div>
      <div id="flowSession" class="flow-step" data-step="2">会话</div>
      <div id="flowSource" class="flow-step" data-step="3">来源</div>
      <div id="flowAnalyze" class="flow-step" data-step="4">分析</div>
      <div id="flowResult" class="flow-step" data-step="5">结果</div>
    </nav>

    <div class="workbench" aria-label="OpenClaw 中文聊天分析界面">
      <aside id="sessionPanel" class="panel session-sidebar locked" aria-labelledby="sessionHeading">
        <div class="sidebar-heading">
          <div>
            <p class="eyebrow">会话</p>
            <h2 id="sessionHeading">历史对话</h2>
          </div>
          <button id="createSession" class="primary-flow">新建对话</button>
        </div>
        <label for="sessionTitle">新会话标题</label>
        <input id="sessionTitle" value="短视频分析">
        <label for="sessionId" class="technical-label">当前会话 ID</label>
        <input id="sessionId" class="technical-field" autocomplete="off" placeholder="创建会话后自动写入">
        <div id="sessionList" class="session-list" aria-live="polite">
          <button type="button" class="session-item empty">登录后显示历史对话</button>
        </div>
      </aside>

      <section id="conversationPanel" class="panel chat-main locked" aria-labelledby="conversationHeading">
        <div class="chat-heading">
          <div>
            <p class="eyebrow">聊天</p>
            <h2 id="conversationHeading">分析对话</h2>
          </div>
          <button id="refreshMessages" class="secondary" type="button">刷新历史</button>
        </div>
        <div id="conversation" class="conversation" aria-live="polite">
          <div class="message assistant">登录后可以新建对话、提交视频链接，并围绕分析结果继续追问。</div>
        </div>
        <div class="composer-actions">
          <div>
            <label for="prompt">输入问题或分析要求</label>
            <textarea id="prompt">请分析这个视频。</textarea>
          </div>
          <button id="sendChat" class="primary-flow" type="button">发送</button>
        </div>
      </section>

      <aside class="tool-stack" aria-label="视频分析工具与结果">
        <section id="videoPanel" class="panel locked" aria-labelledby="videoHeading">
          <div class="section-heading">
            <div>
              <div class="step-title">
                <span class="step-index">03</span>
                <h2 id="videoHeading">视频分析</h2>
              </div>
              <p class="section-note">优先使用视频链接读取；上传作为备用入口。</p>
            </div>
          </div>
          <div class="source-tabs" role="tablist" aria-label="视频来源">
            <button id="linkSourceTab" class="source-tab active" type="button" role="tab" aria-selected="true" aria-controls="linkSourcePanel">链接</button>
            <button id="uploadSourceTab" class="source-tab" type="button" role="tab" aria-selected="false" aria-controls="uploadSourcePanel">上传</button>
          </div>
          <div id="linkSourcePanel" class="source-panel" role="tabpanel" aria-labelledby="linkSourceTab">
            <label for="videoUrl">视频链接</label>
            <input id="videoUrl" placeholder="https://v.douyin.com/...">
            <p class="field-help">先读取链接，确认可解析后再提交模型分析。</p>
            <div class="actions">
              <button id="readVideoLink" class="secondary">读取链接</button>
              <button id="submitJob" class="primary-flow">分析视频</button>
              <button id="pollJob" class="secondary">刷新状态</button>
            </div>
          </div>
          <div id="uploadSourcePanel" class="source-panel" role="tabpanel" aria-labelledby="uploadSourceTab" hidden>
            <label for="videoFile">视频文件</label>
            <input id="videoFile" type="file" accept="video/mp4,video/quicktime,video/webm">
            <p class="field-help">支持 MP4、MOV、WebM，受服务器上传大小限制保护。</p>
            <div class="actions">
              <button id="uploadJob" class="primary-flow">分析上传</button>
              <button id="uploadSmoke" class="secondary">上传检查</button>
            </div>
          </div>
        </section>

        <section class="panel output-panel" aria-labelledby="outputHeading">
          <div class="section-heading">
            <div>
              <div class="step-title">
                <span class="step-index">05</span>
                <h2 id="outputHeading">结果与状态</h2>
              </div>
              <p class="section-note">先看摘要；必要时展开脱敏明细。</p>
            </div>
          </div>
          <div id="nextAction" class="next-action"><span>下一步</span>请先登录进入分析工作台。</div>
          <div class="result-overview" aria-label="结果概览">
            <div class="result-card">
              <span>身份</span>
              <strong id="authMetric">未登录</strong>
              <p>OpenClaw 独立会话状态。</p>
            </div>
            <div class="result-card">
              <span>来源</span>
              <strong id="sourceMetric">等待视频来源</strong>
              <p>链接读取或上传入口。</p>
            </div>
            <div class="result-card">
              <span>分析</span>
              <strong id="analysisMetric">就绪</strong>
              <p>Worker 进度与最终状态。</p>
            </div>
            <div class="result-card">
              <span>结果</span>
              <strong id="resultMetric">暂无结果</strong>
              <p>摘要与结构化结果状态。</p>
            </div>
          </div>
          <div class="status-strip" aria-label="当前任务摘要">
            <div>
              <span class="metric-label">任务</span>
              <strong id="jobMetric">无任务</strong>
            </div>
            <div>
              <span class="metric-label">输出</span>
              <strong id="outputMetric">就绪</strong>
            </div>
          </div>
          <div id="outputSummary" class="output-summary">登录后新建对话，再添加视频链接或上传文件。</div>
          <details class="raw-response">
            <summary>开发详情：脱敏响应</summary>
            <pre id="output">{}</pre>
          </details>
          <details id="validationTools" class="diagnostics-panel">
            <summary>
              <span>验证工具</span>
              <span class="summary-note">诊断与验收</span>
            </summary>
            <div class="operator-actions">
              <div class="actions">
                <button id="identityDiagnostics" class="secondary">身份诊断</button>
                <button id="runSelfTest" class="secondary">自检</button>
                <button id="runSecurityTest" class="secondary">安全检查</button>
                <button id="runPostLoginAcceptance" class="secondary">登录后验收</button>
              </div>
            </div>
          </details>
        </section>
      </aside>
    </div>
  </main>
  <script>
    const output = document.getElementById('output');
    const landingPage = document.getElementById('landingPage');
    const chatApp = document.getElementById('chatApp');
    const loginPanel = document.getElementById('loginPanel');
    const sessionList = document.getElementById('sessionList');
    const authStatus = document.getElementById('authStatus');
    const runState = document.getElementById('runState');
    const authMetric = document.getElementById('authMetric');
    const jobMetric = document.getElementById('jobMetric');
    const outputMetric = document.getElementById('outputMetric');
    const outputSummary = document.getElementById('outputSummary');
    const nextAction = document.getElementById('nextAction');
    const conversation = document.getElementById('conversation');
    const analysisMetric = document.getElementById('analysisMetric');
    const sourceMetric = document.getElementById('sourceMetric');
    const resultMetric = document.getElementById('resultMetric');
    const flowSteps = [
      document.getElementById('flowLogin'),
      document.getElementById('flowSession'),
      document.getElementById('flowSource'),
      document.getElementById('flowAnalyze'),
      document.getElementById('flowResult')
    ];
    const linkSourceTab = document.getElementById('linkSourceTab');
    const uploadSourceTab = document.getElementById('uploadSourceTab');
    const linkSourcePanel = document.getElementById('linkSourcePanel');
    const uploadSourcePanel = document.getElementById('uploadSourcePanel');
    let currentJobId = '';
    const apiPrefix = window.location.hostname === 'ai001.huahuoai.com'
      ? '/console/api/openclaw-api'
      : (window.location.pathname.startsWith('/ai/openclaw-lab') ? '/api/openclaw-api' : '/openclaw-api');
    const terminalStatuses = new Set(['succeeded', 'failed', 'timed_out', 'cancelled']);
    let linkReadable = false;
    let knownSessions = [];

    function openLoginPanel() {
      loginPanel.hidden = false;
      window.setTimeout(() => document.getElementById('loginAccount').focus(), 30);
    }
    function closeLoginPanel() {
      loginPanel.hidden = true;
    }
    function showLanding() {
      landingPage.hidden = false;
      chatApp.hidden = true;
      closeLoginPanel();
    }
    function showChatApp() {
      landingPage.hidden = true;
      loginPanel.hidden = true;
      chatApp.hidden = false;
    }
    function setPanelState(panelId, unlocked) {
      const panel = document.getElementById(panelId);
      if (!panel) return;
      panel.classList.toggle('locked', !unlocked);
      panel.setAttribute('aria-disabled', unlocked ? 'false' : 'true');
    }
    function setPrimaryAction(buttonId) {
      ['loginButton', 'createSession', 'readVideoLink', 'submitJob', 'uploadJob', 'pollJob', 'sendChat'].forEach(id => {
        const button = document.getElementById(id);
        if (button) button.classList.toggle('primary-active', id === buttonId);
      });
    }
    function setNextAction(text) {
      nextAction.textContent = '';
      const label = document.createElement('span');
      label.textContent = '下一步';
      nextAction.appendChild(label);
      nextAction.appendChild(document.createTextNode(text));
    }
    function setFlowStep(index, state) {
      const item = flowSteps[index];
      if (!item) return;
      item.classList.remove('active', 'done', 'locked');
      if (state) item.classList.add(state);
    }
    function activateFlow(index) {
      flowSteps.forEach((item, itemIndex) => {
        item.classList.remove('active', 'done', 'locked');
        if (itemIndex < index) item.classList.add('done');
        if (itemIndex === index) item.classList.add('active');
        if (itemIndex > index) item.classList.add('locked');
      });
    }
    function hasSession() {
      return Boolean(document.getElementById('sessionId').value.trim());
    }
    function isAuthenticated() {
      return authStatus.classList.contains('ok');
    }
    function moveToSourceIfReady() {
      if (hasSession()) {
        activateFlow(2);
      } else if (isAuthenticated()) {
        activateFlow(1);
      } else {
        activateFlow(0);
      }
    }
    function setSourceMode(mode) {
      const upload = mode === 'upload';
      linkSourceTab.classList.toggle('active', !upload);
      uploadSourceTab.classList.toggle('active', upload);
      linkSourceTab.setAttribute('aria-selected', upload ? 'false' : 'true');
      uploadSourceTab.setAttribute('aria-selected', upload ? 'true' : 'false');
      linkSourcePanel.hidden = upload;
      uploadSourcePanel.hidden = !upload;
      sourceMetric.textContent = upload ? '已选择上传' : '已选择链接';
      moveToSourceIfReady();
      syncActionAvailability();
    }
    function syncActionAvailability() {
      const authenticated = isAuthenticated();
      const sessionReady = hasSession();
      const uploadMode = !uploadSourcePanel.hidden;
      const chatReady = authenticated && sessionReady;
      document.getElementById('logoutButton').disabled = !authenticated;
      document.getElementById('refreshMe').disabled = false;
      document.getElementById('loginButton').disabled = authenticated;
      document.getElementById('createSession').disabled = !authenticated;
      document.getElementById('readVideoLink').disabled = !authenticated || !sessionReady;
      document.getElementById('submitJob').disabled = !authenticated || !sessionReady;
      document.getElementById('pollJob').disabled = !authenticated || !currentJobId;
      document.getElementById('uploadJob').disabled = !authenticated || !sessionReady;
      document.getElementById('uploadSmoke').disabled = !authenticated;
      document.getElementById('sendChat').disabled = !chatReady;
      document.getElementById('refreshMessages').disabled = !chatReady;
      setPanelState('sessionPanel', authenticated);
      setPanelState('videoPanel', authenticated && sessionReady);
      setPanelState('conversationPanel', authenticated && sessionReady);
      if (!authenticated) {
        setPrimaryAction('loginButton');
        setNextAction('请先登录，解锁会话、视频来源和聊天分析。');
      } else if (!sessionReady) {
        setPrimaryAction('createSession');
        setNextAction('新建或选择一个历史对话，用来保存链接、上传、消息和结果。');
      } else if (currentJobId) {
        setPrimaryAction('pollJob');
        setNextAction('刷新当前任务状态；完成后即可查看结果。');
      } else if (uploadMode) {
        setPrimaryAction('uploadJob');
        setNextAction('选择视频文件，然后提交上传分析。');
      } else if (linkReadable) {
        setPrimaryAction('submitJob');
        setNextAction('链接读取通过，可以提交模型分析。');
      } else {
        setPrimaryAction('readVideoLink');
        setNextAction('先读取视频链接，确认可解析后再提交模型分析。');
      }
    }
    function setPreLoginView() {
      showLanding();
      setAuthState('未登录', 'todo');
      runState.textContent = '等待登录';
      runState.className = 'run-state todo';
      document.getElementById('loginAccount').disabled = false;
      document.getElementById('loginPassword').disabled = false;
      document.getElementById('loginFeedback').textContent = '';
      authMetric.textContent = '未登录';
      analysisMetric.textContent = '就绪';
      sourceMetric.textContent = '等待视频来源';
      resultMetric.textContent = '暂无结果';
      outputMetric.textContent = '就绪';
      outputSummary.textContent = '登录后新建对话，再添加视频链接或上传文件。';
      outputSummary.className = 'output-summary';
      knownSessions = [];
      renderSessions([]);
      renderMessages([]);
      linkReadable = false;
      setCurrentJob('');
      activateFlow(0);
      syncActionAvailability();
    }
    function setAuthenticatedView() {
      showChatApp();
      setAuthState('已登录', 'ok');
      runState.textContent = hasSession() ? '会话已就绪' : '请选择会话';
      runState.className = 'run-state ok';
      document.getElementById('loginAccount').disabled = true;
      document.getElementById('loginPassword').disabled = true;
      authMetric.textContent = '已登录';
      analysisMetric.textContent = hasSession() ? '可开始分析' : '就绪';
      sourceMetric.textContent = hasSession() ? '等待视频来源' : '请先选择会话';
      resultMetric.textContent = hasSession() ? '暂无结果' : '需要会话';
      outputMetric.textContent = hasSession() ? '就绪' : '需要会话';
      outputSummary.textContent = hasSession()
        ? '会话已就绪。添加视频链接或上传文件即可开始分析。'
        : '登录成功。请新建或选择一个历史对话。';
      outputSummary.className = 'output-summary ok';
      activateFlow(hasSession() ? 2 : 1);
      syncActionAvailability();
    }
    function setRunState(text, tone = 'busy') {
      runState.textContent = text;
      runState.className = 'run-state ' + tone;
      outputMetric.textContent = text;
      analysisMetric.textContent = text;
      syncActionAvailability();
    }
    function setAuthState(text, tone) {
      authStatus.textContent = text;
      authStatus.className = 'status ' + tone;
      authMetric.textContent = text;
      setFlowStep(0, tone === 'ok' ? 'done' : (tone === 'fail' ? 'active' : 'active'));
      syncActionAvailability();
    }
    function setCurrentJob(jobId) {
      currentJobId = jobId || '';
      jobMetric.textContent = currentJobId ? currentJobId.slice(0, 8) + '...' : '无任务';
      syncActionAvailability();
    }
    function summarizeOutput(value) {
      if (typeof value === 'string') {
        return { tone: 'warn', text: value || '暂无输出文本。' };
      }
      if (!value || typeof value !== 'object') {
        return { tone: 'warn', text: '暂无结构化响应。' };
      }
      if (value.post_login_acceptance) {
        const payload = value.post_login_acceptance;
        const steps = Array.isArray(payload.steps) ? payload.steps : [];
        const failed = steps.filter(step => step.ok === false).length;
        const tone = payload.overall === 'PASS' ? 'ok' : (payload.overall === 'FAIL' ? 'fail' : 'warn');
        return { tone, text: '登录后验收 ' + payload.overall + '：共 ' + steps.length + ' 项，失败 ' + failed + ' 项。' };
      }
      if (value.security_test) {
        const steps = Array.isArray(value.security_test) ? value.security_test : [];
        const failed = steps.filter(step => step.ok === false).length;
        return { tone: failed ? 'fail' : 'warn', text: '安全检查：已记录 ' + steps.length + ' 项，失败 ' + failed + ' 项。' };
      }
      if (value.self_test) {
        const steps = Array.isArray(value.self_test) ? value.self_test : [];
        return { tone: 'warn', text: '自检进行中：已记录 ' + steps.length + ' 项。' };
      }
      if (value.upload_smoke) {
        const steps = Array.isArray(value.upload_smoke) ? value.upload_smoke : [];
        const last = steps.length ? steps[steps.length - 1] : null;
        const tone = last && last.ok === false ? 'fail' : 'warn';
        return { tone, text: '上传检查：已记录 ' + steps.length + ' 步。' };
      }
      if (value.video_link_read_check) {
        const payload = value.video_link_read_check;
        const tone = payload.status === 'PASS' ? 'ok' : 'warn';
        const count = payload.direct_video_candidate_count || 0;
        sourceMetric.textContent = payload.status === 'PASS' ? count + ' 个候选' : '已检查链接';
        resultMetric.textContent = '预检';
        return { tone, text: '视频链接读取 ' + payload.status + '：发现 ' + count + ' 个直连候选，未调用模型。' };
      }
      if (value.chat) {
        const status = typeof value.chat.status === 'number' ? value.chat.status : null;
        if (status === 200) {
          return { tone: 'ok', text: 'OpenClaw 已回复，对话已更新。' };
        }
        return { tone: status >= 500 ? 'fail' : 'warn', text: 'OpenClaw 聊天响应：HTTP ' + (status || '未知') + '。' };
      }
      if (value.messages) {
        const count = Array.isArray(value.messages.messages) ? value.messages.messages.length : 0;
        return { tone: 'ok', text: '历史已刷新：当前可见 ' + count + ' 条消息。' };
      }
      const status = typeof value.status === 'number' ? value.status : null;
      const job = value.job || (value.body && value.body.job) || null;
      if (job && job.job_id) {
        setCurrentJob(job.job_id);
        const tone = job.status === 'succeeded' ? 'ok' : (terminalStatuses.has(job.status) ? 'fail' : 'warn');
        analysisMetric.textContent = job.status || '任务';
        resultMetric.textContent = job.result_schema_version || (job.status === 'succeeded' ? '已就绪' : '等待中');
        return { tone, text: '任务 ' + job.status + '：' + job.job_id.slice(0, 8) + '...' };
      }
      if (status) {
        const tone = status >= 200 && status < 300 ? 'ok' : (status === 401 || status === 403 || status >= 500 ? 'fail' : 'warn');
        return { tone, text: '已记录 HTTP ' + status + ' 响应。' };
      }
      return { tone: 'warn', text: '已记录结构化响应。' };
    }
    function show(value) {
      output.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
      const summary = summarizeOutput(value);
      outputSummary.textContent = summary.text;
      outputSummary.className = 'output-summary ' + summary.tone;
    }
    function pushMessage(role, text) {
      const node = document.createElement('div');
      node.className = 'message ' + role;
      node.textContent = text;
      conversation.appendChild(node);
      conversation.scrollTop = conversation.scrollHeight;
    }
    function formatSessionTime(value) {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '';
      return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
    function renderSessions(sessions) {
      sessionList.innerHTML = '';
      if (!Array.isArray(sessions) || sessions.length === 0) {
        const empty = document.createElement('button');
        empty.type = 'button';
        empty.className = 'session-item empty';
        empty.textContent = isAuthenticated() ? '暂无历史对话' : '登录后显示历史对话';
        empty.disabled = true;
        sessionList.appendChild(empty);
        return;
      }
      const activeId = document.getElementById('sessionId').value;
      sessions.forEach(session => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'session-item' + (session.id === activeId ? ' active' : '');
        item.dataset.sessionId = session.id || '';
        const title = document.createElement('strong');
        title.textContent = session.title || '未命名对话';
        const meta = document.createElement('span');
        meta.textContent = formatSessionTime(session.updated_at || session.created_at) || '历史记录';
        item.appendChild(title);
        item.appendChild(meta);
        item.addEventListener('click', () => selectSession(session));
        sessionList.appendChild(item);
      });
    }
    function renderMessages(messages) {
      conversation.innerHTML = '';
      if (!Array.isArray(messages) || messages.length === 0) {
        pushMessage('assistant', '当前对话还没有消息。可以发送问题，或提交视频链接开始分析。');
        return;
      }
      messages.forEach(message => pushMessage(message.role === 'user' ? 'user' : 'assistant', message.content || ''));
    }
    async function withBusy(label, task) {
      setRunState(label, 'busy');
      try {
        const result = await task();
        return result;
      } catch (error) {
        setRunState('发生错误', 'fail');
        show({ error: String(error && error.message || error) });
        throw error;
      }
    }
    function setSessionFromAcceptance(session) {
      if (!session || !session.id) return;
      knownSessions = [session, ...knownSessions.filter(item => item.id !== session.id)];
      document.getElementById('sessionId').value = session.id;
      document.getElementById('sessionTitle').value = session.title || '短视频分析';
      renderSessions(knownSessions);
    }
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    async function pollTerminalJob(jobId, attempts = 40) {
      let lastPoll = null;
      let lastJob = null;
      for (let attempt = 0; attempt < attempts; attempt += 1) {
        await delay(1000);
        lastPoll = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId));
        lastJob = lastPoll.body.job || null;
        if (lastJob && terminalStatuses.has(lastJob.status)) break;
      }
      return { poll: lastPoll, job: lastJob };
    }
    async function api(path, options = {}) {
      const response = await fetch(path, {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options
      });
      const text = await response.text();
      let body;
      try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
      return { status: response.status, body };
    }
    async function loadSessions(options = {}) {
      const result = await api(apiPrefix + '/sessions');
      if (result.status === 200) {
        const sessions = result.body.sessions || [];
        knownSessions = sessions;
        renderSessions(knownSessions);
        if (!document.getElementById('sessionId').value && sessions.length > 0) {
          await selectSession(sessions[0], { quiet: true });
        }
      } else if (!options.quiet) {
        show({ status: result.status, sessions: result.body });
      }
      return result;
    }
    async function selectSession(session, options = {}) {
      if (!session || !session.id) return;
      document.getElementById('sessionId').value = session.id;
      document.getElementById('sessionTitle').value = session.title || '短视频分析';
      linkReadable = false;
      setCurrentJob('');
      setAuthenticatedView();
      renderSessions(knownSessions);
      await refreshMessages({ quiet: true });
      if (!options.quiet) show({ session: { selected: true, id_length: session.id.length } });
    }
    async function refreshMessages(options = {}) {
      return withBusy('刷新消息', async () => {
      const sessionId = document.getElementById('sessionId').value;
      if (!sessionId) {
        show('请先新建或选择一个对话。');
        setRunState('需要会话', 'fail');
        return;
      }
      const result = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      if (result.status === 200) {
        renderMessages(result.body.messages || []);
        setRunState('历史已刷新', 'ok');
      } else {
        setRunState('需要处理', 'fail');
      }
      if (!options.quiet) show({ status: result.status, messages: result.body });
      });
    }
    async function login() {
      return withBusy('正在登录', async () => {
      document.getElementById('loginFeedback').textContent = '';
      const result = await api(apiPrefix + '/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          account: document.getElementById('loginAccount').value,
          password: document.getElementById('loginPassword').value
        })
      });
      if (result.status === 200) {
        document.getElementById('loginPassword').value = '';
        document.getElementById('loginAccount').value = '';
        setAuthenticatedView();
        await loadSessions({ quiet: true });
      } else {
        const message = result.status === 429 ? '登录过于频繁，请稍后再试。' : '账号或密码不正确，请重新输入。';
        document.getElementById('loginFeedback').textContent = message;
        setAuthState(result.status === 429 ? '频率受限' : '登录失败', 'fail');
        setRunState('需要处理', 'fail');
        activateFlow(0);
      }
      show(result);
      });
    }
    async function logout() {
      return withBusy('正在退出', async () => {
      const result = await api(apiPrefix + '/auth/logout', { method: 'POST', body: JSON.stringify({}) });
      document.getElementById('sessionId').value = '';
      knownSessions = [];
      setCurrentJob('');
      setPreLoginView();
      show(result);
      });
    }
    async function refreshMe(options = {}) {
      return withBusy('刷新状态', async () => {
      const result = await api(apiPrefix + '/me');
      if (result.status === 200) {
        setAuthenticatedView();
        await loadSessions({ quiet: true });
      } else {
        setPreLoginView();
      }
      if (!options.quiet) show(result);
      });
    }
    async function createSession() {
      return withBusy('创建对话', async () => {
      const result = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: document.getElementById('sessionTitle').value || '短视频分析' })
      });
      if (result.body.session && result.body.session.id) {
        setSessionFromAcceptance(result.body.session);
        linkReadable = false;
        setCurrentJob('');
        setAuthenticatedView();
        setRunState('会话已就绪', 'ok');
        sourceMetric.textContent = '等待视频来源';
        resultMetric.textContent = '会话已就绪';
        activateFlow(2);
        renderMessages([]);
      } else {
        setRunState('需要处理', 'fail');
      }
      show(result);
      });
    }
    async function identityDiagnostics() {
      return withBusy('身份诊断', async () => {
      show(await api(apiPrefix + '/identity/diagnostics'));
      setRunState('诊断完成', 'ok');
      });
    }
    async function runSelfTest() {
      return withBusy('自检运行中', async () => {
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ self_test: steps });
      };
      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      add('identity_diagnostics', { status: diagnostics.status, body: diagnostics.body });
      if (!diagnostics.body.authenticated) {
        setPreLoginView();
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', { status: me.status, body: me.body });
      if (me.status !== 200) {
        setRunState('需要处理', 'fail');
        return;
      }

      const randomId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      const missing = await api(apiPrefix + '/sessions/' + encodeURIComponent(randomId) + '/messages');
      add('random_session_404', { status: missing.status, ok: missing.status === 404 });

      const sessionResult = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'OpenClaw self test ' + new Date().toISOString() })
      });
      add('create_session', { status: sessionResult.status, body: sessionResult.body });
      const sessionId = sessionResult.body.session && sessionResult.body.session.id;
      if (!sessionId) {
        setRunState('需要处理', 'fail');
        return;
      }
      setSessionFromAcceptance(sessionResult.body.session);
      setAuthenticatedView();

      const jobResult = await api(apiPrefix + '/jobs', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          video_url: 'https://example.com/not-douyin',
          content: 'Self-test invalid URL should be rejected by the worker.',
          idempotency_key: 'self-test-' + sessionId
        })
      });
      add('submit_invalid_url_job', { status: jobResult.status, body: jobResult.body });
      setCurrentJob(jobResult.body.job && jobResult.body.job.job_id || '');
      if (!currentJobId) {
        setRunState('需要处理', 'fail');
        return;
      }

      let lastJob = null;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await delay(1000);
        const poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId));
        lastJob = poll.body.job || null;
        if (lastJob && terminalStatuses.has(lastJob.status)) break;
      }
      add('poll_invalid_url_job', { body: lastJob });

      const messages = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      add('messages', {
        status: messages.status,
        count: messages.body.messages ? messages.body.messages.length : 0
      });
      setRunState('自检完成', 'ok');
      });
    }
    async function runSecurityTest() {
      return withBusy('安全检查运行中', async () => {
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ security_test: steps });
      };
      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      add('identity_diagnostics', { status: diagnostics.status, body: diagnostics.body });
      if (!diagnostics.body.authenticated) {
        setPreLoginView();
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', { status: me.status, authenticated: me.body.authenticated === true });
      if (me.status !== 200) {
        setRunState('需要处理', 'fail');
        return;
      }

      const randomId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      const randomMessages = await api(apiPrefix + '/sessions/' + encodeURIComponent(randomId) + '/messages');
      add('random_session_404', { status: randomMessages.status, ok: randomMessages.status === 404 });
      const randomJob = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId));
      add('random_job_404', { status: randomJob.status, ok: randomJob.status === 404 });
      const randomResult = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId) + '/result');
      add('random_result_404', { status: randomResult.status, ok: randomResult.status === 404 });

      const sessionResult = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'OpenClaw security test ' + new Date().toISOString() })
      });
      add('create_session', { status: sessionResult.status, body: sessionResult.body });
      const sessionId = sessionResult.body.session && sessionResult.body.session.id;
      if (!sessionId) {
        setRunState('需要处理', 'fail');
        return;
      }
      setSessionFromAcceptance(sessionResult.body.session);
      setAuthenticatedView();

      const negativeCases = [
        ['non_allowlisted_domain', 'https://example.com/not-douyin'],
        ['localhost_blocked', 'http://127.0.0.1:8081/apps'],
        ['cloud_metadata_blocked', 'http://169.254.169.254/latest/meta-data/']
      ];
      for (const [caseName, videoUrl] of negativeCases) {
        const created = await api(apiPrefix + '/jobs', {
          method: 'POST',
          body: JSON.stringify({
            session_id: sessionId,
            video_url: videoUrl,
            content: 'Security negative case: ' + caseName,
            idempotency_key: 'security-' + caseName + '-' + sessionId
          })
        });
        add(caseName + '_submitted', { status: created.status, body: created.body });
        const jobId = created.body.job && created.body.job.job_id || '';
        if (!jobId) continue;
        setCurrentJob(jobId);
        let lastJob = null;
        for (let attempt = 0; attempt < 30; attempt += 1) {
          await delay(1000);
          const poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId));
          lastJob = poll.body.job || null;
          if (lastJob && terminalStatuses.has(lastJob.status)) break;
        }
        add(caseName + '_terminal', {
          job_id: jobId,
          status: lastJob ? lastJob.status : 'missing',
          error_code: lastJob ? lastJob.error_code : null,
          ok: !!lastJob && lastJob.status === 'failed' && lastJob.error_code === 'url_rejected'
        });
      }

      const messages = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      add('messages', {
        status: messages.status,
        count: messages.body.messages ? messages.body.messages.length : 0
      });
      const failed = steps.filter(step => step.ok === false).length;
      setRunState(failed ? '安全检查异常' : '安全检查完成', failed ? 'fail' : 'ok');
      });
    }
    async function runPostLoginAcceptance() {
      return withBusy('验收运行中', async () => {
      const steps = [];
      const render = (overall = 'RUNNING') => show({ post_login_acceptance: { overall, steps } });
      const add = (name, result) => {
        steps.push({ name, ...result });
        render();
      };
      const finish = () => {
        const failed = steps.filter(step => step.ok === false);
        const overall = failed.length ? 'FAIL' : 'PASS';
        render(overall);
        setRunState(overall === 'PASS' ? '验收通过' : '验收失败', overall === 'PASS' ? 'ok' : 'fail');
        if (overall === 'PASS') {
          setAuthState('已登录', 'ok');
          if (hasSession()) {
            sourceMetric.textContent = '等待视频来源';
            resultMetric.textContent = '会话已就绪';
            activateFlow(2);
          }
        }
      };

      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      const diagnosticsOk = diagnostics.status === 200
        && diagnostics.body.authenticated === true
        && diagnostics.body.profile_ok === true
        && diagnostics.body.workspace_ok === true
        && diagnostics.body.access_ok === true;
      add('identity_diagnostics', {
        status: diagnostics.status,
        ok: diagnosticsOk,
        authenticated: diagnostics.body.authenticated === true,
        profile_ok: diagnostics.body.profile_ok === true,
        workspace_ok: diagnostics.body.workspace_ok === true,
        access_ok: diagnostics.body.access_ok === true,
        failure_stage: diagnostics.body.failure_stage || null
      });
      if (!diagnosticsOk) {
        finish();
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', {
        status: me.status,
        ok: me.status === 200 && me.body.authenticated === true && typeof me.body.principal_id === 'string',
        authenticated: me.body.authenticated === true,
        principal_len: typeof me.body.principal_id === 'string' ? me.body.principal_id.length : 0
      });
      if (me.status !== 200) {
        finish();
        return;
      }

      const randomId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      const randomMessages = await api(apiPrefix + '/sessions/' + encodeURIComponent(randomId) + '/messages');
      add('random_session_404', { status: randomMessages.status, ok: randomMessages.status === 404 });
      const randomJob = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId));
      add('random_job_404', { status: randomJob.status, ok: randomJob.status === 404 });
      const randomResult = await api(apiPrefix + '/jobs/' + encodeURIComponent(randomId) + '/result');
      add('random_result_404', { status: randomResult.status, ok: randomResult.status === 404 });

      const sessionResult = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'OpenClaw post-login acceptance ' + new Date().toISOString() })
      });
      const sessionId = sessionResult.body.session && sessionResult.body.session.id || '';
      add('create_session', { status: sessionResult.status, ok: sessionResult.status === 201 && !!sessionId });
      if (!sessionId) {
        finish();
        return;
      }
      setSessionFromAcceptance(sessionResult.body.session);
      setAuthenticatedView();

      const negativeCases = [
        ['non_allowlisted_domain', 'https://example.com/not-douyin'],
        ['localhost_blocked', 'http://127.0.0.1:8081/apps'],
        ['cloud_metadata_blocked', 'http://169.254.169.254/latest/meta-data/']
      ];
      for (const [caseName, videoUrl] of negativeCases) {
        const created = await api(apiPrefix + '/jobs', {
          method: 'POST',
          body: JSON.stringify({
            session_id: sessionId,
            video_url: videoUrl,
            content: 'Post-login acceptance negative case: ' + caseName,
            idempotency_key: 'post-login-' + caseName + '-' + sessionId
          })
        });
        const jobId = created.body.job && created.body.job.job_id || '';
        add(caseName + '_submitted', { status: created.status, ok: created.status === 202 && !!jobId });
        if (!jobId) continue;
        setCurrentJob(jobId);
        const terminal = await pollTerminalJob(jobId, 30);
        const terminalJob = terminal.job;
        add(caseName + '_terminal', {
          job_id: jobId,
          status: terminalJob ? terminalJob.status : 'missing',
          error_code: terminalJob ? terminalJob.error_code : null,
          ok: !!terminalJob && terminalJob.status === 'failed' && terminalJob.error_code === 'url_rejected'
        });
      }

      const fileBytes = new Uint8Array([
        0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109,
        0, 0, 0, 0, 105, 115, 111, 109, 109, 112, 52, 49
      ]);
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('content', 'Post-login acceptance uploaded video.');
      form.append('video', new File([fileBytes], 'post-login-acceptance.mp4', { type: 'video/mp4' }));
      const uploadResponse = await fetch(apiPrefix + '/uploads', {
        method: 'POST',
        credentials: 'include',
        body: form
      });
      const uploadText = await uploadResponse.text();
      let uploadBody;
      try { uploadBody = uploadText ? JSON.parse(uploadText) : {}; } catch { uploadBody = { text: uploadText }; }
      const uploadJobId = uploadBody.job && uploadBody.job.job_id || '';
      add('tiny_upload_submitted', { status: uploadResponse.status, ok: uploadResponse.status === 202 && !!uploadJobId });
      if (uploadJobId) {
        setCurrentJob(uploadJobId);
        const uploadTerminal = await pollTerminalJob(uploadJobId, 40);
        const uploadJob = uploadTerminal.job;
        add('tiny_upload_terminal', {
          job_id: uploadJobId,
          status: uploadJob ? uploadJob.status : 'missing',
          ok: !!uploadJob && uploadJob.status === 'succeeded'
        });
        if (uploadJob && uploadJob.status === 'succeeded') {
          const result = await api(apiPrefix + '/jobs/' + encodeURIComponent(uploadJobId) + '/result');
          const platform = result.body.result && result.body.result.result && result.body.result.result.source
            ? result.body.result.result.source.platform
            : null;
          add('tiny_upload_result', {
            status: result.status,
            platform,
            ok: result.status === 200 && platform === 'upload'
          });
        }
      }

      const messages = await api(apiPrefix + '/sessions/' + encodeURIComponent(sessionId) + '/messages');
      add('messages_visible_to_owner', {
        status: messages.status,
        count: messages.body.messages ? messages.body.messages.length : 0,
        ok: messages.status === 200 && !!messages.body.messages && messages.body.messages.length >= 1
      });
      finish();
      });
    }
    async function sendChat() {
      return withBusy('发送中', async () => {
      const sessionId = document.getElementById('sessionId').value;
      const promptText = document.getElementById('prompt').value.trim();
      if (!sessionId || !promptText) {
        show('请先新建或选择对话，并输入问题。');
        setRunState('需要输入', 'fail');
        return;
      }
      pushMessage('user', promptText);
      const result = await api(apiPrefix + '/chat', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, content: promptText })
      });
      if (result.status === 200 && result.body.message) {
        pushMessage('assistant', result.body.message.content || 'OpenClaw 已回复。');
        setRunState('已回复', 'ok');
        resultMetric.textContent = '对话';
        activateFlow(4);
      } else {
        pushMessage('assistant', result.status === 501 ? '当前文本聊天适配器尚未配置，请先使用视频分析入口。' : '聊天请求返回 HTTP ' + result.status + '。');
        setRunState(result.status >= 500 ? '聊天不可用' : '聊天结束', result.status >= 500 ? 'fail' : 'warn');
      }
      show({ chat: { status: result.status, body: result.body } });
      });
    }
    async function submitJob() {
      return withBusy('提交分析', async () => {
      const promptText = document.getElementById('prompt').value || '请分析这个视频。';
      const videoUrl = document.getElementById('videoUrl').value;
      const result = await api(apiPrefix + '/jobs', {
        method: 'POST',
        body: JSON.stringify({
          session_id: document.getElementById('sessionId').value,
          video_url: videoUrl,
          content: promptText
        })
      });
      if (result.body.job && result.body.job.job_id) {
        linkReadable = false;
        setCurrentJob(result.body.job.job_id);
        setRunState('任务已提交', 'ok');
        sourceMetric.textContent = '链接已提交';
        resultMetric.textContent = '等待中';
        activateFlow(3);
        pushMessage('user', '已提交视频链接进行分析。');
        pushMessage('assistant', '任务已提交。稍后刷新状态查看分析进度。');
      } else {
        setRunState('需要处理', 'fail');
      }
      show(result);
      });
    }
    async function readVideoLink() {
      return withBusy('读取链接', async () => {
      const videoUrl = document.getElementById('videoUrl').value;
      const result = await api(apiPrefix + '/video-link/read-check', {
        method: 'POST',
        body: JSON.stringify({ video_url: videoUrl })
      });
      show({ status: result.status, video_link_read_check: result.body });
      if (result.status === 200 && result.body.status === 'PASS') {
        linkReadable = true;
        setRunState('链接可读取', 'ok');
        sourceMetric.textContent = (result.body.direct_video_candidate_count || 0) + ' 个候选';
        resultMetric.textContent = '可提交';
        activateFlow(3);
        pushMessage('assistant', '视频链接可读取。已找到直连候选，尚未调用模型。');
      } else {
        linkReadable = false;
        setRunState('链接检查结束', result.status >= 400 ? 'fail' : 'warn');
        resultMetric.textContent = '预检结束';
      }
      });
    }
    async function uploadJob() {
      return withBusy('上传视频', async () => {
      const fileInput = document.getElementById('videoFile');
      const file = fileInput.files && fileInput.files[0];
      const sessionId = document.getElementById('sessionId').value;
      if (!file || !sessionId) {
        show('请先选择视频文件和对话。');
        setRunState('需要输入', 'fail');
        return;
      }
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('content', document.getElementById('prompt').value || '请分析上传的视频。');
      form.append('video', file);
      const response = await fetch(apiPrefix + '/uploads', {
        method: 'POST',
        credentials: 'include',
        body: form
      });
      const text = await response.text();
      let body;
      try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
      if (body.job && body.job.job_id) {
        linkReadable = false;
        setCurrentJob(body.job.job_id);
        setRunState('上传已提交', 'ok');
        sourceMetric.textContent = '上传已接收';
        resultMetric.textContent = '等待中';
        activateFlow(3);
        pushMessage('user', '已上传视频文件进行分析。');
        pushMessage('assistant', '上传已接收。请刷新状态查看 worker 进度和结果。');
      } else {
        setRunState('需要处理', 'fail');
      }
      show({ status: response.status, body });
      });
    }
    async function uploadTinySmoke() {
      return withBusy('上传检查运行中', async () => {
      let sessionId = document.getElementById('sessionId').value;
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ upload_smoke: steps });
      };
      if (!sessionId) {
        const sessionResult = await api(apiPrefix + '/sessions', {
          method: 'POST',
          body: JSON.stringify({ title: 'OpenClaw upload smoke ' + new Date().toISOString() })
        });
        add('create_session', { status: sessionResult.status, body: sessionResult.body });
        sessionId = sessionResult.body.session && sessionResult.body.session.id || '';
        setSessionFromAcceptance(sessionResult.body.session);
        if (sessionId) setAuthenticatedView();
      }
      if (!sessionId) {
        setRunState('需要处理', 'fail');
        return;
      }
      const fileBytes = new Uint8Array([
        0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109,
        0, 0, 0, 0, 105, 115, 111, 109, 109, 112, 52, 49
      ]);
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('content', 'Smoke test uploaded video.');
      form.append('video', new File([fileBytes], 'tiny-smoke.mp4', { type: 'video/mp4' }));
      const response = await fetch(apiPrefix + '/uploads', {
        method: 'POST',
        credentials: 'include',
        body: form
      });
      const text = await response.text();
      let body;
      try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
      add('upload_job', { status: response.status, body });
      setCurrentJob(body.job && body.job.job_id || '');
      sourceMetric.textContent = '上传检查';
      resultMetric.textContent = currentJobId ? '等待中' : '无任务';
      if (currentJobId) activateFlow(3);
      if (!currentJobId) {
        setRunState('需要处理', 'fail');
        return;
      }
      let lastJob = null;
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await delay(1000);
        const poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId));
        lastJob = poll.body.job || null;
        add('poll_job', { status: poll.status, body: poll.body });
        if (lastJob && terminalStatuses.has(lastJob.status)) break;
      }
      if (lastJob && lastJob.status === 'succeeded') {
        add('job_result', await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId) + '/result'));
      }
      if (lastJob && lastJob.status === 'succeeded') {
        resultMetric.textContent = lastJob.result_schema_version || '已就绪';
        activateFlow(4);
      } else if (lastJob) {
        resultMetric.textContent = terminalStatuses.has(lastJob.status) ? lastJob.status : '等待中';
      }
      setRunState(lastJob && lastJob.status === 'succeeded' ? '上传检查完成' : '上传检查结束', lastJob && lastJob.status === 'succeeded' ? 'ok' : 'fail');
      });
    }
    async function pollJob() {
      return withBusy('刷新任务', async () => {
      if (!currentJobId) {
        show('当前还没有可刷新的任务。');
        setRunState('无任务', 'fail');
        return;
      }
      const jobResult = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId));
      const job = jobResult.body.job;
      if (job && job.status === 'succeeded') {
        const result = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId) + '/result');
        pushMessage('assistant', '分析结果已就绪，请查看右侧结构化结果。');
        show({ job: jobResult, result });
        setRunState('结果已就绪', 'ok');
        resultMetric.textContent = result.body.result && result.body.result.schema_version || '已就绪';
        activateFlow(4);
        return;
      }
      show(jobResult);
      if (job && job.status) {
        resultMetric.textContent = terminalStatuses.has(job.status) ? (job.result_schema_version || job.status) : '等待中';
      }
      setRunState(job && terminalStatuses.has(job.status) ? '任务已结束' : '任务运行中', job && terminalStatuses.has(job.status) ? 'fail' : 'busy');
      });
    }
    linkSourceTab.addEventListener('click', () => setSourceMode('link'));
    uploadSourceTab.addEventListener('click', () => setSourceMode('upload'));
    document.getElementById('openLogin').addEventListener('click', openLoginPanel);
    document.getElementById('closeLogin').addEventListener('click', closeLoginPanel);
    loginPanel.addEventListener('click', event => {
      if (event.target === loginPanel) closeLoginPanel();
    });
    ['loginAccount', 'loginPassword'].forEach(id => {
      document.getElementById(id).addEventListener('keydown', event => {
        if (event.key === 'Enter') login();
      });
    });
    document.getElementById('loginButton').addEventListener('click', login);
    document.getElementById('logoutButton').addEventListener('click', logout);
    document.getElementById('refreshMe').addEventListener('click', refreshMe);
    document.getElementById('identityDiagnostics').addEventListener('click', identityDiagnostics);
    document.getElementById('runSelfTest').addEventListener('click', runSelfTest);
    document.getElementById('runSecurityTest').addEventListener('click', runSecurityTest);
    document.getElementById('runPostLoginAcceptance').addEventListener('click', runPostLoginAcceptance);
    document.getElementById('createSession').addEventListener('click', createSession);
    document.getElementById('readVideoLink').addEventListener('click', readVideoLink);
    document.getElementById('submitJob').addEventListener('click', submitJob);
    document.getElementById('sendChat').addEventListener('click', sendChat);
    document.getElementById('refreshMessages').addEventListener('click', refreshMessages);
    document.getElementById('uploadJob').addEventListener('click', uploadJob);
    document.getElementById('uploadSmoke').addEventListener('click', uploadTinySmoke);
    document.getElementById('pollJob').addEventListener('click', pollJob);
    document.getElementById('sessionId').addEventListener('input', () => {
      if (isAuthenticated()) setAuthenticatedView();
      syncActionAvailability();
    });
    document.getElementById('videoUrl').addEventListener('input', () => {
      linkReadable = false;
      syncActionAvailability();
    });
    setPreLoginView();
    refreshMe({ quiet: true });
  </script>
</body>
</html>"""


def _default_session_store() -> Any:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from .postgres_store import PostgresSessionStore

        return PostgresSessionStore(database_url)
    return InMemorySessionStore()


def _default_job_store() -> Any:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from .postgres_store import PostgresJobStore

        return PostgresJobStore(database_url)
    return InMemoryJobStore()


def create_app(
    *,
    dify: Any | None = None,
    session_store: Any | None = None,
    job_store: Any | None = None,
    gateway: Any | None = None,
    openclaw_authenticator: Any | None = None,
    identity_secret: str | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenClaw Dify Bridge", version="0.1.0")
    identity_provider = os.environ.get("BRIDGE_IDENTITY_PROVIDER", "dify").strip().lower()
    if dify is None and identity_provider == "huahuo_front":
        dify = HuahuoFrontClient(
            os.environ.get("HUAHUO_FRONT_BASE", "https://www.huahuoai.com"),
            tenant_id=os.environ.get("HUAHUO_FRONT_TENANT_ID", "huahuo-front"),
        )
    dify = dify or DifyClient(os.environ.get("DIFY_API_BASE", "http://api:5001"))
    session_store = session_store or _default_session_store()
    job_store = job_store or _default_job_store()
    gateway = gateway or OpenClawGatewayWsClient.from_environment()
    openclaw_authenticator = openclaw_authenticator or default_openclaw_authenticator()
    identity_secret = identity_secret if identity_secret is not None else os.environ.get("BRIDGE_IDENTITY_SECRET", "")
    enable_test_identity_headers = os.environ.get("BRIDGE_ENABLE_TEST_IDENTITY_HEADERS", "").lower() in {"1", "true", "yes"}
    test_identity_secret = os.environ.get("BRIDGE_TEST_IDENTITY_SECRET", "")
    phase4_config = load_phase4_config()
    rate_limiter = SlidingWindowRateLimiter()
    login_limiter = SlidingWindowRateLimiter()
    login_rate_limit = positive_int_from_env("OPENCLAW_LOGIN_RATE_LIMIT_PER_MINUTE", 8)
    openclaw_session_ttl_seconds = positive_int_from_env("OPENCLAW_SESSION_TTL_SECONDS", 7 * 24 * 60 * 60)

    @app.middleware("http")
    async def _forward_dify_refresh_cookies(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        for header in getattr(request.state, "dify_set_cookie_headers", []):
            response.headers.append("set-cookie", header)
        return response

    @app.exception_handler(Exception)
    async def _exception_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": safe_error_message(exc)})

    def health_payload() -> dict[str, Any]:
        return {
            "status": "ok",
            "component": "openclaw-bridge",
            "dify_api_base": os.environ.get("DIFY_API_BASE", "http://api:5001"),
            "identity_provider": identity_provider,
        }

    def runtime_metadata() -> dict[str, Any]:
        max_upload_bytes = positive_int_from_env("MAX_UPLOAD_BYTES", phase4_config.max_upload_bytes)
        return {
            "versions": {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "knowledge_base_version": phase4_config.knowledge_base_version,
                "bridge_version": phase4_config.bridge_version,
                "openclaw_version": phase4_config.openclaw_version,
            },
            "limits": {
                "max_upload_bytes": max_upload_bytes,
                "user_active_job_limit": phase4_config.user_active_job_limit or None,
                "user_rate_limit_per_minute": phase4_config.user_rate_limit_per_minute or None,
                "data_retention_days": phase4_config.data_retention_days or None,
            },
            "access": {
                "tenant_allowlist_enabled": bool(phase4_config.tenant_allowlist_hashes),
                "account_allowlist_enabled": bool(phase4_config.account_allowlist_hashes),
                "identity_provider": identity_provider,
            },
        }

    def principal_allowed(tenant_hash: str, account_hash: str) -> bool:
        if phase4_config.tenant_allowlist_hashes and tenant_hash not in phase4_config.tenant_allowlist_hashes:
            return False
        if phase4_config.account_allowlist_hashes and account_hash not in phase4_config.account_allowlist_hashes:
            return False
        return True

    def enforce_principal_allowed(tenant_hash: str, account_hash: str) -> None:
        if not principal_allowed(tenant_hash, account_hash):
            raise HTTPException(status_code=403, detail="OpenClaw access is not allowed for this account")

    def enforce_job_submission_controls(principal: DifyPrincipal) -> None:
        active_limit = phase4_config.user_active_job_limit
        if active_limit > 0 and hasattr(job_store, "count_active_jobs"):
            active_count = int(job_store.count_active_jobs(principal.principal_id))
            if active_count >= active_limit:
                raise HTTPException(status_code=429, detail="active job limit exceeded")
        rate_limit = phase4_config.user_rate_limit_per_minute
        if not rate_limiter.allow(principal.principal_id, limit=rate_limit):
            raise HTTPException(status_code=429, detail="job submission rate limit exceeded")

    def remember_dify_set_cookie_headers(request: Request, headers: Any) -> None:
        safe_headers = [str(header) for header in (headers or []) if header]
        if not safe_headers:
            return
        existing = list(getattr(request.state, "dify_set_cookie_headers", []))
        request.state.dify_set_cookie_headers = existing + safe_headers

    def set_openclaw_session_cookie(response: JSONResponse, request: Request, value: str, expires_at: datetime) -> None:
        response.set_cookie(
            OPENCLAW_SESSION_COOKIE_NAME,
            value,
            max_age=openclaw_session_ttl_seconds,
            expires=expires_at,
            path="/",
            httponly=True,
            secure=_request_is_secure(request),
            samesite="lax",
        )

    def clear_openclaw_session_cookie(response: JSONResponse, request: Request) -> None:
        response.delete_cookie(
            OPENCLAW_SESSION_COOKIE_NAME,
            path="/",
            secure=_request_is_secure(request),
            samesite="lax",
            httponly=True,
        )

    def principal_from_openclaw_cookie(request: Request) -> tuple[DifyPrincipal, str, str] | None:
        return _principal_from_openclaw_session_cookie(
            identity_secret,
            request.cookies.get(OPENCLAW_SESSION_COOKIE_NAME, ""),
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return health_payload()

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return health_payload()

    @app.get("/openclaw-lab", response_class=HTMLResponse)
    @app.get("/openclaw-lab/", response_class=HTMLResponse)
    @app.get("/ai/openclaw-lab", response_class=HTMLResponse)
    @app.get("/ai/openclaw-lab/", response_class=HTMLResponse)
    async def openclaw_lab() -> HTMLResponse:
        return HTMLResponse(
            LAB_PAGE_HTML,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
            },
        )

    @app.post("/openclaw-api/auth/login")
    @app.post("/ai/openclaw-api/auth/login")
    @app.post("/api/openclaw-api/auth/login")
    @app.post("/console/api/openclaw-api/auth/login")
    async def openclaw_login(request: Request) -> JSONResponse:
        if openclaw_authenticator is None:
            raise HTTPException(status_code=503, detail="password login is not configured")
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        account = str(payload.get("account") or payload.get("username") or payload.get("email") or "").strip()
        password = str(payload.get("password") or "")
        remote_addr = request.client.host if request.client else "unknown"
        rate_key = f"{remote_addr}:{account.lower()[:80]}"
        if not login_limiter.allow(rate_key, limit=login_rate_limit):
            raise HTTPException(status_code=429, detail="login rate limit exceeded")
        try:
            identity = openclaw_authenticator.authenticate(account, password)
            principal = derive_principal(identity_secret, identity.profile, identity.workspaces)
            tenant_hash, account_hash = _principal_hashes(identity_secret, principal)
            enforce_principal_allowed(tenant_hash, account_hash)
            if hasattr(session_store, "ensure_user"):
                session_store.ensure_user(principal.principal_id, tenant_hash, account_hash)
            cookie_value, expires_at = _issue_openclaw_session_cookie(
                identity_secret,
                principal,
                tenant_hash,
                account_hash,
                ttl_seconds=openclaw_session_ttl_seconds,
            )
        except (OpenClawAuthenticationError, PermissionError) as exc:
            raise HTTPException(status_code=401, detail="login failed") from exc
        except IdentityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        response = JSONResponse(
            content={
                "authenticated": True,
                "principal_id": principal.principal_id,
                "expires_at": expires_at.isoformat(),
                **runtime_metadata(),
            }
        )
        set_openclaw_session_cookie(response, request, cookie_value, expires_at)
        return response

    @app.post("/openclaw-api/auth/logout")
    @app.post("/ai/openclaw-api/auth/logout")
    @app.post("/api/openclaw-api/auth/logout")
    @app.post("/console/api/openclaw-api/auth/logout")
    async def openclaw_logout(request: Request) -> JSONResponse:
        response = JSONResponse(content={"authenticated": False})
        clear_openclaw_session_cookie(response, request)
        return response

    async def current_principal(request: Request) -> DifyPrincipal:
        try:
            session_identity = principal_from_openclaw_cookie(request)
            if session_identity is not None:
                principal, tenant_hash, account_hash = session_identity
                enforce_principal_allowed(tenant_hash, account_hash)
                if hasattr(session_store, "ensure_user"):
                    session_store.ensure_user(principal.principal_id, tenant_hash, account_hash)
                return principal
            if _test_identity_headers_allowed(request, enable_test_identity_headers, test_identity_secret):
                profile = {"id": request.headers["x-test-account"]}
                tenant_id = request.headers.get("x-test-tenant", "test-tenant")
                workspaces = {"data": [{"id": tenant_id, "current": True}]}
            elif hasattr(dify, "resolve_identity"):
                identity_context = await dify.resolve_identity(request.headers)
                remember_dify_set_cookie_headers(request, getattr(identity_context, "set_cookie_headers", ()))
                profile, workspaces = identity_context.profile, identity_context.workspaces
            else:
                profile, workspaces = await dify.profile(request.headers), await dify.workspaces(request.headers)
            principal = derive_principal(identity_secret, profile, workspaces)
            tenant_hash, account_hash = _principal_hashes(identity_secret, principal)
            enforce_principal_allowed(tenant_hash, account_hash)
            if hasattr(session_store, "ensure_user"):
                session_store.ensure_user(
                    principal.principal_id,
                    tenant_hash,
                    account_hash,
                )
            return principal
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="login required") from exc
        except IdentityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/openclaw-api/me")
    @app.get("/ai/openclaw-api/me")
    @app.get("/api/openclaw-api/me")
    @app.get("/console/api/openclaw-api/me")
    async def me(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        return {"principal_id": principal.principal_id, "authenticated": True, **runtime_metadata()}

    @app.get("/openclaw-api/identity/diagnostics")
    @app.get("/ai/openclaw-api/identity/diagnostics")
    @app.get("/api/openclaw-api/identity/diagnostics")
    @app.get("/console/api/openclaw-api/identity/diagnostics")
    async def identity_diagnostics(request: Request) -> dict[str, Any]:
        result: dict[str, Any] = {
            "authenticated": False,
            "login_material_present": _has_dify_login_material(request.headers),
            "openclaw_session_present": bool(request.cookies.get(OPENCLAW_SESSION_COOKIE_NAME)),
            "auth_mode": None,
            "huahuo_access_token_present": _has_header(request.headers, "x-huahuo-access-token"),
            "huahuo_app_uuid_present": _has_header(request.headers, "x-huahuo-app-uuid"),
            "profile_ok": False,
            "workspace_ok": False,
            "access_ok": False,
            "current_workspace_count": 0,
            "principal_id": None,
            "failure_stage": None,
            "provider_probe": None,
        }
        try:
            session_identity = principal_from_openclaw_cookie(request)
            if session_identity is not None:
                principal, tenant_hash, account_hash = session_identity
                result["profile_ok"] = True
                result["workspace_ok"] = True
                result["current_workspace_count"] = 1
                if not principal_allowed(tenant_hash, account_hash):
                    result["failure_stage"] = "access"
                    return result
                result["access_ok"] = True
                result["authenticated"] = True
                result["principal_id"] = principal.principal_id
                result["auth_mode"] = "openclaw_session"
                return result
            if _test_identity_headers_allowed(request, enable_test_identity_headers, test_identity_secret):
                profile = {"id": request.headers["x-test-account"]}
                result["profile_ok"] = True
                tenant_id = request.headers.get("x-test-tenant", "test-tenant")
                workspaces = {"data": [{"id": tenant_id, "current": True}]}
                result["current_workspace_count"] = current_workspace_count(workspaces)
                principal = derive_principal(identity_secret, profile, workspaces)
                result["workspace_ok"] = True
                tenant_hash, account_hash = _principal_hashes(identity_secret, principal)
                if not principal_allowed(tenant_hash, account_hash):
                    result["failure_stage"] = "access"
                    return result
                result["access_ok"] = True
                result["authenticated"] = True
                result["principal_id"] = principal.principal_id
                result["auth_mode"] = "test_identity_headers"
                return result
            if hasattr(dify, "safe_identity_probe"):
                try:
                    result["provider_probe"] = await dify.safe_identity_probe(request.headers)
                except Exception:
                    result["provider_probe"] = {"provider": identity_provider, "error_stage": "probe"}
            if hasattr(dify, "resolve_identity"):
                identity_context = await dify.resolve_identity(request.headers)
                remember_dify_set_cookie_headers(request, getattr(identity_context, "set_cookie_headers", ()))
                profile = identity_context.profile
                result["_resolved_workspaces"] = identity_context.workspaces
            else:
                profile = await dify.profile(request.headers)
            result["profile_ok"] = True
        except PermissionError:
            result["failure_stage"] = "profile"
            return result
        except Exception:
            result["failure_stage"] = "profile"
            return result
        try:
            workspaces = result.pop("_resolved_workspaces", None)
            if workspaces is None:
                workspaces = await dify.workspaces(request.headers)
            result["current_workspace_count"] = current_workspace_count(workspaces)
            principal = derive_principal(identity_secret, profile, workspaces)
            result["workspace_ok"] = True
            tenant_hash, account_hash = _principal_hashes(identity_secret, principal)
            if not principal_allowed(tenant_hash, account_hash):
                result["failure_stage"] = "access"
                return result
            result["access_ok"] = True
            result["authenticated"] = True
            result["principal_id"] = principal.principal_id
            result["auth_mode"] = identity_provider
            return result
        except Exception:
            result["failure_stage"] = "workspace"
            return result

    @app.get("/openclaw-api/sessions")
    @app.get("/ai/openclaw-api/sessions")
    @app.get("/api/openclaw-api/sessions")
    @app.get("/console/api/openclaw-api/sessions")
    async def sessions(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        return {"sessions": [_serialize_session(item) for item in session_store.list_sessions(principal.principal_id)]}

    @app.post("/openclaw-api/sessions", status_code=201)
    @app.post("/ai/openclaw-api/sessions", status_code=201)
    @app.post("/api/openclaw-api/sessions", status_code=201)
    @app.post("/console/api/openclaw-api/sessions", status_code=201)
    async def create_session(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        session_id = str(uuid.uuid4())
        routing_user = derive_openclaw_routing_user(identity_secret, principal.principal_id, session_id)
        session = session_store.create_session(
            principal.principal_id,
            str(payload.get("title") or "OpenClaw session"),
            routing_user,
            session_id=session_id,
        )
        return {"session": _serialize_session(session)}

    @app.get("/openclaw-api/sessions/{session_id}/messages")
    @app.get("/ai/openclaw-api/sessions/{session_id}/messages")
    @app.get("/api/openclaw-api/sessions/{session_id}/messages")
    @app.get("/console/api/openclaw-api/sessions/{session_id}/messages")
    async def messages(session_id: str, request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        try:
            messages = session_store.list_messages(session_id, principal.principal_id)
        except (SessionNotFound, SessionOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        return {"messages": [_serialize_message(item) for item in messages]}

    @app.post("/openclaw-api/jobs")
    @app.post("/ai/openclaw-api/jobs")
    @app.post("/api/openclaw-api/jobs")
    @app.post("/console/api/openclaw-api/jobs")
    async def create_job(request: Request) -> JSONResponse:
        principal = await current_principal(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        session_id = str(payload.get("session_id") or "")
        video_url = str(payload.get("video_url") or "").strip()
        if not session_id or not video_url:
            raise HTTPException(status_code=400, detail="session_id and video_url are required")
        try:
            session_store.get_session(session_id, principal.principal_id)
        except (SessionNotFound, SessionOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        idempotency_key = payload.get("idempotency_key")
        normalized_idempotency_key = str(idempotency_key) if idempotency_key else None
        if normalized_idempotency_key and hasattr(job_store, "get_job_by_idempotency"):
            try:
                existing_job = job_store.get_job_by_idempotency(
                    principal.principal_id,
                    session_id,
                    normalized_idempotency_key,
                )
                return JSONResponse(status_code=202, content={"job": _serialize_job(existing_job)})
            except JobNotFound:
                pass
        enforce_job_submission_controls(principal)
        job = job_store.create_job(
            principal.principal_id,
            session_id,
            video_url,
            idempotency_key=normalized_idempotency_key,
        )
        session_store.add_message(
            session_id,
            principal.principal_id,
            "user",
            str(payload.get("content") or "Analyze video"),
            video_url=video_url,
            job_id=job.job_id,
        )
        return JSONResponse(status_code=202, content={"job": _serialize_job(job)})

    @app.post("/openclaw-api/video-link/read-check")
    @app.post("/ai/openclaw-api/video-link/read-check")
    @app.post("/api/openclaw-api/video-link/read-check")
    @app.post("/console/api/openclaw-api/video-link/read-check")
    async def video_link_read_check(request: Request) -> dict[str, Any]:
        await current_principal(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        video_url = str(payload.get("video_url") or "").strip()
        if not video_url:
            raise HTTPException(status_code=400, detail="video_url is required")
        try:
            return probe_video_link(
                video_url,
                config=VideoLinkProbeConfig(
                    max_duration_seconds=positive_int_from_env("MAX_VIDEO_DURATION_SECONDS", 60),
                    max_download_bytes=positive_int_from_env("MAX_DOWNLOAD_BYTES", 512 * 1024 * 1024),
                ),
            )
        except UrlRejected as exc:
            raise HTTPException(status_code=400, detail=safe_error_message(str(exc))) from exc
        except VideoLinkProbeError as exc:
            raise HTTPException(status_code=502, detail=safe_error_message(str(exc))) from exc

    @app.post("/openclaw-api/uploads")
    @app.post("/ai/openclaw-api/uploads")
    @app.post("/api/openclaw-api/uploads")
    @app.post("/console/api/openclaw-api/uploads")
    async def create_upload_job(request: Request) -> JSONResponse:
        principal = await current_principal(request)
        form = await request.form()
        session_id = str(form.get("session_id") or "")
        content = str(form.get("content") or "Analyze uploaded video")
        file = form.get("video")
        if not session_id or not _is_form_upload(file):
            raise HTTPException(status_code=400, detail="session_id and video file are required")
        try:
            session_store.get_session(session_id, principal.principal_id)
            enforce_job_submission_controls(principal)
            max_upload_bytes = positive_int_from_env("MAX_UPLOAD_BYTES", phase4_config.max_upload_bytes)
            await file.seek(0)
            stored = store_upload_fileobj(
                file.file,
                filename=str(file.filename or "video.mp4"),
                max_bytes=max_upload_bytes,
            )
        except (SessionNotFound, SessionOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except UploadStoreError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await file.close()
        job = job_store.create_job(principal.principal_id, session_id, stored.uri)
        session_store.add_message(
            session_id,
            principal.principal_id,
            "user",
            content,
            video_url=stored.uri,
            job_id=job.job_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "job": _serialize_job(job),
                "upload": {
                    "filename": stored.filename,
                    "size_bytes": stored.size_bytes,
                    "sha256": stored.sha256,
                },
            },
        )

    @app.get("/openclaw-api/jobs/{job_id}")
    @app.get("/ai/openclaw-api/jobs/{job_id}")
    @app.get("/api/openclaw-api/jobs/{job_id}")
    @app.get("/console/api/openclaw-api/jobs/{job_id}")
    async def get_job(job_id: str, request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        try:
            job = job_store.get_job(job_id, principal.principal_id)
        except (JobNotFound, JobOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        return {"job": _serialize_job(job)}

    @app.get("/openclaw-api/jobs/{job_id}/result")
    @app.get("/ai/openclaw-api/jobs/{job_id}/result")
    @app.get("/api/openclaw-api/jobs/{job_id}/result")
    @app.get("/console/api/openclaw-api/jobs/{job_id}/result")
    async def get_job_result(job_id: str, request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        try:
            result = job_store.get_result(job_id, principal.principal_id)
        except (JobNotFound, JobOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="job result not found") from exc
        return {"result": _serialize_result(result)}

    @app.get("/openclaw-api/jobs/{job_id}/events")
    @app.get("/ai/openclaw-api/jobs/{job_id}/events")
    @app.get("/api/openclaw-api/jobs/{job_id}/events")
    @app.get("/console/api/openclaw-api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request) -> StreamingResponse:
        principal = await current_principal(request)
        try:
            job_store.get_job(job_id, principal.principal_id)
        except (JobNotFound, JobOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

        async def stream():
            last_status: str | None = None
            while True:
                if await request.is_disconnected():
                    return
                try:
                    job = job_store.get_job(job_id, principal.principal_id)
                except (JobNotFound, JobOwnershipError):
                    yield _sse_event("error", {"error": "job not found"})
                    return
                serialized = _serialize_job(job)
                status = serialized["status"]
                if status != last_status:
                    yield _sse_event("job", {"job": serialized})
                    last_status = status
                if job.status in TERMINAL_STATUSES:
                    yield _sse_event("done", {"job_id": job.job_id, "status": job.status.value})
                    return
                yield _sse_event("heartbeat", {"job_id": job.job_id, "status": job.status.value})
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/openclaw-api/retention/cleanup")
    @app.post("/ai/openclaw-api/retention/cleanup")
    @app.post("/api/openclaw-api/retention/cleanup")
    @app.post("/console/api/openclaw-api/retention/cleanup")
    async def cleanup_retention(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        retention_days = phase4_config.data_retention_days
        if retention_days <= 0:
            raise HTTPException(status_code=400, detail="data retention cleanup is disabled")
        if not hasattr(job_store, "cleanup_terminal_jobs_before"):
            raise HTTPException(status_code=501, detail="job store does not support retention cleanup")
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        result = job_store.cleanup_terminal_jobs_before(principal.principal_id, cutoff)
        deleted_messages = 0
        if hasattr(session_store, "delete_messages_for_jobs"):
            deleted_messages = session_store.delete_messages_for_jobs(principal.principal_id, result.deleted_job_ids)
        deleted_uploads = 0
        for uri in result.upload_uris:
            try:
                if delete_upload_uri(uri):
                    deleted_uploads += 1
            except UploadStoreError:
                continue
        return {
            "status": "ok",
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
            "deleted_jobs": result.deleted_jobs,
            "deleted_results": result.deleted_results,
            "deleted_messages": deleted_messages,
            "deleted_uploads": deleted_uploads,
        }

    @app.post("/openclaw-api/chat")
    @app.post("/ai/openclaw-api/chat")
    @app.post("/api/openclaw-api/chat")
    @app.post("/console/api/openclaw-api/chat")
    async def chat(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        if payload.get("video_url"):
            return await create_job(request)
        principal = await current_principal(request)
        session_id = str(payload.get("session_id") or "")
        content = str(payload.get("content") or "").strip()
        if not session_id or not content:
            raise HTTPException(status_code=400, detail="session_id and content are required")
        if isinstance(gateway, DisabledGatewayClient):
            raise HTTPException(status_code=501, detail="offline draft has no Gateway chat adapter")
        try:
            session = session_store.get_session(session_id, principal.principal_id)
            history = session_store.list_messages(session_id, principal.principal_id)
            user_message = session_store.add_message(session_id, principal.principal_id, "user", content)
        except (SessionNotFound, SessionOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except MessageValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        chat_request = GatewayChatRequest(
            routing_user=session.openclaw_routing_user,
            session_id=session.id,
            message_id=user_message.id,
            content=user_message.content,
            history=tuple({"role": item.role, "content": item.content} for item in history),
        )
        try:
            result = await gateway.chat(chat_request)
        except GatewayNotConfigured as exc:
            raise HTTPException(status_code=501, detail="offline draft has no Gateway chat adapter") from exc
        except GatewayError as exc:
            raise HTTPException(status_code=502, detail=safe_error_message(exc)) from exc
        assistant_message = session_store.add_message(
            session_id,
            principal.principal_id,
            "assistant",
            result.content,
        )
        return JSONResponse(
            status_code=200,
            content={
                "message": _serialize_message(assistant_message),
                "session": _serialize_session(session_store.get_session(session_id, principal.principal_id)),
            },
        )

    return app


app = create_app()
