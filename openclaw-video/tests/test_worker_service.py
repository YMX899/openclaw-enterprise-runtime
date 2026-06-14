import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openclaw_video.douyin_wrapper import DouyinAnalysisResult, ModelRateLimitError, VideoTooLargeForModelError
from openclaw_video.douyin_wrapper import DouyinWrapperError
from openclaw_video.job_state import JobStatus
from openclaw_video.job_store import InMemoryJobStore
from openclaw_video.result_schema import RESULT_SCHEMA_VERSION
from openclaw_video.upload_store import store_upload_bytes
from openclaw_video.worker_service import VideoAnalysisWorker, WorkerConfig


def public_resolver(_host: str, _port: int | None) -> list[str]:
    return ["110.242.68.66"]


def no_redirect(_url: str) -> str | None:
    return None


def ok_analyzer(video_url: str, _output_dir: Path) -> DouyinAnalysisResult:
    return DouyinAnalysisResult(
        payload={
            "schema_version": RESULT_SCHEMA_VERSION,
            "source": {
                "video_url_canonical": video_url,
                "platform": "douyin",
                "duration_seconds": 12,
            },
            "summary": "A concise test result.",
            "signals": {"hook": "test"},
            "raw_tool_result": {"fixture": True},
            "created_at": "2026-06-06T00:00:00Z",
        },
        stdout="",
        stderr="",
    )


def invalid_analyzer(_video_url: str, _output_dir: Path) -> DouyinAnalysisResult:
    return DouyinAnalysisResult(payload={"schema_version": "wrong"}, stdout="", stderr="")


def timeout_analyzer(_video_url: str, _output_dir: Path) -> DouyinAnalysisResult:
    raise TimeoutError("fixture timeout")


def video_too_large_analyzer(_video_url: str, _output_dir: Path) -> DouyinAnalysisResult:
    raise VideoTooLargeForModelError("fixture video too large")


def tool_failed_analyzer(_video_url: str, _output_dir: Path) -> DouyinAnalysisResult:
    raise DouyinWrapperError("fixture tool detail")


class BrokerJobStore(InMemoryJobStore):
    def __init__(self):
        super().__init__()
        self.cooldowns = {}
        self.selected = []
        self.rate_limited = []
        self.leases = []
        self.released = []

    def list_api_key_cooldowns(self, provider: str, key_hashes: list[str]) -> dict[str, dict]:
        return {
            key_hash: self.cooldowns.get((provider, key_hash), {})
            for key_hash in key_hashes
            if (provider, key_hash) in self.cooldowns
        }

    def mark_api_key_selected(self, provider: str, key_hash: str) -> None:
        self.selected.append((provider, key_hash))

    def mark_api_key_rate_limited(self, provider: str, key_hash: str, cooldown_seconds: int) -> None:
        self.rate_limited.append((provider, key_hash, cooldown_seconds))

    def acquire_lane_lease(
        self,
        lane: str,
        *,
        worker_id: str,
        max_concurrent: int,
        lease_seconds: int,
    ) -> tuple[str, int] | None:
        self.leases.append(
            {
                "lane": lane,
                "worker_id": worker_id,
                "max_concurrent": max_concurrent,
                "lease_seconds": lease_seconds,
            }
        )
        return ("lease-1", 0)

    def release_lane_lease(self, lane: str, lease_id: str) -> None:
        self.released.append((lane, lease_id))


