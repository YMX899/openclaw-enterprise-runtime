import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_phase1_5_host_readiness.py"
spec = importlib.util.spec_from_file_location("check_phase1_5_host_readiness", SCRIPT_PATH)
host_readiness = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = host_readiness
spec.loader.exec_module(host_readiness)


class HostReadinessTests(unittest.TestCase):
    def test_docker_format_placeholder_is_no_go(self):
        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            result = host_readiness.check_docker(lambda command: (0, "Docker server={{.Server.Version}}", ""))

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("not evaluated", result.evidence)

    def test_docker_engine_passes_when_server_version_returns(self):
        with mock.patch("shutil.which", return_value="/usr/bin/docker"):
            result = host_readiness.check_docker(lambda command: (0, "Docker server=28.1.1", ""))

        self.assertEqual(result.status, "PASS")
        self.assertIn("28.1.1", result.evidence)

    def test_disk_free_requires_threshold(self):
        low_bytes = str(5 * 1024**3)
        result = host_readiness.check_disk(20, lambda command: (0, low_bytes, ""))

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("need 20GiB", result.evidence)

    def test_memory_requires_threshold(self):
        low_bytes = str(4 * 1024**3)
        result = host_readiness.check_memory(8, lambda command: (0, low_bytes, ""))

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("need 8GiB", result.evidence)

    def test_os_requires_linux_x86_64(self):
        with mock.patch("platform.system", return_value="Darwin"), mock.patch(
            "platform.machine", return_value="arm64"
        ):
            result = host_readiness.check_os()

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("expected Linux", result.evidence)


if __name__ == "__main__":
    unittest.main()
