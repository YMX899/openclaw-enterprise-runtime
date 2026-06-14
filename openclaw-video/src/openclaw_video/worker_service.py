from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from typing import Callable

from .douyin_wrapper import (
    DouyinAnalysisResult,
    ModelRateLimitError,
    DouyinWrapperError,
    VideoTooLargeForModelError,
    run_douyin_chong,
    run_upload_video_analysis,
)
from .job_store import InMemoryJobStore, JobLeaseError, VideoJob
from .model_broker import (
    DEFAULT_VIDEO_MODEL_LANE,
    DEFAULT_VIDEO_MODEL_LANE_LEASE_SECONDS,
    DEFAULT_VIDEO_MODEL_MAX_CONCURRENT,
    SelectedApiKey,
    acquire_lane,
    is_rate_limit_error,
    load_bailian_config,
    select_api_key,
)
from .result_schema import RESULT_SCHEMA_VERSION, ResultSchemaError, validate_result_payload
from .upload_store import UploadNotFound, UploadStoreError, is_upload_uri, resolve_upload_uri
from .url_guard import (
    RedirectFetcher,
    Resolver,
    UrlRejected,
    default_redirect_fetcher,
    default_resolver,
    validate_video_url,
    validate_video_url_with_redirects,
)
from .video_limits import (
    DEFAULT_MAX_DOWNLOAD_BYTES,
    DEFAULT_MAX_MODEL_VIDEO_BYTES,
    DEFAULT_MAX_VIDEO_DURATION_SECONDS,
    DEFAULT_MAX_VIDEO_FRAMES,
    DEFAULT_VIDEO_UNDERSTANDING_FPS,
    MAX_VIDEO_UNDERSTANDING_FPS,
    MIN_VIDEO_UNDERSTANDING_FPS,
)


logger = logging.getLogger(__name__)


class UploadTooLargeError(RuntimeError):
    """Uploaded video is too large for local preprocessing."""


Analyzer = Callable[[str, Path], DouyinAnalysisResult]


