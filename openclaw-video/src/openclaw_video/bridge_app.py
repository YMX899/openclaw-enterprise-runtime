from __future__ import annotations

import os
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
except ImportError as exc:  # pragma: no cover - import checked in container image
    raise RuntimeError("fastapi is required for openclaw-bridge") from exc

from .redaction import safe_error_message


def create_app() -> FastAPI:
    app = FastAPI(title="OpenClaw Dify Bridge", version="0.1.0")

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
    async def me() -> dict[str, Any]:
        raise HTTPException(status_code=501, detail="Dify profile/workspace adapter not wired in offline draft")

    @app.get("/openclaw-api/sessions")
    async def sessions() -> dict[str, Any]:
        raise HTTPException(status_code=501, detail="database adapter not wired in offline draft")

    @app.post("/openclaw-api/jobs")
    async def create_job() -> dict[str, Any]:
        raise HTTPException(status_code=501, detail="job queue adapter not wired in offline draft")

    return app


app = create_app()

