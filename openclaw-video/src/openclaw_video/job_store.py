from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from threading import Lock

from .job_state import JobStatus, TERMINAL_STATUSES


class JobOwnershipError(PermissionError):
    pass


class JobNotFound(KeyError):
    pass


class JobLeaseError(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass
class VideoJob:
    owner_principal_id: str
    bridge_session_id: str
    video_url_canonical: str
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=now_utc)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int = 0
    error_code: str | None = None
    result_schema_version: str | None = None
    result_location: str | None = None
    idempotency_key: str | None = None
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    job_spec: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoResult:
    job_id: str
    owner_principal_id: str
    schema_version: str
    result: dict
    created_at: datetime = field(default_factory=now_utc)


@dataclass(frozen=True)
class RetentionCleanupResult:
    deleted_jobs: int
    deleted_results: int
    deleted_job_ids: tuple[str, ...]
    upload_uris: tuple[str, ...]


class InMemoryJobStore:
    """Small deterministic job store for offline tests.

    Production must replace this with Postgres using FOR UPDATE SKIP LOCKED.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, VideoJob] = {}
        self._results: dict[str, VideoResult] = {}
        self._lock = Lock()

    def create_job(
        self,
        owner_principal_id: str,
        bridge_session_id: str,
        video_url_canonical: str,
        *,
        idempotency_key: str | None = None,
        job_spec: dict[str, Any] | None = None,
    ) -> VideoJob:
        job = VideoJob(
            owner_principal_id=owner_principal_id,
            bridge_session_id=bridge_session_id,
            video_url_canonical=video_url_canonical,
            idempotency_key=idempotency_key,
            job_spec=dict(job_spec or {}),
        )
        with self._lock:
            if idempotency_key:
                for existing in self._jobs.values():
                    if (
                        existing.owner_principal_id == owner_principal_id
                        and existing.bridge_session_id == bridge_session_id
                        and existing.idempotency_key == idempotency_key
                    ):
                        return existing
            self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str, owner_principal_id: str | None = None) -> VideoJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFound(job_id)
            if owner_principal_id is not None and job.owner_principal_id != owner_principal_id:
                raise JobOwnershipError(job_id)
            return job

    def get_job_by_idempotency(
        self,
        owner_principal_id: str,
        bridge_session_id: str,
        idempotency_key: str,
    ) -> VideoJob:
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.owner_principal_id == owner_principal_id
                    and job.bridge_session_id == bridge_session_id
                    and job.idempotency_key == idempotency_key
                ):
                    return job
        raise JobNotFound(idempotency_key)

    def count_active_jobs(self, owner_principal_id: str) -> int:
        with self._lock:
            return sum(
                1
                for job in self._jobs.values()
                if job.owner_principal_id == owner_principal_id and job.status not in TERMINAL_STATUSES
            )

    def claim_next(self, worker_id: str = "worker", lease_seconds: int = 900) -> VideoJob | None:
        with self._lock:
            queued = sorted(
                (job for job in self._jobs.values() if job.status == JobStatus.QUEUED),
                key=lambda item: item.created_at,
            )
            if not queued:
                return None
            job = queued[0]
            now = now_utc()
            job.status = JobStatus.RUNNING
            job.started_at = job.started_at or now
            job.attempt_count += 1
            job.worker_id = worker_id
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return job

    def heartbeat_job(self, job_id: str, worker_id: str, lease_seconds: int = 900) -> VideoJob:
        with self._lock:
            job = self._jobs[job_id]
            if job.status != JobStatus.RUNNING or job.worker_id != worker_id:
                raise JobLeaseError(job_id)
            now = now_utc()
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            return job

    def recover_expired_leases(self, *, now: datetime | None = None) -> int:
        reference = now or now_utc()
        recovered = 0
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.status == JobStatus.RUNNING
                    and job.lease_expires_at is not None
                    and job.lease_expires_at < reference
                ):
                    job.status = JobStatus.QUEUED
                    job.worker_id = None
                    job.heartbeat_at = None
                    job.lease_expires_at = None
                    recovered += 1
        return recovered

    def complete_job(
        self,
        job_id: str,
        result: dict,
        schema_version: str,
        *,
        worker_id: str | None = None,
    ) -> VideoJob:
        with self._lock:
            job = self._jobs[job_id]
            if worker_id is not None and job.worker_id != worker_id:
                raise JobLeaseError(job_id)
            job.status = JobStatus.SUCCEEDED
            job.finished_at = now_utc()
            job.error_code = None
            job.result_schema_version = schema_version
            job.result_location = f"memory://video_results/{job_id}"
            job.worker_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            self._results[job_id] = VideoResult(
                job_id=job_id,
                owner_principal_id=job.owner_principal_id,
                schema_version=schema_version,
                result=result,
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
        with self._lock:
            job = self._jobs[job_id]
            if worker_id is not None and job.worker_id != worker_id:
                raise JobLeaseError(job_id)
            job.status = JobStatus.TIMED_OUT if timed_out else JobStatus.FAILED
            job.finished_at = now_utc()
            job.error_code = error_code
            job.worker_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            return job

    def cancel_job(self, job_id: str, owner_principal_id: str) -> VideoJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFound(job_id)
            if job.owner_principal_id != owner_principal_id:
                raise JobOwnershipError(job_id)
            job.status = JobStatus.CANCELLED
            job.finished_at = now_utc()
            job.worker_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            return job

    def get_result(self, job_id: str, owner_principal_id: str | None = None) -> VideoResult:
        with self._lock:
            result = self._results.get(job_id)
            if not result:
                raise JobNotFound(job_id)
            if owner_principal_id is not None and result.owner_principal_id != owner_principal_id:
                raise JobOwnershipError(job_id)
            return result

    def cleanup_terminal_jobs_before(self, owner_principal_id: str, cutoff: datetime) -> RetentionCleanupResult:
        with self._lock:
            deleted_job_ids = [
                job_id
                for job_id, job in self._jobs.items()
                if job.owner_principal_id == owner_principal_id
                and job.status in TERMINAL_STATUSES
                and job.finished_at is not None
                and job.finished_at < cutoff
            ]
            upload_uris = tuple(
                self._jobs[job_id].video_url_canonical
                for job_id in deleted_job_ids
                if self._jobs[job_id].video_url_canonical.startswith("upload://")
            )
            deleted_results = 0
            for job_id in deleted_job_ids:
                if job_id in self._results:
                    del self._results[job_id]
                    deleted_results += 1
                del self._jobs[job_id]
        return RetentionCleanupResult(
            deleted_jobs=len(deleted_job_ids),
            deleted_results=deleted_results,
            deleted_job_ids=tuple(deleted_job_ids),
            upload_uris=upload_uris,
        )
