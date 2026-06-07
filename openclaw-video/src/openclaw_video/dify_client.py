from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from http.cookies import SimpleCookie
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
    "host",
    "x-csrf-token",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
    "x-real-ip",
    "x-xsrf-token",
}

HUAHUO_ACCESS_TOKEN_HEADER = "x-huahuo-access-token"
HUAHUO_APP_UUID_HEADER = "x-huahuo-app-uuid"
HUAHUO_REFRESH_TOKEN_HEADER = "x-huahuo-refresh-token"


@dataclass(frozen=True)
class DifyIdentityContext:
    profile: dict
    workspaces: object
    set_cookie_headers: tuple[str, ...] = ()
    refreshed: bool = False


def identity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return only the browser headers needed for Dify identity lookup.

    These headers may be sent to Dify API only. They must never be logged or
    forwarded to OpenClaw Gateway.
    """

    forwarded: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in FORWARDED_IDENTITY_HEADERS:
            forwarded[key] = value
    if not _header_value(forwarded, "authorization"):
        access_token = _dify_access_token_from_cookie(headers)
        if access_token:
            forwarded["Authorization"] = "Bearer " + access_token
    host = _header_value(headers, "host")
    if host:
        forwarded.setdefault("Origin", f"https://{host}")
        forwarded.setdefault("Referer", f"https://{host}/")
    return forwarded


def _safe_cookie_names(headers: Mapping[str, str]) -> list[str]:
    cookie = _header_value(headers, "cookie")
    names: list[str] = []
    for item in cookie.split(";"):
        name = item.split("=", 1)[0].strip()
        if name:
            names.append(name)
    return sorted(set(names))


def _cookie_value(headers: Mapping[str, str], name: str) -> str:
    cookie_header = _header_value(headers, "cookie")
    if not cookie_header:
        return ""
    parsed = SimpleCookie()
    try:
        parsed.load(cookie_header)
    except Exception:
        parsed = SimpleCookie()
    morsel = parsed.get(name)
    if morsel and morsel.value:
        return morsel.value
    for item in cookie_header.split(";"):
        key, sep, value = item.partition("=")
        if sep and key.strip() == name:
            return value.strip()
    return ""


def _dify_access_token_from_cookie(headers: Mapping[str, str]) -> str:
    for name in ("access_token", "__Host-access_token", "__Secure-access_token"):
        value = _cookie_value(headers, name)
        if value:
            return value
    return ""


def _cookie_dict(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    parsed = SimpleCookie()
    try:
        parsed.load(cookie_header)
    except Exception:
        parsed = SimpleCookie()
    for name, morsel in parsed.items():
        cookies[name] = morsel.value
    if cookies:
        return cookies
    for item in cookie_header.split(";"):
        key, sep, value = item.partition("=")
        if sep and key.strip():
            cookies[key.strip()] = value.strip()
    return cookies


def _set_cookie_names(set_cookie_headers: list[str] | tuple[str, ...]) -> list[str]:
    names: list[str] = []
    for header in set_cookie_headers:
        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except Exception:
            parsed = SimpleCookie()
        for name in parsed.keys():
            names.append(name)
    return sorted(set(names))


def _headers_with_set_cookie_values(headers: Mapping[str, str], set_cookie_headers: list[str] | tuple[str, ...]) -> dict[str, str]:
    refreshed = {str(key): str(value) for key, value in headers.items()}
    cookies = _cookie_dict(_header_value(headers, "cookie"))
    for header in set_cookie_headers:
        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except Exception:
            continue
        for name, morsel in parsed.items():
            if morsel.value:
                cookies[name] = morsel.value
    if cookies:
        refreshed["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
    csrf_token = cookies.get("csrf_token") or cookies.get("__Host-csrf_token") or cookies.get("__Secure-csrf_token")
    if csrf_token:
        refreshed["X-CSRF-Token"] = csrf_token
    return refreshed


def dify_identity_material_present(headers: Mapping[str, str]) -> bool:
    return bool(identity_headers(headers))


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


def huahuo_cookie_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return Huahuo cookie material for same-site identity lookup only."""

    cookie = _header_value(headers, "cookie").strip()
    return {"Cookie": cookie} if cookie else {}


def huahuo_identity_material_present(headers: Mapping[str, str]) -> bool:
    return bool(huahuo_identity_headers(headers) or huahuo_cookie_headers(headers))


def huahuo_front_request_headers(headers: Mapping[str, str], *, access_token: str | None = None) -> dict[str, str]:
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=UTF-8",
        "Cache-Control": "max-age=1000",
        "Origin": "https://www.huahuoai.com",
        "Referer": "https://www.huahuoai.com/?id=4",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        ),
    }
    request_headers.update(huahuo_cookie_headers(headers))
    request_headers.update(huahuo_identity_headers(headers, access_token=access_token))
    return request_headers


