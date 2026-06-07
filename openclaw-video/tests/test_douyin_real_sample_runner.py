import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_douyin_real_sample.py"
spec = importlib.util.spec_from_file_location("run_douyin_real_sample", SCRIPT_PATH)
real_sample = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(real_sample)


FAKE_ADAPTER = r"""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input-url", required=True)
parser.add_argument("--output-json", required=True)
parser.add_argument("--max-bytes", required=True)
parser.add_argument("--max-duration-seconds", required=True)
parser.add_argument("--max-frames", required=True)
parser.add_argument("--env-file", required=True)
parser.add_argument("--no-shell", action="store_true", required=True)
args = parser.parse_args()
Path(args.output_json).write_text(json.dumps({
    "schema_version": "openclaw-video-result.v1",
    "source": {
        "video_url_canonical": args.input_url,
        "platform": "douyin",
        "duration_seconds": 12.5,
    },
    "summary": "sample analysis",
    "signals": {"hook": None, "topic": None, "audience": None, "structure": None, "visual_notes": None, "risk_notes": None},
    "raw_tool_result": {"tool": "fake"},
    "created_at": datetime.now(UTC).isoformat(),
}, ensure_ascii=False), encoding="utf-8")
"""


FAKE_FAILING_ADAPTER = r"""
import sys

print("ArkAuthenticationError: status_code: 401 authentication failed", file=sys.stderr)
raise SystemExit(2)
"""


class DouyinRealSampleRunnerTests(unittest.TestCase):
    def test_success_writes_sanitized_evidence_without_secret_contents(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = root / "fake_adapter.py"
            adapter.write_text(textwrap.dedent(FAKE_ADAPTER), encoding="utf-8")
            env_file = root / "douyin.env"
            env_file.write_text("ARK_API_KEY=secret-value-that-must-not-appear\n", encoding="utf-8")
            output_dir = root / "out"

            args = real_sample.build_parser().parse_args(
                [
                    "--input-url", "https://www.douyin.com/video/123",
                    "--env-file", str(env_file),
                    "--adapter-bin", str(adapter),
                    "--output-dir", str(output_dir),
                ]
            )
            exit_code, summary = real_sample.run(args)

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["status"], "succeeded")
            self.assertEqual(summary["result"]["schema_version"], "openclaw-video-result.v1")
            self.assertEqual(summary["result"]["summary_chars"], len("sample analysis"))
            evidence = json.loads((output_dir / "sanitized-run.json").read_text(encoding="utf-8"))
            evidence_text = json.dumps(evidence, ensure_ascii=False)
            self.assertNotIn("secret-value-that-must-not-appear", evidence_text)
            self.assertNotIn("https://www.douyin.com/video/123", evidence_text)
            self.assertFalse(evidence["secret_file_contents_recorded"])
            self.assertFalse(evidence["process"]["stdout_recorded"])
            self.assertFalse(evidence["process"]["stderr_recorded"])

    def test_missing_env_file_fails_without_running_adapter(self):
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            args = real_sample.build_parser().parse_args(
                [
                    "--input-url", "https://www.douyin.com/video/123",
                    "--env-file", str(Path(tmp) / "missing.env"),
                    "--adapter-bin", str(Path(tmp) / "missing_adapter.py"),
                    "--output-dir", str(output_dir),
                ]
            )
            exit_code, summary = real_sample.run(args)

            self.assertEqual(exit_code, 2)
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["error_code"], "env_file_missing")
            self.assertTrue((output_dir / "sanitized-run.json").exists())

    def test_adapter_failure_records_only_sanitized_error_categories(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = root / "failing_adapter.py"
            adapter.write_text(textwrap.dedent(FAKE_FAILING_ADAPTER), encoding="utf-8")
            env_file = root / "douyin.env"
            env_file.write_text("ARK_API_KEY=secret-value-that-must-not-appear\n", encoding="utf-8")
            output_dir = root / "out"

            args = real_sample.build_parser().parse_args(
                [
                    "--input-url", "https://www.douyin.com/video/123",
                    "--env-file", str(env_file),
                    "--adapter-bin", str(adapter),
                    "--output-dir", str(output_dir),
                ]
            )
            exit_code, summary = real_sample.run(args)

            self.assertEqual(exit_code, 2)
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["error_code"], "adapter_nonzero_exit")
            self.assertIn("http_401", summary["error_categories"])
            self.assertIn("authentication", summary["error_categories"])
            evidence = json.loads((output_dir / "sanitized-run.json").read_text(encoding="utf-8"))
            evidence_text = json.dumps(evidence, ensure_ascii=False)
            self.assertNotIn("secret-value-that-must-not-appear", evidence_text)
            self.assertNotIn("ArkAuthenticationError", evidence_text)
            self.assertFalse(evidence["process"]["stdout_recorded"])
            self.assertFalse(evidence["process"]["stderr_recorded"])


if __name__ == "__main__":
    unittest.main()
