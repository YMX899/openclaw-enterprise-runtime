from __future__ import annotations

import os
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
except ImportError as exc:  # pragma: no cover - import checked in container image
    raise RuntimeError("fastapi is required for openclaw-bridge") from exc

from .redaction import safe_error_message
from .dify_client import DifyClient
from .identity import IdentityError, derive_principal


def create_app() -> FastAPI:
    app = FastAPI(title="OpenClaw Dify Bridge", version="0.1.0")
    dify = DifyClient(os.environ.get("DIFY_API_BASE", "http://api:5001"))
    identity_secret = os.environ.get("BRIDGE_IDENTITY_SECRET", "")

    @app.exception_handler(Exception)
    async def _exception_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": safe_error_message(exc)})

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "component": "openclaw-bridge",
            "dify_api_base": os.environ.get("DIFY_API_BASE", "http://api:5001"),
        }

    @app.get("/openclaw-api/me")
    async def me(request: Request) -> dict[str, Any]:
        try:
            profile, workspaces = await dify.profile(request.headers), await dify.workspaces(request.headers)
            principal = derive_principal(identity_secret, profile, workspaces)
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail="login required") from exc
        except IdentityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"principal_id": principal.principal_id, "authenticated": True}

    @app.get("/openclaw-api/sessions")
    async def sessions() -> dict[str, Any]:
        raise HTTPException(status_code=501, detail="database adapter not wired in offline draft")

    @app.post("/openclaw-api/jobs")
    async def create_job() -> dict[str, Any]:
        raise HTTPException(status_code=501, detail="job queue adapter not wired in offline draft")

    return app


app = create_app()
