from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import time
from typing import Mapping
from urllib.parse import urlencode
import uuid

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("httpx is required for DifyClient") from exc


FORWARDED_IDENTITY_HEADERS = {
    "authorization",
    "cookie",
    "x-csrf-token",
    "x-xsrf-token",
}

HUAHUO_ACCESS_TOKEN_HEADER = "x-huahuo-access-token"


def identity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return only the browser headers needed for Dify identity lookup.

    These headers may be sent to Dify API only. They must never be logged or
    forwarded to OpenClaw Gateway.
    """

    forwarded: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in FORWARDED_IDENTITY_HEADERS:
            forwarded[key] = value
    return forwarded


def _header_value(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def huahuo_authorization_header(access_token: str, *, app_uuid: str | None = None, app_time_ms: int | None = None) -> str:
    """Return the Huahuo frontend Authorization header for an access token.

    The public Huahuo frontend derives a signed Bearer payload from the
    `Access-Token` localStorage value. Bridge accepts that local token only from
    the same-origin Lab page, builds the signed header server-side, and forwards
    only this Authorization header to Huahuo's user-info endpoint.
    """

    token = access_token.strip()
    if not token:
        return ""
    app_uuid = app_uuid or uuid.uuid4().hex
    app_time_ms = app_time_ms if app_time_ms is not None else int(time.time() * 1000)
    first = hashlib.md5(("WEB" + app_uuid).encode("utf-8")).hexdigest().upper()
    app_sign = hashlib.md5((first + str(app_time_ms)).encode("utf-8")).hexdigest().upper()
    payload = urlencode(
        {
            "appVersion": "1.0.1",
            "appType": "WEB",
            "appUuid": app_uuid,
            "appTime": str(app_time_ms),
            "appSign": app_sign,
            "token": token,
        }
    )
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return "Bearer " + encoded


def huahuo_identity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return only Huahuo frontend identity material for user lookup."""

    explicit = _header_value(headers, HUAHUO_ACCESS_TOKEN_HEADER)
    if explicit:
        authorization = huahuo_authorization_header(explicit)
        return {"Authorization": authorization} if authorization else {}
    authorization = _header_value(headers, "authorization")
    if authorization.startswith("Bearer "):
        return {"Authorization": authorization}
    return {}


@dataclass(frozen=True)
class DifyClient:
    base_url: str
    timeout_seconds: float = 10.0

    async def _get_json(self, path: str, headers: Mapping[str, str]) -> object:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.get(path, headers=identity_headers(headers))
            if response.status_code == 401:
                raise PermissionError("dify login required")
            response.raise_for_status()
            return response.json()

    async def profile(self, headers: Mapping[str, str]) -> dict:
        data = await self._get_json("/console/api/account/profile", headers)
        if not isinstance(data, dict):
            raise ValueError("Dify profile response must be a JSON object")
        return data

    async def workspaces(self, headers: Mapping[str, str]) -> object:
        return await self._get_json("/console/api/workspaces", headers)


@dataclass(frozen=True)
class HuahuoFrontClient:
    base_url: str
    tenant_id: str = "huahuo-front"
    timeout_seconds: float = 10.0

    async def _get_json(self, path: str, headers: Mapping[str, str]) -> object:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.get(path, headers=huahuo_identity_headers(headers))
            if response.status_code in {401, 403}:
                raise PermissionError("huahuo login required")
            response.raise_for_status()
            return response.json()

    async def profile(self, headers: Mapping[str, str]) -> dict:
        payload = await self._get_json("/api/front/user/queryUserInfo", headers)
        if not isinstance(payload, dict):
            raise ValueError("Huahuo user-info response must be a JSON object")
        if payload.get("status") != 1:
            raise PermissionError("huahuo login required")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Huahuo user-info data must be a JSON object")
        account_id = data.get("id") or data.get("userId") or data.get("loginName") or data.get("mobile") or data.get("email")
        if account_id in (None, ""):
            raise ValueError("Huahuo user-info response did not contain a user id")
        return {"id": f"huahuo:{account_id}"}

    async def workspaces(self, headers: Mapping[str, str]) -> object:
        return {"data": [{"id": self.tenant_id, "current": True}]}
