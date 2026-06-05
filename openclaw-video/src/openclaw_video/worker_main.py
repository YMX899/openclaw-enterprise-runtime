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
    store = PostgresJobStore(database_url)
    worker = VideoAnalysisWorker(
        store,
        config=WorkerConfig(
            timeout_seconds=timeout_seconds,
            worker_id=worker_id,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        ),
    )
    while True:
        store.recover_expired_leases()
        job = worker.run_once()
        if job is None:
            time.sleep(interval)


if __name__ == "__main__":
    main()
