import importlib.util
import json
from pathlib import Path
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_root_private_sidecar_bundle.py"
spec = importlib.util.spec_from_file_location("build_root_private_sidecar_bundle", SCRIPT_PATH)
bundle_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = bundle_module
spec.loader.exec_module(bundle_module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


PASS_PREFLIGHT = {
    "schema_version": "openclaw-root-private-sidecar-preflight.v1",
    "target_host": "root",
    "scope": "private-sidecar-no-public-route",
    "overall": "GO",
    "checks": [
        {"check_id": "target_host", "status": "PASS", "evidence": "root"},
        {"check_id": "git_clean", "status": "PASS", "evidence": "clean"},
        {"check_id": "git_tagged_head", "status": "PASS", "evidence": "tag"},
        {"check_id": "ubuntu22_phase", "status": "PASS", "evidence": "PASS"},
        {"check_id": "private_compose_contract", "status": "PASS", "evidence": "private"},
        {"check_id": "public_route_absent", "status": "PASS", "evidence": "absent"},
    ],
}


class RootPrivateSidecarBundleTests(unittest.TestCase):
    def test_preflight_no_go_does_not_write_bundle(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            output = Path(tmp) / "out"
            write(repo / "openclaw-video/README.md", "safe")

            with mock.patch.object(bundle_module, "_load_preflight_module") as load_preflight:
                load_preflight.return_value.preflight.return_value = {
                    "overall": "NO_GO",
                    "checks": [{"check_id": "private_compose_contract", "status": "NO_GO"}],
                }

                result = bundle_module.build_bundle(repo, output, "root")

        self.assertEqual(result.status, "NO_GO")
        self.assertFalse(output.exists())

    def test_private_bundle_contains_only_sidecar_materials_and_manifest(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            output = Path(tmp) / "out"
            write(repo / "openclaw-video/docker-compose.openclaw-video.yaml", "compose")
            write(repo / "openclaw-video/docker/bridge/Dockerfile", "bridge")
            write(repo / "openclaw-video/docker/worker/Dockerfile", "worker")
            write(repo / "openclaw-video/docker/openclaw-gateway/Dockerfile", "gateway")
            write(repo / "artifacts/knowledge-base-short-video/2026.06.06/VERSION", "2026.06.06")
            write(repo / "scripts/preflight_root_private_sidecar.py", "preflight")
            write(repo / "scripts/build_root_private_sidecar_bundle.py", "bundle")
            write(repo / "phase1.5-exit-proof.md", "proof")
            write(repo / "unrelated-large.svg", "not included")
            write(repo / ".env", "secret")
            write(repo / "openclaw-video/secrets/token", "secret")
            write(repo / "tmp/raw.txt", "secret")
            write(repo / "openclaw-video/vendor/douyin_chong/.douyin_storage_state.json", "secret")

            def fake_git(_repo, args):
                if args == ["rev-parse", "HEAD"]:
                    return "b" * 40
                if args == ["tag", "--points-at", "HEAD"]:
                    return "private-tag"
                raise AssertionError(args)

            with mock.patch.object(bundle_module, "_load_preflight_module") as load_preflight, mock.patch.object(
                bundle_module, "_git", side_effect=fake_git
            ):
                load_preflight.return_value.preflight.return_value = PASS_PREFLIGHT

                result = bundle_module.build_bundle(repo, output, "root")

            self.assertEqual(result.status, "PASS")
            manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(manifest["scope"], "private-sidecar-no-public-route")
            self.assertEqual(manifest["git_tags"], ["private-tag"])

            with tarfile.open(result.bundle_path, "r:gz") as archive:
                names = set(archive.getnames())

        self.assertIn("openclaw-video/docker-compose.openclaw-video.yaml", names)
        self.assertIn("artifacts/knowledge-base-short-video/2026.06.06/VERSION", names)
        self.assertIn("scripts/preflight_root_private_sidecar.py", names)
        self.assertNotIn("unrelated-large.svg", names)
        self.assertNotIn(".env", names)
        self.assertFalse(any(name.startswith("openclaw-video/secrets/") for name in names))
        self.assertFalse(any(name.startswith("tmp/") for name in names))
        self.assertFalse(any("storage" in name.lower() for name in names))


if __name__ == "__main__":
    unittest.main()