class WorkerServiceTests(unittest.TestCase):
    def test_run_once_succeeds(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(
            store,
            analyzer=ok_analyzer,
            url_resolver=public_resolver,
            redirect_fetcher=no_redirect,
        )
        completed = worker.run_once()
        self.assertEqual(completed.job_id, job.job_id)
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(store.get_result(job.job_id, "owner").schema_version, RESULT_SCHEMA_VERSION)

    def test_run_once_rejects_bad_url(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://example.com/video")
        worker = VideoAnalysisWorker(store, analyzer=ok_analyzer, redirect_fetcher=no_redirect)
        failed = worker.run_once()
        self.assertEqual(failed.job_id, job.job_id)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.error_code, "url_rejected")

    def test_run_once_fails_invalid_result(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(
            store,
            analyzer=invalid_analyzer,
            url_resolver=public_resolver,
            redirect_fetcher=no_redirect,
        )
        failed = worker.run_once()
        self.assertEqual(failed.job_id, job.job_id)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.error_code, "tool_failed")

    def test_run_once_logs_tool_failure_detail(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(
            store,
            analyzer=tool_failed_analyzer,
            url_resolver=public_resolver,
            redirect_fetcher=no_redirect,
        )

        with self.assertLogs("openclaw_video.worker_service", level="WARNING") as logs:
            failed = worker.run_once()

        self.assertEqual(failed.error_code, "tool_failed")
        self.assertIn("fixture tool detail", "\n".join(logs.output))

    def test_run_once_marks_timeout(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(
            store,
            analyzer=timeout_analyzer,
            url_resolver=public_resolver,
            redirect_fetcher=no_redirect,
        )
        failed = worker.run_once()
        self.assertEqual(failed.job_id, job.job_id)
        self.assertEqual(failed.status, JobStatus.TIMED_OUT)
        self.assertEqual(failed.error_code, "tool_timeout")

    def test_run_once_marks_model_video_size_limit(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(
            store,
            analyzer=video_too_large_analyzer,
            url_resolver=public_resolver,
            redirect_fetcher=no_redirect,
        )
        failed = worker.run_once()
        self.assertEqual(failed.job_id, job.job_id)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.error_code, "video_too_large")

    def test_run_once_does_not_complete_after_lease_changes(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")

        def takeover() -> None:
            current = store.get_job(job.job_id)
            current.worker_id = "worker-b"

        def stale_worker_analyzer(video_url: str, output_dir: Path) -> DouyinAnalysisResult:
            takeover()
            return ok_analyzer(video_url, output_dir)

        worker = VideoAnalysisWorker(
            store,
            analyzer=stale_worker_analyzer,
            url_resolver=public_resolver,
            redirect_fetcher=no_redirect,
        )
        current = worker.run_once()
        self.assertEqual(current.job_id, job.job_id)
        self.assertEqual(current.status, JobStatus.RUNNING)
        self.assertEqual(current.worker_id, "worker-b")

    def test_run_once_analyzes_redirect_target(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        seen = {}

        def analyzer(video_url: str, output_dir: Path) -> DouyinAnalysisResult:
            seen["video_url"] = video_url
            return ok_analyzer(video_url, output_dir)

        def redirect_fetcher(url: str) -> str | None:
            if url == "https://v.douyin.com/abc":
                return "https://www.douyin.com/video/1"
            return None

        worker = VideoAnalysisWorker(
            store,
            analyzer=analyzer,
            url_resolver=public_resolver,
            redirect_fetcher=redirect_fetcher,
        )
        completed = worker.run_once()
        self.assertEqual(completed.job_id, job.job_id)
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(seen["video_url"], "https://www.douyin.com/video/1")

    def test_run_once_analyzes_uploaded_video_without_url_guard(self):
        store = InMemoryJobStore()
        with TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"BRIDGE_UPLOAD_DIR": tmp}):
            stored = store_upload_bytes(b"video bytes", filename="sample.mp4", upload_dir=Path(tmp))
            job = store.create_job("owner", "session", stored.uri)
            worker = VideoAnalysisWorker(store)

            fake_payload = {
                "schema_version": RESULT_SCHEMA_VERSION,
                "source": {"video_url_canonical": stored.uri, "platform": "upload", "duration_seconds": None},
                "summary": "上传视频的真实分析结果",
                "signals": {
                    "hook": None, "topic": None, "audience": None,
                    "structure": None, "visual_notes": "上传视频的真实分析结果", "risk_notes": None,
                },
                "raw_tool_result": {"tool": "openclaw-upload-analyzer", "mode": "files_api", "filename": "sample.mp4", "size_bytes": 11},
                "created_at": "2026-06-10T00:00:00Z",
            }
            captured = {}

            def fake_run(**kwargs):
                captured.update(kwargs)
                return DouyinAnalysisResult(payload=fake_payload, stdout="", stderr="")

            with mock.patch("openclaw_video.worker_service.run_upload_video_analysis", side_effect=fake_run):
                completed = worker.run_once()

            self.assertEqual(completed.job_id, job.job_id)
            self.assertEqual(completed.status, JobStatus.SUCCEEDED)
            result = store.get_result(job.job_id, "owner").result
            self.assertEqual(result["source"]["platform"], "upload")
            self.assertEqual(result["source"]["video_url_canonical"], stored.uri)
            self.assertEqual(result["raw_tool_result"]["mode"], "files_api")
            # the worker passed the local path + upload URI as source label to the analyzer
            self.assertEqual(captured["source_label"], stored.uri)
            self.assertTrue(str(captured["file_path"]).endswith("sample.mp4"))

    def test_run_once_fails_oversize_upload_with_friendly_code(self):
        store = InMemoryJobStore()
        with TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"BRIDGE_UPLOAD_DIR": tmp}):
            stored = store_upload_bytes(b"x" * 2048, filename="big.mp4", upload_dir=Path(tmp))
            job = store.create_job("owner", "session", stored.uri)
            worker = VideoAnalysisWorker(
                store, config=WorkerConfig(max_inline_upload_bytes=1024, heartbeat_interval_seconds=0)
            )

            completed = worker.run_once()

            self.assertEqual(completed.job_id, job.job_id)
            self.assertEqual(completed.status, JobStatus.FAILED)
            self.assertEqual(completed.error_code, "upload_too_large")

    def test_upload_analysis_uses_bailian_key_pool_and_lane(self):
        store = BrokerJobStore()
        with TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "BRIDGE_UPLOAD_DIR": tmp,
                "BAILIAN_API_KEYS": "key-one,key-two",
                "BAILIAN_OPENAI_BASE_URL": "https://example.test/compatible-mode/v1",
                "BAILIAN_MODEL": "model-1",
            },
        ):
            stored = store_upload_bytes(b"video bytes", filename="sample.mp4", upload_dir=Path(tmp))
            job = store.create_job("owner", "session", stored.uri)
            captured = {}
            fake_payload = {
                "schema_version": RESULT_SCHEMA_VERSION,
                "source": {"video_url_canonical": stored.uri, "platform": "upload", "duration_seconds": None},
                "summary": "ok",
                "signals": {
                    "hook": None,
                    "topic": None,
                    "audience": None,
                    "structure": None,
                    "visual_notes": "ok",
                    "risk_notes": None,
                },
                "raw_tool_result": {"tool": "openclaw-upload-analyzer", "mode": "files_api"},
                "created_at": "2026-06-10T00:00:00Z",
            }

            def fake_run(**kwargs):
                captured.update(kwargs)
                return DouyinAnalysisResult(payload=fake_payload, stdout="", stderr="")

            worker = VideoAnalysisWorker(store, config=WorkerConfig(heartbeat_interval_seconds=0))
            with mock.patch("openclaw_video.worker_service.run_upload_video_analysis", side_effect=fake_run):
                completed = worker.run_once()

        self.assertEqual(completed.job_id, job.job_id)
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(captured["env"]["BAILIAN_SELECTED_API_KEY"], "key-one")
        self.assertEqual(captured["env"]["BAILIAN_OPENAI_BASE_URL"], "https://example.test/compatible-mode/v1")
        self.assertEqual(captured["env"]["BAILIAN_MODEL"], "model-1")
        self.assertEqual(store.leases[0]["lane"], "video_model_request")
        self.assertEqual(store.leases[0]["max_concurrent"], 200)
        self.assertEqual(store.released, [("video_model_request", "lease-1")])
        self.assertEqual(len(store.selected), 1)
        self.assertNotIn("key-one", str(store.selected))
        self.assertNotIn("key-two", str(store.selected))

    def test_rate_limit_marks_selected_key_cooldown(self):
        store = BrokerJobStore()
        with TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "BRIDGE_UPLOAD_DIR": tmp,
                "BAILIAN_API_KEYS": "key-one,key-two",
                "BAILIAN_API_KEY_COOLDOWN_SECONDS": "123",
            },
        ):
            stored = store_upload_bytes(b"video bytes", filename="sample.mp4", upload_dir=Path(tmp))
            job = store.create_job("owner", "session", stored.uri)
            worker = VideoAnalysisWorker(store, config=WorkerConfig(heartbeat_interval_seconds=0))
            with mock.patch(
                "openclaw_video.worker_service.run_upload_video_analysis",
                side_effect=ModelRateLimitError("HTTP 429 rate_limit"),
            ):
                completed = worker.run_once()

        self.assertEqual(completed.job_id, job.job_id)
        self.assertEqual(completed.status, JobStatus.TIMED_OUT)
        self.assertEqual(completed.error_code, "tool_timeout")
        self.assertEqual(len(store.rate_limited), 1)
        self.assertEqual(store.rate_limited[0][0], "bailian-openai-compatible")
        self.assertEqual(store.rate_limited[0][2], 123)
        self.assertEqual(store.selected[0][1], store.rate_limited[0][1])
        self.assertNotIn("key-one", str(store.rate_limited))
        self.assertNotIn("key-two", str(store.rate_limited))



if __name__ == "__main__":
    unittest.main()
