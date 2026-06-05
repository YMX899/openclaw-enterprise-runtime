import unittest
from pathlib import Path

from openclaw_video.douyin_wrapper import DouyinAnalysisResult
from openclaw_video.job_state import JobStatus
from openclaw_video.job_store import InMemoryJobStore
from openclaw_video.result_schema import RESULT_SCHEMA_VERSION
from openclaw_video.worker_service import VideoAnalysisWorker


def public_resolver(_host: str, _port: int | None) -> list[str]:
    return ["110.242.68.66"]


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


class WorkerServiceTests(unittest.TestCase):
    def test_run_once_succeeds(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(store, analyzer=ok_analyzer, url_resolver=public_resolver)
        completed = worker.run_once()
        self.assertEqual(completed.job_id, job.job_id)
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(store.get_result(job.job_id, "owner").schema_version, RESULT_SCHEMA_VERSION)

    def test_run_once_rejects_bad_url(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://example.com/video")
        worker = VideoAnalysisWorker(store, analyzer=ok_analyzer)
        failed = worker.run_once()
        self.assertEqual(failed.job_id, job.job_id)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.error_code, "url_rejected")

    def test_run_once_fails_invalid_result(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(store, analyzer=invalid_analyzer, url_resolver=public_resolver)
        failed = worker.run_once()
        self.assertEqual(failed.job_id, job.job_id)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(failed.error_code, "tool_failed")

    def test_run_once_marks_timeout(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        worker = VideoAnalysisWorker(store, analyzer=timeout_analyzer, url_resolver=public_resolver)
        failed = worker.run_once()
        self.assertEqual(failed.job_id, job.job_id)
        self.assertEqual(failed.status, JobStatus.TIMED_OUT)
        self.assertEqual(failed.error_code, "tool_timeout")


if __name__ == "__main__":
    unittest.main()
