import importlib.util
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "promote_douyin_real_sample_evidence.py"
spec = importlib.util.spec_from_file_location("promote_douyin_real_sample_evidence", SCRIPT_PATH)
promotion = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = promotion
spec.loader.exec_module(promotion)


def valid_evidence() -> dict:
    return {
        "schema_version": "douyin-real-sample-evidence.v1",
        "created_at": "2026-06-06T00:00:00+00:00",
        "status": "succeeded",
        "input_url_sha256": "a" * 64,
        "input_url_host": "www.douyin.com",
        "env_file_present": True,
        "secret_file_contents_recorded": False,
        "adapter_bin_name": "openclaw-douyin-adapter",
        "output_dir": "tmp/douyin-real-samples/sample",
        "result_json": "tmp/douyin-real-samples/sample/result.json",
        "limits": {
            "timeout_seconds": 900,
            "max_bytes": 536870912,
            "max_duration_seconds": 60,
            "max_frames": 1200,
        },
        "process": {
            "returncode": 0,
            "elapsed_seconds": 12.3,
            "stdout_chars": 0,
            "stderr_chars": 0,
            "stdout_recorded": False,
            "stderr_recorded": False,
            "max_rss_kb_before": 0,
            "max_rss_kb_after": 123456,
        },
        "result": {
            "schema_version": "openclaw-video-result.v1",
            "platform": "douyin",
            "duration_seconds": 12.5,
            "summary_chars": 15,
            "signals_keys": ["audience", "hook", "risk_notes", "structure", "topic", "visual_notes"],
            "result_json_bytes": 1234,
            "result_json_sha256": "b" * 64,
            "raw_tool_result_keys": ["tool"],
        },
    }


class DouyinRealSamplePromotionTests(unittest.TestCase):
    def test_promotes_sanitized_evidence_and_strips_local_paths(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sanitized-run.json"
            dest = root / "REAL_SAMPLE_EVIDENCE.json"
            source.write_text(json.dumps(valid_evidence()), encoding="utf-8")

            args = promotion.build_parser().parse_args(["--source", str(source), "--dest", str(dest)])
            with redirect_stdout(StringIO()):
                exit_code = promotion.run(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "douyin-real-sample-evidence.v1")
            self.assertEqual(payload["status"], "succeeded")
            self.assertNotIn("output_dir", payload)
            self.assertNotIn("result_json", payload)
            self.assertRegex(payload["source_evidence_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("promoted_at", payload)

    def test_rejects_raw_http_url(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sanitized-run.json"
            dest = root / "REAL_SAMPLE_EVIDENCE.json"
            evidence = valid_evidence()
            evidence["raw_url"] = "http://www.douyin.com/video/123"
            source.write_text(json.dumps(evidence), encoding="utf-8")

            args = promotion.build_parser().parse_args(["--source", str(source), "--dest", str(dest)])

            with self.assertRaises(promotion.EvidenceError):
                promotion.run(args)

            self.assertFalse(dest.exists())

    def test_refuses_to_overwrite_without_force(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sanitized-run.json"
            dest = root / "REAL_SAMPLE_EVIDENCE.json"
            source.write_text(json.dumps(valid_evidence()), encoding="utf-8")
            dest.write_text("existing\n", encoding="utf-8")

            args = promotion.build_parser().parse_args(["--source", str(source), "--dest", str(dest)])

            with self.assertRaises(promotion.EvidenceError):
                promotion.run(args)

            self.assertEqual(dest.read_text(encoding="utf-8"), "existing\n")

    def test_dry_run_validates_without_writing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sanitized-run.json"
            dest = root / "REAL_SAMPLE_EVIDENCE.json"
            source.write_text(json.dumps(valid_evidence()), encoding="utf-8")

            args = promotion.build_parser().parse_args(
                ["--source", str(source), "--dest", str(dest), "--dry-run"]
            )
            with redirect_stdout(StringIO()):
                exit_code = promotion.run(args)

            self.assertEqual(exit_code, 0)
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
