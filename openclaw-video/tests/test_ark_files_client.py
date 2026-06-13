import unittest
from unittest.mock import patch

from openclaw_video.ark_files_client import ArkFileProcessingError, ArkFilesClient


class ArkFilesClientTests(unittest.TestCase):
    def test_wait_file_active_polls_processing_until_active(self):
        client = ArkFilesClient(api_key="test")
        statuses = [{"id": "file-1", "status": "processing"}, {"id": "file-1", "status": "active"}]
        with (
            patch.object(ArkFilesClient, "retrieve_file", side_effect=lambda _file_id: statuses.pop(0)) as retrieve,
            patch("openclaw_video.ark_files_client.time.sleep") as sleep,
        ):
            result = client.wait_file_active("file-1", timeout_seconds=10, poll_interval_seconds=0.1)
        self.assertEqual(result["status"], "active")
        self.assertEqual(retrieve.call_count, 2)
        sleep.assert_called_once_with(0.1)

    def test_wait_file_active_rejects_failed_and_unknown_status(self):
        client = ArkFilesClient(api_key="test")
        with patch.object(ArkFilesClient, "retrieve_file", return_value={"id": "file-1", "status": "failed"}):
            with self.assertRaisesRegex(ArkFileProcessingError, "failed"):
                client.wait_file_active("file-1", timeout_seconds=10)
        with patch.object(ArkFilesClient, "retrieve_file", return_value={"id": "file-1", "status": "queued"}):
            with self.assertRaisesRegex(ArkFileProcessingError, "queued"):
                client.wait_file_active("file-1", timeout_seconds=10)

    def test_wait_file_active_times_out_while_processing(self):
        client = ArkFilesClient(api_key="test")
        with (
            patch.object(ArkFilesClient, "retrieve_file", return_value={"id": "file-1", "status": "processing"}),
            patch("openclaw_video.ark_files_client.time.monotonic", side_effect=[0, 2]),
        ):
            with self.assertRaisesRegex(TimeoutError, "processing"):
                client.wait_file_active("file-1", timeout_seconds=1)

    def test_create_video_response_sends_input_video_file_id(self):
        client = ArkFilesClient(api_key="test-key", base_url="https://ark.example/api/v3", timeout_seconds=12)

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"id": "resp-1", "output_text": "ok"}

        with patch("openclaw_video.ark_files_client.requests.post", return_value=Response()) as post:
            payload = client.create_video_response(model="model-1", file_id="file-1", prompt="请分析", fps=2.0)

        self.assertEqual(payload["id"], "resp-1")
        request = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], "https://ark.example/api/v3/responses")
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(request["timeout"], 12)
        self.assertEqual(request["json"]["model"], "model-1")
        content = request["json"]["input"][0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": "请分析"})
        self.assertEqual(content[1], {"type": "input_video", "file_id": "file-1", "fps": 2.0})
        self.assertEqual(request["json"]["max_output_tokens"], 12000)
        self.assertNotIn("max_tokens", request["json"])


if __name__ == "__main__":
    unittest.main()
