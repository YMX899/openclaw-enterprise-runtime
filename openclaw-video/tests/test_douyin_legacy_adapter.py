from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import openclaw_video.douyin_legacy_adapter as adapter_module
from openclaw_video.douyin_legacy_adapter import (
    LegacyAdapterError,
    _canonicalize_input_for_resolver,
    _load_legacy_components,
    run_adapter,
)


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
    env_snapshots = []

    @classmethod
    def from_env(cls, **kwargs):
        cls.calls.append(kwargs)
        cls.env_snapshots.append(
            {
                key: adapter_module.os.environ.get(key)
                for key in ("ARK_API_KEY", "MEDIAKIT_API_KEY", "MODEL", "ARK_MODEL", "ARK_BASE_URL", "MEDIAKIT_BASE_URL")
            }
        )
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
        FakeConfig.env_snapshots = []
        FakeArkClient.calls = []
        FakeResolver.video = FakeVideo()
        FakeArkClient.completion = FakeCompletion()

    def test_vendored_candidate_components_are_importable(self):
        vendor_root = Path(__file__).resolve().parents[1] / "vendor"
        with patch.dict("openclaw_video.douyin_legacy_adapter.os.environ", {"DOUYIN_CHONG_PYTHONPATH": str(vendor_root)}):
            AppConfig, UniversalVideoResolver, ArkVideoClient = _load_legacy_components()
        self.assertEqual(AppConfig.__name__, "AppConfig")
        self.assertEqual(UniversalVideoResolver.__name__, "UniversalVideoResolver")
        self.assertEqual(ArkVideoClient.__name__, "ArkVideoClient")

    def test_vendored_douyin_resolver_builds_shortlink_candidates_from_redirect_url(self):
        from douyin_chong.clients.douyin import DouyinVideoResolver

        resolver = DouyinVideoResolver()
        candidates = resolver._build_page_candidates(
            source_url="https://v.douyin.com/lx-ONOPrxjU/",
            normalized_url="https://v.douyin.com/lx-ONOPrxjU/",
            share_url="https://www.iesdouyin.com/share/video/7648317087237562266/?from_ssr=1",
        )

        self.assertIn("https://www.iesdouyin.com/share/video/7648317087237562266/", candidates)

    def test_vendored_douyin_resolver_extracts_note_id(self):
        from douyin_chong.clients.douyin import DouyinVideoResolver

        resolver = DouyinVideoResolver()

        self.assertEqual(
            resolver._extract_video_id("https://www.douyin.com/note/7648317087237562266?previous_page=web_code_link"),
            "7648317087237562266",
        )

    def test_shortlink_is_canonicalized_before_legacy_resolver(self):
        with patch(
            "openclaw_video.douyin_legacy_adapter.validate_video_url_with_redirects"
        ) as validator:
            validator.return_value = type(
                "Validated",
                (),
                {"canonical": "https://www.iesdouyin.com/share/video/7648317087237562266/?from_ssr=1"},
            )()
            self.assertEqual(
                _canonicalize_input_for_resolver("https://v.douyin.com/lx-ONOPrxjU/"),
                "https://www.iesdouyin.com/share/video/7648317087237562266/?from_ssr=1",
            )

        self.assertEqual(
            _canonicalize_input_for_resolver("https://www.douyin.com/video/7648317087237562266"),
            "https://www.douyin.com/video/7648317087237562266",
        )

    def test_writes_committed_result_schema_without_default_env(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            output_json = Path(tmp) / "result.json"

            with patch.dict(
                "openclaw_video.douyin_legacy_adapter.os.environ",
                {
                    "ARK_API_KEY": "ambient-should-not-leak",
                    "MODEL": "ambient-model",
                },
                clear=False,
            ):
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
                self.assertEqual(adapter_module.os.environ["ARK_API_KEY"], "ambient-should-not-leak")
            written_payload = json.loads(output_json.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "openclaw-video-result.v1")
        self.assertEqual(payload["source"]["platform"], "douyin")
        self.assertEqual(payload["summary"], "分析结果")
        self.assertEqual(written_payload, payload)
        self.assertEqual(FakeConfig.env_snapshots[0]["ARK_API_KEY"], None)
        self.assertEqual(FakeConfig.env_snapshots[0]["MODEL"], None)
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

    def test_unknown_size_uses_bounded_stream_probe(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            output_json = Path(tmp) / "result.json"
            FakeResolver.video = FakeVideo(size_mb=None)

            with patch(
                "openclaw_video.douyin_legacy_adapter._probe_stream_size_bytes",
                return_value=1536,
            ) as probe:
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

        probe.assert_called_once_with("https://video.example/video.mp4", max_bytes=2000000)
        self.assertEqual(payload["raw_tool_result"]["size_bytes"], 1536)
        self.assertEqual(payload["schema_version"], "openclaw-video-result.v1")

    def test_unknown_size_probe_failure_fails_closed(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            FakeResolver.video = FakeVideo(size_mb=None)

            with patch(
                "openclaw_video.douyin_legacy_adapter._probe_stream_size_bytes",
                side_effect=LegacyAdapterError("video size exceeds limit"),
            ):
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


    def test_input_file_inline_analysis_builds_upload_payload(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            video_file = Path(tmp) / "clip.mp4"
            video_file.write_bytes(b"fake-video-bytes")
            output_json = Path(tmp) / "result.json"

            payload = run_adapter(
                [
                    "--input-file", str(video_file),
                    "--source-label", "upload://abc/clip.mp4",
                    "--output-json", str(output_json),
                    "--max-bytes", "2000000",
                    "--env-file", str(env_file),
                    "--no-shell",
                ],
                component_loader=fake_components,
            )

        self.assertEqual(payload["schema_version"], "openclaw-video-result.v1")
        self.assertEqual(payload["source"]["platform"], "upload")
        self.assertEqual(payload["source"]["video_url_canonical"], "upload://abc/clip.mp4")
        self.assertEqual(payload["summary"], "分析结果")
        self.assertEqual(payload["raw_tool_result"]["mode"], "inline-base64")
        self.assertEqual(payload["raw_tool_result"]["filename"], "clip.mp4")
        # the model received an inline base64 data: URL, not a resolved link
        sent_url = FakeArkClient.calls[0]["video_urls"][0]
        self.assertTrue(sent_url.startswith("data:video/mp4;base64,"))

    def test_input_file_too_large_fails_closed(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            video_file = Path(tmp) / "big.mp4"
            video_file.write_bytes(b"x" * 2000)
            with self.assertRaises(LegacyAdapterError):
                run_adapter(
                    [
                        "--input-file", str(video_file),
                        "--output-json", str(Path(tmp) / "result.json"),
                        "--max-bytes", "1000",
                        "--env-file", str(env_file),
                        "--no-shell",
                    ],
                    component_loader=fake_components,
                )

    def test_requires_exactly_one_input(self):
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "douyin.env"
            env_file.write_text("ARK_API_KEY=test\n", encoding="utf-8")
            # neither --input-url nor --input-file
            with self.assertRaises(LegacyAdapterError):
                run_adapter(
                    [
                        "--output-json", str(Path(tmp) / "r.json"),
                        "--max-bytes", "2000000",
                        "--env-file", str(env_file),
                        "--no-shell",
                    ],
                    component_loader=fake_components,
                )
            # both at once
            with self.assertRaises(LegacyAdapterError):
                run_adapter(
                    [
                        "--input-url", "https://www.douyin.com/video/1",
                        "--input-file", str(env_file),
                        "--output-json", str(Path(tmp) / "r2.json"),
                        "--max-bytes", "2000000",
                        "--env-file", str(env_file),
                        "--no-shell",
                    ],
                    component_loader=fake_components,
                )


if __name__ == "__main__":
    unittest.main()
