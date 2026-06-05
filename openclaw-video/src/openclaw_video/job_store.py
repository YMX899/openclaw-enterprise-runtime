from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock

from .job_state import JobStatus


class JobOwnershipError(PermissionError):
    pass


class JobNotFound(KeyError):
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


@dataclass
class VideoResult:
    job_id: str
    owner_principal_id: str
    schema_version: str
    result: dict
    created_at: datetime = field(default_factory=now_utc)


class InMemoryJobStore:
    """Small deterministic job store for offline tests.

    Production must replace this with Postgres using FOR UPDATE SKIP LOCKED.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, VideoJob] = {}
        self._results: dict[str, VideoResult] = {}
        self._lock = Lock()

    def create_job(self, owner_principal_id: str, bridge_session_id: str, video_url_canonical: str) -> VideoJob:
        job = VideoJob(
            owner_principal_id=owner_principal_id,
            bridge_session_id=bridge_session_id,
            video_url_canonical=video_url_canonical,
        )
        with self._lock:
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

    def claim_next(self) -> VideoJob | None:
        with self._lock:
            queued = sorted(
                (job for job in self._jobs.values() if job.status == JobStatus.QUEUED),
                key=lambda item: item.created_at,
            )
            if not queued:
                return None
            job = queued[0]
            job.status = JobStatus.RUNNING
            job.started_at = now_utc()
            job.attempt_count += 1
            return job

    def complete_job(self, job_id: str, result: dict, schema_version: str) -> VideoJob:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.SUCCEEDED
            job.finished_at = now_utc()
            job.error_code = None
            job.result_schema_version = schema_version
            job.result_location = f"memory://video_results/{job_id}"
            self._results[job_id] = VideoResult(
                job_id=job_id,
                owner_principal_id=job.owner_principal_id,
                schema_version=schema_version,
                result=result,
            )
            return job

    def fail_job(self, job_id: str, error_code: str, timed_out: bool = False) -> VideoJob:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JobStatus.TIMED_OUT if timed_out else JobStatus.FAILED
            job.finished_at = now_utc()
            job.error_code = error_code
            return job

    def get_result(self, job_id: str, owner_principal_id: str | None = None) -> VideoResult:
        with self._lock:
            result = self._results.get(job_id)
            if not result:
                raise JobNotFound(job_id)
            if owner_principal_id is not None and result.owner_principal_id != owner_principal_id:
                raise JobOwnershipError(job_id)
            return result

