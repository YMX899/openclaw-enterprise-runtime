from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("httpx is required for OpenClawGatewayClient") from exc


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenClawGatewayClient:
    base_url: str
    token: str
    timeout_seconds: float = 30.0

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise GatewayError("OpenClaw Gateway token is required")
        return {"Authorization": f"Bearer {self.token}"}

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.get("/health", headers=self._headers())
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise GatewayError("Gateway health response must be an object")
            return data

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.post("/channels/dify-web/chat", headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise GatewayError("Gateway chat response must be an object")
            return data

