from __future__ import annotations

import os
import time

from .postgres_store import PostgresJobStore
from .worker_service import VideoAnalysisWorker, WorkerConfig


def main() -> None:
    """Worker entrypoint for the V1 low-concurrency durable queue."""

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for video-analysis-worker")
    concurrency = int(os.environ.get("WORKER_CONCURRENCY", "1"))
    if concurrency != 1:
        raise RuntimeError("V1 requires WORKER_CONCURRENCY=1 until load tests prove Dify safety")
    interval = int(os.environ.get("WORKER_IDLE_SECONDS", "5"))
    timeout_seconds = int(os.environ.get("JOB_TIMEOUT_SECONDS", "900"))
    worker_id = os.environ.get("WORKER_ID", "video-analysis-worker-1")
    heartbeat_interval_seconds = int(os.environ.get("JOB_HEARTBEAT_SECONDS", "30"))
    max_download_bytes = int(os.environ.get("MAX_DOWNLOAD_BYTES", str(512 * 1024 * 1024)))
    max_duration_seconds = int(os.environ.get("MAX_VIDEO_DURATION_SECONDS", "60"))
    max_frames = int(os.environ.get("MAX_VIDEO_FRAMES", "1200"))
    max_inline_upload_bytes = int(os.environ.get("MAX_INLINE_UPLOAD_BYTES", str(60 * 1024 * 1024)))
    store = PostgresJobStore(database_url)
    worker = VideoAnalysisWorker(
        store,
        config=WorkerConfig(
            timeout_seconds=timeout_seconds,
            worker_id=worker_id,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            max_download_bytes=max_download_bytes,
            max_duration_seconds=max_duration_seconds,
            max_frames=max_frames,
            max_inline_upload_bytes=max_inline_upload_bytes,
        ),
    )
    while True:
        store.recover_expired_leases()
        job = worker.run_once()
        if job is None:
            time.sleep(interval)


if __name__ == "__main__":
    main()
