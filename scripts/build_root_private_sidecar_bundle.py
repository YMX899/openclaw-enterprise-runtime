#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile


REPO_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "preflight_root_private_sidecar.py"

INCLUDE_PREFIXES = (
    "openclaw-video/",
    "artifacts/douyin_chong/",
    "artifacts/knowledge-base-short-video/2026.06.06/",
    "artifacts/openclaw-2026.3.13/",
    "scripts/",
)

INCLUDE_FILES = {
    "phase1.5-exit-proof.md",
    "ubuntu22-dify-browser-baseline-20260606.md",
    "openresty-route-map-redacted.md",
    "production-root-missing-gates-20260606.md",
}

EXCLUDE_PARTS = {
    ".git",
    ".phase1-sandbox",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "secrets",
    "tmp",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pem",
    ".key",
    ".crt",
    ".p12",
    ".pfx",
    ".log",
    ".tmp",
    ".bak",
}

EXCLUDE_NAMES = {
    ".env",
    ".env.local",
    "codex-browser-cookies.db",
}


@dataclass(frozen=True)
class PrivateBundleResult:
    status: str
    evidence: str
    bundle_path: str | None = None
    manifest_path: str | None = None
    sha256: str | None = None
    git_commit: str | None = None
    git_tags: str | None = None


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location("preflight_root_private_sidecar", PREFLIGHT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"git exited {completed.returncode}"
        raise RuntimeError(detail)
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_include(path: Path, repo: Path) -> bool:
    relative = path.relative_to(repo)
    relative_name = str(relative).replace("\\", "/")
    if not (relative_name in INCLUDE_FILES or any(relative_name.startswith(prefix) for prefix in INCLUDE_PREFIXES)):
        return False
    if set(relative.parts) & EXCLUDE_PARTS:
        return False
    if any(part.startswith(".env.") for part in relative.parts):
        return False
    if path.name in EXCLUDE_NAMES:
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    if "storage" in relative_name.lower() or "cookie" in relative_name.lower():
        return False
    return True


def _write_bundle(repo: Path, output_dir: Path, commit: str) -> tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"openclaw-root-private-sidecar-{commit[:12]}.tar.gz"
    with tarfile.open(bundle_path, "w:gz") as archive:
        for path in sorted(repo.rglob("*")):
            if path == bundle_path or not path.is_file():
                continue
            if should_include(path, repo):
                archive.add(path, arcname=str(path.relative_to(repo)).replace("\\", "/"))
    return bundle_path, _sha256(bundle_path)


def _assert_bundle_sanitized(bundle_path: Path) -> None:
    forbidden_patterns = [
        re.compile(r"(^|/)\.env(\.|$)"),
        re.compile(r"(^|/)secrets/"),
        re.compile(r"(^|/)\.phase1-sandbox/"),
        re.compile(r"(^|/)tmp/"),
        re.compile(r"storage", re.IGNORECASE),
        re.compile(r"cookie", re.IGNORECASE),
        re.compile(r"\.(pem|key|crt|p12|pfx|pyc|log)$", re.IGNORECASE),
    ]
    required_entries = {
        "openclaw-video/docker-compose.openclaw-video.yaml",
        "openclaw-video/docker/bridge/Dockerfile",
        "openclaw-video/docker/worker/Dockerfile",
        "openclaw-video/docker/openclaw-gateway/Dockerfile",
        "artifacts/knowledge-base-short-video/2026.06.06/VERSION",
        "scripts/preflight_root_private_sidecar.py",
    }
    with tarfile.open(bundle_path, "r:gz") as archive:
        names = set(archive.getnames())
    offenders = [name for name in names if any(pattern.search(name) for pattern in forbidden_patterns)]
    if offenders:
        raise RuntimeError("private sidecar bundle contains forbidden files: " + ", ".join(offenders[:10]))
    missing = sorted(required_entries - names)
    if missing:
        raise RuntimeError("private sidecar bundle is missing required entries: " + ", ".join(missing))


def build_bundle(repo: Path, output_dir: Path, target_host: str = "root") -> PrivateBundleResult:
    preflight_module = _load_preflight_module()
    preflight = preflight_module.preflight(repo, target_host)
    if preflight["overall"] != "GO":
        no_go = [check["check_id"] for check in preflight["checks"] if check["status"] != "PASS"]
        return PrivateBundleResult("NO_GO", "private sidecar preflight is not GO: " + ", ".join(no_go))

    commit = _git(repo, ["rev-parse", "HEAD"])
    tags = _git(repo, ["tag", "--points-at", "HEAD"]) or "none"
    bundle_path, digest = _write_bundle(repo, output_dir, commit)
    _assert_bundle_sanitized(bundle_path)

    manifest = {
        "schema_version": "openclaw-root-private-sidecar-bundle.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target_host": target_host,
        "scope": "private-sidecar-no-public-route",
        "git_commit": commit,
        "git_tags": [line for line in tags.splitlines() if line] or ["none"],
        "bundle_path": str(bundle_path),
        "bundle_sha256": digest,
        "preflight": preflight,
    }
    manifest_path = output_dir / f"openclaw-root-private-sidecar-{commit[:12]}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return PrivateBundleResult(
        "PASS",
        "private sidecar deployment bundle created",
        bundle_path=str(bundle_path),
        manifest_path=str(manifest_path),
        sha256=digest,
        git_commit=commit,
        git_tags=tags,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a sanitized private root sidecar bundle after preflight GO.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "tmp" / "root-private-sidecar-bundles"))
    parser.add_argument("--target-host", default="root")
    parser.add_argument("--fail-on-no-go", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_bundle(Path(args.repo_root).resolve(), Path(args.output_dir).resolve(), args.target_host)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    if args.fail_on_no_go and result.status != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
