from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Iterable


class SessionOwnershipError(PermissionError):
    pass


class SessionNotFound(KeyError):
    pass


class MessageValidationError(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass
class BridgeSession:
    owner_principal_id: str
    title: str
    openclaw_routing_user: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)


@dataclass
class BridgeMessage:
    session_id: str
    owner_principal_id: str
    role: str
    content: str
    video_url: str | None = None
    job_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=now_utc)


class InMemorySessionStore:
    """Small deterministic session store for offline ACL tests.

    Production must replace this with the Bridge Postgres adapter.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, BridgeSession] = {}
        self._messages: dict[str, list[BridgeMessage]] = {}
        self._prefs: dict[str, dict] = {}
        self._lock = Lock()

    def create_session(
        self,
        owner_principal_id: str,
        title: str,
        openclaw_routing_user: str,
        *,
        session_id: str | None = None,
    ) -> BridgeSession:
        normalized_title = title.strip() or "OpenClaw session"
        session = BridgeSession(
            owner_principal_id=owner_principal_id,
            title=normalized_title[:120],
            openclaw_routing_user=openclaw_routing_user,
            id=session_id or str(uuid.uuid4()),
        )
        with self._lock:
            self._sessions[session.id] = session
            self._messages[session.id] = []
        return session

    def get_prefs(self, principal_id: str) -> dict:
        with self._lock:
            return dict(self._prefs.get(principal_id, {}))

    def put_prefs(self, principal_id: str, prefs: dict) -> dict:
        payload = dict(prefs) if isinstance(prefs, dict) else {}
        with self._lock:
            self._prefs[principal_id] = payload
            return dict(payload)

    def list_sessions(self, owner_principal_id: str) -> list[BridgeSession]:
        with self._lock:
            sessions = [
                session for session in self._sessions.values() if session.owner_principal_id == owner_principal_id
            ]
            return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def get_session(self, session_id: str, owner_principal_id: str | None = None) -> BridgeSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            if owner_principal_id is not None and session.owner_principal_id != owner_principal_id:
                raise SessionOwnershipError(session_id)
            return session

    def add_message(
        self,
        session_id: str,
        owner_principal_id: str,
        role: str,
        content: str,
        *,
        video_url: str | None = None,
        job_id: str | None = None,
    ) -> BridgeMessage:
        if role not in {"user", "assistant", "system", "tool"}:
            raise MessageValidationError("unsupported message role")
        if not content.strip():
            raise MessageValidationError("message content is required")
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            if session.owner_principal_id != owner_principal_id:
                raise SessionOwnershipError(session_id)
            message = BridgeMessage(
                session_id=session_id,
                owner_principal_id=owner_principal_id,
                role=role,
                content=content,
                video_url=video_url,
                job_id=job_id,
            )
            self._messages[session_id].append(message)
            session.updated_at = now_utc()
            return message

    def list_messages(self, session_id: str, owner_principal_id: str) -> list[BridgeMessage]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise SessionNotFound(session_id)
            if session.owner_principal_id != owner_principal_id:
                raise SessionOwnershipError(session_id)
            messages: Iterable[BridgeMessage] = self._messages.get(session_id, [])
            return sorted(messages, key=lambda item: item.created_at)

    def delete_messages_for_jobs(self, owner_principal_id: str, job_ids: Iterable[str]) -> int:
        targets = set(job_ids)
        if not targets:
            return 0
        deleted = 0
        with self._lock:
            for session_id, messages in list(self._messages.items()):
                session = self._sessions.get(session_id)
                if not session or session.owner_principal_id != owner_principal_id:
                    continue
                kept = [message for message in messages if message.job_id not in targets]
                deleted += len(messages) - len(kept)
                self._messages[session_id] = kept
        return deleted
