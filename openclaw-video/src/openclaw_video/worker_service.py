from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Callable

from .douyin_wrapper import DouyinAnalysisResult, DouyinWrapperError, run_douyin_chong
from .job_store import InMemoryJobStore, JobLeaseError, VideoJob
from .result_schema import RESULT_SCHEMA_VERSION, ResultSchemaError, validate_result_payload
from .url_guard import Resolver, UrlRejected, default_resolver, validate_video_url


Analyzer = Callable[[str, Path], DouyinAnalysisResult]


@dataclass(frozen=True)
class WorkerConfig:
    timeout_seconds: int = 900
    worker_id: str = "video-analysis-worker-1"
    heartbeat_interval_seconds: int = 30


class VideoAnalysisWorker:
    def __init__(
        self,
        store: InMemoryJobStore,
        *,
        analyzer: Analyzer | None = None,
        url_resolver: Resolver = default_resolver,
        config: WorkerConfig | None = None,
    ) -> None:
        self.store = store
        self.config = config or WorkerConfig()
        self.analyzer = analyzer or self._default_analyzer
        self.url_resolver = url_resolver

    def _default_analyzer(self, video_url: str, output_dir: Path) -> DouyinAnalysisResult:
        return run_douyin_chong(
            video_url=video_url,
            output_dir=output_dir,
            timeout_seconds=self.config.timeout_seconds,
        )

    def _start_heartbeat(self, job: VideoJob) -> Callable[[], None]:
        interval = self.config.heartbeat_interval_seconds
        if interval <= 0:
            return lambda: None
        stop = Event()

        def beat() -> None:
            while not stop.wait(interval):
                try:
                    self.store.heartbeat_job(job.job_id, self.config.worker_id, self.config.timeout_seconds)
                except Exception:
                    return

        thread = Thread(target=beat, name=f"openclaw-job-heartbeat-{job.job_id}", daemon=True)
        thread.start()

        def stop_heartbeat() -> None:
            stop.set()
            thread.join(timeout=1)

        return stop_heartbeat

    def _fail_job(self, job: VideoJob, error_code: str, *, timed_out: bool = False) -> VideoJob:
        try:
            return self.store.fail_job(
                job.job_id,
                error_code,
                timed_out=timed_out,
                worker_id=self.config.worker_id,
            )
        except JobLeaseError:
            return self.store.get_job(job.job_id)

    def run_once(self) -> VideoJob | None:
        job = self.store.claim_next(self.config.worker_id, self.config.timeout_seconds)
        if not job:
            return None
        stop_heartbeat = self._start_heartbeat(job)
        try:
            validated = validate_video_url(job.video_url_canonical, resolver=self.url_resolver)
            with TemporaryDirectory(prefix="openclaw-video-") as tmp:
                analysis = self.analyzer(validated.canonical, Path(tmp))
            payload = validate_result_payload(analysis.payload)
            return self.store.complete_job(
                job.job_id,
                payload,
                RESULT_SCHEMA_VERSION,
                worker_id=self.config.worker_id,
            )
        except TimeoutError:
            return self._fail_job(job, "tool_timeout", timed_out=True)
        except UrlRejected:
            return self._fail_job(job, "url_rejected")
        except (DouyinWrapperError, ResultSchemaError, ValueError):
            return self._fail_job(job, "tool_failed")
        except JobLeaseError:
            return self.store.get_job(job.job_id)
        finally:
            stop_heartbeat()