@dataclass(frozen=True)
class DifyClient:
    base_url: str
    timeout_seconds: float = 10.0
    transport: httpx.AsyncBaseTransport | None = None

    async def _get_json(self, path: str, headers: Mapping[str, str]) -> object:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.get(path, headers=identity_headers(headers))
            if response.status_code == 401:
                raise PermissionError("dify login required")
            response.raise_for_status()
            return response.json()

    async def _refresh_console_tokens(self, headers: Mapping[str, str]) -> tuple[str, ...]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.post("/console/api/refresh-token", headers=identity_headers(headers))
            if response.status_code in {401, 403}:
                raise PermissionError("dify refresh required")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("result") != "success":
                raise PermissionError("dify refresh failed")
            set_cookie_headers = tuple(response.headers.get_list("set-cookie"))
            if not set_cookie_headers:
                raise PermissionError("dify refresh did not return cookies")
            return set_cookie_headers

    async def resolve_identity(self, headers: Mapping[str, str]) -> DifyIdentityContext:
        try:
            profile = await self.profile(headers)
            workspaces = await self.workspaces(headers)
            return DifyIdentityContext(profile=profile, workspaces=workspaces)
        except PermissionError:
            set_cookie_headers = await self._refresh_console_tokens(headers)
            refreshed_headers = _headers_with_set_cookie_values(headers, set_cookie_headers)
            profile = await self.profile(refreshed_headers)
            workspaces = await self.workspaces(refreshed_headers)
            return DifyIdentityContext(
                profile=profile,
                workspaces=workspaces,
                set_cookie_headers=set_cookie_headers,
                refreshed=True,
            )

    async def safe_identity_probe(self, headers: Mapping[str, str]) -> dict[str, object]:
        result: dict[str, object] = {
            "provider": "dify",
            "identity_headers_present": dify_identity_material_present(headers),
            "cookie_names": _safe_cookie_names(headers),
            "authorization_present": bool(_header_value(headers, "authorization")),
            "authorization_generated_from_cookie": bool(
                not _header_value(headers, "authorization") and _dify_access_token_from_cookie(headers)
            ),
            "csrf_header_present": bool(_header_value(headers, "x-csrf-token") or _header_value(headers, "x-xsrf-token")),
            "profile_http_status": None,
            "profile_body_keys": [],
            "workspaces_http_status": None,
            "workspaces_body_keys": [],
            "refresh_attempted": False,
            "refresh_http_status": None,
            "refresh_set_cookie_names": [],
            "retry_profile_http_status": None,
            "retry_profile_body_keys": [],
            "retry_workspaces_http_status": None,
            "retry_workspaces_body_keys": [],
            "error_stage": None,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                profile_response = await client.get(
                    "/console/api/account/profile",
                    headers=identity_headers(headers),
                )
                result["profile_http_status"] = profile_response.status_code
                if profile_response.status_code not in {401, 403}:
                    profile_payload = profile_response.json()
                    if isinstance(profile_payload, dict):
                        result["profile_body_keys"] = sorted(str(key) for key in profile_payload.keys())
                workspaces_response = await client.get(
                    "/console/api/workspaces",
                    headers=identity_headers(headers),
                )
                result["workspaces_http_status"] = workspaces_response.status_code
                if workspaces_response.status_code not in {401, 403}:
                    workspaces_payload = workspaces_response.json()
                    if isinstance(workspaces_payload, dict):
                        result["workspaces_body_keys"] = sorted(str(key) for key in workspaces_payload.keys())
                if profile_response.status_code in {401, 403}:
                    result["refresh_attempted"] = True
                    refresh_response = await client.post(
                        "/console/api/refresh-token",
                        headers=identity_headers(headers),
                    )
                    result["refresh_http_status"] = refresh_response.status_code
                    if refresh_response.status_code in {401, 403}:
                        result["error_stage"] = "refresh_http"
                        return result
                    refresh_payload = refresh_response.json()
                    if not isinstance(refresh_payload, dict) or refresh_payload.get("result") != "success":
                        result["error_stage"] = "refresh_payload"
                        return result
                    set_cookie_headers = tuple(refresh_response.headers.get_list("set-cookie"))
                    result["refresh_set_cookie_names"] = _set_cookie_names(set_cookie_headers)
                    if not set_cookie_headers:
                        result["error_stage"] = "refresh_cookies"
                        return result
                    refreshed_headers = _headers_with_set_cookie_values(headers, set_cookie_headers)
                    retry_profile_response = await client.get(
                        "/console/api/account/profile",
                        headers=identity_headers(refreshed_headers),
                    )
                    result["retry_profile_http_status"] = retry_profile_response.status_code
                    if retry_profile_response.status_code not in {401, 403}:
                        retry_profile_payload = retry_profile_response.json()
                        if isinstance(retry_profile_payload, dict):
                            result["retry_profile_body_keys"] = sorted(str(key) for key in retry_profile_payload.keys())
                    retry_workspaces_response = await client.get(
                        "/console/api/workspaces",
                        headers=identity_headers(refreshed_headers),
                    )
                    result["retry_workspaces_http_status"] = retry_workspaces_response.status_code
                    if retry_workspaces_response.status_code not in {401, 403}:
                        retry_workspaces_payload = retry_workspaces_response.json()
                        if isinstance(retry_workspaces_payload, dict):
                            result["retry_workspaces_body_keys"] = sorted(
                                str(key) for key in retry_workspaces_payload.keys()
                            )
                return result
        except httpx.HTTPError:
            result["error_stage"] = "network"
            return result
        except ValueError:
            result["error_stage"] = "json"
            return result

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
            "identity_headers_present": huahuo_identity_material_present(headers),
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
