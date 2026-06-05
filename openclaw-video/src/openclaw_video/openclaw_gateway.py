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
class GatewayChatRequest:
    routing_user: str
    session_id: str
    message_id: str
    content: str
    history: tuple[dict[str, str], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "routing_user": self.routing_user,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "content": self.content,
            "history": list(self.history),
        }


@dataclass(frozen=True)
class GatewayChatResult:
    content: str
    raw: dict[str, Any]


class GatewayNotConfigured(GatewayError):
    pass


class DisabledGatewayClient:
    async def chat(self, request: GatewayChatRequest) -> GatewayChatResult:
        raise GatewayNotConfigured("Gateway chat adapter is not configured")


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

    async def chat(self, request: GatewayChatRequest) -> GatewayChatResult:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.post("/channels/dify-web/chat", headers=self._headers(), json=request.to_payload())
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise GatewayError("Gateway chat response must be an object")
            content = data.get("content") or data.get("message") or data.get("text")
            if not isinstance(content, str) or not content.strip():
                raise GatewayError("Gateway chat response must contain content")
            return GatewayChatResult(content=content, raw=data)
