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
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
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
from .video_limits import DEFAULT_MAX_DOWNLOAD_BYTES, DEFAULT_MAX_VIDEO_DURATION_SECONDS
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


from pathlib import Path as _Path


def _resolve_webdist_dir() -> "_Path":
    """Locate the built web assets. Works both from the repo (src/.../webdist)
    and inside the bridge image (COPY src -> /app/src/...) regardless of whether
    the package was pip-installed without package data."""
    candidates = [
        _Path(__file__).resolve().parent / "webdist",
        _Path("/app/src/openclaw_video/webdist"),
        _Path("/app/webdist"),
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return candidates[0]


WEBDIST_DIR = _resolve_webdist_dir()
_LAB_FALLBACK_HTML = (
    "<!doctype html><meta charset=\"utf-8\">"
    "<title>OpenClaw</title><body>UI assets are not built. "
    "Run `npm run build` in openclaw-video/web.</body>"
)


def lab_index_html() -> str:
    try:
        return (WEBDIST_DIR / "index.html").read_text(encoding="utf-8")
    except OSError:
        return _LAB_FALLBACK_HTML


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

    @app.get("/openclaw-lab/", response_class=HTMLResponse)
    @app.get("/ai/openclaw-lab/", response_class=HTMLResponse)
    async def openclaw_lab() -> HTMLResponse:
        # Serve the built single-page app shell. Relative asset URLs ("./assets/..")
        # resolve under the trailing-slash page path; the no-slash routes redirect here.
        return HTMLResponse(
            lab_index_html(),
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
            },
        )

    @app.get("/openclaw-lab")
    @app.get("/ai/openclaw-lab")
    async def openclaw_lab_redirect(request: Request) -> RedirectResponse:
        return RedirectResponse(url=request.url.path + "/", status_code=308)

    @app.get("/openclaw-lab/assets/{asset_path:path}")
    @app.get("/ai/openclaw-lab/assets/{asset_path:path}")
    async def openclaw_lab_assets(asset_path: str) -> FileResponse:
        assets_root = (WEBDIST_DIR / "assets").resolve()
        target = (assets_root / asset_path).resolve()
        try:
            target.relative_to(assets_root)
        except ValueError:
            raise HTTPException(status_code=404, detail="not found")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(
            target,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
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

    @app.get("/openclaw-api/prefs")
    @app.get("/ai/openclaw-api/prefs")
    @app.get("/api/openclaw-api/prefs")
    @app.get("/console/api/openclaw-api/prefs")
    async def get_user_prefs(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        prefs: dict[str, Any] = {}
        if hasattr(session_store, "get_prefs"):
            try:
                prefs = session_store.get_prefs(principal.principal_id) or {}
            except Exception:
                prefs = {}
        return {"prefs": prefs}

    @app.put("/openclaw-api/prefs")
    @app.put("/ai/openclaw-api/prefs")
    @app.put("/api/openclaw-api/prefs")
    @app.put("/console/api/openclaw-api/prefs")
    async def put_user_prefs(request: Request) -> dict[str, Any]:
        principal = await current_principal(request)
        payload = await request.json()
        prefs = payload.get("prefs") if isinstance(payload, dict) else None
        if not isinstance(prefs, dict):
            raise HTTPException(status_code=400, detail="prefs object is required")
        if len(json.dumps(prefs, ensure_ascii=False)) > 65536:
            raise HTTPException(status_code=413, detail="prefs payload too large")
        if not hasattr(session_store, "put_prefs"):
            raise HTTPException(status_code=501, detail="prefs storage is not configured")
        saved = session_store.put_prefs(principal.principal_id, prefs)
        return {"prefs": saved}

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
                if request.headers.get("x-test-multiple-current") == "1":
                    workspaces = {"data": [{"id": tenant_id, "current": True}, {"id": "test-tenant-b", "current": True}]}
                else:
                    workspaces = {"data": [{"id": tenant_id, "current": True}]}
                result["current_workspace_count"] = current_workspace_count(workspaces)
                try:
                    principal = derive_principal(identity_secret, profile, workspaces)
                except Exception:
                    result["failure_stage"] = "workspace"
                    return result
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

    @app.post("/openclaw-api/sessions/{session_id}/messages")
    @app.post("/ai/openclaw-api/sessions/{session_id}/messages")
    @app.post("/api/openclaw-api/sessions/{session_id}/messages")
    @app.post("/console/api/openclaw-api/sessions/{session_id}/messages")
    async def create_message(session_id: str, request: Request) -> JSONResponse:
        principal = await current_principal(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        role = str(payload.get("role") or "user").strip() or "user"
        if role != "user":
            raise HTTPException(status_code=400, detail="only user messages can be created")
        content = str(payload.get("content") or "").strip()
        video_url = str(payload.get("video_url") or "").strip() or None
        if not content and video_url:
            content = video_url
        try:
            message = session_store.add_message(
                session_id,
                principal.principal_id,
                role,
                content,
                video_url=video_url,
            )
        except (SessionNotFound, SessionOwnershipError) as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except MessageValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(status_code=201, content={"message": _serialize_message(message)})

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
                    max_duration_seconds=positive_int_from_env("MAX_VIDEO_DURATION_SECONDS", DEFAULT_MAX_VIDEO_DURATION_SECONDS),
                    max_download_bytes=positive_int_from_env("MAX_DOWNLOAD_BYTES", DEFAULT_MAX_DOWNLOAD_BYTES),
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
