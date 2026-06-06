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
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "preflight_root_deploy.py"

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
class BundleResult:
    status: str
    evidence: str
    bundle_path: str | None = None
    manifest_path: str | None = None
    sha256: str | None = None
    git_commit: str | None = None
    git_tags: str | None = None


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location("preflight_root_deploy", PREFLIGHT_PATH)
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
    parts = set(relative.parts)
    if parts & EXCLUDE_PARTS:
        return False
    if any(part.startswith(".env.") for part in relative.parts):
        return False
    if path.name in EXCLUDE_NAMES:
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    if "storage" in str(relative).lower() or "cookie" in str(relative).lower():
        return False
    return True


def _write_bundle(repo: Path, output_dir: Path, commit: str) -> tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"openclaw-root-deploy-{commit[:12]}.tar.gz"
    with tarfile.open(bundle_path, "w:gz") as archive:
        for path in sorted(repo.rglob("*")):
            if path == bundle_path or not path.is_file():
                continue
            if not should_include(path, repo):
                continue
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
    with tarfile.open(bundle_path, "r:gz") as archive:
        names = archive.getnames()
    offenders = [name for name in names if any(pattern.search(name) for pattern in forbidden_patterns)]
    if offenders:
        raise RuntimeError("deployment bundle contains forbidden files: " + ", ".join(offenders[:10]))


def build_bundle(repo: Path, output_dir: Path, target_host: str = "root") -> BundleResult:
    preflight_module = _load_preflight_module()
    preflight = preflight_module.preflight(repo, target_host)
    if preflight["overall"] != "GO":
        no_go = [check["check_id"] for check in preflight["checks"] if check["status"] != "PASS"]
        return BundleResult("NO_GO", "root deploy preflight is not GO: " + ", ".join(no_go))

    commit = _git(repo, ["rev-parse", "HEAD"])
    tags = _git(repo, ["tag", "--points-at", "HEAD"]) or "none"
    bundle_path, digest = _write_bundle(repo, output_dir, commit)
    _assert_bundle_sanitized(bundle_path)

    manifest = {
        "schema_version": "openclaw-root-deploy-bundle.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target_host": target_host,
        "git_commit": commit,
        "git_tags": [line for line in tags.splitlines() if line] or ["none"],
        "bundle_path": str(bundle_path),
        "bundle_sha256": digest,
        "preflight": preflight,
    }
    manifest_path = output_dir / f"openclaw-root-deploy-{commit[:12]}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return BundleResult(
        "PASS",
        "deployment bundle created",
        bundle_path=str(bundle_path),
        manifest_path=str(manifest_path),
        sha256=digest,
        git_commit=commit,
        git_tags=tags,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a sanitized root deployment bundle after preflight GO.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "tmp" / "root-deploy-bundles"))
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
