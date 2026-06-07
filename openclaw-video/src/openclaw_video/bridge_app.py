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
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenClaw Lab</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f4f6f8;
      color: #111827;
      --page: #f4f6f8;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --border: #d6dde8;
      --border-strong: #b9c4d3;
      --text: #111827;
      --muted: #5e6a7d;
      --faint: #eef2f7;
      --primary: #1f5eff;
      --primary-strong: #174bd4;
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
      background:
        linear-gradient(180deg, #fbfcfe 0, var(--page) 240px, #edf2f7 100%);
      color: var(--text);
    }
    main.shell { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 36px; }
    header.topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }
    .brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
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
    h1 { font-size: 30px; line-height: 1.08; margin: 0; font-weight: 760; }
    h2 { font-size: 16px; line-height: 1.25; margin: 0; font-weight: 760; }
    h3 { font-size: 15px; line-height: 1.25; margin: 0; font-weight: 730; }
    .top-status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
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
    .run-state.busy { background: var(--info-bg); color: var(--info); border-color: #b9e8ef; }
    .run-state.warn { background: var(--warning-bg); color: var(--warning); border-color: #f4d18f; }
    .panel-badge { background: #f2f6fb; border-color: var(--border); color: #445166; }
    .panel {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: rgba(255, 255, 255, .96);
      padding: 16px;
      box-shadow: 0 14px 34px rgba(18, 31, 52, .055);
    }
    .panel + .panel { margin-top: 12px; }
    .section-heading {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 12px;
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
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .field-row { display: grid; grid-template-columns: minmax(190px, .72fr) minmax(0, 1fr); gap: 14px; }
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
    .workbench {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(390px, .92fr);
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
    .conversation {
      display: grid;
      gap: 8px;
      min-height: 86px;
      max-height: 190px;
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
    .output-panel {
      position: sticky;
      top: 14px;
      overflow: hidden;
    }
    .status-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
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
      min-height: 330px;
      max-height: 520px;
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
    @media (max-width: 960px) {
      .workbench { grid-template-columns: 1fr; }
      .output-panel { position: static; }
      pre { min-height: 320px; }
    }
    @media (max-width: 760px) {
      main.shell { width: min(100% - 20px, 1180px); padding-top: 18px; }
      header.topbar { align-items: flex-start; flex-direction: column; }
      .top-status { width: 100%; justify-content: stretch; }
      .status, .run-state { flex: 1 1 auto; }
      .grid { grid-template-columns: 1fr; }
      .field-row { grid-template-columns: 1fr; }
      .session-layout { grid-template-columns: 1fr; }
      .session-actions { min-width: 0; }
      .session-actions .actions { margin-top: 11px; }
      .status-strip { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .brand-mark { width: 40px; height: 40px; }
      h1 { font-size: 26px; }
      .panel { padding: 15px; }
      .section-heading { flex-direction: column; }
      .actions { display: grid; grid-template-columns: 1fr; }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">OC</div>
        <div>
          <p class="eyebrow">Short video analysis workbench</p>
          <h1>OpenClaw Lab</h1>
        </div>
      </div>
      <div class="top-status" aria-label="OpenClaw runtime status">
        <div id="runState" class="run-state busy">Ready</div>
        <div id="authStatus" class="status">Checking</div>
      </div>
    </header>

    <div class="workbench">
      <div class="control-stack">
        <section class="panel" aria-labelledby="loginHeading">
          <div class="section-heading">
            <div>
              <h2 id="loginHeading">OpenClaw Login</h2>
              <p class="section-note">Use the standalone OpenClaw session for analysis jobs and acceptance checks.</p>
            </div>
            <span class="panel-badge">Private session</span>
          </div>
          <div class="grid">
            <div>
              <label for="loginAccount">Account</label>
              <input id="loginAccount" autocomplete="username" inputmode="text" placeholder="OpenClaw account">
            </div>
            <div>
              <label for="loginPassword">Password</label>
              <input id="loginPassword" type="password" autocomplete="current-password" placeholder="Password">
            </div>
          </div>
          <div class="actions">
            <button id="loginButton">Login</button>
            <button id="logoutButton" class="secondary">Logout</button>
            <button id="refreshMe" class="secondary">Refresh Login</button>
            <button id="identityDiagnostics" class="secondary">Identity Check</button>
          </div>
        </section>

        <section class="panel" aria-labelledby="sessionHeading">
          <div class="section-heading">
            <div>
              <h2 id="sessionHeading">Session</h2>
              <p class="section-note">Create a workspace before submitting a link or upload.</p>
            </div>
          </div>
          <div class="session-layout">
            <div>
              <label for="sessionTitle">Title</label>
              <input id="sessionTitle" value="Video analysis">
            </div>
            <div class="session-actions">
              <div class="actions">
                <button id="createSession">Create Session</button>
                <button id="runSelfTest" class="secondary">Self Test</button>
              </div>
              <div class="actions validation-actions" aria-label="Acceptance and safety checks">
                <button id="runSecurityTest" class="secondary">Security Test</button>
                <button id="runPostLoginAcceptance" class="secondary">Post-Login Acceptance</button>
              </div>
            </div>
          </div>
        </section>

        <section class="panel" aria-labelledby="videoHeading">
          <div class="section-heading">
            <div>
              <h2 id="videoHeading">Video Job</h2>
              <p class="section-note">Analyze an allowlisted video link or upload a compact video file for the same session.</p>
            </div>
          </div>
          <div class="field-row">
            <div>
              <label for="sessionId">Session ID</label>
              <input id="sessionId" autocomplete="off" placeholder="Created session id">
            </div>
            <div>
              <label for="videoUrl">Video URL</label>
              <input id="videoUrl" placeholder="https://v.douyin.com/...">
            </div>
          </div>
          <p class="field-help">Links are validated by the server before a worker reads the media.</p>
          <label>Conversation</label>
          <div id="conversation" class="conversation" aria-live="polite">
            <div class="message assistant">Log in, create a session, then send a video link for OpenClaw to analyze.</div>
          </div>
          <label for="prompt">Prompt</label>
          <textarea id="prompt">Analyze this video.</textarea>
          <div class="actions">
            <button id="readVideoLink" class="secondary">Read Link</button>
            <button id="submitJob">Submit Job</button>
            <button id="pollJob" class="secondary">Poll Job</button>
          </div>
          <div class="divider"></div>
          <h3>Upload Video</h3>
          <label for="videoFile">Video File</label>
          <input id="videoFile" type="file" accept="video/mp4,video/quicktime,video/webm">
          <p class="field-help">Supported local checks use MP4, MOV, and WebM within the configured upload limit.</p>
          <div class="actions">
            <button id="uploadJob">Upload Job</button>
            <button id="uploadSmoke" class="secondary">Tiny Upload</button>
          </div>
        </section>
      </div>

      <section class="panel output-panel" aria-labelledby="outputHeading">
        <div class="section-heading">
          <div>
            <h2 id="outputHeading">Job Result & Status</h2>
            <p class="section-note">Responses are shown as sanitized JSON for review, acceptance, and support handoff.</p>
          </div>
        </div>
        <div class="status-strip" aria-label="Current job summary">
          <div>
            <span class="metric-label">Auth</span>
            <strong id="authMetric">Checking</strong>
          </div>
          <div>
            <span class="metric-label">Job</span>
            <strong id="jobMetric">No job yet</strong>
          </div>
          <div>
            <span class="metric-label">Output</span>
            <strong id="outputMetric">Idle</strong>
          </div>
        </div>
        <div id="outputSummary" class="output-summary">Waiting for a login refresh, session action, job, or safety test.</div>
        <pre id="output">{}</pre>
      </section>
    </div>
  </main>
  <script>
    const output = document.getElementById('output');
    const authStatus = document.getElementById('authStatus');
    const runState = document.getElementById('runState');
    const authMetric = document.getElementById('authMetric');
    const jobMetric = document.getElementById('jobMetric');
    const outputMetric = document.getElementById('outputMetric');
    const outputSummary = document.getElementById('outputSummary');
    const conversation = document.getElementById('conversation');
    let currentJobId = '';
    const apiPrefix = window.location.hostname === 'ai001.huahuoai.com'
      ? '/console/api/openclaw-api'
      : (window.location.pathname.startsWith('/ai/openclaw-lab') ? '/api/openclaw-api' : '/openclaw-api');
    const terminalStatuses = new Set(['succeeded', 'failed', 'timed_out', 'cancelled']);

    function setRunState(text, tone = 'busy') {
      runState.textContent = text;
      runState.className = 'run-state ' + tone;
      outputMetric.textContent = text;
    }
    function setAuthState(text, tone) {
      authStatus.textContent = text;
      authStatus.className = 'status ' + tone;
      authMetric.textContent = text;
    }
    function setCurrentJob(jobId) {
      currentJobId = jobId || '';
      jobMetric.textContent = currentJobId ? currentJobId.slice(0, 8) + '...' : 'No job yet';
    }
    function summarizeOutput(value) {
      if (typeof value === 'string') {
        return { tone: 'warn', text: value || 'No output text.' };
      }
      if (!value || typeof value !== 'object') {
        return { tone: 'warn', text: 'No structured response yet.' };
      }
      if (value.post_login_acceptance) {
        const payload = value.post_login_acceptance;
        const steps = Array.isArray(payload.steps) ? payload.steps : [];
        const failed = steps.filter(step => step.ok === false).length;
        const tone = payload.overall === 'PASS' ? 'ok' : (payload.overall === 'FAIL' ? 'fail' : 'warn');
        return { tone, text: 'Post-login acceptance ' + payload.overall + ': ' + steps.length + ' checks, ' + failed + ' failed.' };
      }
      if (value.security_test) {
        const steps = Array.isArray(value.security_test) ? value.security_test : [];
        const failed = steps.filter(step => step.ok === false).length;
        return { tone: failed ? 'fail' : 'warn', text: 'Security test running: ' + steps.length + ' checks captured, ' + failed + ' failed.' };
      }
      if (value.self_test) {
        const steps = Array.isArray(value.self_test) ? value.self_test : [];
        return { tone: 'warn', text: 'Self test running: ' + steps.length + ' checks captured.' };
      }
      if (value.upload_smoke) {
        const steps = Array.isArray(value.upload_smoke) ? value.upload_smoke : [];
        const last = steps.length ? steps[steps.length - 1] : null;
        const tone = last && last.ok === false ? 'fail' : 'warn';
        return { tone, text: 'Tiny upload smoke: ' + steps.length + ' steps captured.' };
      }
      if (value.video_link_read_check) {
        const payload = value.video_link_read_check;
        const tone = payload.status === 'PASS' ? 'ok' : 'warn';
        const count = payload.direct_video_candidate_count || 0;
        return { tone, text: 'Video link read check ' + payload.status + ': ' + count + ' direct candidates, model not invoked.' };
      }
      const status = typeof value.status === 'number' ? value.status : null;
      const job = value.job || (value.body && value.body.job) || null;
      if (job && job.job_id) {
        setCurrentJob(job.job_id);
        const tone = job.status === 'succeeded' ? 'ok' : (terminalStatuses.has(job.status) ? 'fail' : 'warn');
        return { tone, text: 'Job ' + job.status + ': ' + job.job_id.slice(0, 8) + '...' };
      }
      if (status) {
        const tone = status >= 200 && status < 300 ? 'ok' : (status === 401 || status === 403 || status >= 500 ? 'fail' : 'warn');
        return { tone, text: 'HTTP ' + status + ' response captured.' };
      }
      return { tone: 'warn', text: 'Structured response captured.' };
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
    async function withBusy(label, task) {
      setRunState(label, 'busy');
      try {
        const result = await task();
        return result;
      } catch (error) {
        setRunState('Error', 'fail');
        show({ error: String(error && error.message || error) });
        throw error;
      }
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
    async function login() {
      return withBusy('Logging in', async () => {
      const result = await api(apiPrefix + '/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          account: document.getElementById('loginAccount').value,
          password: document.getElementById('loginPassword').value
        })
      });
      if (result.status === 200) {
        document.getElementById('loginPassword').value = '';
        setAuthState('Authenticated', 'ok');
        setRunState('Ready', 'ok');
      } else {
        setAuthState(result.status === 429 ? 'Rate Limited' : 'Login Failed', 'fail');
        setRunState('Needs attention', 'fail');
      }
      show(result);
      });
    }
    async function logout() {
      return withBusy('Logging out', async () => {
      const result = await api(apiPrefix + '/auth/logout', { method: 'POST', body: JSON.stringify({}) });
      setAuthState('Login Required', 'fail');
      setRunState('Ready', 'busy');
      show(result);
      });
    }
    async function refreshMe(options = {}) {
      return withBusy('Refreshing', async () => {
      const result = await api(apiPrefix + '/me');
      if (result.status === 200) {
        setAuthState('Authenticated', 'ok');
        setRunState('Ready', 'ok');
      } else {
        setAuthState('Login Required', 'fail');
        setRunState('Login required', 'fail');
      }
      if (!options.quiet) show(result);
      });
    }
    async function createSession() {
      return withBusy('Creating session', async () => {
      const result = await api(apiPrefix + '/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: document.getElementById('sessionTitle').value || 'Video analysis' })
      });
      if (result.body.session && result.body.session.id) {
        document.getElementById('sessionId').value = result.body.session.id;
        setRunState('Session ready', 'ok');
      } else {
        setRunState('Needs attention', 'fail');
      }
      show(result);
      });
    }
    async function identityDiagnostics() {
      return withBusy('Checking identity', async () => {
      show(await api(apiPrefix + '/identity/diagnostics'));
      setRunState('Diagnostics done', 'ok');
      });
    }
    async function runSelfTest() {
      return withBusy('Self test running', async () => {
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ self_test: steps });
      };
      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      add('identity_diagnostics', { status: diagnostics.status, body: diagnostics.body });
      if (!diagnostics.body.authenticated) {
        setRunState('Login required', 'fail');
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', { status: me.status, body: me.body });
      if (me.status !== 200) {
        setRunState('Needs attention', 'fail');
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
        setRunState('Needs attention', 'fail');
        return;
      }
      document.getElementById('sessionId').value = sessionId;

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
        setRunState('Needs attention', 'fail');
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
      setRunState('Self test done', 'ok');
      });
    }
    async function runSecurityTest() {
      return withBusy('Security test running', async () => {
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ security_test: steps });
      };
      const diagnostics = await api(apiPrefix + '/identity/diagnostics');
      add('identity_diagnostics', { status: diagnostics.status, body: diagnostics.body });
      if (!diagnostics.body.authenticated) {
        setRunState('Login required', 'fail');
        return;
      }

      const me = await api(apiPrefix + '/me');
      add('me', { status: me.status, authenticated: me.body.authenticated === true });
      if (me.status !== 200) {
        setRunState('Needs attention', 'fail');
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
        setRunState('Needs attention', 'fail');
        return;
      }
      document.getElementById('sessionId').value = sessionId;

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
      setRunState(failed ? 'Security issues' : 'Security done', failed ? 'fail' : 'ok');
      });
    }
    async function runPostLoginAcceptance() {
      return withBusy('Acceptance running', async () => {
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
        setRunState(overall === 'PASS' ? 'Acceptance PASS' : 'Acceptance FAIL', overall === 'PASS' ? 'ok' : 'fail');
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
      document.getElementById('sessionId').value = sessionId;

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
    async function submitJob() {
      return withBusy('Submitting job', async () => {
      const promptText = document.getElementById('prompt').value || 'Analyze this video.';
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
        setCurrentJob(result.body.job.job_id);
        setRunState('Job submitted', 'ok');
        pushMessage('user', 'Submitted a video link for analysis.');
        pushMessage('assistant', 'Job submitted. Poll the job when the worker has progressed.');
      } else {
        setRunState('Needs attention', 'fail');
      }
      show(result);
      });
    }
    async function readVideoLink() {
      return withBusy('Reading link', async () => {
      const videoUrl = document.getElementById('videoUrl').value;
      const result = await api(apiPrefix + '/video-link/read-check', {
        method: 'POST',
        body: JSON.stringify({ video_url: videoUrl })
      });
      show({ status: result.status, video_link_read_check: result.body });
      if (result.status === 200 && result.body.status === 'PASS') {
        setRunState('Link readable', 'ok');
        pushMessage('assistant', 'Video link is readable. Direct candidates were found without invoking the model.');
      } else {
        setRunState('Link check ended', result.status >= 400 ? 'fail' : 'warn');
      }
      });
    }
    async function uploadJob() {
      return withBusy('Uploading video', async () => {
      const fileInput = document.getElementById('videoFile');
      const file = fileInput.files && fileInput.files[0];
      const sessionId = document.getElementById('sessionId').value;
      if (!file || !sessionId) {
        show('Select a video file and session first.');
        setRunState('Needs input', 'fail');
        return;
      }
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('content', document.getElementById('prompt').value || 'Analyze uploaded video.');
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
        setCurrentJob(body.job.job_id);
        setRunState('Upload submitted', 'ok');
        pushMessage('user', 'Uploaded a video file for analysis.');
        pushMessage('assistant', 'Upload accepted. Poll the job for worker status and result.');
      } else {
        setRunState('Needs attention', 'fail');
      }
      show({ status: response.status, body });
      });
    }
    async function uploadTinySmoke() {
      return withBusy('Tiny upload running', async () => {
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
        document.getElementById('sessionId').value = sessionId;
      }
      if (!sessionId) {
        setRunState('Needs attention', 'fail');
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
      if (!currentJobId) {
        setRunState('Needs attention', 'fail');
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
      setRunState(lastJob && lastJob.status === 'succeeded' ? 'Tiny upload done' : 'Tiny upload ended', lastJob && lastJob.status === 'succeeded' ? 'ok' : 'fail');
      });
    }
    async function pollJob() {
      return withBusy('Polling job', async () => {
      if (!currentJobId) {
        show('No job_id is available yet.');
        setRunState('No job selected', 'fail');
        return;
      }
      const jobResult = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId));
      const job = jobResult.body.job;
      if (job && job.status === 'succeeded') {
        const result = await api(apiPrefix + '/jobs/' + encodeURIComponent(currentJobId) + '/result');
        pushMessage('assistant', 'Analysis result is ready. Review the structured output panel.');
        show({ job: jobResult, result });
        setRunState('Result ready', 'ok');
        return;
      }
      show(jobResult);
      setRunState(job && terminalStatuses.has(job.status) ? 'Job ended' : 'Job running', job && terminalStatuses.has(job.status) ? 'fail' : 'busy');
      });
    }
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
    document.getElementById('uploadJob').addEventListener('click', uploadJob);
    document.getElementById('uploadSmoke').addEventListener('click', uploadTinySmoke);
    document.getElementById('pollJob').addEventListener('click', pollJob);
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
