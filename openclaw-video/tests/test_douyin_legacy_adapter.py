from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openclaw_video.douyin_legacy_adapter import LegacyAdapterError, run_adapter


@dataclass(frozen=True)
class FakeVideo:
    source_url: str = "https://www.douyin.com/video/1"
    video_id: str = "1"
    share_url: str = "https://www.iesdouyin.com/share/video/1/"
    playwm_url: str = "https://video.example/wm.mp4"
    video_url: str = "https://video.example/video.mp4"
    author: str = "author"
    desc: str = "desc"
    duration_ms: int = 30000
    content_type: str = "video/mp4"
    size_mb: float = 1.5
    video_url_source: str = "direct"


@dataclass(frozen=True)
class FakeCompletion:
    output_text: str = "分析结果"
    usage: dict | None = None
    request_id: str = "req-1"
    error_message: str = ""
    api_error_message: str = ""


class FakeConfig:
    calls = []

    @classmethod
    def from_env(cls, **kwargs):
        cls.calls.append(kwargs)
        return {"config": kwargs}


class FakeResolver:
    video = FakeVideo()

    def resolve(self, source_url):
        return self.video


class FakeArkClient:
    calls = []
    completion = FakeCompletion()

    def __init__(self, config):
        self.config = config

    def analyze(self, *, video_urls, prompt):
        self.calls.append({"video_urls": video_urls, "prompt": prompt})
        return self.completion


def fake_components():
    return FakeConfig, FakeResolver, FakeArkClient


class DouyinLegacyAdapterTests(unittest.TestCase):
    def setUp(self):
        FakeConfig.calls = []
        FakeArkClient.calls = []
        FakeResolver.video = FakeVideo()
        FakeArkClient.completion = FakeCompletion()

    def test_writes_committed_result_schema_without_default_env(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            output_json = Path(tmp) / "result.json"

            payload = run_adapter(
                [
                    "--input-url", "https://www.douyin.com/video/1",
                    "--output-json", str(output_json),
                    "--max-bytes", "2000000",
                    "--max-duration-seconds", "60",
                    "--max-frames", "1200",
                    "--env-file", str(env_file),
                    "--no-shell",
                ],
                component_loader=fake_components,
            )
            written_payload = json.loads(output_json.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "openclaw-video-result.v1")
        self.assertEqual(payload["source"]["platform"], "douyin")
        self.assertEqual(payload["summary"], "分析结果")
        self.assertEqual(written_payload, payload)
        config_call = FakeConfig.calls[0]
        self.assertEqual(config_call["env_path"], env_file.resolve())
        self.assertEqual(config_call["max_workers"], 1)
        self.assertEqual(config_call["fps"], 4.0)
        self.assertIn("https://video.example/video.mp4", FakeArkClient.calls[0]["video_urls"])

    def test_missing_explicit_env_file_fails_closed(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(LegacyAdapterError):
                run_adapter(
                    [
                        "--input-url", "https://www.douyin.com/video/1",
                        "--output-json", str(Path(tmp) / "result.json"),
                        "--max-bytes", "2000000",
                        "--max-duration-seconds", "60",
                        "--max-frames", "1200",
                        "--env-file", str(Path(tmp) / "missing.env"),
                        "--no-shell",
                    ],
                    component_loader=fake_components,
                )

    def test_duration_size_and_frame_limits_fail_closed(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            FakeResolver.video = FakeVideo(duration_ms=61000, size_mb=1)
            with self.assertRaises(LegacyAdapterError):
                run_adapter(
                    [
                        "--input-url", "https://www.douyin.com/video/1",
                        "--output-json", str(Path(tmp) / "result.json"),
                        "--max-bytes", "2000000",
                        "--max-duration-seconds", "60",
                        "--max-frames", "1200",
                        "--env-file", str(env_file),
                        "--no-shell",
                    ],
                    component_loader=fake_components,
                )

            FakeResolver.video = FakeVideo(duration_ms=30000, size_mb=3)
            with self.assertRaises(LegacyAdapterError):
                run_adapter(
                    [
                        "--input-url", "https://www.douyin.com/video/1",
                        "--output-json", str(Path(tmp) / "result.json"),
                        "--max-bytes", "2000000",
                        "--max-duration-seconds", "60",
                        "--max-frames", "1200",
                        "--env-file", str(env_file),
                        "--no-shell",
                    ],
                    component_loader=fake_components,
                )

    def test_empty_legacy_output_fails_closed(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            FakeArkClient.completion = FakeCompletion(output_text="", api_error_message="model failed")
            with self.assertRaises(LegacyAdapterError):
                run_adapter(
                    [
                        "--input-url", "https://www.douyin.com/video/1",
                        "--output-json", str(Path(tmp) / "result.json"),
                        "--max-bytes", "2000000",
                        "--max-duration-seconds", "60",
                        "--max-frames", "1200",
                        "--env-file", str(env_file),
                        "--no-shell",
                    ],
                    component_loader=fake_components,
                )


if __name__ == "__main__":
    unittest.main()
