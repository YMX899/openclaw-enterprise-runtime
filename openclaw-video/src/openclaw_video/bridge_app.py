from __future__ import annotations

import asyncio
import hmac
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
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
      background: #f7f8fa;
      color: #1d2433;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: #f7f8fa; }
    main { width: min(1080px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 40px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    h1 { font-size: 28px; line-height: 1.1; margin: 0; font-weight: 700; }
    .status { min-width: 128px; border-radius: 8px; padding: 8px 10px; background: #e9edf3; color: #364153; font-size: 14px; text-align: center; }
    .status.ok { background: #d9f7e7; color: #145a32; }
    .status.fail { background: #ffe2df; color: #8a1f17; }
    section { border: 1px solid #dce2ea; border-radius: 8px; background: #ffffff; padding: 16px; margin-top: 14px; }
    h2 { font-size: 16px; line-height: 1.25; margin: 0 0 12px; }
    label { display: block; font-size: 13px; color: #596579; margin: 10px 0 6px; }
    input, textarea {
      width: 100%;
      border: 1px solid #c7d0dd;
      border-radius: 6px;
      min-height: 40px;
      padding: 9px 10px;
      font: inherit;
      color: #1d2433;
      background: #fff;
    }
    textarea { min-height: 92px; resize: vertical; }
    button {
      border: 0;
      border-radius: 6px;
      min-height: 40px;
      padding: 0 14px;
      font: inherit;
      font-weight: 600;
      color: #fff;
      background: #2563eb;
      cursor: pointer;
    }
    button.secondary { background: #334155; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
    pre {
      min-height: 180px;
      max-height: 420px;
      overflow: auto;
      margin: 0;
      padding: 12px;
      border-radius: 8px;
      background: #101827;
      color: #e5eefc;
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    @media (max-width: 760px) {
      main { width: min(100% - 20px, 1080px); padding-top: 16px; }
      header { align-items: flex-start; flex-direction: column; }
      .status { width: 100%; text-align: left; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>OpenClaw Lab</h1>
      <div id="authStatus" class="status">Checking</div>
    </header>
    <section>
      <h2>Session</h2>
      <label for="sessionTitle">Title</label>
      <input id="sessionTitle" value="Video analysis">
      <div class="actions">
        <button id="createSession">Create Session</button>
        <button id="refreshMe" class="secondary">Refresh Login</button>
        <button id="identityDiagnostics" class="secondary">Identity Check</button>
        <button id="runSelfTest" class="secondary">Self Test</button>
      </div>
    </section>
    <section class="grid">
      <div>
        <h2>Video Job</h2>
        <label for="sessionId">Session ID</label>
        <input id="sessionId" autocomplete="off">
        <label for="videoUrl">Video URL</label>
        <input id="videoUrl" placeholder="https://v.douyin.com/...">
        <label for="prompt">Prompt</label>
        <textarea id="prompt">Analyze this video.</textarea>
        <div class="actions">
          <button id="submitJob">Submit Job</button>
          <button id="pollJob" class="secondary">Poll Job</button>
        </div>
        <h2 style="margin-top:18px">Upload Video</h2>
        <label for="videoFile">Video File</label>
        <input id="videoFile" type="file" accept="video/mp4,video/quicktime,video/webm">
        <div class="actions">
          <button id="uploadJob">Upload Job</button>
        </div>
      </div>
      <div>
        <h2>Output</h2>
        <pre id="output">{}</pre>
      </div>
    </section>
  </main>
  <script>
    const output = document.getElementById('output');
    const authStatus = document.getElementById('authStatus');
    let currentJobId = '';
    const terminalStatuses = new Set(['succeeded', 'failed', 'timed_out', 'cancelled']);

    function show(value) {
      output.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    }
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    function huahuoAccessToken() {
      try { return window.localStorage && window.localStorage.getItem('Access-Token') || ''; }
      catch { return ''; }
    }
    function huahuoAppUuid() {
      try { return window.localStorage && window.localStorage.getItem('APP-UUID') || ''; }
      catch { return ''; }
    }
    function huahuoRefreshToken() {
      try { return window.localStorage && window.localStorage.getItem('Refresh-Token') || ''; }
      catch { return ''; }
    }
    function authHeaders() {
      const token = huahuoAccessToken();
      const appUuid = huahuoAppUuid();
      const refreshToken = huahuoRefreshToken();
      if (!token) return {};
      const headers = { 'X-Huahuo-Access-Token': token };
      if (appUuid) headers['X-Huahuo-App-UUID'] = appUuid;
      if (refreshToken) headers['X-Huahuo-Refresh-Token'] = refreshToken;
      return headers;
    }
    async function api(path, options = {}) {
      const response = await fetch(path, {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(options.headers || {}) },
        ...options
      });
      const text = await response.text();
      let body;
      try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
      return { status: response.status, body };
    }
    async function refreshMe() {
      const result = await api('/openclaw-api/me');
      if (result.status === 200) {
        authStatus.textContent = 'Authenticated';
        authStatus.className = 'status ok';
      } else {
        authStatus.textContent = 'Login Required';
        authStatus.className = 'status fail';
      }
      show(result);
    }
    async function createSession() {
      const result = await api('/openclaw-api/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: document.getElementById('sessionTitle').value || 'Video analysis' })
      });
      if (result.body.session && result.body.session.id) {
        document.getElementById('sessionId').value = result.body.session.id;
      }
      show(result);
    }
    async function identityDiagnostics() {
      show(await api('/openclaw-api/identity/diagnostics'));
    }
    async function runSelfTest() {
      const steps = [];
      const add = (name, result) => {
        steps.push({ name, ...result });
        show({ self_test: steps });
      };
      const diagnostics = await api('/openclaw-api/identity/diagnostics');
      add('identity_diagnostics', { status: diagnostics.status, body: diagnostics.body });
      if (!diagnostics.body.authenticated) return;

      const me = await api('/openclaw-api/me');
      add('me', { status: me.status, body: me.body });
      if (me.status !== 200) return;

      const randomId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
      const missing = await api('/openclaw-api/sessions/' + encodeURIComponent(randomId) + '/messages');
      add('random_session_404', { status: missing.status, ok: missing.status === 404 });

      const sessionResult = await api('/openclaw-api/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'OpenClaw self test ' + new Date().toISOString() })
      });
      add('create_session', { status: sessionResult.status, body: sessionResult.body });
      const sessionId = sessionResult.body.session && sessionResult.body.session.id;
      if (!sessionId) return;
      document.getElementById('sessionId').value = sessionId;

      const jobResult = await api('/openclaw-api/jobs', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          video_url: 'https://example.com/not-douyin',
          content: 'Self-test invalid URL should be rejected by the worker.',
          idempotency_key: 'self-test-' + sessionId
        })
      });
      add('submit_invalid_url_job', { status: jobResult.status, body: jobResult.body });
      currentJobId = jobResult.body.job && jobResult.body.job.job_id || '';
      if (!currentJobId) return;

      let lastJob = null;
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await delay(1000);
        const poll = await api('/openclaw-api/jobs/' + encodeURIComponent(currentJobId));
        lastJob = poll.body.job || null;
        if (lastJob && terminalStatuses.has(lastJob.status)) break;
      }
      add('poll_invalid_url_job', { body: lastJob });

      const messages = await api('/openclaw-api/sessions/' + encodeURIComponent(sessionId) + '/messages');
      add('messages', {
        status: messages.status,
        count: messages.body.messages ? messages.body.messages.length : 0
      });
    }
    async function submitJob() {
      const result = await api('/openclaw-api/jobs', {
        method: 'POST',
        body: JSON.stringify({
          session_id: document.getElementById('sessionId').value,
          video_url: document.getElementById('videoUrl').value,
          content: document.getElementById('prompt').value
        })
      });
      if (result.body.job && result.body.job.job_id) currentJobId = result.body.job.job_id;
      show(result);
    }
    async function uploadJob() {
      const fileInput = document.getElementById('videoFile');
      const file = fileInput.files && fileInput.files[0];
      const sessionId = document.getElementById('sessionId').value;
      if (!file || !sessionId) {
        show('Select a video file and session first.');
        return;
      }
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('content', document.getElementById('prompt').value || 'Analyze uploaded video.');
      form.append('video', file);
      const response = await fetch('/openclaw-api/uploads', {
        method: 'POST',
        credentials: 'include',
        headers: authHeaders(),
        body: form
      });
      const text = await response.text();
      let body;
      try { body = text ? JSON.parse(text) : {}; } catch { body = { text }; }
      if (body.job && body.job.job_id) currentJobId = body.job.job_id;
      show({ status: response.status, body });
    }
    async function pollJob() {
      if (!currentJobId) {
        show('No job_id is available yet.');
        return;
      }
      const jobResult = await api('/openclaw-api/jobs/' + encodeURIComponent(currentJobId));
      const job = jobResult.body.job;
      if (job && job.status === 'succeeded') {
        const result = await api('/openclaw-api/jobs/' + encodeURIComponent(currentJobId) + '/result');
        show({ job: jobResult, result });
        return;
      }
      show(jobResult);
    }
    document.getElementById('refreshMe').addEventListener('click', refreshMe);
    document.getElementById('identityDiagnostics').addEventListener('click', identityDiagnostics);
    document.getElementById('runSelfTest').addEventListener('click', runSelfTest);
    document.getElementById('createSession').addEventListener('click', createSession);
    document.getElementById('submitJob').addEventListener('click', submitJob);
    document.getElementById('uploadJob').addEventListener('click', uploadJob);
    document.getElementById('pollJob').addEventListener('click', pollJob);
    refreshMe();
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
    identity_secret = identity_secret if identity_secret is not None else os.environ.get("BRIDGE_IDENTITY_SECRET", "")
    enable_test_identity_headers = os.environ.get("BRIDGE_ENABLE_TEST_IDENTITY_HEADERS", "").lower() in {"1", "true", "yes"}
    test_identity_secret = os.environ.get("BRIDGE_TEST_IDENTITY_SECRET", "")
    phase4_config = load_phase4_config()
    rate_limiter = SlidingWindowRateLimiter()

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

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return health_payload()

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return health_payload()

    @app.get("/openclaw-lab", response_class=HTMLResponse)
    @app.get("/openclaw-lab/", response_class=HTMLResponse)
    async def openclaw_lab() -> HTMLResponse:
        return HTMLResponse(
            LAB_PAGE_HTML,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
            },
        )

    async def current_principal(request: Request) -> DifyPrincipal:
        try:
            if _test_identity_headers_allowed(request, enable_test_identity_headers, test_identity_secret):
                profile = {"id": request.headers["x-test-account"]}
                tenant_id = request.headers.get("x-test-tenant", "test-tenant")
                workspaces = {"data": [{"id": tenant_id, "current": True}]}
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
    async def me(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        return {"principal_id": principal.principal_id, "authenticated": True, **runtime_metadata()}

    @app.get("/openclaw-api/identity/diagnostics")
    async def identity_diagnostics(request: Request) -> dict[str, Any]:
        result: dict[str, Any] = {
            "authenticated": False,
            "login_material_present": _has_dify_login_material(request.headers),
            "huahuo_access_token_present": _has_header(request.headers, "x-huahuo-access-token"),
            "huahuo_app_uuid_present": _has_header(request.headers, "x-huahuo-app-uuid"),
            "profile_ok": False,
            "workspace_ok": False,
            "access_ok": False,
            "current_workspace_count": 0,
            "principal_id": None,
            "failure_stage": None,
        }
        try:
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
                return result
            profile = await dify.profile(request.headers)
            result["profile_ok"] = True
        except PermissionError:
            result["failure_stage"] = "profile"
            return result
        except Exception:
            result["failure_stage"] = "profile"
            return result
        try:
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
            return result
        except Exception:
            result["failure_stage"] = "workspace"
            return result

    @app.get("/openclaw-api/sessions")
    async def sessions(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        return {"sessions": [_serialize_session(item) for item in session_store.list_sessions(principal.principal_id)]}

    @app.post("/openclaw-api/sessions", status_code=201)
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
    async def messages(session_id: str, request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        try:
            messages = session_store.list_messages(session_id, principal.principal_id)
        except (SessionNotFound, SessionOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        return {"messages": [_serialize_message(item) for item in messages]}

    @app.post("/openclaw-api/jobs")
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

    @app.post("/openclaw-api/uploads")
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
    async def get_job(job_id: str, request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        try:
            job = job_store.get_job(job_id, principal.principal_id)
        except (JobNotFound, JobOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        return {"job": _serialize_job(job)}

    @app.get("/openclaw-api/jobs/{job_id}/result")
    async def get_job_result(job_id: str, request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        try:
            result = job_store.get_result(job_id, principal.principal_id)
        except (JobNotFound, JobOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="job result not found") from exc
        return {"result": _serialize_result(result)}

    @app.get("/openclaw-api/jobs/{job_id}/events")
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
