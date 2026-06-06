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
HUAHUO_APP_UUID_HEADER = "x-huahuo-app-uuid"
HUAHUO_REFRESH_TOKEN_HEADER = "x-huahuo-refresh-token"


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


def huahuo_identity_headers(headers: Mapping[str, str], *, access_token: str | None = None) -> dict[str, str]:
    """Return only Huahuo frontend identity material for user lookup."""

    explicit = access_token or _header_value(headers, HUAHUO_ACCESS_TOKEN_HEADER)
    if explicit:
        app_uuid = _header_value(headers, HUAHUO_APP_UUID_HEADER)
        authorization = huahuo_authorization_header(explicit, app_uuid=app_uuid or None)
        return {"Authorization": authorization} if authorization else {}
    authorization = _header_value(headers, "authorization")
    if authorization.startswith("Bearer "):
        return {"Authorization": authorization}
    return {}


def huahuo_front_request_headers(headers: Mapping[str, str], *, access_token: str | None = None) -> dict[str, str]:
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=UTF-8",
        "Cache-Control": "max-age=1000",
        "Origin": "https://www.huahuoai.com",
        "Referer": "https://www.huahuoai.com/ai/?id=4",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        ),
    }
    request_headers.update(huahuo_identity_headers(headers, access_token=access_token))
    return request_headers


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
    transport: httpx.AsyncBaseTransport | None = None

    @staticmethod
    def _payload_requires_refresh(payload: object) -> bool:
        if not isinstance(payload, dict) or "status" not in payload:
            return False
        status = payload.get("status")
        return status not in (1, "normal")

    async def _get_json(self, path: str, headers: Mapping[str, str]) -> object:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.get(path, headers=huahuo_front_request_headers(headers))
            payload: object | None = None
            if response.status_code not in {401, 403}:
                response.raise_for_status()
                payload = response.json()
            if response.status_code in {401, 403} or self._payload_requires_refresh(payload):
                refreshed_access_token = await self._refresh_access_token(client, headers)
                if refreshed_access_token:
                    response = await client.get(
                        path,
                        headers=huahuo_front_request_headers(headers, access_token=refreshed_access_token),
                    )
            if response.status_code in {401, 403}:
                raise PermissionError("huahuo login required")
            response.raise_for_status()
            return response.json()

    async def _refresh_access_token(self, client: httpx.AsyncClient, headers: Mapping[str, str]) -> str:
        refresh_token = _header_value(headers, HUAHUO_REFRESH_TOKEN_HEADER).strip()
        if not refresh_token:
            return ""
        response = await client.post(
            "/api/updateToken",
            headers=huahuo_front_request_headers(headers),
            json={"refreshToken": refresh_token},
        )
        if response.status_code in {401, 403}:
            return ""
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != 1:
            return ""
        data = payload.get("data")
        if not isinstance(data, dict):
            return ""
        access_token = data.get("accessToken")
        return str(access_token) if access_token else ""

    async def safe_identity_probe(self, headers: Mapping[str, str]) -> dict[str, object]:
        result: dict[str, object] = {
            "provider": "huahuo_front",
            "identity_headers_present": bool(huahuo_identity_headers(headers)),
            "profile_http_status": None,
            "profile_business_status": None,
            "profile_data_keys": [],
            "refresh_attempted": False,
            "refresh_http_status": None,
            "refresh_business_status": None,
            "refresh_issued_access_token": False,
            "retry_http_status": None,
            "retry_business_status": None,
            "retry_data_keys": [],
            "error_stage": None,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get("/api/front/user/queryUserInfo", headers=huahuo_front_request_headers(headers))
                result["profile_http_status"] = response.status_code
                payload: object | None = None
                if response.status_code not in {401, 403}:
                    payload = response.json()
                    if isinstance(payload, dict):
                        result["profile_business_status"] = payload.get("status")
                        data = payload.get("data")
                        if isinstance(data, dict):
                            result["profile_data_keys"] = sorted(str(key) for key in data.keys())
                if response.status_code in {401, 403} or self._payload_requires_refresh(payload):
                    result["refresh_attempted"] = True
                    refresh_token = _header_value(headers, HUAHUO_REFRESH_TOKEN_HEADER).strip()
                    if not refresh_token:
                        result["error_stage"] = "refresh_missing"
                        return result
                    refresh_response = await client.post(
                        "/api/updateToken",
                        headers=huahuo_front_request_headers(headers),
                        json={"refreshToken": refresh_token},
                    )
                    result["refresh_http_status"] = refresh_response.status_code
                    if refresh_response.status_code in {401, 403}:
                        result["error_stage"] = "refresh_http"
                        return result
                    refresh_payload = refresh_response.json()
                    if isinstance(refresh_payload, dict):
                        result["refresh_business_status"] = refresh_payload.get("status")
                        data = refresh_payload.get("data")
                        access_token = data.get("accessToken") if isinstance(data, dict) else None
                        result["refresh_issued_access_token"] = bool(access_token)
                    else:
                        access_token = None
                    if not access_token:
                        result["error_stage"] = "refresh_payload"
                        return result
                    retry_response = await client.get(
                        "/api/front/user/queryUserInfo",
                        headers=huahuo_front_request_headers(headers, access_token=str(access_token)),
                    )
                    result["retry_http_status"] = retry_response.status_code
                    if retry_response.status_code not in {401, 403}:
                        retry_payload = retry_response.json()
                        if isinstance(retry_payload, dict):
                            result["retry_business_status"] = retry_payload.get("status")
                            data = retry_payload.get("data")
                            if isinstance(data, dict):
                                result["retry_data_keys"] = sorted(str(key) for key in data.keys())
                    if retry_response.status_code in {401, 403}:
                        result["error_stage"] = "retry_http"
                return result
        except httpx.HTTPError:
            result["error_stage"] = "network"
            return result
        except ValueError:
            result["error_stage"] = "json"
            return result

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
