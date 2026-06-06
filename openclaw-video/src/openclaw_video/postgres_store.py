from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .job_state import JobStatus
from .job_store import JobLeaseError, JobNotFound, JobOwnershipError, VideoJob, VideoResult
from .session_store import (
    BridgeMessage,
    BridgeSession,
    MessageValidationError,
    SessionNotFound,
    SessionOwnershipError,
)

try:  # pragma: no cover - exercised in the production image/venv
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - keeps system-python unit tests importable
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]


ConnectionFactory = Callable[[], Any]


class PostgresDependencyError(RuntimeError):
    pass


def _normalize_title(title: str) -> str:
    return (title.strip() or "OpenClaw session")[:120]


def _row_to_session(row: dict[str, Any]) -> BridgeSession:
    return BridgeSession(
        id=str(row["id"]),
        owner_principal_id=row["owner_principal_id"],
        title=row["title"],
        openclaw_routing_user=row["openclaw_routing_user"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: dict[str, Any]) -> BridgeMessage:
    return BridgeMessage(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        owner_principal_id=row["owner_principal_id"],
        role=row["role"],
        content=row["content"],
        video_url=row["video_url"],
        job_id=str(row["job_id"]) if row["job_id"] else None,
        created_at=row["created_at"],
    )


def _row_to_job(row: dict[str, Any]) -> VideoJob:
    return VideoJob(
        job_id=str(row["job_id"]),
        owner_principal_id=row["owner_principal_id"],
        bridge_session_id=str(row["bridge_session_id"]),
        video_url_canonical=row["video_url_canonical"],
        status=JobStatus(row["status"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        attempt_count=row["attempt_count"],
        error_code=row["error_code"],
        result_schema_version=row["result_schema_version"],
        result_location=row["result_location"],
        idempotency_key=row["idempotency_key"],
        worker_id=row["worker_id"],
        heartbeat_at=row["heartbeat_at"],
        lease_expires_at=row["lease_expires_at"],
    )


def _row_to_result(row: dict[str, Any]) -> VideoResult:
    return VideoResult(
        job_id=str(row["job_id"]),
        owner_principal_id=row["owner_principal_id"],
        schema_version=row["schema_version"],
        result=row["result"],
        created_at=row["created_at"],
    )


class _BasePostgresStore:
    def __init__(self, conninfo: str | None = None, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.conninfo = conninfo
        self.connection_factory = connection_factory
        if not conninfo and not connection_factory:
            raise ValueError("conninfo or connection_factory is required")

    def _connect(self) -> Any:
        if self.connection_factory:
            return self.connection_factory()
        if psycopg is None or dict_row is None:
            raise PostgresDependencyError("psycopg[binary] is required for Postgres stores")
        return psycopg.connect(self.conninfo, row_factory=dict_row)

    def ensure_user(self, principal_id: str, tenant_hash: str, account_hash: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bridge_users (principal_id, tenant_hash, account_hash)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (principal_id) DO UPDATE
                    SET tenant_hash = EXCLUDED.tenant_hash,
                        account_hash = EXCLUDED.account_hash,
                        last_seen_at = now()
                    """,
                    (principal_id, tenant_hash, account_hash),
                )


class PostgresSessionStore(_BasePostgresStore):
    def create_session(
        self,
        owner_principal_id: str,
        title: str,
        openclaw_routing_user: str,
        *,
        session_id: str | None = None,
    ) -> BridgeSession:
        normalized_title = _normalize_title(title)
        with self._connect() as conn:
            with conn.cursor() as cur:
                if session_id:
                    cur.execute(
                        """
                        INSERT INTO bridge_sessions (id, owner_principal_id, title, openclaw_routing_user)
                        VALUES (%s, %s, %s, %s)
                        RETURNING *
                        """,
                        (session_id, owner_principal_id, normalized_title, openclaw_routing_user),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO bridge_sessions (owner_principal_id, title, openclaw_routing_user)
                        VALUES (%s, %s, %s)
                        RETURNING *
                        """,
                        (owner_principal_id, normalized_title, openclaw_routing_user),
                    )
                return _row_to_session(cur.fetchone())

    def list_sessions(self, owner_principal_id: str) -> list[BridgeSession]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM bridge_sessions
                    WHERE owner_principal_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (owner_principal_id,),
                )
                return [_row_to_session(row) for row in cur.fetchall()]

    def get_session(self, session_id: str, owner_principal_id: str | None = None) -> BridgeSession:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM bridge_sessions WHERE id = %s", (session_id,))
                row = cur.fetchone()
        if not row:
            raise SessionNotFound(session_id)
        session = _row_to_session(row)
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner_principal_id FROM bridge_sessions WHERE id = %s", (session_id,))
                owner_row = cur.fetchone()
                if not owner_row:
                    raise SessionNotFound(session_id)
                if owner_row["owner_principal_id"] != owner_principal_id:
                    raise SessionOwnershipError(session_id)
                cur.execute(
                    """
                    INSERT INTO bridge_messages
                      (session_id, owner_principal_id, role, content, video_url, job_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (session_id, owner_principal_id, role, content, video_url, job_id),
                )
                message = _row_to_message(cur.fetchone())
                cur.execute("UPDATE bridge_sessions SET updated_at = now() WHERE id = %s", (session_id,))
                return message

    def list_messages(self, session_id: str, owner_principal_id: str) -> list[BridgeMessage]:
        self.get_session(session_id, owner_principal_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM bridge_messages
                    WHERE session_id = %s AND owner_principal_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id, owner_principal_id),
                )
                return [_row_to_message(row) for row in cur.fetchall()]


class PostgresJobStore(_BasePostgresStore):
    def create_job(
        self,
        owner_principal_id: str,
        bridge_session_id: str,
        video_url_canonical: str,
        *,
        idempotency_key: str | None = None,
    ) -> VideoJob:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if idempotency_key:
                    cur.execute(
                        """
                        INSERT INTO video_jobs
                          (owner_principal_id, bridge_session_id, video_url_canonical, idempotency_key, status)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (owner_principal_id, bridge_session_id, idempotency_key)
                        WHERE idempotency_key IS NOT NULL
                        DO UPDATE SET idempotency_key = video_jobs.idempotency_key
                        RETURNING *
                        """,
                        (
                            owner_principal_id,
                            bridge_session_id,
                            video_url_canonical,
                            idempotency_key,
                            JobStatus.QUEUED.value,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO video_jobs
                          (owner_principal_id, bridge_session_id, video_url_canonical, status)
                        VALUES (%s, %s, %s, %s)
                        RETURNING *
                        """,
                        (owner_principal_id, bridge_session_id, video_url_canonical, JobStatus.QUEUED.value),
                    )
                return _row_to_job(cur.fetchone())

    def get_job(self, job_id: str, owner_principal_id: str | None = None) -> VideoJob:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM video_jobs WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
        if not row:
            raise JobNotFound(job_id)
        job = _row_to_job(row)
        if owner_principal_id is not None and job.owner_principal_id != owner_principal_id:
            raise JobOwnershipError(job_id)
        return job

    def get_job_by_idempotency(
        self,
        owner_principal_id: str,
        bridge_session_id: str,
        idempotency_key: str,
    ) -> VideoJob:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM video_jobs
                    WHERE owner_principal_id = %s
                      AND bridge_session_id = %s
                      AND idempotency_key = %s
                    """,
                    (owner_principal_id, bridge_session_id, idempotency_key),
                )
                row = cur.fetchone()
        if not row:
            raise JobNotFound(idempotency_key)
        return _row_to_job(row)

    def count_active_jobs(self, owner_principal_id: str) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) AS active_count
                    FROM video_jobs
                    WHERE owner_principal_id = %s
                      AND status IN ('queued', 'running')
                    """,
                    (owner_principal_id,),
                )
                row = cur.fetchone()
        if not row:
            return 0
        return int(row["active_count"])

    def claim_next(self, worker_id: str = "worker", lease_seconds: int = 900) -> VideoJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH next_job AS (
                      SELECT job_id
                      FROM video_jobs
                      WHERE status = 'queued'
                      ORDER BY created_at ASC
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1
                    )
                    UPDATE video_jobs AS j
                    SET status = 'running',
                        started_at = COALESCE(j.started_at, now()),
                        attempt_count = j.attempt_count + 1,
                        worker_id = %s,
                        heartbeat_at = now(),
                        lease_expires_at = now() + make_interval(secs => %s)
                    FROM next_job
                    WHERE j.job_id = next_job.job_id
                    RETURNING j.*
                    """,
                    (worker_id, lease_seconds),
                )
                row = cur.fetchone()
        return _row_to_job(row) if row else None

    def heartbeat_job(self, job_id: str, worker_id: str, lease_seconds: int = 900) -> VideoJob:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET heartbeat_at = now(),
                        lease_expires_at = now() + make_interval(secs => %s)
                    WHERE job_id = %s
                      AND worker_id = %s
                      AND status = 'running'
                    RETURNING *
                    """,
                    (lease_seconds, job_id, worker_id),
                )
                row = cur.fetchone()
        if not row:
            raise JobLeaseError(job_id)
        return _row_to_job(row)

    def recover_expired_leases(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET status = 'queued',
                        worker_id = NULL,
                        heartbeat_at = NULL,
                        lease_expires_at = NULL
                    WHERE status = 'running'
                      AND lease_expires_at < now()
                    RETURNING job_id
                    """
                )
                return len(cur.fetchall())

    def complete_job(
        self,
        job_id: str,
        result: dict,
        schema_version: str,
        *,
        worker_id: str | None = None,
    ) -> VideoJob:
        if Jsonb is None:
            raise PostgresDependencyError("psycopg Jsonb adapter is required for Postgres stores")
        result_location = f"postgres://video_results/{job_id}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                if worker_id is None:
                    cur.execute(
                        """
                        UPDATE video_jobs
                        SET status = 'succeeded',
                            finished_at = now(),
                            error_code = NULL,
                            result_schema_version = %s,
                            result_location = %s,
                            worker_id = NULL,
                            heartbeat_at = NULL,
                            lease_expires_at = NULL
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (schema_version, result_location, job_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE video_jobs
                        SET status = 'succeeded',
                            finished_at = now(),
                            error_code = NULL,
                            result_schema_version = %s,
                            result_location = %s,
                            worker_id = NULL,
                            heartbeat_at = NULL,
                            lease_expires_at = NULL
                        WHERE job_id = %s
                          AND worker_id = %s
                          AND status = 'running'
                        RETURNING *
                        """,
                        (schema_version, result_location, job_id, worker_id),
                    )
                row = cur.fetchone()
                if not row:
                    if worker_id is None:
                        raise JobNotFound(job_id)
                    raise JobLeaseError(job_id)
                job = _row_to_job(row)
                cur.execute(
                    """
                    INSERT INTO video_results (job_id, owner_principal_id, schema_version, result)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (job_id) DO UPDATE
                    SET schema_version = EXCLUDED.schema_version,
                        result = EXCLUDED.result,
                        created_at = now()
                    """,
                    (job_id, job.owner_principal_id, schema_version, Jsonb(result)),
                )
                return job

    def fail_job(
        self,
        job_id: str,
        error_code: str,
        timed_out: bool = False,
        *,
        worker_id: str | None = None,
    ) -> VideoJob:
        status = JobStatus.TIMED_OUT if timed_out else JobStatus.FAILED
        with self._connect() as conn:
            with conn.cursor() as cur:
                if worker_id is None:
                    cur.execute(
                        """
                        UPDATE video_jobs
                        SET status = %s,
                            finished_at = now(),
                            error_code = %s,
                            worker_id = NULL,
                            heartbeat_at = NULL,
                            lease_expires_at = NULL
                        WHERE job_id = %s
                        RETURNING *
                        """,
                        (status.value, error_code, job_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE video_jobs
                        SET status = %s,
                            finished_at = now(),
                            error_code = %s,
                            worker_id = NULL,
                            heartbeat_at = NULL,
                            lease_expires_at = NULL
                        WHERE job_id = %s
                          AND worker_id = %s
                          AND status = 'running'
                        RETURNING *
                        """,
                        (status.value, error_code, job_id, worker_id),
                    )
                row = cur.fetchone()
        if not row:
            if worker_id is None:
                raise JobNotFound(job_id)
            raise JobLeaseError(job_id)
        return _row_to_job(row)

    def cancel_job(self, job_id: str, owner_principal_id: str) -> VideoJob:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner_principal_id FROM video_jobs WHERE job_id = %s", (job_id,))
                owner_row = cur.fetchone()
                if not owner_row:
                    raise JobNotFound(job_id)
                if owner_row["owner_principal_id"] != owner_principal_id:
                    raise JobOwnershipError(job_id)
                cur.execute(
                    """
                    UPDATE video_jobs
                    SET status = 'cancelled',
                        finished_at = now(),
                        worker_id = NULL,
                        heartbeat_at = NULL,
                        lease_expires_at = NULL
                    WHERE job_id = %s
                    RETURNING *
                    """,
                    (job_id,),
                )
                return _row_to_job(cur.fetchone())

    def get_result(self, job_id: str, owner_principal_id: str | None = None) -> VideoResult:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM video_results WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
        if not row:
            raise JobNotFound(job_id)
        result = _row_to_result(row)
        if owner_principal_id is not None and result.owner_principal_id != owner_principal_id:
            raise JobOwnershipError(job_id)
        return result
