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
from .agent_persona import (
    NEW_SESSION_GREETING,
    build_agent_message,
    build_branch_prompt,
    current_video_from_history,
    derive_state,
    detect_intent,
    error_reply_for,
    fixed_state_reply,
    guardrail_for_message,
)


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
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei UI", Inter, ui-sans-serif, system-ui, "Segoe UI", sans-serif;
      background: #f4f6fb;
      color: #0b1220;
      --page: #f3f5fb;
      --surface: #ffffff;
      --surface-soft: #f7f9fd;
      --surface-raised: #fbfcff;
      --border: #e3e8f0;
      --border-strong: #cbd3e1;
      --text: #0b1220;
      --muted: #67738a;
      --faint: #eef1f8;
      --primary: #2563ff;
      --primary-strong: #1648d6;
      --primary-soft: #eaf1ff;
      --primary-ring: rgba(37, 99, 255, .16);
      --analysis: #0f766e;
      --ink: #141b2d;
      --success: #11785f;
      --success-bg: #e3f7ef;
      --danger: #c0362c;
      --danger-bg: #fdeae7;
      --warning: #9a5b00;
      --warning-bg: #fff3d7;
      --info: #0a6c84;
      --info-bg: #e1f5f8;
      --r-xs: 8px;
      --r-sm: 12px;
      --r-md: 16px;
      --r-lg: 22px;
      --r-pill: 999px;
      --shadow-sm: 0 1px 2px rgba(16, 24, 40, .04), 0 1px 3px rgba(16, 24, 40, .05);
      --shadow-md: 0 2px 6px rgba(16, 24, 40, .05), 0 12px 28px rgba(16, 24, 40, .07);
      --shadow-lg: 0 8px 24px rgba(16, 24, 40, .09), 0 28px 60px rgba(16, 24, 40, .12);
      --shadow-primary: 0 8px 18px rgba(37, 99, 255, .22), 0 2px 5px rgba(37, 99, 255, .18);
      --ease: cubic-bezier(.22, .61, .36, 1);
    }
    @media (prefers-reduced-motion: reduce) {
      * { transition: none !important; animation: none !important; scroll-behavior: auto !important; }
    }
    * { box-sizing: border-box; }
    ::selection { background: rgba(37, 99, 255, .18); color: var(--ink); }
    * { scrollbar-width: thin; scrollbar-color: #c3ccdb transparent; }
    *::-webkit-scrollbar { width: 10px; height: 10px; }
    *::-webkit-scrollbar-thumb { background: #c8d1de; border-radius: var(--r-pill); border: 3px solid transparent; background-clip: content-box; }
    *::-webkit-scrollbar-thumb:hover { background: #aab6c8; background-clip: content-box; }
    *::-webkit-scrollbar-track { background: transparent; }
    pre::-webkit-scrollbar-thumb { background: #3a4761; background-clip: content-box; }
    html { min-height: 100%; background: var(--page); }
    body {
      margin: 0;
      min-height: 100vh;
      overflow-x: hidden;
      background:
        radial-gradient(1200px 600px at 88% -8%, rgba(37, 99, 255, .07), transparent 60%),
        radial-gradient(900px 500px at -6% 4%, rgba(15, 118, 110, .05), transparent 55%),
        linear-gradient(180deg, #fbfcff 0, var(--page) 280px, #eaeef7 100%);
      color: var(--text);
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
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
      width: 46px;
      height: 46px;
      flex: 0 0 auto;
      border-radius: 14px;
      background: linear-gradient(150deg, #3b78ff 0%, #2563ff 45%, #143fb0 100%);
      color: #ffffff;
      font-weight: 800;
      letter-spacing: .5px;
      box-shadow: 0 10px 22px rgba(37, 99, 255, .32), inset 0 1px 0 rgba(255, 255, 255, .4);
    }
    .eyebrow { margin: 0 0 3px; color: #5a6678; font-size: 12.5px; font-weight: 650; letter-spacing: .2px; }
    .brand-subtitle {
      margin: 5px 0 0;
      max-width: 620px;
      color: #586579;
      font-size: 14px;
      line-height: 1.4;
    }
    h1 { font-size: 30px; line-height: 1.08; margin: 0; font-weight: 750; letter-spacing: -.5px; }
    h2 { font-size: 16px; line-height: 1.25; margin: 0; font-weight: 700; letter-spacing: -.2px; }
    h3 { font-size: 15px; line-height: 1.25; margin: 0; font-weight: 700; }
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
      min-height: 40px;
      padding: 0 8px;
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      background: rgba(255, 255, 255, .9);
      color: #586579;
      font-size: 12px;
      font-weight: 700;
      box-shadow: var(--shadow-sm);
      transition: background .25s var(--ease), color .25s var(--ease), border-color .25s var(--ease), box-shadow .25s var(--ease);
    }
    .flow-step::before {
      content: attr(data-step);
      display: grid;
      place-items: center;
      width: 21px;
      height: 21px;
      border-radius: var(--r-pill);
      background: #e8eef7;
      color: #42526a;
      font-size: 11px;
      font-weight: 800;
      transition: background .25s var(--ease), color .25s var(--ease);
    }
    .flow-step.active {
      border-color: #b8cdfd;
      background: var(--primary-soft);
      color: var(--primary-strong);
      box-shadow: 0 6px 16px rgba(37, 99, 255, .12);
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
      min-height: 36px;
      border-radius: var(--r-pill);
      padding: 7px 13px;
      border: 1px solid transparent;
      background: var(--faint);
      color: #334155;
      font-size: 13px;
      font-weight: 650;
      white-space: nowrap;
      transition: background .25s var(--ease), color .25s var(--ease), border-color .25s var(--ease);
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
      border-radius: var(--r-md);
      background: rgba(255, 255, 255, .98);
      padding: 18px;
      box-shadow: var(--shadow-md);
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
      width: 28px;
      height: 28px;
      border-radius: var(--r-xs);
      background: var(--primary-soft);
      color: var(--primary);
      font-size: 12px;
      font-weight: 800;
      flex: 0 0 auto;
    }
    .section-note { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.45; max-width: 640px; }
    label { display: block; font-size: 13px; color: #475569; margin: 10px 0 6px; font-weight: 650; }
    input, textarea {
      width: 100%;
      border: 1px solid var(--border-strong);
      border-radius: var(--r-xs);
      min-height: 44px;
      padding: 11px 13px;
      font: inherit;
      color: var(--text);
      background: #fbfcff;
      box-shadow: inset 0 1px 0 rgba(17, 24, 39, .03);
      transition: border-color .2s var(--ease), box-shadow .2s var(--ease), background .2s var(--ease);
    }
    input:hover, textarea:hover { border-color: #b6c0d2; }
    input::placeholder, textarea::placeholder { color: #97a2b3; }
    input:focus-visible,
    textarea:focus-visible,
    button:focus-visible {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 4px var(--primary-ring);
    }
    textarea { min-height: 96px; resize: vertical; }
    input[type="file"] { padding: 8px; background: var(--surface); }
    input[type="file"]::file-selector-button {
      min-height: 34px;
      margin-right: 10px;
      border: 1px solid var(--border);
      border-radius: var(--r-xs);
      padding: 0 12px;
      background: var(--primary-soft);
      color: var(--primary-strong);
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: background .2s var(--ease);
    }
    input[type="file"]::file-selector-button:hover { background: #dee9ff; }
    button {
      border: 1px solid transparent;
      border-radius: var(--r-xs);
      min-height: 44px;
      padding: 0 17px;
      font: inherit;
      font-weight: 650;
      color: #fff;
      background: var(--primary);
      cursor: pointer;
      box-shadow: var(--shadow-primary);
      transition: transform .16s var(--ease), box-shadow .16s var(--ease), background .16s var(--ease), border-color .16s var(--ease), opacity .16s var(--ease);
    }
    button:hover { background: var(--primary-strong); transform: translateY(-1px); box-shadow: 0 12px 24px rgba(37, 99, 255, .28), 0 3px 6px rgba(37, 99, 255, .2); }
    button:active { transform: translateY(0) scale(.985); }
    button.secondary {
      color: #283449;
      background: #f5f7fb;
      border-color: var(--border);
      box-shadow: none;
    }
    button.secondary:hover { background: #eaeff6; border-color: #c6d1df; box-shadow: none; transform: translateY(-1px); }
    button:disabled { opacity: .5; cursor: not-allowed; }
    button:disabled:hover { transform: none; box-shadow: none; }
    button.primary-flow {
      min-width: 148px;
      background: var(--primary-soft);
      color: var(--primary-strong);
      border-color: #cad9ff;
      box-shadow: none;
    }
    button.primary-flow:hover { background: #dee9ff; box-shadow: none; }
    button.primary-flow.primary-active {
      background: var(--primary);
      color: #fff;
      border-color: transparent;
      box-shadow: var(--shadow-primary);
    }
    button.primary-flow.primary-active:hover { background: var(--primary-strong); box-shadow: 0 12px 24px rgba(37, 99, 255, .28); }
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
      min-height: 46px;
      margin: 10px 0 12px;
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 4px;
      background: #eef1f8;
    }
    .source-tab {
      min-height: 38px;
      padding: 0 12px;
      border-radius: var(--r-xs);
      background: transparent;
      color: #42526a;
      border-color: transparent;
      box-shadow: none;
      font-weight: 650;
    }
    .source-tab:hover { background: rgba(255,255,255,.7); color: var(--ink); box-shadow: none; transform: none; }
    .source-tab.active {
      background: #fff;
      color: var(--primary);
      border-color: #d8e3ff;
      box-shadow: var(--shadow-sm);
    }
    .source-tab.active:hover { transform: none; }
    .source-panel[hidden] { display: none; }
    .source-panel {
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 14px;
      background: var(--surface-raised);
    }
    .source-panel .actions { margin-top: 12px; }
    .conversation {
      display: grid;
      gap: 10px;
      min-height: 112px;
      max-height: 230px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 12px;
      background: linear-gradient(180deg, #fbfdff, #f5f8fc);
    }
    .message {
      width: fit-content;
      max-width: min(100%, 620px);
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 10px 13px;
      background: var(--surface);
      color: var(--ink);
      font-size: 13.5px;
      line-height: 1.5;
      box-shadow: var(--shadow-sm);
      animation: msg-in .3s var(--ease) both;
    }
    @keyframes msg-in {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .message.user {
      justify-self: end;
      border-color: #bfd0ff;
      background: linear-gradient(180deg, #f1f6ff, #e9f1ff);
      border-bottom-right-radius: 5px;
    }
    .message.assistant {
      justify-self: start;
      border-color: #c8e6d8;
      background: linear-gradient(180deg, #f3fbf7, #edf9f3);
      border-bottom-left-radius: 5px;
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
      border-radius: var(--r-sm);
      padding: 12px 14px;
      background: linear-gradient(180deg, #f1f6ff, var(--primary-soft));
      color: #1c3a8a;
      font-size: 13.5px;
      line-height: 1.5;
      font-weight: 600;
    }
    .next-action span {
      display: block;
      margin-bottom: 3px;
      color: #56708f;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .6px;
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
      border-radius: var(--r-sm);
      padding: 12px;
      background: linear-gradient(180deg, #ffffff, #f7f9fd);
      box-shadow: var(--shadow-sm);
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
      border-radius: var(--r-sm);
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
      min-height: 44px;
      display: flex;
      align-items: center;
      margin-bottom: 10px;
      border: 1px solid var(--border);
      border-left: 4px solid #8aa2c5;
      border-radius: var(--r-sm);
      padding: 10px 13px;
      background: #f7f9fd;
      color: #334155;
      font-size: 13.5px;
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
      padding: 15px;
      border-radius: var(--r-sm);
      border: 1px solid #0f172a;
      background: linear-gradient(180deg, #161f33, #111829);
      color: #e8f0fb;
      font-family: "SF Mono", ui-monospace, "JetBrains Mono", "Cascadia Code", Consolas, monospace;
      font-size: 12.5px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, .05);
    }
    .raw-response {
      margin-top: 10px;
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      background: #f7f9fd;
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
    .hero-copy { animation: hero-rise .6s var(--ease) both; }
    .hero-preview { animation: hero-rise .6s var(--ease) .12s both; }
    .hero-kicker { animation: hero-rise .5s var(--ease) both; }
    @keyframes hero-rise {
      from { opacity: 0; transform: translateY(18px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .hero-stats {
      display: flex;
      flex-wrap: wrap;
      gap: 28px;
      margin: 30px 0 0;
      padding-top: 22px;
      border-top: 1px solid rgba(120, 134, 158, .22);
      animation: hero-rise .6s var(--ease) .2s both;
    }
    .hero-stats div { min-width: 0; }
    .hero-stats strong {
      display: block;
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -.5px;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }
    .hero-stats span {
      display: block;
      margin-top: 3px;
      color: #5e6a7d;
      font-size: 13px;
      font-weight: 600;
    }
    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      margin: 0 0 16px;
      padding: 6px 13px 6px 9px;
      border: 1px solid #cfe0ff;
      border-radius: var(--r-pill);
      background: rgba(234, 241, 255, .8);
      color: var(--primary-strong);
      font-size: 12.5px;
      font-weight: 700;
    }
    .hero-badge::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: var(--r-pill);
      background: #18b368;
      box-shadow: 0 0 0 4px rgba(24, 179, 104, .18);
    }
    .hero-preview {
      border: 1px solid rgba(214, 221, 232, .92);
      border-radius: var(--r-lg);
      padding: 20px;
      background: rgba(255, 255, 255, .9);
      box-shadow: var(--shadow-lg);
      backdrop-filter: blur(8px);
    }
    .preview-topline {
      width: 100%;
      height: 8px;
      margin-bottom: 22px;
      border-radius: var(--r-pill);
      background: linear-gradient(90deg, #2563ff 0 38%, #14b8a6 38% 68%, #f59e0b 68% 100%);
    }
    .preview-message {
      width: fit-content;
      max-width: 88%;
      margin: 10px 0;
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 12px 14px;
      color: var(--ink);
      font-size: 14px;
      line-height: 1.55;
      background: #ffffff;
      box-shadow: var(--shadow-sm);
    }
    .preview-message.user {
      margin-left: auto;
      border-color: #bfd0ff;
      background: #edf4ff;
      border-bottom-right-radius: 5px;
    }
    .preview-message.assistant {
      border-color: #bfe8dc;
      background: #eefbf7;
      border-bottom-left-radius: 5px;
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
      border-radius: var(--r-md);
      padding: 20px;
      background: rgba(255, 255, 255, .82);
      box-shadow: var(--shadow-md);
      transition: transform .25s var(--ease), box-shadow .25s var(--ease);
    }
    .capability-grid article:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); }
    .capability-grid article { animation: hero-rise .55s var(--ease) both; }
    .capability-grid article:nth-child(1) { animation-delay: .26s; }
    .capability-grid article:nth-child(2) { animation-delay: .34s; }
    .capability-grid article:nth-child(3) { animation-delay: .42s; }
    .capability-grid span {
      display: inline-grid;
      place-items: center;
      width: 30px;
      height: 30px;
      border-radius: var(--r-xs);
      background: var(--primary-soft);
      color: var(--primary);
      font-size: 13px;
      font-weight: 800;
    }
    .capability-grid h3 { margin-top: 14px; font-size: 18px; }
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
      background: rgba(15, 23, 42, .42);
      backdrop-filter: blur(16px);
      animation: overlay-in .2s var(--ease) both;
    }
    @keyframes overlay-in { from { opacity: 0; } to { opacity: 1; } }
    .login-card {
      position: relative;
      width: min(560px, 100%);
      border: 1px solid rgba(255, 255, 255, .7);
      border-radius: var(--r-lg);
      padding: 28px;
      background: #ffffff;
      box-shadow: var(--shadow-lg);
      animation: card-in .32s var(--ease) both;
    }
    @keyframes card-in {
      from { opacity: 0; transform: translateY(14px) scale(.97); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .icon-button {
      position: absolute;
      top: 16px;
      right: 16px;
      min-width: 38px;
      width: 38px;
      min-height: 38px;
      padding: 0;
      border-radius: var(--r-pill);
      color: #445166;
      background: #f3f5fa;
      border-color: var(--border);
      box-shadow: none;
      font-size: 22px;
      line-height: 1;
    }
    .icon-button:hover {
      color: var(--ink);
      background: #e7ecf4;
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
      min-height: 46px;
      justify-content: flex-start;
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 9px 11px;
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
    /* ===== ChatGPT-style logged-in layout ===== */
    .chat-app {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: 100vh;
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
    }
    .cg-sidebar {
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      border-right: 1px solid var(--border);
      background: linear-gradient(180deg, #fbfcff, #f4f6fb);
      padding: 16px 14px;
      gap: 14px;
    }
    .cg-sidebar.locked { opacity: .55; pointer-events: none; }
    .cg-sidebar-top { display: grid; gap: 12px; }
    .cg-brand { gap: 10px; }
    .cg-new-chat { width: 100%; min-height: 44px; }
    .cg-session-meta { display: grid; gap: 4px; }
    .cg-session-meta label { margin: 6px 0 2px; }
    .cg-session-list {
      flex: 1 1 auto;
      margin-top: 4px;
      max-height: none;
      overflow: auto;
      padding-right: 2px;
    }
    .cg-sidebar-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding-top: 12px;
      border-top: 1px solid var(--border);
    }
    .cg-sidebar-footer .status { flex: 0 1 auto; }
    .cg-sidebar-footer button { min-height: 40px; }
    .cg-main {
      display: grid;
      grid-template-rows: auto auto 1fr auto auto auto;
      min-height: 100vh;
      max-height: 100vh;
      min-width: 0;
      background: var(--surface);
    }
    .cg-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 16px 24px 12px;
      border-bottom: 1px solid var(--faint);
    }
    .cg-topbar-title h1 { font-size: 19px; letter-spacing: -.3px; }
    .cg-flow-hint { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
    .cg-topbar-status { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
    .cg-flow-steps { margin: 12px 24px 4px; }
    .cg-conversation {
      border: 0;
      border-radius: 0;
      background: transparent;
      max-height: none;
      min-height: 0;
      overflow: auto;
      padding: 18px 24px;
      gap: 14px;
      align-content: start;
    }
    .cg-conversation .message {
      max-width: min(100%, 760px);
      font-size: 14.5px;
      box-shadow: var(--shadow-sm);
    }
    .cg-conversation .message.assistant {
      justify-self: start;
    }
    .cg-conversation .message.user {
      justify-self: end;
    }
    /* ===== ChatGPT-style logged-in layout ===== */
    .chat-app {
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: 100vh;
      width: 100%;
      max-width: none;
      margin: 0;
      padding: 0;
    }
    .cg-sidebar {
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      max-height: 100vh;
      border-right: 1px solid var(--border);
      background: #f7f7f8;
      padding: 12px 10px;
      gap: 10px;
    }
    .cg-sidebar.locked { opacity: .55; pointer-events: none; }
    .cg-sidebar-top { display: grid; gap: 10px; }
    .cg-brand { gap: 10px; padding: 4px 6px; }
    .cg-brand .brand-mark { width: 34px; height: 34px; border-radius: 9px; }
    .cg-brand h2 { font-size: 15px; }
    .cg-new-chat {
      width: 100%; min-height: 44px; justify-content: flex-start;
      background: #fff; color: var(--ink); border: 1px solid var(--border);
      box-shadow: var(--shadow-sm); font-weight: 600;
    }
    .cg-new-chat:hover { background: #fff; border-color: var(--border-strong); box-shadow: var(--shadow-md); }
    .cg-session-list {
      flex: 1 1 auto;
      margin-top: 4px;
      max-height: none;
      overflow: auto;
      padding-right: 2px;
      display: grid;
      gap: 2px;
      align-content: start;
    }
    .cg-session-list .session-item {
      min-height: 40px; border: 0; border-radius: 8px; padding: 8px 10px;
      background: transparent; box-shadow: none; font-size: 13.5px; font-weight: 500;
    }
    .cg-session-list .session-item:hover { background: #ececf1; border: 0; }
    .cg-session-list .session-item.active { background: #e3e3e8; color: var(--ink); border: 0; }
    .cg-session-list .session-item span { font-size: 11px; }
    .cg-sidebar-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--border);
    }
    .cg-sidebar-footer .status { flex: 0 1 auto; font-size: 12px; min-height: 30px; }
    .cg-sidebar-footer button { min-height: 38px; }
    .cg-main {
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-height: 100vh;
      max-height: 100vh;
      min-width: 0;
      background: #fff;
    }
    .cg-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 12px 20px;
      border-bottom: 1px solid var(--faint);
    }
    .cg-topbar-title h1 { font-size: 16px; font-weight: 650; letter-spacing: -.2px; color: var(--ink); }
    .cg-topbar-status { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
    .cg-conversation {
      border: 0;
      border-radius: 0;
      background: transparent;
      max-height: none;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 26px 0 8px;
      gap: 0;
      display: block;
    }
    /* ChatGPT message rows: full-width band, centered content */
    .cg-conversation .message {
      display: block;
      width: 100%;
      max-width: none;
      margin: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
      padding: 16px 0;
      font-size: 15px;
      line-height: 1.7;
      color: var(--ink);
      animation: msg-in .3s var(--ease) both;
    }
    .cg-conversation .message.assistant { background: #f7f7f8; }
    .cg-conversation .message.user { background: transparent; }
    .cg-conversation .message::before {
      content: attr(data-role-label);
      display: block;
      max-width: 768px;
      margin: 0 auto 6px;
      padding: 0 20px;
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      letter-spacing: .3px;
    }
    .cg-conversation .message > .cg-msg-inner {
      max-width: 768px;
      margin: 0 auto;
      padding: 0 20px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .cg-msg-attachment {
      display: inline-flex; align-items: center; gap: 8px;
      margin-top: 8px; padding: 8px 12px;
      border: 1px solid var(--border); border-radius: var(--r-sm);
      background: #fff; font-size: 13px; color: var(--ink);
    }
    .cg-msg-attachment::before { content: "🎬"; }
    .cg-shots {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
      gap: 8px;
      margin-top: 10px;
      max-width: 768px;
    }
    .cg-shots img {
      width: 100%; height: 84px; object-fit: cover;
      border: 1px solid var(--border); border-radius: var(--r-sm);
      cursor: pointer; transition: transform .15s var(--ease);
    }
    .cg-shots img:hover { transform: scale(1.03); }
    .cg-progress {
      max-width: 768px; margin: 10px 0 0;
    }
    .cg-progress-bar {
      height: 8px; border-radius: var(--r-pill);
      background: #e6e8ee; overflow: hidden;
    }
    .cg-progress-fill {
      height: 100%; width: 0%;
      background: linear-gradient(90deg, #2563ff, #14b8a6);
      border-radius: var(--r-pill);
      transition: width .4s var(--ease);
    }
    .cg-progress-fill.indeterminate {
      width: 40% !important;
      animation: cg-indeterminate 1.2s var(--ease) infinite;
    }
    @keyframes cg-indeterminate {
      0% { margin-left: -40%; }
      100% { margin-left: 100%; }
    }
    .cg-progress-label { margin: 6px 0 0; font-size: 12px; color: var(--muted); }
    .cg-progress-label-done { color: var(--success); font-weight: 650; }
    .cg-progress-label-failed { color: var(--danger); font-weight: 650; }
    .cg-progress-done, .cg-progress-failed { margin-top: 8px; }
    .cg-composer-wrap {
      padding: 10px 20px 14px;
      background: linear-gradient(180deg, rgba(255,255,255,0), #fff 40%);
    }
    .cg-composer {
      max-width: 768px;
      margin: 0 auto;
      border: 1px solid var(--border-strong);
      border-radius: 26px;
      background: #fff;
      box-shadow: var(--shadow-md);
      padding: 8px 8px 8px 8px;
    }
    .cg-attachment {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin: 2px 6px 8px;
      padding: 6px 10px;
      border: 1px solid #cad9ff;
      border-radius: var(--r-pill);
      background: var(--primary-soft);
      color: var(--primary-strong);
      font-size: 12.5px;
      font-weight: 650;
      max-width: 100%;
    }
    .cg-attachment-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 280px; }
    .cg-attachment-clear {
      min-height: 22px; width: 22px; min-width: 22px; padding: 0;
      border-radius: var(--r-pill); font-size: 15px; line-height: 1;
      background: rgba(37,99,255,.12); color: var(--primary-strong); box-shadow: none; border: 0;
    }
    .cg-attachment-clear:hover { background: rgba(37,99,255,.2); transform: none; box-shadow: none; }
    .cg-link-hint {
      margin: 2px 6px 8px; padding: 6px 10px;
      border-radius: var(--r-xs); background: #eefaf4; color: var(--success);
      font-size: 12.5px; font-weight: 650;
    }
    .cg-composer-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: end; }
    .cg-attach-btn {
      min-height: 40px; width: 40px; min-width: 40px; padding: 0;
      font-size: 22px; line-height: 1; border-radius: var(--r-pill);
      background: transparent; color: #5e6a7d; border: 0; box-shadow: none;
    }
    .cg-attach-btn:hover { background: #f0f2f6; color: var(--ink); transform: none; box-shadow: none; }
    .cg-input {
      min-height: 40px; max-height: 220px; resize: none;
      border: 0; border-radius: 0; background: transparent;
      box-shadow: none; padding: 9px 4px; line-height: 1.5; font-size: 15px;
    }
    .cg-input:hover { border: 0; }
    .cg-input:focus-visible { outline: none; box-shadow: none; border: 0; }
    .cg-send {
      min-width: 40px; width: 40px; min-height: 40px; padding: 0;
      border-radius: var(--r-pill); font-size: 18px; line-height: 1;
      background: var(--ink); color: #fff; box-shadow: none;
    }
    .cg-send:hover { background: #000; transform: none; box-shadow: none; }
    .cg-send:disabled { background: #d4d8e0; color: #fff; }
    .cg-composer-help { max-width: 768px; margin: 8px auto 0; text-align: center; color: var(--muted); font-size: 12px; }
    .cg-dev-drawer {
      margin: 0 20px 16px;
      max-width: 768px;
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      background: var(--surface-soft);
      overflow: hidden;
    }
    .cg-main > .cg-dev-drawer { margin-left: auto; margin-right: auto; width: calc(100% - 40px); }
    .cg-dev-drawer summary {
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      cursor: pointer; list-style: none; padding: 12px 14px;
      font-weight: 700; color: var(--ink);
    }
    .cg-dev-drawer summary::-webkit-details-marker { display: none; }
    .cg-dev-drawer summary::after {
      content: "展开"; min-width: 56px; text-align: center;
      border: 1px solid var(--border); border-radius: var(--r-pill);
      padding: 4px 9px; color: #526176; background: #fff; font-size: 12px; font-weight: 650;
    }
    .cg-dev-drawer[open] summary::after { content: "收起"; }
    .cg-dev-body { padding: 0 14px 14px; }
    .cg-dev-actions { margin-top: 10px; }
    @media (max-width: 960px) {
      .chat-app { grid-template-columns: 1fr; }
      .cg-sidebar {
        min-height: 0;
        max-height: 34vh;
        border-right: 0;
        border-bottom: 1px solid var(--border);
      }
      .cg-main { min-height: 66vh; max-height: none; }
      .cg-conversation .message::before,
      .cg-conversation .message > .cg-msg-inner { padding: 0 16px; }
      .cg-composer, .cg-composer-help, .cg-dev-drawer { max-width: none; }
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
      .hero-stats { gap: 18px; margin-top: 24px; }
      .hero-stats strong { font-size: 22px; }
      .login-card { padding: 22px 16px 18px; }
    }

    /* ===== M-UI overhaul (theme, sidebar, menus, modals, toasts, mobile) ===== */
    :root[data-theme="dark"] {
      color-scheme: dark;
      background: #0d1117;
      color: #e6edf6;
      --page: #0d1117;
      --surface: #161b22;
      --surface-soft: #1b222c;
      --surface-raised: #1e2630;
      --border: #2a313c;
      --border-strong: #3a434f;
      --text: #e6edf6;
      --muted: #9aa7b8;
      --faint: #1b222c;
      --primary: #4d8bff;
      --primary-strong: #6ea2ff;
      --primary-soft: #16233d;
      --primary-ring: rgba(77, 139, 255, .26);
      --analysis: #2dd4bf;
      --ink: #e6edf6;
      --success: #3fd09a;
      --success-bg: #14271f;
      --danger: #ff7a6e;
      --danger-bg: #2a1714;
      --warning: #e2b04a;
      --warning-bg: #2a2110;
      --info: #4cc4dc;
      --info-bg: #102630;
      --shadow-sm: 0 1px 2px rgba(0,0,0,.3), 0 1px 3px rgba(0,0,0,.35);
      --shadow-md: 0 2px 6px rgba(0,0,0,.35), 0 12px 28px rgba(0,0,0,.45);
      --shadow-lg: 0 8px 24px rgba(0,0,0,.5), 0 28px 60px rgba(0,0,0,.6);
      --shadow-primary: 0 8px 18px rgba(77,139,255,.28), 0 2px 5px rgba(77,139,255,.22);
    }
    :root[data-theme="dark"] body {
      background:
        radial-gradient(1200px 600px at 88% -8%, rgba(77,139,255,.10), transparent 60%),
        radial-gradient(900px 500px at -6% 4%, rgba(45,212,191,.06), transparent 55%),
        linear-gradient(180deg, #11161e 0, var(--page) 280px, #0a0e14 100%);
    }

    /* icon sizing for inline SVGs */
    .ic { width: 18px; height: 18px; flex: none; stroke: currentColor; fill: none; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .ic-sm { width: 16px; height: 16px; }

    /* session search */
    .cg-search { position: relative; margin: 4px 2px 8px; }
    .cg-search .ic { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: var(--muted); width: 16px; height: 16px; pointer-events: none; }
    .cg-search input {
      width: 100%; height: 38px; padding: 0 32px 0 34px; border-radius: var(--r-sm);
      border: 1px solid var(--border); background: var(--surface-soft); color: var(--text);
      font-size: 13.5px; outline: none; transition: border-color .18s var(--ease), box-shadow .18s var(--ease);
    }
    .cg-search input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-ring); }
    .cg-search-clear { position: absolute; right: 7px; top: 50%; transform: translateY(-50%); width: 22px; height: 22px;
      border: none; background: transparent; color: var(--muted); border-radius: var(--r-pill); cursor: pointer; display: none; align-items: center; justify-content: center; }
    .cg-search-clear:hover { background: var(--faint); color: var(--text); }
    .cg-search.has-value .cg-search-clear { display: inline-flex; }

    /* session list items + group labels + row menu */
    .cg-group-label { font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); padding: 12px 10px 4px; }
    .cg-group-label:first-child { padding-top: 2px; }
    .session-row { position: relative; display: flex; align-items: center; }
    .session-row > .session-item { flex: 1; min-width: 0; }
    .session-item .session-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
    .session-item .session-sub { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
    .session-row .row-menu-btn {
      position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
      width: 28px; height: 28px; border: none; background: transparent; color: var(--muted);
      border-radius: var(--r-xs); cursor: pointer; display: none; align-items: center; justify-content: center;
    }
    .session-row:hover .row-menu-btn, .session-row.active .row-menu-btn, .session-row .row-menu-btn[aria-expanded="true"] { display: inline-flex; }
    .session-row .row-menu-btn:hover { background: var(--surface); color: var(--text); }
    .session-item.empty { color: var(--muted); font-style: normal; cursor: default; }
    .session-skeleton { height: 40px; border-radius: var(--r-sm); margin: 4px 2px; background: linear-gradient(90deg, var(--faint) 25%, var(--surface-soft) 37%, var(--faint) 63%); background-size: 400% 100%; animation: shimmer 1.3s ease infinite; }
    @keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }
    .cg-list-empty { color: var(--muted); font-size: 13px; text-align: center; padding: 22px 12px; line-height: 1.6; }

    /* generic dropdown menu */
    .menu-pop {
      position: absolute; z-index: 60; min-width: 184px; padding: 6px; background: var(--surface);
      border: 1px solid var(--border); border-radius: var(--r-md); box-shadow: var(--shadow-lg);
      display: flex; flex-direction: column; gap: 2px;
    }
    .menu-pop[hidden] { display: none; }
    .menu-pop button {
      display: flex; align-items: center; gap: 10px; width: 100%; padding: 9px 10px; border: none; background: transparent;
      color: var(--text); font-size: 13.5px; text-align: left; border-radius: var(--r-xs); cursor: pointer;
    }
    .menu-pop button:hover, .menu-pop button:focus-visible { background: var(--faint); outline: none; }
    .menu-pop button.danger { color: var(--danger); }
    .menu-pop button.danger:hover { background: var(--danger-bg); }
    .menu-pop .menu-sep { height: 1px; background: var(--border); margin: 4px 2px; }
    .menu-pop .menu-account { padding: 8px 10px 6px; }
    .menu-pop .menu-account strong { display: block; font-size: 13.5px; }
    .menu-pop .menu-account span { display: block; font-size: 12px; color: var(--muted); margin-top: 2px; word-break: break-all; }
    .menu-check { margin-left: auto; color: var(--primary); display: none; }
    .menu-pop button[aria-checked="true"] .menu-check { display: inline-flex; }

    /* sidebar footer user button */
    .cg-user-btn {
      display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px; border-radius: var(--r-sm);
      border: 1px solid transparent; background: transparent; color: var(--text); cursor: pointer; text-align: left;
    }
    .cg-user-btn:hover { background: var(--faint); }
    .cg-user-avatar { width: 30px; height: 30px; flex: none; border-radius: var(--r-pill); background: var(--primary); color: #fff;
      display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; }
    .cg-user-meta { min-width: 0; flex: 1; }
    .cg-user-meta strong { display: block; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .cg-user-meta span { display: block; font-size: 11.5px; color: var(--muted); }

    /* modal / confirm */
    .modal-overlay { position: fixed; inset: 0; z-index: 90; background: rgba(8,12,20,.42); backdrop-filter: blur(2px);
      display: flex; align-items: center; justify-content: center; padding: 18px; opacity: 0; transition: opacity .18s var(--ease); }
    :root[data-theme="dark"] .modal-overlay { background: rgba(0,0,0,.58); }
    .modal-overlay.show { opacity: 1; }
    .modal-overlay[hidden] { display: none; }
    .modal {
      width: min(440px, 100%); background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg);
      box-shadow: var(--shadow-lg); padding: 22px; transform: translateY(8px) scale(.98); transition: transform .18s var(--ease);
    }
    .modal-overlay.show .modal { transform: none; }
    .modal h3 { margin: 0 0 8px; font-size: 17px; }
    .modal p { margin: 0 0 18px; color: var(--muted); font-size: 14px; line-height: 1.6; }
    .modal input[type="text"] { width: 100%; height: 42px; padding: 0 12px; border-radius: var(--r-sm); border: 1px solid var(--border);
      background: var(--surface-soft); color: var(--text); font-size: 14px; outline: none; margin-bottom: 18px; }
    .modal input[type="text"]:focus { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-ring); }
    .modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
    .btn { height: 40px; padding: 0 18px; border-radius: var(--r-sm); font-size: 14px; font-weight: 600; cursor: pointer; border: 1px solid var(--border); background: var(--surface); color: var(--text); transition: background .15s var(--ease), border-color .15s var(--ease); }
    .btn:hover { background: var(--faint); }
    .btn-primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    .btn-primary:hover { background: var(--primary-strong); border-color: var(--primary-strong); }
    .btn-danger { background: var(--danger); border-color: var(--danger); color: #fff; }
    .btn-danger:hover { filter: brightness(1.06); }

    /* toasts */
    .toast-host { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 95; display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none; }
    .toast { pointer-events: auto; display: flex; align-items: center; gap: 10px; max-width: 92vw; padding: 10px 14px; border-radius: var(--r-pill);
      background: var(--ink); color: #fff; font-size: 13.5px; box-shadow: var(--shadow-md); opacity: 0; transform: translateY(8px); transition: opacity .2s var(--ease), transform .2s var(--ease); }
    :root[data-theme="dark"] .toast { background: #2a313c; }
    .toast.show { opacity: 1; transform: none; }
    .toast.success { background: var(--success); }
    .toast.error { background: var(--danger); }
    .toast .toast-action { background: rgba(255,255,255,.18); border: none; color: #fff; font-size: 12.5px; font-weight: 600; padding: 4px 10px; border-radius: var(--r-pill); cursor: pointer; }

    /* message action bar + copy on code */
    .cg-msg-actions { display: flex; gap: 4px; margin-top: 6px; opacity: 0; transition: opacity .15s var(--ease); }
    .message:hover .cg-msg-actions, .cg-msg-actions:focus-within { opacity: 1; }
    .cg-msg-actions button { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 9px; border-radius: var(--r-xs);
      border: 1px solid transparent; background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; }
    .cg-msg-actions button:hover { background: var(--faint); color: var(--text); }
    .cg-msg-inner pre { position: relative; }
    .code-copy-btn { position: absolute; top: 8px; right: 8px; height: 26px; padding: 0 9px; border-radius: var(--r-xs); border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text); font-size: 11.5px; cursor: pointer; opacity: .9; }
    .code-copy-btn:hover { background: var(--faint); }

    /* mobile menu button (topbar) + overlay */
    .cg-menu-btn { display: none; width: 38px; height: 38px; align-items: center; justify-content: center; border: 1px solid var(--border);
      background: var(--surface); color: var(--text); border-radius: var(--r-sm); cursor: pointer; }
    .cg-scrim { position: fixed; inset: 0; z-index: 40; background: rgba(8,12,20,.4); opacity: 0; transition: opacity .2s var(--ease); }
    .cg-scrim[hidden] { display: none; }
    .cg-scrim.show { opacity: 1; }

    @media (max-width: 820px) {
      .cg-menu-btn { display: inline-flex; }
      .cg-sidebar { position: fixed; left: 0; top: 0; bottom: 0; z-index: 50; width: 84vw; max-width: 320px;
        transform: translateX(-104%); transition: transform .24s var(--ease); box-shadow: var(--shadow-lg); }
      .cg-sidebar.drawer-open { transform: none; }
      .modal { width: 100%; border-radius: var(--r-lg) var(--r-lg) 0 0; align-self: flex-end; }
      .modal-overlay { align-items: flex-end; padding: 0; }
    }

    /* dark-mode surface overrides for chat areas that hardcode light colors */
    :root[data-theme="dark"] .cg-main { background: var(--surface); }
    :root[data-theme="dark"] .cg-conversation .message.assistant { background: var(--surface-soft); }
    :root[data-theme="dark"] .cg-composer { background: var(--surface-soft); border-color: var(--border-strong); }
    :root[data-theme="dark"] .cg-composer-wrap { background: linear-gradient(180deg, rgba(22,27,34,0), var(--surface) 42%); }
    :root[data-theme="dark"] .cg-msg-attachment { background: var(--surface); }
    :root[data-theme="dark"] .cg-attachment { background: var(--faint); }
    :root[data-theme="dark"] .cg-progress-bar { background: var(--faint); }
    :root[data-theme="dark"] input,
    :root[data-theme="dark"] textarea,
    :root[data-theme="dark"] select { background: var(--surface-soft); color: var(--text); border-color: var(--border); }
    :root[data-theme="dark"] .cg-input { background: transparent; }
    :root[data-theme="dark"] .secondary { background: var(--surface-soft); color: var(--text); border-color: var(--border); }
    :root[data-theme="dark"] .login-card,
    :root[data-theme="dark"] .cg-dev-drawer,
    :root[data-theme="dark"] .result-card,
    :root[data-theme="dark"] .output-summary,
    :root[data-theme="dark"] .status-strip { background: var(--surface-soft); border-color: var(--border); }
    :root[data-theme="dark"] pre,
    :root[data-theme="dark"] #output { background: var(--faint); color: var(--text); }
  </style>
</head>
<body>
  <div id="toastHost" class="toast-host" aria-live="polite" aria-atomic="false"></div>
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
          <span class="hero-badge">服务运行中 · OpenClaw 自有登录</span>
          <p class="hero-kicker">独立登录 · 视频链接读取 · 模型分析 · 历史对话</p>
          <h2>把一个视频链接变成清晰、可复查、可继续追问的分析结果。</h2>
          <p class="hero-text">OpenClaw 面向短视频运营、内容研究和业务分析场景，用户只需要在本站登录，提交视频链接或上传文件，就可以在同一个中文聊天界面里查看分析进度、结果摘要和历史会话。</p>
          <div class="hero-stats" aria-label="平台能力概览">
            <div>
              <strong>3 步</strong>
              <span>登录 · 读取 · 分析</span>
            </div>
            <div>
              <strong>链接 / 上传</strong>
              <span>双入口视频来源</span>
            </div>
            <div>
              <strong>独立会话</strong>
              <span>无需登录 Dify</span>
            </div>
          </div>
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

  <main id="chatApp" class="chat-app" hidden>
    <aside id="sessionPanel" class="cg-sidebar locked" aria-labelledby="sessionHeading">
      <div class="cg-sidebar-top">
        <div class="brand cg-brand">
          <div class="brand-mark" aria-hidden="true">OC</div>
          <div class="brand-copy">
            <p class="eyebrow">OpenClaw</p>
            <h2 id="sessionHeading">短视频分析</h2>
          </div>
        </div>
        <button id="createSession" class="cg-new-chat primary-flow" type="button">＋ 新建对话</button>
      </div>
      <div class="cg-session-meta sr-only">
        <label for="sessionTitle">新会话标题</label>
        <input id="sessionTitle" value="短视频分析">
        <label for="sessionId" class="technical-label">当前会话 ID</label>
        <input id="sessionId" class="technical-field" autocomplete="off" placeholder="创建会话后自动写入">
      </div>
      <div class="cg-search" id="sessionSearchWrap">
        <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m21 21-4.3-4.3"></path></svg>
        <input id="sessionSearch" type="search" placeholder="搜索对话" aria-label="搜索对话" autocomplete="off">
        <button id="sessionSearchClear" class="cg-search-clear" type="button" aria-label="清除搜索">
          <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>
        </button>
      </div>
      <div id="sessionList" class="cg-session-list session-list" aria-label="历史对话" aria-live="polite">
        <button type="button" class="session-item empty">登录后显示历史对话</button>
      </div>
      <div class="cg-sidebar-footer">
        <button id="userMenuBtn" class="cg-user-btn" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="userMenu">
          <span class="cg-user-avatar" id="userAvatar" aria-hidden="true">OC</span>
          <span class="cg-user-meta">
            <strong id="userName">未登录</strong>
            <span id="authStatus" class="status todo">未登录</span>
          </span>
          <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>
        </button>
        <div id="userMenu" class="menu-pop" role="menu" aria-labelledby="userMenuBtn" hidden>
          <div class="menu-account">
            <strong id="menuUserName">未登录</strong>
            <span id="menuUserSub">OpenClaw 独立短视频分析会话</span>
          </div>
          <div class="menu-sep"></div>
          <button type="button" role="menuitemradio" data-theme-choice="light" aria-checked="false">
            <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5"></circle><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"></path></svg>
            浅色模式 <span class="menu-check"><svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 5 5 9-11"></path></svg></span>
          </button>
          <button type="button" role="menuitemradio" data-theme-choice="dark" aria-checked="false">
            <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"></path></svg>
            深色模式 <span class="menu-check"><svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 5 5 9-11"></path></svg></span>
          </button>
          <button type="button" role="menuitemradio" data-theme-choice="system" aria-checked="false">
            <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="13" rx="2"></rect><path d="M8 21h8M12 17v4"></path></svg>
            跟随系统 <span class="menu-check"><svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 5 5 9-11"></path></svg></span>
          </button>
          <div class="menu-sep"></div>
          <button id="aboutBtn" type="button" role="menuitem">
            <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 16v-4M12 8h.01"></path></svg>
            关于 OpenClaw
          </button>
          <button id="logoutButton" class="danger" type="button" role="menuitem">
            <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"></path></svg>
            退出登录
          </button>
        </div>
      </div>
    </aside>

    <section class="cg-main" aria-label="OpenClaw 中文聊天分析界面">
      <header class="cg-topbar">
        <button id="cgMenuBtn" class="cg-menu-btn" type="button" aria-label="打开会话菜单" aria-controls="sessionPanel" aria-expanded="false">
          <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"></path></svg>
        </button>
        <div class="cg-topbar-title">
          <h1 id="cgConvTitle">OpenClaw</h1>
        </div>
        <div class="cg-topbar-status" aria-label="OpenClaw 运行状态">
          <div id="runState" class="run-state todo">等待登录</div>
          <button id="refreshMe" class="secondary" type="button">刷新</button>
        </div>
        <p id="cgFlowHint" class="sr-only">粘贴抖音视频链接或上传视频文件，也可以直接提问。</p>
      </header>

      <nav class="flow-steps cg-flow-steps" aria-label="分析流程" hidden>
        <div id="flowLogin" class="flow-step active" data-step="1">登录</div>
        <div id="flowSession" class="flow-step" data-step="2">会话</div>
        <div id="flowSource" class="flow-step" data-step="3">来源</div>
        <div id="flowAnalyze" class="flow-step" data-step="4">分析</div>
        <div id="flowResult" class="flow-step" data-step="5">结果</div>
      </nav>

      <div id="conversation" class="cg-conversation conversation" aria-live="polite">
        <div class="message assistant" data-role-label="OpenClaw"><div class="cg-msg-inner">你好，我是 OpenClaw 短视频分析助手。把抖音视频链接粘贴进下方输入框，或点击 ＋ 上传视频文件，我就开始分析；也可以直接提问。</div></div>
      </div>

      <div id="nextAction" class="next-action cg-next-action" hidden><span>下一步</span>请先登录进入分析工作台。</div>

      <div class="cg-composer-wrap">
        <div class="cg-composer">
          <div id="composerAttachment" class="cg-attachment" hidden>
            <span id="composerAttachmentName" class="cg-attachment-name">未选择文件</span>
            <button id="composerAttachmentClear" class="cg-attachment-clear" type="button" aria-label="移除附件">×</button>
          </div>
          <div id="composerLinkHint" class="cg-link-hint" hidden>检测到视频链接，将作为视频来源分析。</div>
          <div class="cg-composer-row">
            <button id="composerAttach" class="cg-attach-btn" type="button" aria-label="上传视频文件" title="上传视频文件">＋</button>
            <textarea id="prompt" class="cg-input" rows="1" placeholder="给 OpenClaw 发送消息，或粘贴抖音视频链接…"></textarea>
            <button id="sendChat" class="cg-send" type="button" aria-label="发送" title="发送">↑</button>
          </div>
        </div>
        <p class="cg-composer-help">OpenClaw 可能会出错，请核对重要信息。视频分析结果以页面展示为准。</p>
      </div>

      <input id="videoFile" type="file" accept="video/mp4,video/quicktime,video/webm" class="sr-only" tabindex="-1" aria-hidden="true">
      <input id="videoUrl" type="hidden" value="">
      <input id="prompt-default" type="hidden" value="请分析这个视频。">

      <details id="devDrawer" class="cg-dev-drawer">
        <summary>
          <span>诊断与结果明细</span>
          <span class="summary-note">验证工具 · 链接读取 · 任务状态 · 验收 · 原始 JSON</span>
        </summary>
        <div class="cg-dev-body">
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
          <div id="outputSummary" class="output-summary">登录后新建对话，再粘贴视频链接或上传文件。</div>
          <div class="actions cg-dev-actions">
            <button id="readVideoLink" class="secondary" type="button">读取链接</button>
            <button id="submitJob" class="secondary" type="button">分析视频</button>
            <button id="pollJob" class="secondary" type="button">刷新状态</button>
            <button id="uploadJob" class="secondary" type="button">分析上传</button>
            <button id="uploadSmoke" class="secondary" type="button">上传检查</button>
            <button id="refreshMessages" class="secondary" type="button">刷新历史</button>
          </div>
          <div class="actions cg-dev-actions">
            <button id="identityDiagnostics" class="secondary" type="button">身份诊断</button>
            <button id="runSelfTest" class="secondary" type="button">自检</button>
            <button id="runSecurityTest" class="secondary" type="button">安全检查</button>
            <button id="runPostLoginAcceptance" class="secondary" type="button">登录后验收</button>
          </div>
          <details class="raw-response">
            <summary>开发详情：脱敏响应</summary>
            <pre id="output">{}</pre>
          </details>
        </div>
      </details>
    </section>

    <div id="cgScrim" class="cg-scrim" hidden></div>
    <div id="sessionRowMenu" class="menu-pop" role="menu" hidden>
      <button type="button" data-row-action="rename" role="menuitem">
        <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"></path></svg>
        重命名
      </button>
      <button type="button" data-row-action="delete" class="danger" role="menuitem">
        <svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"></path></svg>
        删除对话
      </button>
    </div>
    <div id="modalHost" class="modal-overlay" hidden role="dialog" aria-modal="true" aria-labelledby="modalTitle">
      <div class="modal">
        <h3 id="modalTitle">提示</h3>
        <p id="modalDesc"></p>
        <input id="modalInput" type="text" hidden aria-label="输入">
        <div class="modal-actions">
          <button id="modalCancel" class="btn" type="button">取消</button>
          <button id="modalConfirm" class="btn btn-primary" type="button">确定</button>
        </div>
      </div>
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
    const linkSourcePanel = null;
    const uploadSourcePanel = null;
    let attachedFile = null;
    let composerMode = 'chat';
    const composerAttachment = document.getElementById('composerAttachment');
    const composerAttachmentName = document.getElementById('composerAttachmentName');
    const composerLinkHint = document.getElementById('composerLinkHint');
    const videoFileInput = document.getElementById('videoFile');
    const VIDEO_LINK_RE = /(https?:\/\/(?:[\w.-]*\.)?douyin\.com\/(?!user\/)[^\s]*|https?:\/\/v\.douyin\.com\/[^\s]+|https?:\/\/www\.iesdouyin\.com\/[^\s]+)/i;
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
    function detectVideoLink(text) {
      const match = (text || '').match(VIDEO_LINK_RE);
      return match ? match[0] : '';
    }
    function updateComposerMode() {
      const text = document.getElementById('prompt').value || '';
      const link = detectVideoLink(text);
      if (attachedFile) {
        composerMode = 'upload';
      } else if (link) {
        composerMode = 'link';
        document.getElementById('videoUrl').value = link;
      } else {
        composerMode = 'chat';
        document.getElementById('videoUrl').value = '';
      }
      if (composerLinkHint) composerLinkHint.hidden = !(composerMode === 'link');
      moveToSourceIfReady();
      syncActionAvailability();
    }
    function setAttachedFile(file) {
      attachedFile = file || null;
      if (composerAttachment) composerAttachment.hidden = !attachedFile;
      if (composerAttachmentName) composerAttachmentName.textContent = attachedFile ? attachedFile.name : '未选择文件';
      updateComposerMode();
    }
    function syncActionAvailability() {
      const authenticated = isAuthenticated();
      const sessionReady = hasSession();
      const uploadMode = composerMode === 'upload';
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
        setPrimaryAction('sendChat');
        setNextAction('分析任务进行中，完成后结果会自动出现在对话里。');
      } else if (uploadMode) {
        setPrimaryAction('sendChat');
        setNextAction('已选择视频文件，点击发送即可提交分析。');
      } else if (composerMode === 'link') {
        setPrimaryAction('sendChat');
        setNextAction('检测到视频链接，点击发送将先读取链接再提交分析。');
      } else {
        setPrimaryAction('sendChat');
        setNextAction('粘贴抖音视频链接、上传视频，或直接输入问题后发送。');
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
      node.setAttribute('data-role-label', role === 'user' ? '你' : 'OpenClaw');
      const inner = document.createElement('div');
      inner.className = 'cg-msg-inner';
      inner.textContent = text;
      node.appendChild(inner);
      if (role === 'assistant') {
        node.appendChild(buildMsgActions(node));
      }
      conversation.appendChild(node);
      conversation.scrollTop = conversation.scrollHeight;
      return node;
    }
    function messageInner(node) {
      return node ? node.querySelector('.cg-msg-inner') : null;
    }
    function addAttachmentChip(node, name) {
      const inner = messageInner(node);
      if (!inner) return;
      const chip = document.createElement('div');
      chip.className = 'cg-msg-attachment';
      chip.textContent = name;
      inner.appendChild(chip);
      conversation.scrollTop = conversation.scrollHeight;
    }
    function attachProgress(node, label) {
      const inner = messageInner(node);
      if (!inner) return null;
      const wrap = document.createElement('div');
      wrap.className = 'cg-progress';
      const bar = document.createElement('div');
      bar.className = 'cg-progress-bar';
      const fill = document.createElement('div');
      fill.className = 'cg-progress-fill indeterminate';
      bar.appendChild(fill);
      const lab = document.createElement('p');
      lab.className = 'cg-progress-label';
      lab.textContent = label || '处理中…';
      wrap.appendChild(bar);
      wrap.appendChild(lab);
      inner.appendChild(wrap);
      conversation.scrollTop = conversation.scrollHeight;
      return {
        set(pct, text) {
          fill.classList.remove('indeterminate');
          fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
          if (text) lab.textContent = text;
        },
        indeterminate(text) {
          fill.classList.add('indeterminate');
          if (text) lab.textContent = text;
        },
        done(text) {
          // Remove the progress bar entirely and show a clean done line,
          // so a full bar never lingers and looks "stuck".
          wrap.classList.add('cg-progress-done');
          bar.remove();
          lab.textContent = (text ? ('✓ ' + text) : '✓ 已完成');
          lab.classList.add('cg-progress-label-done');
          conversation.scrollTop = conversation.scrollHeight;
        },
        fail(text) {
          wrap.classList.add('cg-progress-failed');
          bar.remove();
          lab.textContent = (text ? ('✕ ' + text) : '✕ 未完成');
          lab.classList.add('cg-progress-label-failed');
          conversation.scrollTop = conversation.scrollHeight;
        },
        remove() { wrap.remove(); }
      };
    }
    function addScreenshots(node, urls) {
      const inner = messageInner(node);
      if (!inner || !Array.isArray(urls) || !urls.length) return;
      const grid = document.createElement('div');
      grid.className = 'cg-shots';
      urls.forEach(u => {
        const img = document.createElement('img');
        img.src = u;
        img.loading = 'lazy';
        img.addEventListener('click', () => window.open(u, '_blank'));
        grid.appendChild(img);
      });
      inner.appendChild(grid);
      conversation.scrollTop = conversation.scrollHeight;
    }
    function formatSessionTime(value) {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '';
      return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    }
    function sessionDisplayTitle(session) {
      const o = sessionOverrides[session.id];
      return (o && o.title) || session.title || '未命名对话';
    }
    function sessionGroup(value) {
      const d = value ? new Date(value) : null;
      if (!d || Number.isNaN(d.getTime())) return '更早';
      const now = new Date();
      const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      const t = d.getTime();
      if (t >= startToday) return '今天';
      if (t >= startToday - 86400000) return '昨天';
      if (t >= startToday - 7 * 86400000) return '最近 7 天';
      if (t >= startToday - 30 * 86400000) return '最近 30 天';
      return '更早';
    }
    function visibleSessions(list) {
      const q = (currentSearchQuery || '').trim().toLowerCase();
      return (list || [])
        .filter(s => !(sessionOverrides[s.id] && sessionOverrides[s.id].deleted))
        .filter(s => !q || sessionDisplayTitle(s).toLowerCase().includes(q));
    }
    function renderSessions(sessions) {
      sessionList.innerHTML = '';
      const all = Array.isArray(sessions) ? sessions : [];
      const q = (currentSearchQuery || '').trim();
      const visible = visibleSessions(all);
      if (visible.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'cg-list-empty';
        if (!isAuthenticated()) empty.textContent = '登录后显示历史对话';
        else if (q) empty.textContent = '没有匹配“' + q + '”的对话';
        else empty.textContent = '还没有对话，点击上方“新建对话”开始。';
        sessionList.appendChild(empty);
        return;
      }
      const activeId = document.getElementById('sessionId').value;
      const order = ['今天', '昨天', '最近 7 天', '最近 30 天', '更早'];
      const groups = {};
      visible.forEach(s => {
        const g = sessionGroup(s.updated_at || s.created_at);
        (groups[g] = groups[g] || []).push(s);
      });
      order.forEach(g => {
        if (!groups[g]) return;
        const label = document.createElement('div');
        label.className = 'cg-group-label';
        label.textContent = g;
        sessionList.appendChild(label);
        groups[g].forEach(session => {
          const row = document.createElement('div');
          row.className = 'session-row' + (session.id === activeId ? ' active' : '');
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'session-item' + (session.id === activeId ? ' active' : '');
          item.dataset.sessionId = session.id || '';
          const title = document.createElement('span');
          title.className = 'session-title';
          title.textContent = sessionDisplayTitle(session);
          item.appendChild(title);
          item.addEventListener('click', () => selectSession(session));
          const menuBtn = document.createElement('button');
          menuBtn.type = 'button';
          menuBtn.className = 'row-menu-btn';
          menuBtn.setAttribute('aria-label', '对话操作');
          menuBtn.setAttribute('aria-haspopup', 'menu');
          menuBtn.innerHTML = '<svg class="ic ic-sm" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><circle cx="5" cy="12" r="1.7"></circle><circle cx="12" cy="12" r="1.7"></circle><circle cx="19" cy="12" r="1.7"></circle></svg>';
          menuBtn.addEventListener('click', e => { e.stopPropagation(); openSessionRowMenu(menuBtn, session); });
          row.appendChild(item);
          row.appendChild(menuBtn);
          sessionList.appendChild(row);
        });
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
        // Load messages from the server so the per-session greeting (if any)
        // posted by the Bridge appears in the conversation.
        await refreshMessages({ quiet: true });
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
    function uploadVideoWithProgress(file, sessionId, content, progress) {
      return new Promise((resolve) => {
        const form = new FormData();
        form.append('session_id', sessionId);
        form.append('content', content || '请分析上传的视频。');
        form.append('video', file);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', apiPrefix + '/uploads', true);
        xhr.withCredentials = true;
        xhr.upload.onprogress = (e) => {
          if (progress && e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            progress.set(pct, '上传中… ' + pct + '%');
          }
        };
        xhr.onload = () => {
          let body; try { body = xhr.responseText ? JSON.parse(xhr.responseText) : {}; } catch { body = { text: xhr.responseText }; }
          resolve({ status: xhr.status, body });
        };
        xhr.onerror = () => resolve({ status: 0, body: {} });
        xhr.send(form);
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
      const { status, body } = await uploadVideoWithProgress(file, sessionId, document.getElementById('prompt').value, null);
      if (body.job && body.job.job_id) {
        linkReadable = false;
        setCurrentJob(body.job.job_id);
        setRunState('上传已提交', 'ok');
        sourceMetric.textContent = '上传已接收';
        resultMetric.textContent = '等待中';
        activateFlow(3);
      } else {
        setRunState('需要处理', 'fail');
      }
      show({ status, body });
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
    function extractScreenshots(result) {
      // Pull any frame/screenshot URLs from the sanitized result payload if present.
      const r = result && result.body && result.body.result && result.body.result.result;
      if (!r) return [];
      const urls = [];
      const collect = (arr) => { if (Array.isArray(arr)) arr.forEach(u => { if (typeof u === 'string' && /^https?:|^\//.test(u)) urls.push(u); }); };
      collect(r.frame_urls); collect(r.screenshots); collect(r.frames);
      if (r.signals && Array.isArray(r.signals.frame_urls)) collect(r.signals.frame_urls);
      return urls.slice(0, 8);
    }
    async function autoPollCurrentJob(progress, assistantNode) {
      if (!currentJobId) return;
      const jobId = currentJobId;
      if (progress) progress.indeterminate('正在分析视频…');
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await delay(2000);
        if (currentJobId !== jobId) return;
        let poll;
        try { poll = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId)); }
        catch { continue; }
        const job = poll.body.job || null;
        if (!job) continue;
        if (job.status === 'succeeded') {
          const result = await api(apiPrefix + '/jobs/' + encodeURIComponent(jobId) + '/result');
          if (progress) progress.done('分析完成');
          const summary = result.body.result && result.body.result.result && result.body.result.result.summary;
          const shots = extractScreenshots(result);
          if (assistantNode) {
            const inner = messageInner(assistantNode);
            if (inner) inner.firstChild ? (inner.childNodes[0].textContent = summary || '分析完成，结果已就绪。') : (inner.textContent = summary || '分析完成，结果已就绪。');
            if (shots.length) addScreenshots(assistantNode, shots);
          } else {
            const node = pushMessage('assistant', summary || '分析完成，结果已就绪。');
            if (shots.length) addScreenshots(node, shots);
          }
          show({ job: poll, result });
          setRunState('结果已就绪', 'ok');
          resultMetric.textContent = (result.body.result && result.body.result.schema_version) || '已就绪';
          activateFlow(4);
          return;
        }
        if (terminalStatuses.has(job.status)) {
          if (progress) progress.fail('分析未完成');
          const reply = buildJobErrorReply(job.error_code);
          if (assistantNode) { const inner = messageInner(assistantNode); if (inner) inner.childNodes[0] ? (inner.childNodes[0].textContent = reply) : (inner.textContent = reply); }
          else pushMessage('assistant', reply);
          show({ job: poll });
          setRunState('任务结束', 'fail');
          resultMetric.textContent = job.status;
          return;
        }
      }
      if (progress) progress.fail('分析超时，请稍后重试');
    }
    function buildJobErrorReply(errorCode) {
      const map = {
        url_rejected: '这个链接没有通过安全校验或无法解析。请发抖音单条视频页链接（形如 https://www.douyin.com/video/xxxx），不要发主页或非抖音链接。',
        tool_timeout: '这条视频解析超时了。可以稍后重试，或换一条更短的单条视频链接。',
        tool_failed: '这条视频暂时没能成功解析，所以我不能假装看过它。可以确认视频未被删除/设为私密，或换完整视频页链接重试。'
      };
      return map[errorCode] || '分析任务未能完成。可以稍后重试，或换一条视频链接。';
    }
    async function handleComposerSend() {
      const promptText = document.getElementById('prompt').value.trim();
      // Upload path
      if (composerMode === 'upload' && attachedFile) {
        const sessionId = document.getElementById('sessionId').value;
        if (!sessionId) { setNextAction('请先登录并新建对话。'); return; }
        const fileName = attachedFile.name;
        const userNode = pushMessage('user', promptText || '请分析我上传的视频。');
        addAttachmentChip(userNode, fileName);
        const assistantNode = pushMessage('assistant', '已收到视频文件，正在上传…');
        const progress = attachProgress(assistantNode, '准备上传…');
        document.getElementById('prompt').value = '';
        updateComposerMode();
        const { body } = await uploadVideoWithProgress(attachedFile, sessionId, promptText || '请分析上传的视频。', progress);
        setAttachedFile(null);
        if (body.job && body.job.job_id) {
          setCurrentJob(body.job.job_id);
          progress.indeterminate('上传完成，正在分析视频…');
          activateFlow(3);
          await autoPollCurrentJob(progress, assistantNode);
        } else {
          progress.fail('上传失败，请重试');
        }
        return;
      }
      // Video link path
      if (composerMode === 'link') {
        const sessionId = document.getElementById('sessionId').value;
        if (!sessionId) { setNextAction('请先登录并新建对话。'); return; }
        const link = document.getElementById('videoUrl').value;
        const userNode = pushMessage('user', promptText || '请分析这个视频。');
        addAttachmentChip(userNode, link);
        const assistantNode = pushMessage('assistant', '正在读取视频链接…');
        const progress = attachProgress(assistantNode, '读取链接中…');
        document.getElementById('prompt').value = '';
        const read = await api(apiPrefix + '/video-link/read-check', { method: 'POST', body: JSON.stringify({ video_url: link }) });
        show({ status: read.status, video_link_read_check: read.body });
        if (read.status === 200 && read.body.status === 'PASS') {
          linkReadable = true;
          progress.indeterminate('链接可读取，正在提交分析…');
          const jobRes = await api(apiPrefix + '/jobs', { method: 'POST', body: JSON.stringify({ session_id: sessionId, video_url: link, content: promptText || '请分析这个视频。' }) });
          if (jobRes.body.job && jobRes.body.job.job_id) {
            setCurrentJob(jobRes.body.job.job_id);
            activateFlow(3);
            await autoPollCurrentJob(progress, assistantNode);
          } else {
            progress.fail('提交分析失败，请重试');
          }
        } else {
          progress.fail('链接无法读取');
          const inner = messageInner(assistantNode);
          if (inner) inner.childNodes[0].textContent = buildJobErrorReply('url_rejected');
        }
        updateComposerMode();
        return;
      }
      // Plain chat path
      await sendChat();
    }
    document.getElementById('composerAttach').addEventListener('click', () => videoFileInput.click());
    videoFileInput.addEventListener('change', () => {
      const file = videoFileInput.files && videoFileInput.files[0];
      setAttachedFile(file || null);
    });
    document.getElementById('composerAttachmentClear').addEventListener('click', () => {
      videoFileInput.value = '';
      setAttachedFile(null);
    });
    document.getElementById('prompt').addEventListener('input', updateComposerMode);
    document.getElementById('prompt').addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (!document.getElementById('sendChat').disabled) handleComposerSend();
      }
    });
    document.getElementById('openLogin').addEventListener('click', openLoginPanel);
    document.getElementById('closeLogin').addEventListener('click', closeLoginPanel);
    window.addEventListener('openclaw:open-login', openLoginPanel);
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
    document.getElementById('sendChat').addEventListener('click', handleComposerSend);
    document.getElementById('refreshMessages').addEventListener('click', refreshMessages);
    document.getElementById('uploadJob').addEventListener('click', uploadJob);
    document.getElementById('uploadSmoke').addEventListener('click', uploadTinySmoke);
    document.getElementById('pollJob').addEventListener('click', pollJob);
    document.getElementById('sessionId').addEventListener('input', () => {
      if (isAuthenticated()) setAuthenticatedView();
      syncActionAvailability();
    });

    /* ===== M-UI overhaul: theme, menus, modal, toast, search, mobile ===== */
    // theme (light / dark / system). Session-scoped only: the page intentionally
    // keeps NO browser storage (security contract), so this resets to system on reload.
    let themeChoice = 'system';
    const themeMedia = window.matchMedia('(prefers-color-scheme: dark)');
    function applyTheme() {
      const choice = themeChoice || 'system';
      const dark = choice === 'dark' || (choice === 'system' && themeMedia.matches);
      document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
      document.querySelectorAll('[data-theme-choice]').forEach(b => {
        b.setAttribute('aria-checked', String(b.dataset.themeChoice === choice));
      });
    }
    function setTheme(choice) { themeChoice = choice; applyTheme(); }
    themeMedia.addEventListener('change', applyTheme);
    applyTheme();

    // toast
    const toastHost = document.getElementById('toastHost');
    function toast(message, opts) {
      opts = opts || {};
      const el = document.createElement('div');
      el.className = 'toast' + (opts.type ? (' ' + opts.type) : '');
      el.setAttribute('role', 'status');
      const span = document.createElement('span');
      span.textContent = message;
      el.appendChild(span);
      let timer;
      const dismiss = () => { el.classList.remove('show'); setTimeout(() => el.remove(), 220); };
      if (opts.actionLabel && typeof opts.onAction === 'function') {
        const btn = document.createElement('button');
        btn.className = 'toast-action'; btn.type = 'button'; btn.textContent = opts.actionLabel;
        btn.addEventListener('click', () => { clearTimeout(timer); dismiss(); opts.onAction(); });
        el.appendChild(btn);
      }
      toastHost.appendChild(el);
      requestAnimationFrame(() => el.classList.add('show'));
      timer = setTimeout(dismiss, opts.duration || 3200);
      return dismiss;
    }

    // modal (confirm / prompt) -> Promise
    const modalHost = document.getElementById('modalHost');
    const modalTitle = document.getElementById('modalTitle');
    const modalDesc = document.getElementById('modalDesc');
    const modalInput = document.getElementById('modalInput');
    const modalCancel = document.getElementById('modalCancel');
    const modalConfirm = document.getElementById('modalConfirm');
    let modalResolve = null;
    let modalLastFocus = null;
    function closeModal(value) {
      modalHost.classList.remove('show');
      modalHost.hidden = true;
      const r = modalResolve; modalResolve = null;
      if (modalLastFocus && modalLastFocus.focus) { try { modalLastFocus.focus(); } catch (e) {} }
      if (r) r(value);
    }
    function openModal(opts) {
      opts = opts || {};
      modalLastFocus = document.activeElement;
      modalTitle.textContent = opts.title || '提示';
      modalDesc.textContent = opts.desc || '';
      modalDesc.style.display = opts.desc ? '' : 'none';
      if (opts.prompt) { modalInput.hidden = false; modalInput.value = opts.value || ''; }
      else { modalInput.hidden = true; }
      modalConfirm.textContent = opts.confirmText || '确定';
      modalConfirm.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-primary');
      modalHost.hidden = false;
      requestAnimationFrame(() => modalHost.classList.add('show'));
      setTimeout(() => {
        const f = opts.prompt ? modalInput : modalConfirm;
        if (f && f.focus) f.focus();
        if (opts.prompt && modalInput.select) modalInput.select();
      }, 30);
      return new Promise(resolve => { modalResolve = resolve; });
    }
    modalConfirm.addEventListener('click', () => closeModal(modalInput.hidden ? true : modalInput.value));
    modalCancel.addEventListener('click', () => closeModal(null));
    modalHost.addEventListener('click', e => { if (e.target === modalHost) closeModal(null); });
    modalInput.addEventListener('keydown', e => { if (e.key === 'Enter') closeModal(modalInput.value); });

    // single open popup manager + outside-click + Esc
    let openPop = null;
    function closePop() {
      if (openPop) {
        openPop.el.hidden = true;
        if (openPop.btn) openPop.btn.setAttribute('aria-expanded', 'false');
        openPop = null;
      }
    }
    function showPop(el, btn) {
      closePop();
      el.hidden = false;
      if (btn) btn.setAttribute('aria-expanded', 'true');
      openPop = { el: el, btn: btn };
    }
    function placePop(el, btn, opts) {
      opts = opts || {};
      el.hidden = false;
      el.style.position = 'fixed';
      el.style.left = '-9999px';
      el.style.top = '0px';
      const w = el.offsetWidth, h = el.offsetHeight;
      const r = btn.getBoundingClientRect();
      let left = opts.alignRight ? (r.right - w) : r.left;
      let top = opts.above ? (r.top - h - 6) : (r.bottom + 6);
      if (opts.above && top < 8) top = r.bottom + 6;
      left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
      top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
      el.style.left = left + 'px';
      el.style.top = top + 'px';
    }
    document.addEventListener('click', e => {
      if (openPop && !openPop.el.contains(e.target) && (!openPop.btn || !openPop.btn.contains(e.target))) closePop();
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      if (modalHost && !modalHost.hidden) { closeModal(null); return; }
      if (openPop) { const b = openPop.btn; closePop(); if (b && b.focus) b.focus(); return; }
      if (sidebar && sidebar.classList.contains('drawer-open')) closeDrawer();
    });

    // user menu (theme / about / logout)
    const userMenuBtn = document.getElementById('userMenuBtn');
    const userMenu = document.getElementById('userMenu');
    userMenuBtn.addEventListener('click', e => {
      e.stopPropagation();
      if (openPop && openPop.el === userMenu) { closePop(); return; }
      placePop(userMenu, userMenuBtn, { above: true });
      showPop(userMenu, userMenuBtn);
      const first = userMenu.querySelector('button');
      if (first) first.focus();
    });
    userMenu.querySelectorAll('[data-theme-choice]').forEach(b => {
      b.addEventListener('click', () => {
        setTheme(b.dataset.themeChoice);
        const label = { light: '浅色', dark: '深色', system: '跟随系统' }[b.dataset.themeChoice] || '';
        toast('已切换至' + label + '模式');
      });
    });
    document.getElementById('aboutBtn').addEventListener('click', () => {
      closePop();
      openModal({ title: '关于 OpenClaw', desc: 'OpenClaw 短视频分析助手：支持抖音视频链接读取与本地视频文件上传的多模态分析，围绕选题、前 3 秒钩子、内容结构、画面设计与转化引导给出可执行建议。本页为 OpenClaw 自有会话，独立于 Dify 登录。', confirmText: '知道了' });
    });

    // local session overrides (rename / delete). Session-scoped in-memory only —
    // the page keeps no browser storage by design; swappable to a backend prefs API later.
    let sessionOverrides = {};
    function persistOverrides() { /* session-scoped; intentionally no browser storage */ }
    function setSessionOverride(id, patch) { sessionOverrides[id] = Object.assign({}, sessionOverrides[id], patch); persistOverrides(); }

    // per-session row menu
    const sessionRowMenu = document.getElementById('sessionRowMenu');
    let rowMenuSession = null;
    function openSessionRowMenu(btn, session) {
      rowMenuSession = session;
      placePop(sessionRowMenu, btn, { alignRight: true });
      showPop(sessionRowMenu, btn);
    }
    sessionRowMenu.querySelector('[data-row-action="rename"]').addEventListener('click', async () => {
      const s = rowMenuSession; closePop(); if (!s) return;
      const name = await openModal({ title: '重命名对话', prompt: true, value: sessionDisplayTitle(s), confirmText: '保存' });
      if (name == null) return;
      const t = String(name).trim();
      if (!t) return;
      setSessionOverride(s.id, { title: t });
      renderSessions(knownSessions);
      if (document.getElementById('sessionId').value === s.id) document.getElementById('cgConvTitle').textContent = t;
      toast('已重命名（本地）', { type: 'success' });
    });
    sessionRowMenu.querySelector('[data-row-action="delete"]').addEventListener('click', async () => {
      const s = rowMenuSession; closePop(); if (!s) return;
      const ok = await openModal({ title: '删除对话', desc: '将从本地列表移除“' + sessionDisplayTitle(s) + '”。该操作仅在当前浏览器生效，不会删除服务器端记录。', danger: true, confirmText: '删除' });
      if (!ok) return;
      const prev = sessionOverrides[s.id] ? Object.assign({}, sessionOverrides[s.id]) : null;
      setSessionOverride(s.id, { deleted: true });
      if (document.getElementById('sessionId').value === s.id) {
        document.getElementById('sessionId').value = '';
        conversation.innerHTML = '';
        document.getElementById('cgConvTitle').textContent = 'OpenClaw';
      }
      renderSessions(knownSessions);
      toast('已删除（本地）', {
        type: 'success', actionLabel: '撤销', duration: 5000,
        onAction: () => {
          if (prev) sessionOverrides[s.id] = prev; else delete sessionOverrides[s.id];
          persistOverrides();
          renderSessions(knownSessions);
          toast('已撤销删除');
        }
      });
    });

    // session search (client-side filter)
    let currentSearchQuery = '';
    const sessionSearch = document.getElementById('sessionSearch');
    const sessionSearchWrap = document.getElementById('sessionSearchWrap');
    sessionSearch.addEventListener('input', () => {
      currentSearchQuery = sessionSearch.value;
      sessionSearchWrap.classList.toggle('has-value', !!currentSearchQuery);
      renderSessions(knownSessions);
    });
    document.getElementById('sessionSearchClear').addEventListener('click', () => {
      sessionSearch.value = '';
      currentSearchQuery = '';
      sessionSearchWrap.classList.remove('has-value');
      renderSessions(knownSessions);
      sessionSearch.focus();
    });

    // message copy action
    function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(() => true).catch(() => fallbackCopy(text));
      }
      return Promise.resolve(fallbackCopy(text));
    }
    function fallbackCopy(text) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        const ok = document.execCommand('copy'); ta.remove(); return ok;
      } catch (e) { return false; }
    }
    function buildMsgActions(node) {
      const bar = document.createElement('div');
      bar.className = 'cg-msg-actions';
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button'; copyBtn.title = '复制'; copyBtn.setAttribute('aria-label', '复制消息');
      copyBtn.innerHTML = '<svg class="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg><span>复制</span>';
      copyBtn.addEventListener('click', () => {
        const inner = messageInner(node);
        const txt = inner ? inner.textContent : '';
        copyText(txt).then(ok => toast(ok ? '已复制' : '复制失败', { type: ok ? 'success' : 'error' }));
      });
      bar.appendChild(copyBtn);
      return bar;
    }

    // mobile sidebar drawer
    const sidebar = document.getElementById('sessionPanel');
    const scrim = document.getElementById('cgScrim');
    const cgMenuBtn = document.getElementById('cgMenuBtn');
    function openDrawer() {
      sidebar.classList.add('drawer-open');
      scrim.hidden = false;
      requestAnimationFrame(() => scrim.classList.add('show'));
      cgMenuBtn.setAttribute('aria-expanded', 'true');
    }
    function closeDrawer() {
      sidebar.classList.remove('drawer-open');
      scrim.classList.remove('show');
      setTimeout(() => { scrim.hidden = true; }, 200);
      cgMenuBtn.setAttribute('aria-expanded', 'false');
    }
    cgMenuBtn.addEventListener('click', () => {
      if (sidebar.classList.contains('drawer-open')) closeDrawer(); else openDrawer();
    });
    scrim.addEventListener('click', closeDrawer);
    sessionList.addEventListener('click', e => {
      if (e.target.closest('.session-item') && window.innerWidth <= 820) closeDrawer();
    });
    document.getElementById('createSession').addEventListener('click', () => {
      if (window.innerWidth <= 820) closeDrawer();
    });

    // composer textarea autosize
    const promptEl = document.getElementById('prompt');
    function autosizePrompt() {
      promptEl.style.height = 'auto';
      const next = Math.min(promptEl.scrollHeight, 200);
      promptEl.style.height = next + 'px';
      promptEl.style.overflowY = promptEl.scrollHeight > 200 ? 'auto' : 'hidden';
    }
    promptEl.addEventListener('input', autosizePrompt);

    // reflect auth state into the sidebar user identity
    function reflectIdentity() {
      const authed = isAuthenticated();
      const name = authed ? '已登录用户' : '未登录';
      const un = document.getElementById('userName');
      const mn = document.getElementById('menuUserName');
      const av = document.getElementById('userAvatar');
      if (un) un.textContent = name;
      if (mn) mn.textContent = name;
      if (av) av.textContent = authed ? '用' : 'OC';
    }
    try {
      new MutationObserver(reflectIdentity).observe(
        document.getElementById('authStatus'),
        { childList: true, characterData: true, subtree: true, attributes: true }
      );
    } catch (e) {}
    reflectIdentity();

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
    inject_session_greeting: bool | None = None,
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
    if inject_session_greeting is None:
        inject_session_greeting = os.environ.get("BRIDGE_INJECT_SESSION_GREETING", "1").lower() in {"1", "true", "yes"}
    enable_test_identity_headers = os.environ.get("BRIDGE_ENABLE_TEST_IDENTITY_HEADERS", "").lower() in {"1", "true", "yes"}
    test_identity_secret = os.environ.get("BRIDGE_TEST_IDENTITY_SECRET", "")
    enable_dify_provider_identity = os.environ.get("OPENCLAW_ENABLE_DIFY_PROVIDER_IDENTITY", "0").lower() in {
        "1",
        "true",
        "yes",
    }
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
            elif not enable_dify_provider_identity:
                raise PermissionError("login required")
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
            if not enable_dify_provider_identity:
                result["failure_stage"] = "profile"
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
        # M2: post a greeting message to guide the user every time a new
        # conversation is opened. Failures are non-fatal — the session itself
        # is created either way.
        if inject_session_greeting:
            try:
                session_store.add_message(
                    session.id, principal.principal_id, "assistant", NEW_SESSION_GREETING,
                )
            except Exception:
                pass
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

        # ── Bridge-side guardrails (M2) ──────────────────────────────────
        # Rule 1: non-douyin URL or profile link → fixed reply, skip agent.
        guardrail = guardrail_for_message(content)
        if guardrail is not None:
            assistant_message = session_store.add_message(
                session_id, principal.principal_id, "assistant", guardrail.content,
            )
            return JSONResponse(
                status_code=200,
                content={
                    "message": _serialize_message(assistant_message),
                    "session": _serialize_session(session_store.get_session(session_id, principal.principal_id)),
                },
            )

        # Rule 2: detect intent + derive conversation state. State is derived
        # from persisted message + job history (no DB stage column). Deterministic
        # guidance/error branches are answered with fixed Bridge copy; coaching
        # branches (feedback_given / follow_up) call the agent with the real
        # analysis summary injected.
        intent = detect_intent(content)
        is_first_turn = not any(msg.role == "user" for msg in history)
        has_terminal_video = any(getattr(msg, "job_id", None) for msg in history)

        def _job_status(job_id: str) -> str | None:
            try:
                job = job_store.get_job(job_id, principal.principal_id)
            except (JobNotFound, JobOwnershipError):
                return None
            return getattr(job.status, "value", str(job.status))

        # Latest video job (newest message with a job_id) → analyzing/failed signal.
        latest_status: str | None = None
        latest_error_code: str | None = None
        try:
            for msg in reversed(history):
                jid = getattr(msg, "job_id", None)
                if not jid:
                    continue
                try:
                    job = job_store.get_job(jid, principal.principal_id)
                except (JobNotFound, JobOwnershipError):
                    continue
                latest_status = getattr(job.status, "value", str(job.status))
                latest_error_code = getattr(job, "error_code", None)
                break
        except Exception:
            pass
        video_failed = latest_status in {"failed", "timed_out", "cancelled"}
        video_analyzing = latest_status in {"queued", "running"}
        current_video_job_id, _current_video_url = current_video_from_history(history, _job_status)
        has_current_video = current_video_job_id is not None

        state = derive_state(
            has_user_history=not is_first_turn,
            has_terminal_video=has_terminal_video,
            video_failed=video_failed,
            intent=intent,
            has_current_video=has_current_video,
            video_analyzing=video_analyzing,
        )

        # ── Branch A: deterministic Bridge reply (no agent call) ─────────
        fixed_reply = error_reply_for(latest_error_code) if video_failed else fixed_state_reply(state, intent)
        if fixed_reply is not None:
            assistant_message = session_store.add_message(
                session_id, principal.principal_id, "assistant", fixed_reply,
            )
            return JSONResponse(
                status_code=200,
                content={
                    "message": _serialize_message(assistant_message),
                    "session": _serialize_session(session_store.get_session(session_id, principal.principal_id)),
                },
            )

        # ── Branch B: agent-generated reply ─────────────────────────────
        if state in {"feedback_given", "follow_up"} and current_video_job_id:
            analysis_summary: str | None = None
            try:
                video_result = job_store.get_result(current_video_job_id, principal.principal_id)
                payload = getattr(video_result, "result", None)
                if isinstance(payload, dict):
                    analysis_summary = str(payload.get("summary") or "")
            except (JobNotFound, JobOwnershipError):
                pass
            agent_content = build_branch_prompt(
                content, state=state, intent=intent, analysis_summary=analysis_summary,
            )
        else:
            agent_content = build_agent_message(content, is_first_turn=is_first_turn, state=state)

        # ── OpenClaw Gateway agent call ──────────────────────────────────
        chat_request = GatewayChatRequest(
            routing_user=session.openclaw_routing_user,
            session_id=session.id,
            message_id=user_message.id,
            content=agent_content,
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
