from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openclaw_video.douyin_wrapper import DouyinWrapperError, run_douyin_chong, run_upload_video_analysis


class Completed:
    returncode = 0
    stdout = (
        '{"schema_version":"openclaw-video-result.v1",'
        '"source":{"video_url_canonical":"https://www.douyin.com/video/1","platform":"douyin"},'
        '"summary":"ok","signals":{},"created_at":"2026-06-06T00:00:00Z"}'
    )
    stderr = ""


class DouyinWrapperTests(unittest.TestCase):
    def test_runs_fixed_argument_command_with_resource_limits(self):
        with TemporaryDirectory() as tmp, patch("openclaw_video.douyin_wrapper.subprocess.run") as run:
            run.return_value = Completed()
            result = run_douyin_chong(
                video_url="https://www.douyin.com/video/1",
                output_dir=Path(tmp),
                binary="/opt/douyin_chong/douyin_chong",
                timeout_seconds=123,
                max_download_bytes=1000,
                max_duration_seconds=60,
                max_frames=1200,
            )
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(command[0], "/opt/douyin_chong/douyin_chong")
        self.assertIn("--input-url", command)
        self.assertIn("--output-json", command)
        self.assertIn("--max-bytes", command)
        self.assertIn("1000", command)
        self.assertIn("--max-duration-seconds", command)
        self.assertIn("60", command)
        self.assertIn("--max-frames", command)
        self.assertIn("1200", command)
        self.assertIn("--no-shell", command)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 123)
        self.assertEqual(result.payload["schema_version"], "openclaw-video-result.v1")

    def test_adds_explicit_env_file_only_when_configured(self):
        with (
            TemporaryDirectory() as tmp,
            patch("openclaw_video.douyin_wrapper.subprocess.run") as run,
            patch.dict("openclaw_video.douyin_wrapper.os.environ", {"DOUYIN_CHONG_ENV_FILE": "/run/secrets/env"}, clear=True),
        ):
            run.return_value = Completed()
            run_douyin_chong(
                video_url="https://www.douyin.com/video/1",
                output_dir=Path(tmp),
                binary="/usr/local/bin/openclaw-douyin-adapter",
            )
        command = run.call_args.args[0]
        self.assertIn("--env-file", command)
        self.assertIn("/run/secrets/env", command)
        self.assertLess(command.index("--env-file"), command.index("--no-shell"))

    def test_rejects_non_positive_resource_limits(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(DouyinWrapperError):
                run_douyin_chong(
                    video_url="https://www.douyin.com/video/1",
                    output_dir=Path(tmp),
                    binary="/opt/douyin_chong/douyin_chong",
                    max_download_bytes=0,
                )

    def test_subprocess_timeout_maps_to_timeout_error(self):
        with TemporaryDirectory() as tmp, patch("openclaw_video.douyin_wrapper.subprocess.run") as run:
            run.side_effect = subprocess.TimeoutExpired(cmd=["douyin_chong"], timeout=1)
            with self.assertRaises(TimeoutError):
                run_douyin_chong(
                    video_url="https://www.douyin.com/video/1",
                    output_dir=Path(tmp),
                    binary="/opt/douyin_chong/douyin_chong",
                    timeout_seconds=1,
                )

    def test_invalid_schema_is_rejected_in_wrapper(self):
        class InvalidCompleted:
            returncode = 0
            stdout = '{"schema_version":"wrong"}'
            stderr = ""

        with TemporaryDirectory() as tmp, patch("openclaw_video.douyin_wrapper.subprocess.run") as run:
            run.return_value = InvalidCompleted()
            with self.assertRaises(ValueError):
                run_douyin_chong(
                    video_url="https://www.douyin.com/video/1",
                    output_dir=Path(tmp),
                    binary="/opt/douyin_chong/douyin_chong",
                )


class UploadCompleted:
    returncode = 0
    stdout = (
        '{"schema_version":"openclaw-video-result.v1",'
        '"source":{"video_url_canonical":"upload://x/clip.mp4","platform":"upload"},'
        '"summary":"ok","signals":{},"created_at":"2026-06-10T00:00:00Z"}'
    )
    stderr = ""


class UploadAnalysisWrapperTests(unittest.TestCase):
    def test_upload_analysis_builds_input_file_command(self):
        with TemporaryDirectory() as tmp, patch("openclaw_video.douyin_wrapper.subprocess.run") as run:
            run.return_value = UploadCompleted()
            result = run_upload_video_analysis(
                file_path="/data/uploads/x/clip.mp4",
                output_dir=Path(tmp),
                source_label="upload://x/clip.mp4",
                binary="/usr/local/bin/openclaw-douyin-adapter",
                env_file="/run/secrets/env",
                timeout_seconds=123,
                max_bytes=1000,
            )
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(command[0], "/usr/local/bin/openclaw-douyin-adapter")
        self.assertIn("--input-file", command)
        self.assertIn("/data/uploads/x/clip.mp4", command)
        self.assertIn("--source-label", command)
        self.assertIn("upload://x/clip.mp4", command)
        self.assertIn("--max-bytes", command)
        self.assertIn("1000", command)
        self.assertIn("--env-file", command)
        self.assertIn("/run/secrets/env", command)
        self.assertIn("--no-shell", command)
        self.assertNotIn("--input-url", command)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 123)
        self.assertEqual(result.payload["source"]["platform"], "upload")

    def test_upload_analysis_requires_binary_and_env(self):
        with TemporaryDirectory() as tmp, patch.dict("openclaw_video.douyin_wrapper.os.environ", {}, clear=True):
            with self.assertRaises(DouyinWrapperError):
                run_upload_video_analysis(
                    file_path="/x.mp4",
                    output_dir=Path(tmp),
                    source_label="upload://x/clip.mp4",
                    binary=None,
                )


if __name__ == "__main__":
    unittest.main()
