import importlib.util
import json
from pathlib import Path
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_root_deploy_bundle.py"
spec = importlib.util.spec_from_file_location("build_root_deploy_bundle", SCRIPT_PATH)
bundle_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = bundle_module
spec.loader.exec_module(bundle_module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


PASS_PREFLIGHT = {
    "schema_version": "openclaw-root-deploy-preflight.v1",
    "target_host": "root",
    "overall": "GO",
    "checks": [
        {"check_id": "target_host", "status": "PASS", "evidence": "root"},
        {"check_id": "git_clean", "status": "PASS", "evidence": "clean"},
        {"check_id": "git_tagged_head", "status": "PASS", "evidence": "tag"},
        {"check_id": "production_readiness", "status": "PASS", "evidence": "GO"},
    ],
}


class RootDeployBundleTests(unittest.TestCase):
    def test_current_repo_bundle_result_matches_preflight(self):
        with TemporaryDirectory() as tmp:
            result = bundle_module.build_bundle(REPO_ROOT, Path(tmp), "root")
            produced = list(Path(tmp).glob("*"))

        if result.status == "PASS":
            self.assertTrue(Path(result.bundle_path).is_file())
            self.assertTrue(Path(result.manifest_path).is_file())
            self.assertTrue(produced)
        else:
            self.assertEqual(result.status, "NO_GO")
            self.assertEqual(produced, [])

    def test_preflight_no_go_does_not_write_bundle(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            output = Path(tmp) / "out"
            write(repo / "openclaw-video/README.md", "safe")

            with mock.patch.object(bundle_module, "_load_preflight_module") as load_preflight:
                load_preflight.return_value.preflight.return_value = {
                    "overall": "NO_GO",
                    "checks": [{"check_id": "production_readiness", "status": "NO_GO"}],
                }

                result = bundle_module.build_bundle(repo, output, "root")

        self.assertEqual(result.status, "NO_GO")
        self.assertFalse(output.exists())

    def test_preflight_go_writes_sanitized_bundle_and_manifest(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            output = Path(tmp) / "out"
            write(repo / "openclaw-video/README.md", "safe")
            write(repo / "scripts/preflight_root_deploy.py", "safe")
            write(repo / ".env", "secret")
            write(repo / "secrets/openclaw_gateway_token", "secret")
            write(repo / ".phase1-sandbox/runtime.log", "secret")
            write(repo / "tmp/raw.txt", "secret")
            write(repo / "openclaw-video/vendor/douyin_chong/.douyin_storage_state.json", "secret")

            def fake_git(_repo, args):
                if args == ["rev-parse", "HEAD"]:
                    return "a" * 40
                if args == ["tag", "--points-at", "HEAD"]:
                    return "release-tag"
                raise AssertionError(args)

            with mock.patch.object(bundle_module, "_load_preflight_module") as load_preflight, mock.patch.object(
                bundle_module, "_git", side_effect=fake_git
            ):
                load_preflight.return_value.preflight.return_value = PASS_PREFLIGHT

                result = bundle_module.build_bundle(repo, output, "root")

            self.assertEqual(result.status, "PASS")
            bundle_path = Path(result.bundle_path)
            manifest_path = Path(result.manifest_path)
            self.assertTrue(bundle_path.is_file())
            self.assertTrue(manifest_path.is_file())
            self.assertRegex(result.sha256, r"^[0-9a-f]{64}$")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["bundle_sha256"], result.sha256)
            self.assertEqual(manifest["git_commit"], "a" * 40)
            self.assertEqual(manifest["git_tags"], ["release-tag"])

            with tarfile.open(bundle_path, "r:gz") as archive:
                names = set(archive.getnames())

        self.assertIn("openclaw-video/README.md", names)
        self.assertIn("scripts/preflight_root_deploy.py", names)
        self.assertNotIn(".env", names)
        self.assertFalse(any(name.startswith("secrets/") for name in names))
        self.assertFalse(any(name.startswith(".phase1-sandbox/") for name in names))
        self.assertFalse(any(name.startswith("tmp/") for name in names))
        self.assertFalse(any("storage" in name.lower() for name in names))

    def test_sanitizer_rejects_forbidden_bundle_entries(self):
        with TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bad.tar.gz"
            with tarfile.open(bundle, "w:gz") as archive:
                secret = Path(tmp) / "token.pem"
                secret.write_text("secret", encoding="utf-8")
                archive.add(secret, arcname="secrets/token.pem")

            with self.assertRaisesRegex(RuntimeError, "forbidden files"):
                bundle_module._assert_bundle_sanitized(bundle)


if __name__ == "__main__":
    unittest.main()
