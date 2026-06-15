import unittest
from unittest import mock

from openclaw_video.worker_main import resolve_worker_id


class WorkerMainTests(unittest.TestCase):
    def test_resolve_worker_id_prefers_explicit_env(self):
        with mock.patch.dict("os.environ", {"WORKER_ID": "worker-explicit", "HOSTNAME": "container-host"}):
            self.assertEqual(resolve_worker_id(), "worker-explicit")

    def test_resolve_worker_id_uses_container_hostname(self):
        with mock.patch.dict("os.environ", {"HOSTNAME": "openclaw-video-video-analysis-worker-3"}, clear=True):
            self.assertEqual(resolve_worker_id(), "openclaw-video-video-analysis-worker-3")

    def test_resolve_worker_id_falls_back_to_socket_hostname(self):
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch("openclaw_video.worker_main.socket.gethostname", return_value="runtime-host"),
        ):
            self.assertEqual(resolve_worker_id(), "runtime-host")


if __name__ == "__main__":
    unittest.main()
