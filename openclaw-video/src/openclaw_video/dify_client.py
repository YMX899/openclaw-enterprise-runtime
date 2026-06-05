from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

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

