from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openclaw_video.agent_video_cli import run_cli
from openclaw_video.douyin_legacy_adapter import LegacyAdapterError


@dataclass(frozen=True)
class FakeArgs:
    input_url: str
    output_json: str


def fake_payload(input_url: str) -> dict:
    return {
        "schema_version": "openclaw-video-result.v1",
        "source": {
            "video_url_canonical": input_url,
            "platform": "douyin",
            "duration_seconds": 12.3,
        },
        "summary": "分析结果",
        "signals": {
            "hook": "开头强",
            "topic": "主题",
            "audience": "受众",
            "structure": "结构",
            "visual_notes": "画面",
            "risk_notes": None,
        },
        "raw_tool_result": {
            "adapter": "openclaw_video.douyin_legacy_adapter",
            "content_type": "video/mp4",
            "size_bytes": 1234,
            "video_url_source": "direct",
            "request_id": "req-1",
            "usage": {"total_tokens": 10},
            "limits": {
                "max_download_bytes": 10000,
                "max_duration_seconds": 300,
                "max_frames": 6000,
                "fps": 4.0,
            },
        },
        "created_at": "2026-06-07T00:00:00+00:00",
    }


class AgentVideoCliTests(unittest.TestCase):
    def test_cli_returns_sanitized_success_payload(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            raw_url = "https://v.douyin.com/abc?token=secret"

            def fake_run_adapter(argv):
                self.assertIn("--no-shell", argv)
                return fake_payload(raw_url)

            with patch("openclaw_video.agent_video_cli.run_adapter", side_effect=fake_run_adapter):
                code, payload = run_cli(["--input-url", raw_url, "--env-file", str(env_file)])

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["analysis"]["summary"], "分析结果")
        self.assertTrue(payload["analysis"]["tool_meta"]["request_id_present"])
        self.assertFalse(payload["input"]["raw_input_url_recorded"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(raw_url, serialized)
        self.assertNotIn("token=secret", serialized)

    def test_cli_returns_sanitized_failure_payload(self):
        raw_url = "https://v.douyin.com/abc?token=secret"
        with patch(
            "openclaw_video.agent_video_cli.run_adapter",
            side_effect=LegacyAdapterError(f"Could not extract video id from URL: {raw_url}"),
        ):
            code, payload = run_cli(["--input-url", raw_url, "--env-file", "/missing"])

        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["error_code"], "douyin_resolver_failed")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(raw_url, serialized)
        self.assertNotIn("token=secret", serialized)
        self.assertIn("[redacted-url]", payload["error_message"])


if __name__ == "__main__":
    unittest.main()