def _host_is_direct_xiaohongshu(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")


@dataclass(frozen=True)
class WorkerConfig:
    timeout_seconds: int = 900
    worker_id: str = "video-analysis-worker-1"
    heartbeat_interval_seconds: int = 30
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    max_model_video_bytes: int = DEFAULT_MAX_MODEL_VIDEO_BYTES
    max_duration_seconds: int = DEFAULT_MAX_VIDEO_DURATION_SECONDS
    max_frames: int = DEFAULT_MAX_VIDEO_FRAMES
    video_understanding_fps: float = DEFAULT_VIDEO_UNDERSTANDING_FPS
    min_video_understanding_fps: float = MIN_VIDEO_UNDERSTANDING_FPS
    max_video_understanding_fps: float = MAX_VIDEO_UNDERSTANDING_FPS
    max_inline_upload_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    video_model_lane: str = DEFAULT_VIDEO_MODEL_LANE
    video_model_max_concurrent: int = DEFAULT_VIDEO_MODEL_MAX_CONCURRENT
    video_model_lane_lease_seconds: int = DEFAULT_VIDEO_MODEL_LANE_LEASE_SECONDS
    video_model_lane_wait_seconds: int = 60


class VideoAnalysisWorker:
    def __init__(
        self,
        store: InMemoryJobStore,
        *,
        analyzer: Analyzer | None = None,
        url_resolver: Resolver = default_resolver,
        redirect_fetcher: RedirectFetcher = default_redirect_fetcher,
        config: WorkerConfig | None = None,
    ) -> None:
        self.store = store
        self.config = config or WorkerConfig()
        self.analyzer = analyzer or self._default_analyzer
        self.url_resolver = url_resolver
        self.redirect_fetcher = redirect_fetcher
        self.provider_config = load_bailian_config()

    def _select_model_key(self) -> SelectedApiKey | None:
        config = self.provider_config
        if not config:
            return None
        if not all(hasattr(self.store, name) for name in ("list_api_key_cooldowns", "mark_api_key_selected")):
            return None
        return select_api_key(config, self.store)  # type: ignore[arg-type]

    def _mark_rate_limited(self, selected: SelectedApiKey | None) -> None:
        if not selected or not hasattr(self.store, "mark_api_key_rate_limited"):
            return
        config = self.provider_config
        cooldown_seconds = config.cooldown_seconds if config else 60
        self.store.mark_api_key_rate_limited(selected.provider, selected.key_hash, cooldown_seconds)  # type: ignore[attr-defined]

    def _env_for_selected_key(self, selected: SelectedApiKey | None) -> dict[str, str] | None:
        if not selected:
            return None
        env = dict(os.environ)
        env["BAILIAN_SELECTED_API_KEY"] = selected.api_key
        env["BAILIAN_OPENAI_BASE_URL"] = selected.base_url
        env["BAILIAN_MODEL"] = selected.model
        env["BAILIAN_PROVIDER"] = selected.provider
        return env

    def _run_with_model_lane(self, operation: Callable[[SelectedApiKey | None], DouyinAnalysisResult]) -> DouyinAnalysisResult:
        selected = self._select_model_key()
        if not hasattr(self.store, "acquire_lane_lease"):
            return operation(selected)
        try:
            with acquire_lane(
                self.store,  # type: ignore[arg-type]
                self.config.video_model_lane,
                worker_id=self.config.worker_id,
                max_concurrent=self.config.video_model_max_concurrent,
                lease_seconds=self.config.video_model_lane_lease_seconds,
                wait_timeout_seconds=self.config.video_model_lane_wait_seconds,
            ):
                return operation(selected)
        except BaseException as exc:
            if isinstance(exc, ModelRateLimitError) or is_rate_limit_error(exc):
                self._mark_rate_limited(selected)
            raise

    def _default_analyzer(self, video_url: str, output_dir: Path) -> DouyinAnalysisResult:
        if is_upload_uri(video_url):
            return self._analyze_uploaded_video(video_url, output_dir)
        return self._run_with_model_lane(
            lambda selected: run_douyin_chong(
                video_url=video_url,
                output_dir=output_dir,
                timeout_seconds=self.config.timeout_seconds,
                max_download_bytes=self.config.max_download_bytes,
                max_model_video_bytes=self.config.max_model_video_bytes,
                max_duration_seconds=self.config.max_duration_seconds,
                max_frames=self.config.max_frames,
                video_understanding_fps=self.config.video_understanding_fps,
                min_video_understanding_fps=self.config.min_video_understanding_fps,
                max_video_understanding_fps=self.config.max_video_understanding_fps,
                env=self._env_for_selected_key(selected),
            )
        )

    def _analyze_uploaded_video(self, video_uri: str, output_dir: Path) -> DouyinAnalysisResult:
        path = resolve_upload_uri(video_uri)
        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            raise DouyinWrapperError("uploaded video is empty")
        if size_bytes > self.config.max_inline_upload_bytes:
            raise UploadTooLargeError("uploaded video exceeds preprocessing size limit")
        # Let the adapter enforce the shared 500 MiB Files API boundary and
        # submit uploads through the same Responses video path as links.
        return self._run_with_model_lane(
            lambda selected: run_upload_video_analysis(
                file_path=str(path),
                output_dir=output_dir,
                source_label=video_uri,
                timeout_seconds=self.config.timeout_seconds,
                max_bytes=self.config.max_inline_upload_bytes,
                env=self._env_for_selected_key(selected),
            )
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

    def _log_failure(self, job: VideoJob, error_code: str, exc: BaseException) -> None:
        logger.warning(
            "video job failed job_id=%s error_code=%s exception=%s detail=%s",
            job.job_id,
            error_code,
            type(exc).__name__,
            str(exc)[:2000],
        )

    def run_once(self) -> VideoJob | None:
        job = self.store.claim_next(self.config.worker_id, self.config.timeout_seconds)
        if not job:
            return None
        stop_heartbeat = self._start_heartbeat(job)
        try:
            if is_upload_uri(job.video_url_canonical):
                canonical = job.video_url_canonical
            else:
                if _host_is_direct_xiaohongshu(job.video_url_canonical):
                    validated = validate_video_url(job.video_url_canonical, resolver=self.url_resolver)
                else:
                    validated = validate_video_url_with_redirects(
                        job.video_url_canonical,
                        resolver=self.url_resolver,
                        redirect_fetcher=self.redirect_fetcher,
                    )
                canonical = validated.canonical
            with TemporaryDirectory(prefix="openclaw-video-") as tmp:
                analysis = self.analyzer(canonical, Path(tmp))
            payload = validate_result_payload(analysis.payload)
            return self.store.complete_job(
                job.job_id,
                payload,
                RESULT_SCHEMA_VERSION,
                worker_id=self.config.worker_id,
            )
        except (TimeoutError, ModelRateLimitError) as exc:
            self._log_failure(job, "tool_timeout", exc)
            return self._fail_job(job, "tool_timeout", timed_out=True)
        except UrlRejected as exc:
            self._log_failure(job, "url_rejected", exc)
            return self._fail_job(job, "url_rejected")
        except UploadTooLargeError as exc:
            self._log_failure(job, "upload_too_large", exc)
            return self._fail_job(job, "upload_too_large")
        except VideoTooLargeForModelError as exc:
            self._log_failure(job, "video_too_large", exc)
            return self._fail_job(job, "video_too_large")
        except (DouyinWrapperError, ResultSchemaError, ValueError, UploadStoreError, UploadNotFound) as exc:
            self._log_failure(job, "tool_failed", exc)
            return self._fail_job(job, "tool_failed")
        except JobLeaseError:
            return self.store.get_job(job.job_id)
        finally:
            stop_heartbeat()
