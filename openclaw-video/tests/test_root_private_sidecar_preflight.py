import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "preflight_root_private_sidecar.py"
spec = importlib.util.spec_from_file_location("preflight_root_private_sidecar", SCRIPT_PATH)
preflight_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = preflight_module
spec.loader.exec_module(preflight_module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


PASS_UBUNTU_AUDIT = {
    "overall": "PASS",
    "checks": [
        {"check_id": "openclaw_security", "status": "PASS"},
        {"check_id": "douyin_artifact", "status": "PASS"},
        {"check_id": "douyin_current_phase", "status": "PASS"},
        {"check_id": "phase1_5_exit_proof", "status": "PASS"},
        {"check_id": "ubuntu22_dify_authenticated_baseline", "status": "PASS"},
        {"check_id": "openresty_no_route_change", "status": "PASS"},
    ],
}


MIN_COMPOSE = """
name: openclaw-video

services:
  openclaw-bridge:
    environment:
      OPENCLAW_GATEWAY_URL: ws://openclaw-gateway:18789
      OPENCLAW_GATEWAY_TOKEN_FILE: /run/secrets/openclaw_gateway_token
      OPENCLAW_GATEWAY_DEVICE_KEY_FILE: /run/secrets/openclaw_bridge_device_key.pem
      DOUYIN_CHONG_ENV_FILE: /run/secrets/douyin_chong_env
      WORKER_CONCURRENCY: "1"
    ports:
      - "127.0.0.1:18181:3000"
    volumes:
      - ../artifacts/knowledge-base-short-video/2026.06.06:/knowledge/short-video:ro
    networks:
      - openclaw-internal
      - dify-default
  bridge-postgres:
    image: postgres:15-alpine
    ports: []
    networks:
      - openclaw-internal
  openclaw-gateway:
    ports: []
    networks:
      - openclaw-internal
  video-analysis-worker:
    networks:
      - openclaw-internal

networks:
  openclaw-internal:
    name: openclaw_video_internal
  dify-default:
    external: true
    name: ${DIFY_DOCKER_NETWORK:-docker_default}
"""


class RootPrivateSidecarPreflightTests(unittest.TestCase):
    def test_rejects_non_root_target(self):
        result = preflight_module.check_target_host("ubuntu22.04")

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("root", result.evidence)

    def test_private_compose_contract_passes_minimal_private_shape(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "openclaw-video/docker-compose.openclaw-video.yaml", MIN_COMPOSE)

            result = preflight_module.check_private_compose_contract(repo)

        self.assertEqual(result.status, "PASS")

    def test_private_compose_contract_rejects_public_gateway_port(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "openclaw-video/docker-compose.openclaw-video.yaml",
                MIN_COMPOSE.replace("ports: []", 'ports:\n      - "0.0.0.0:18789:18789"', 1),
            )

            result = preflight_module.check_private_compose_contract(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("0.0.0.0:18789", result.evidence)

    def test_private_compose_contract_rejects_worker_on_dify_network(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "openclaw-video/docker-compose.openclaw-video.yaml",
                MIN_COMPOSE.replace(
                    "  video-analysis-worker:\n    networks:\n      - openclaw-internal",
                    "  video-analysis-worker:\n    networks:\n      - openclaw-internal\n      - dify-default",
                ),
            )

            result = preflight_module.check_private_compose_contract(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("video-analysis-worker", result.evidence)

    def test_private_compose_contract_requires_root_available_postgres_image(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(
                repo / "openclaw-video/docker-compose.openclaw-video.yaml",
                MIN_COMPOSE.replace("image: postgres:15-alpine", "image: postgres:16-alpine"),
            )

            result = preflight_module.check_private_compose_contract(repo)

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("postgres:15-alpine", result.evidence)

    def test_preflight_go_when_private_gates_pass(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "openclaw-video/docker-compose.openclaw-video.yaml", MIN_COMPOSE)
            write(repo / "openresty-route-map-redacted.md", "no OpenClaw route present\n")
            git_results = {
                ("status", "--short"): (0, "", ""),
                ("tag", "--points-at", "HEAD"): (0, "private-tag", ""),
            }

            def fake_git(_repo, args):
                return git_results[tuple(args)]

            with mock.patch.object(preflight_module, "_git", side_effect=fake_git), mock.patch.object(
                preflight_module, "_load_ubuntu22_audit"
            ) as load_audit:
                load_audit.return_value.audit.return_value = PASS_UBUNTU_AUDIT

                report = preflight_module.preflight(repo, "root")

        self.assertEqual(report["overall"], "GO")
        self.assertEqual(report["scope"], "private-sidecar-no-public-route")

    def test_preflight_does_not_check_authenticated_public_dify_baseline(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            write(repo / "openclaw-video/docker-compose.openclaw-video.yaml", MIN_COMPOSE)
            write(repo / "openresty-route-map-redacted.md", "no OpenClaw route present\n")
            git_results = {
                ("status", "--short"): (0, "", ""),
                ("tag", "--points-at", "HEAD"): (0, "private-tag", ""),
            }

            def fake_git(_repo, args):
                return git_results[tuple(args)]

            with mock.patch.object(preflight_module, "_git", side_effect=fake_git), mock.patch.object(
                preflight_module, "_load_ubuntu22_audit"
            ) as load_audit:
                load_audit.return_value.audit.return_value = PASS_UBUNTU_AUDIT

                report = preflight_module.preflight(repo, "root")

        self.assertEqual(report["overall"], "GO")
        serialized = str(report)
        self.assertNotIn("authenticated_dify_baseline", serialized)


if __name__ == "__main__":
    unittest.main()
