import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "preflight_root_deploy.py"
spec = importlib.util.spec_from_file_location("preflight_root_deploy", SCRIPT_PATH)
preflight_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = preflight_module
spec.loader.exec_module(preflight_module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pass_audit(*, include_git_clean=False):
    gates = [
        {"gate_id": "openclaw_security", "status": "PASS"},
        {"gate_id": "douyin_artifact", "status": "PASS"},
        {"gate_id": "video_link_read_mode", "status": "PASS"},
        {"gate_id": "real_video_analysis_root_evidence", "status": "PASS"},
        {"gate_id": "openclaw_owned_login", "status": "PASS"},
        {"gate_id": "openresty_no_route_change", "status": "PASS"},
    ]
    if include_git_clean:
        gates.append({"gate_id": "git_clean", "status": "PASS"})
    return {"overall": "GO", "gates": gates}


def no_go_audit(*, include_git_clean=False):
    gates = [
        {"gate_id": "real_video_analysis_root_evidence", "status": "NO_GO"},
        {"gate_id": "openclaw_owned_login", "status": "NO_GO"},
    ]
    if include_git_clean:
        gates.append({"gate_id": "git_clean", "status": "PASS"})
    return {"overall": "NO_GO", "gates": gates}


def no_go_link_mode_and_auth_audit(*, include_git_clean=False):
    gates = [
        {"gate_id": "openclaw_security", "status": "PASS"},
        {"gate_id": "douyin_artifact", "status": "PASS"},
        {"gate_id": "video_link_read_mode", "status": "NO_GO"},
        {"gate_id": "real_video_analysis_root_evidence", "status": "PASS"},
        {"gate_id": "openclaw_owned_login", "status": "NO_GO"},
        {"gate_id": "openresty_no_route_change", "status": "PASS"},
    ]
    if include_git_clean:
        gates.append({"gate_id": "git_clean", "status": "PASS"})
    return {"overall": "NO_GO", "gates": gates}


def no_go_only_link_mode_audit(*, include_git_clean=False):
    gates = [
        {"gate_id": "openclaw_security", "status": "PASS"},
        {"gate_id": "douyin_artifact", "status": "PASS"},
        {"gate_id": "video_link_read_mode", "status": "NO_GO"},
        {"gate_id": "real_video_analysis_root_evidence", "status": "PASS"},
        {"gate_id": "openclaw_owned_login", "status": "PASS"},
        {"gate_id": "openresty_no_route_change", "status": "PASS"},
    ]
    if include_git_clean:
        gates.append({"gate_id": "git_clean", "status": "PASS"})
    return {"overall": "NO_GO", "gates": gates}


class RootDeployPreflightTests(unittest.TestCase):
    def test_current_repo_preflight_reflects_actual_release_state(self):
        report = preflight_module.preflight(REPO_ROOT, "root")
        statuses = {check["check_id"]: check["status"] for check in report["checks"]}
        expected = "GO" if all(status == "PASS" for status in statuses.values()) else "NO_GO"

        self.assertEqual(report["overall"], expected)
        self.assertIn("git_clean", statuses)
        self.assertIn("git_tagged_head", statuses)
        self.assertIn("production_readiness", statuses)

    def test_rejects_non_root_target(self):
        result = preflight_module.check_target_host("ubuntu22.04")

        self.assertEqual(result.status, "NO_GO")
        self.assertIn("root", result.evidence)

    def test_all_required_evidence_passes(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git_results = {
                ("status", "--short"): (0, "", ""),
                ("tag", "--points-at", "HEAD"): (0, "release-tag", ""),
            }

            def fake_git(_repo, args):
                return git_results[tuple(args)]

            with mock.patch.object(preflight_module, "_git", side_effect=fake_git), mock.patch.object(
                preflight_module, "_load_audit_module"
            ) as load_audit:
                load_audit.return_value.audit.side_effect = lambda _repo, include_git_clean=False: pass_audit(
                    include_git_clean=include_git_clean
                )

                report = preflight_module.preflight(repo, "root")

        self.assertEqual(report["overall"], "GO")
        self.assertTrue(all(check["status"] == "PASS" for check in report["checks"]))

    def test_no_go_audit_blocks_even_with_valid_proof(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)

            with mock.patch.object(preflight_module, "_git", return_value=(0, "release-tag", "")), mock.patch.object(
                preflight_module, "_load_audit_module"
            ) as load_audit:
                load_audit.return_value.audit.side_effect = lambda _repo, include_git_clean=False: no_go_audit(
                    include_git_clean=include_git_clean
                )

                report = preflight_module.preflight(repo, "root")

        statuses = {check["check_id"]: check["status"] for check in report["checks"]}
        self.assertEqual(report["overall"], "NO_GO")
        self.assertEqual(statuses["production_readiness"], "NO_GO")

    def test_link_mode_gate_and_auth_gate_both_block(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git_results = {
                ("status", "--short"): (0, "", ""),
                ("tag", "--points-at", "HEAD"): (0, "release-tag", ""),
            }

            def fake_git(_repo, args):
                return git_results[tuple(args)]

            with mock.patch.object(preflight_module, "_git", side_effect=fake_git), mock.patch.object(
                preflight_module, "_load_audit_module"
            ) as load_audit:
                load_audit.return_value.audit.side_effect = (
                    lambda _repo, include_git_clean=False: no_go_link_mode_and_auth_audit(
                        include_git_clean=include_git_clean
                    )
                )

                report = preflight_module.preflight(repo, "root")

        statuses = {check["check_id"]: check for check in report["checks"]}
        self.assertEqual(report["overall"], "NO_GO")
        self.assertEqual(statuses["production_readiness"]["status"], "NO_GO")
        self.assertIn("openclaw_owned_login", statuses["production_readiness"]["evidence"])
        self.assertIn("video_link_read_mode", statuses["production_readiness"]["evidence"])

    def test_link_mode_gate_blocks_when_it_is_the_only_missing_gate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git_results = {
                ("status", "--short"): (0, "", ""),
                ("tag", "--points-at", "HEAD"): (0, "release-tag", ""),
            }

            def fake_git(_repo, args):
                return git_results[tuple(args)]

            with mock.patch.object(preflight_module, "_git", side_effect=fake_git), mock.patch.object(
                preflight_module, "_load_audit_module"
            ) as load_audit:
                load_audit.return_value.audit.side_effect = lambda _repo, include_git_clean=False: no_go_only_link_mode_audit(
                    include_git_clean=include_git_clean
                )

                report = preflight_module.preflight(repo, "root")

        self.assertEqual(report["overall"], "NO_GO")


if __name__ == "__main__":
    unittest.main()
