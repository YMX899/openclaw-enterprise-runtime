from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import uuid4

from .job_state import JobStatus
from .job_store import JobLeaseError, JobNotFound, JobOwnershipError, RetentionCleanupResult, VideoJob, VideoResult
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
        job_spec=row.get("job_spec") if isinstance(row.get("job_spec"), dict) else {},
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

    def get_prefs(self, principal_id: str) -> dict:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT prefs FROM bridge_user_prefs WHERE principal_id = %s",
                    (principal_id,),
                )
                row = cur.fetchone()
        if not row:
            return {}
        prefs = row.get("prefs")
        return prefs if isinstance(prefs, dict) else {}

    def put_prefs(self, principal_id: str, prefs: dict) -> dict:
        payload = prefs if isinstance(prefs, dict) else {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bridge_user_prefs (principal_id, prefs, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (principal_id) DO UPDATE
                    SET prefs = EXCLUDED.prefs, updated_at = now()
                    RETURNING prefs
                    """,
                    (principal_id, Jsonb(payload)),
                )
                row = cur.fetchone()
        if row and isinstance(row.get("prefs"), dict):
            return row["prefs"]
        return payload


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

    def delete_messages_for_jobs(self, owner_principal_id: str, job_ids: list[str] | tuple[str, ...]) -> int:
        if not job_ids:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM bridge_messages
                    WHERE owner_principal_id = %s
                      AND job_id = ANY(%s::uuid[])
                    RETURNING id
                    """,
                    (owner_principal_id, list(job_ids)),
                )
                return len(cur.fetchall())


class PostgresJobStore(_BasePostgresStore):
    def heartbeat_worker(self, worker_id: str, *, state: str = "idle", current_job_id: str | None = None) -> None:
        if state not in {"idle", "running", "draining", "stopped"}:
            raise ValueError("unsupported worker state")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO video_worker_registry
                      (worker_id, state, current_job_id, last_seen_at, updated_at)
                    VALUES (%s, %s, %s, now(), now())
                    ON CONFLICT (worker_id) DO UPDATE
                    SET state = CASE
                          WHEN video_worker_registry.state = 'draining' AND EXCLUDED.state <> 'stopped'
                            THEN 'draining'
                          ELSE EXCLUDED.state
                        END,
                        current_job_id = EXCLUDED.current_job_id,
                        last_seen_at = now(),
                        updated_at = now()
                    """,
                    (worker_id, state, current_job_id),
                )

    def mark_worker_stopped(self, worker_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO video_worker_registry
                      (worker_id, state, current_job_id, last_seen_at, updated_at)
                    VALUES (%s, 'stopped', NULL, now(), now())
                    ON CONFLICT (worker_id) DO UPDATE
                    SET state = 'stopped',
                        current_job_id = NULL,
                        last_seen_at = now(),
                        updated_at = now()
                    """,
                    (worker_id,),
                )

    def is_worker_draining(self, worker_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state FROM video_worker_registry WHERE worker_id = %s",
                    (worker_id,),
                )
                row = cur.fetchone()
        return bool(row and row.get("state") == "draining")

    def request_worker_drain(self, worker_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO video_worker_registry
                      (worker_id, state, last_seen_at, drain_requested_at, updated_at)
                    VALUES (%s, 'draining', now(), now(), now())
                    ON CONFLICT (worker_id) DO UPDATE
                    SET state = 'draining',
                        drain_requested_at = COALESCE(video_worker_registry.drain_requested_at, now()),
                        updated_at = now()
                    """,
                    (worker_id,),
                )

    def clear_worker_drain(self, worker_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE video_worker_registry
                    SET state = CASE WHEN current_job_id IS NULL THEN 'idle' ELSE 'running' END,
                        drain_requested_at = NULL,
                        updated_at = now()
                    WHERE worker_id = %s
                    """,
                    (worker_id,),
                )

    def list_workers(self, *, seen_within_seconds: int = 300) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT worker_id, state, current_job_id, last_seen_at, drain_requested_at, updated_at
                    FROM video_worker_registry
                    WHERE last_seen_at >= now() - make_interval(secs => %s)
                      AND state <> 'stopped'
                    ORDER BY worker_id ASC
                    """,
                    (max(1, int(seen_within_seconds)),),
                )
                return [dict(row) for row in cur.fetchall()]

    def count_video_jobs_by_status(self) -> dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, count(*) AS count
                    FROM video_jobs
                    WHERE status IN ('queued', 'running')
                    GROUP BY status
                    """
                )
                rows = cur.fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def create_job(
        self,
        owner_principal_id: str,
        bridge_session_id: str,
        video_url_canonical: str,
        *,
        idempotency_key: str | None = None,
        job_spec: dict[str, Any] | None = None,
    ) -> VideoJob:
        spec_payload = job_spec if isinstance(job_spec, dict) else {}
        spec_param = Jsonb(spec_payload) if Jsonb is not None else spec_payload
        with self._connect() as conn:
            with conn.cursor() as cur:
                if idempotency_key:
                    cur.execute(
                        """
                        INSERT INTO video_jobs
                          (owner_principal_id, bridge_session_id, video_url_canonical, idempotency_key, status, job_spec)
                        VALUES (%s, %s, %s, %s, %s, %s)
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
                            spec_param,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO video_jobs
                          (owner_principal_id, bridge_session_id, video_url_canonical, status, job_spec)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            owner_principal_id,
                            bridge_session_id,
                            video_url_canonical,
                            JobStatus.QUEUED.value,
                            spec_param,
                        ),
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
        if self.is_worker_draining(worker_id):
            self.heartbeat_worker(worker_id, state="draining")
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH next_job AS (
                      SELECT job_id
                      FROM video_jobs
                      WHERE status = 'queued'
                        AND NOT EXISTS (
                          SELECT 1
                          FROM video_jobs active
                          WHERE active.bridge_session_id = video_jobs.bridge_session_id
                            AND active.status = 'running'
                        )
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

    @staticmethod
    def hash_api_key(api_key: str) -> str:
        return sha256(api_key.strip().encode("utf-8")).hexdigest()

    def list_api_key_cooldowns(self, provider: str, key_hashes: list[str]) -> dict[str, dict[str, Any]]:
        if not key_hashes:
            return {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider, key_hash, cooldown_until, rate_limit_count, last_selected_at
                    FROM model_api_key_cooldowns
                    WHERE provider = %s
                      AND key_hash = ANY(%s::text[])
                    """,
                    (provider, key_hashes),
                )
                rows = cur.fetchall()
        return {row["key_hash"]: dict(row) for row in rows}

    def mark_api_key_selected(self, provider: str, key_hash: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_api_key_cooldowns
                      (provider, key_hash, last_selected_at, updated_at)
                    VALUES (%s, %s, now(), now())
                    ON CONFLICT (provider, key_hash) DO UPDATE
                    SET last_selected_at = now(), updated_at = now()
                    """,
                    (provider, key_hash),
                )

    def mark_api_key_rate_limited(self, provider: str, key_hash: str, cooldown_seconds: int) -> None:
        cooldown_seconds = max(0, int(cooldown_seconds))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO model_api_key_cooldowns
                      (provider, key_hash, cooldown_until, rate_limit_count, updated_at)
                    VALUES (%s, %s, now() + make_interval(secs => %s), 1, now())
                    ON CONFLICT (provider, key_hash) DO UPDATE
                    SET cooldown_until = now() + make_interval(secs => %s),
                        rate_limit_count = model_api_key_cooldowns.rate_limit_count + 1,
                        updated_at = now()
                    """,
                    (provider, key_hash, cooldown_seconds, cooldown_seconds),
                )

    def acquire_lane_lease(
        self,
        lane: str,
        *,
        worker_id: str,
        max_concurrent: int,
        lease_seconds: int,
    ) -> tuple[str, int] | None:
        max_concurrent = max(1, int(max_concurrent))
        lease_seconds = max(1, int(lease_seconds))
        lease_id = str(uuid4())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM model_lane_leases
                    WHERE lane = %s
                      AND expires_at < now()
                    """,
                    (lane,),
                )
                cur.execute(
                    """
                    WITH slots AS (
                      SELECT generate_series(0, %s - 1) AS slot_index
                    ),
                    available AS (
                      SELECT slots.slot_index
                      FROM slots
                      LEFT JOIN model_lane_leases existing
                        ON existing.lane = %s
                       AND existing.slot_index = slots.slot_index
                      WHERE existing.slot_index IS NULL
                      ORDER BY slots.slot_index
                      LIMIT 1
                    )
                    INSERT INTO model_lane_leases
                      (lane, slot_index, lease_id, worker_id, expires_at)
                    SELECT %s, slot_index, %s, %s, now() + make_interval(secs => %s)
                    FROM available
                    ON CONFLICT DO NOTHING
                    RETURNING lease_id, slot_index
                    """,
                    (max_concurrent, lane, lane, lease_id, worker_id, lease_seconds),
                )
                row = cur.fetchone()
        if not row:
            return None
        return str(row["lease_id"]), int(row["slot_index"])

    def release_lane_lease(self, lane: str, lease_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM model_lane_leases
                    WHERE lane = %s
                      AND lease_id = %s
                    """,
                    (lane, lease_id),
                )

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

    def cleanup_terminal_jobs_before(self, owner_principal_id: str, cutoff: Any) -> RetentionCleanupResult:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH doomed AS (
                      SELECT job_id, video_url_canonical
                      FROM video_jobs
                      WHERE owner_principal_id = %s
                        AND status IN ('succeeded', 'failed', 'timed_out', 'cancelled')
                        AND finished_at IS NOT NULL
                        AND finished_at < %s
                    ),
                    deleted_results AS (
                      DELETE FROM video_results
                      WHERE owner_principal_id = %s
                        AND job_id IN (SELECT job_id FROM doomed)
                      RETURNING job_id
                    ),
                    deleted_jobs AS (
                      DELETE FROM video_jobs
                      WHERE owner_principal_id = %s
                        AND job_id IN (SELECT job_id FROM doomed)
                      RETURNING job_id
                    )
                    SELECT
                      (SELECT count(*) FROM deleted_jobs) AS deleted_jobs,
                      (SELECT count(*) FROM deleted_results) AS deleted_results,
                      COALESCE(array_agg(job_id::text), ARRAY[]::text[]) AS deleted_job_ids,
                      COALESCE(
                        array_agg(video_url_canonical)
                          FILTER (WHERE video_url_canonical LIKE 'upload://%%'),
                        ARRAY[]::text[]
                      ) AS upload_uris
                    FROM doomed
                    """,
                    (owner_principal_id, cutoff, owner_principal_id, owner_principal_id),
                )
                row = cur.fetchone()
        if not row:
            return RetentionCleanupResult(0, 0, (), ())
        return RetentionCleanupResult(
            deleted_jobs=int(row["deleted_jobs"]),
            deleted_results=int(row["deleted_results"]),
            deleted_job_ids=tuple(row["deleted_job_ids"] or ()),
            upload_uris=tuple(row["upload_uris"] or ()),
        )
