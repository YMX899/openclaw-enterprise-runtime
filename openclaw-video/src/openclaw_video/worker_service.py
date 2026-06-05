from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from .douyin_wrapper import DouyinAnalysisResult, DouyinWrapperError, run_douyin_chong
from .job_store import InMemoryJobStore, VideoJob
from .result_schema import RESULT_SCHEMA_VERSION, ResultSchemaError, validate_result_payload
from .url_guard import Resolver, UrlRejected, default_resolver, validate_video_url


Analyzer = Callable[[str, Path], DouyinAnalysisResult]


@dataclass(frozen=True)
class WorkerConfig:
    timeout_seconds: int = 900


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

    def run_once(self) -> VideoJob | None:
        job = self.store.claim_next()
        if not job:
            return None
        try:
            validated = validate_video_url(job.video_url_canonical, resolver=self.url_resolver)
            with TemporaryDirectory(prefix="openclaw-video-") as tmp:
                analysis = self.analyzer(validated.canonical, Path(tmp))
            payload = validate_result_payload(analysis.payload)
            return self.store.complete_job(job.job_id, payload, RESULT_SCHEMA_VERSION)
        except TimeoutError:
            return self.store.fail_job(job.job_id, "tool_timeout", timed_out=True)
        except UrlRejected:
            return self.store.fail_job(job.job_id, "url_rejected")
        except (DouyinWrapperError, ResultSchemaError, ValueError):
            return self.store.fail_job(job.job_id, "tool_failed")
