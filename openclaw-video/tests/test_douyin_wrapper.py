from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openclaw_video.douyin_wrapper import DouyinWrapperError, run_douyin_chong


class Completed:
    returncode = 0
    stdout = '{"schema_version":"openclaw-video-analysis.v1"}'
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
        self.assertEqual(result.payload["schema_version"], "openclaw-video-analysis.v1")

    def test_rejects_non_positive_resource_limits(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(DouyinWrapperError):
                run_douyin_chong(
                    video_url="https://www.douyin.com/video/1",
                    output_dir=Path(tmp),
                    binary="/opt/douyin_chong/douyin_chong",
                    max_download_bytes=0,
                )


if __name__ == "__main__":
    unittest.main()
