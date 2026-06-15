from __future__ import annotations

import logging
import os
import socket
import time

from .postgres_store import PostgresJobStore
from .video_limits import (
    DEFAULT_MAX_DOWNLOAD_BYTES,
    DEFAULT_MAX_MODEL_VIDEO_BYTES,
    DEFAULT_VIDEO_UNDERSTANDING_FPS,
    MAX_VIDEO_UNDERSTANDING_FPS,
    MIN_VIDEO_UNDERSTANDING_FPS,
)
from .worker_service import VideoAnalysisWorker, WorkerConfig


def resolve_worker_id() -> str:
    configured = os.environ.get("WORKER_ID", "").strip()
    if configured:
        return configured
    hostname = os.environ.get("HOSTNAME", "").strip() or socket.gethostname().strip()
    return hostname or "video-analysis-worker"


def main() -> None:
    """Worker entrypoint for the V1 low-concurrency durable queue."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for video-analysis-worker")
    concurrency = int(os.environ.get("WORKER_CONCURRENCY", "1"))
    if concurrency != 1:
        raise RuntimeError("V1 requires WORKER_CONCURRENCY=1 until load tests prove Dify safety")
    interval = int(os.environ.get("WORKER_IDLE_SECONDS", "5"))
    timeout_seconds = int(os.environ.get("JOB_TIMEOUT_SECONDS", "900"))
    worker_id = resolve_worker_id()
    heartbeat_interval_seconds = int(os.environ.get("JOB_HEARTBEAT_SECONDS", "30"))
    max_download_bytes = int(os.environ.get("MAX_DOWNLOAD_BYTES", str(DEFAULT_MAX_DOWNLOAD_BYTES)))
    max_model_video_bytes = int(os.environ.get("MAX_MODEL_VIDEO_BYTES", str(DEFAULT_MAX_MODEL_VIDEO_BYTES)))
    max_duration_seconds = int(os.environ.get("MAX_VIDEO_DURATION_SECONDS", "0"))
    max_frames = int(os.environ.get("MAX_VIDEO_FRAMES", "0"))
    video_understanding_fps = float(os.environ.get("DOUYIN_CHONG_FPS", str(DEFAULT_VIDEO_UNDERSTANDING_FPS)))
    min_video_understanding_fps = float(os.environ.get("MIN_VIDEO_UNDERSTANDING_FPS", str(MIN_VIDEO_UNDERSTANDING_FPS)))
    max_video_understanding_fps = float(os.environ.get("MAX_VIDEO_UNDERSTANDING_FPS", str(MAX_VIDEO_UNDERSTANDING_FPS)))
    max_inline_upload_bytes = int(os.environ.get("MAX_INLINE_UPLOAD_BYTES", str(max_download_bytes)))
    video_model_max_concurrent = int(os.environ.get("VIDEO_MODEL_MAX_CONCURRENT", "200"))
    video_model_lane = os.environ.get("VIDEO_MODEL_LANE", "video_model_request")
    video_model_lane_lease_seconds = int(os.environ.get("VIDEO_MODEL_LANE_LEASE_SECONDS", str(timeout_seconds)))
    video_model_lane_wait_seconds = int(os.environ.get("VIDEO_MODEL_LANE_WAIT_SECONDS", "60"))
    store = PostgresJobStore(database_url)
    worker = VideoAnalysisWorker(
        store,
        config=WorkerConfig(
            timeout_seconds=timeout_seconds,
            worker_id=worker_id,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            max_download_bytes=max_download_bytes,
            max_model_video_bytes=max_model_video_bytes,
            max_duration_seconds=max_duration_seconds,
            max_frames=max_frames,
            video_understanding_fps=video_understanding_fps,
            min_video_understanding_fps=min_video_understanding_fps,
            max_video_understanding_fps=max_video_understanding_fps,
            max_inline_upload_bytes=max_inline_upload_bytes,
            video_model_lane=video_model_lane,
            video_model_max_concurrent=video_model_max_concurrent,
            video_model_lane_lease_seconds=video_model_lane_lease_seconds,
            video_model_lane_wait_seconds=video_model_lane_wait_seconds,
        ),
    )
    while True:
        store.recover_expired_leases()
        job = worker.run_once()
        if job is None:
            time.sleep(interval)


if __name__ == "__main__":
    main()
