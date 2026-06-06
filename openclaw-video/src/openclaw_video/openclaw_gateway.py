from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

try:
    import websockets
except ImportError:  # pragma: no cover - dependency checked in container image
    websockets = None

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
except ImportError:  # pragma: no cover - dependency checked in container image
    serialization = None
    ed25519 = None


OPENCLAW_PROTOCOL_VERSION = 3
OPENCLAW_GATEWAY_CLIENT_ID = "gateway-client"
OPENCLAW_GATEWAY_CLIENT_MODE = "backend"
OPENCLAW_GATEWAY_SCOPES = ("operator.read", "operator.write")
OPENCLAW_GATEWAY_CAPS = ()
OPENCLAW_GATEWAY_USER_AGENT = "openclaw-video-bridge/0.1"


class GatewayError(RuntimeError):
    pass


class GatewayProtocolError(GatewayError):
    pass


@dataclass(frozen=True)
class GatewayChatRequest:
    routing_user: str
    session_id: str
    message_id: str
    content: str
    history: tuple[dict[str, str], ...]

    @property
    def openclaw_session_key(self) -> str:
        return f"agent:main:{self.routing_user}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "routing_user": self.routing_user,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "content": self.content,
            "history": list(self.history),
            "openclaw_session_key": self.openclaw_session_key,
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


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _normalize_device_metadata(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[A-Z]", lambda match: chr(ord(match.group(0)) + 32), value.strip())


@dataclass(frozen=True)
class OpenClawDeviceIdentity:
    private_key_pem: str
    public_key_raw_base64url: str
    device_id: str

    @classmethod
    def from_private_key_pem(cls, private_key_pem: str) -> "OpenClawDeviceIdentity":
        if serialization is None or ed25519 is None:
            raise GatewayNotConfigured("cryptography is required for OpenClaw Gateway device signing")
        key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            raise GatewayError("OpenClaw Gateway device key must be an Ed25519 private key")
        public_key = key.public_key()
        public_raw = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return cls(
            private_key_pem=private_key_pem,
            public_key_raw_base64url=_base64url(public_raw),
            device_id=hashlib.sha256(public_raw).hexdigest(),
        )

    @classmethod
    def from_file(cls, path: str) -> "OpenClawDeviceIdentity":
        if not path:
            raise GatewayNotConfigured("OpenClaw Gateway device key path is required")
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_private_key_pem(handle.read())

    def sign(self, payload: str) -> str:
        if serialization is None or ed25519 is None:
            raise GatewayNotConfigured("cryptography is required for OpenClaw Gateway device signing")
        key = serialization.load_pem_private_key(self.private_key_pem.encode("utf-8"), password=None)
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            raise GatewayError("OpenClaw Gateway device key must be an Ed25519 private key")
        return _base64url(key.sign(payload.encode("utf-8")))


def build_device_auth_payload_v3(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: tuple[str, ...],
    signed_at_ms: int,
    token: str,
    nonce: str,
    platform: str,
    device_family: str,
) -> str:
    return "|".join(
        [
            "v3",
            device_id,
            client_id,
            client_mode,
            role,
            ",".join(scopes),
            str(signed_at_ms),
            token,
            nonce,
            _normalize_device_metadata(platform),
            _normalize_device_metadata(device_family),
        ]
    )


@dataclass(frozen=True)
class OpenClawGatewayWsClient:
    url: str
    token: str
    device_identity: OpenClawDeviceIdentity
    timeout_seconds: float = 30.0
    client_version: str = "openclaw-video-bridge"
    platform: str = "node"
    device_family: str = "Bridge"
    scopes: tuple[str, ...] = field(default_factory=lambda: OPENCLAW_GATEWAY_SCOPES)

    @classmethod
    def from_environment(cls) -> "OpenClawGatewayWsClient | DisabledGatewayClient":
        url = os.environ.get("OPENCLAW_GATEWAY_URL", "").strip()
        token = _read_secret_from_env_or_file("OPENCLAW_GATEWAY_TOKEN", "OPENCLAW_GATEWAY_TOKEN_FILE")
        device_key_path = os.environ.get("OPENCLAW_GATEWAY_DEVICE_KEY_FILE", "").strip()
        if not url or not token or not device_key_path:
            return DisabledGatewayClient()
        return cls(url=url, token=token, device_identity=OpenClawDeviceIdentity.from_file(device_key_path))

    def connect_params(self, nonce: str | None = None, signed_at_ms: int | None = None) -> dict[str, Any]:
        if not self.token:
            raise GatewayNotConfigured("OpenClaw Gateway token is required")
        nonce = nonce or str(uuid.uuid4())
        signed_at_ms = signed_at_ms or int(time.time() * 1000)
        signature_payload = build_device_auth_payload_v3(
            device_id=self.device_identity.device_id,
            client_id=OPENCLAW_GATEWAY_CLIENT_ID,
            client_mode=OPENCLAW_GATEWAY_CLIENT_MODE,
            role="operator",
            scopes=tuple(self.scopes),
            signed_at_ms=signed_at_ms,
            token=self.token,
            nonce=nonce,
            platform=self.platform,
            device_family=self.device_family,
        )
        return {
            "minProtocol": OPENCLAW_PROTOCOL_VERSION,
            "maxProtocol": OPENCLAW_PROTOCOL_VERSION,
            "client": {
                "id": OPENCLAW_GATEWAY_CLIENT_ID,
                "version": self.client_version,
                "platform": self.platform,
                "mode": OPENCLAW_GATEWAY_CLIENT_MODE,
                "deviceFamily": self.device_family,
                "instanceId": str(uuid.uuid4()),
            },
            "role": "operator",
            "scopes": list(self.scopes),
            "caps": list(OPENCLAW_GATEWAY_CAPS),
            "commands": [],
            "permissions": {},
            "auth": {"token": self.token},
            "locale": "zh-CN",
            "userAgent": OPENCLAW_GATEWAY_USER_AGENT,
            "device": {
                "id": self.device_identity.device_id,
                "publicKey": self.device_identity.public_key_raw_base64url,
                "signature": self.device_identity.sign(signature_payload),
                "signedAt": signed_at_ms,
                "nonce": nonce,
            },
        }

    def chat_send_params(self, request: GatewayChatRequest, *, idempotency_key: str | None = None) -> dict[str, Any]:
        return {
            "sessionKey": request.openclaw_session_key,
            "message": request.content,
            "idempotencyKey": idempotency_key or request.message_id,
            "deliver": False,
            "timeoutMs": int(self.timeout_seconds * 1000),
        }

    async def chat(self, request: GatewayChatRequest) -> GatewayChatResult:
        if websockets is None:
            raise GatewayNotConfigured("websockets is required for OpenClaw Gateway WS adapter")
        async with websockets.connect(self.url, open_timeout=self.timeout_seconds) as websocket:
            challenge = await self._wait_for_challenge(websocket)
            await self._request(websocket, "connect", self.connect_params(nonce=challenge.get("nonce")))
            ack = await self._request(websocket, "chat.send", self.chat_send_params(request))
            payload = _assert_ok_payload(ack, "chat.send")
            run_id = payload.get("runId")
            if not isinstance(run_id, str) or not run_id:
                raise GatewayProtocolError("OpenClaw chat.send did not return runId")
            terminal = await self._wait_for_terminal_chat_event(websocket, run_id)
            content = _extract_chat_event_content(terminal)
            return GatewayChatResult(content=content, raw={"ack": ack, "terminal": terminal})

    async def _wait_for_challenge(self, websocket: Any) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            frame = await self._recv_json(websocket)
            if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
                payload = frame.get("payload")
                if isinstance(payload, dict):
                    return payload
        raise GatewayProtocolError("OpenClaw Gateway did not send connect.challenge")

    async def _request(self, websocket: Any, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = f"bridge-{uuid.uuid4()}"
        await websocket.send(json.dumps({"type": "req", "id": request_id, "method": method, "params": params}))
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            frame = await self._recv_json(websocket)
            if frame.get("type") == "res" and frame.get("id") == request_id:
                if frame.get("ok") is False:
                    raise GatewayError(_gateway_error_message(frame))
                return frame
        raise GatewayProtocolError(f"OpenClaw Gateway method timed out: {method}")

    async def _recv_json(self, websocket: Any) -> dict[str, Any]:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise GatewayProtocolError("OpenClaw Gateway receive timed out") from exc
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise GatewayProtocolError("OpenClaw Gateway frame must be an object")
        return data

    async def _wait_for_terminal_chat_event(self, websocket: Any, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            frame = await self._recv_json(websocket)
            if frame.get("type") != "event" or frame.get("event") != "chat":
                continue
            payload = frame.get("payload")
            if not isinstance(payload, dict) or payload.get("runId") != run_id:
                continue
            state = payload.get("state")
            if state in {"final", "error", "aborted"}:
                return frame
        raise GatewayProtocolError("OpenClaw chat terminal event timed out")


def _read_secret_from_env_or_file(value_name: str, file_name: str) -> str:
    file_path = os.environ.get(file_name, "").strip()
    if file_path:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    return os.environ.get(value_name, "").strip()


def _assert_ok_payload(frame: dict[str, Any], method: str) -> dict[str, Any]:
    if frame.get("ok") is not True:
        raise GatewayError(_gateway_error_message(frame) or f"OpenClaw Gateway method failed: {method}")
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        raise GatewayProtocolError(f"OpenClaw Gateway {method} payload must be an object")
    return payload


def _gateway_error_message(frame: dict[str, Any]) -> str:
    error = frame.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message
        code = error.get("code")
        if isinstance(code, str) and code.strip():
            return code
    return "OpenClaw Gateway request failed"


def _extract_chat_event_content(frame: dict[str, Any]) -> str:
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        raise GatewayProtocolError("OpenClaw chat event payload must be an object")
    if payload.get("state") == "error":
        raise GatewayError(str(payload.get("errorMessage") or "OpenClaw chat failed"))
    message = payload.get("message")
    if not isinstance(message, dict):
        raise GatewayProtocolError("OpenClaw final chat event missing message")
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "\n".join(part.strip() for part in parts if part.strip())
    else:
        text = ""
    if not text:
        raise GatewayProtocolError("OpenClaw final chat event did not contain text")
    if "Agent failed before reply" in text or "Auth store:" in text:
        raise GatewayError("OpenClaw agent failed before reply")
    return text
