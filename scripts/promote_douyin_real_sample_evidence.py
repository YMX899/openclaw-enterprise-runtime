#!/usr/bin/env python
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO_ROOT / "artifacts" / "douyin_chong" / "REAL_SAMPLE_EVIDENCE.json"


class EvidenceError(ValueError):
    pass


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_raw_url(evidence: dict[str, Any]) -> None:
    if re.search(r"https?://", _json_text(evidence), re.IGNORECASE):
        raise EvidenceError("evidence contains a raw URL")


def validate_evidence(evidence: dict[str, Any]) -> None:
    if evidence.get("schema_version") != "douyin-real-sample-evidence.v1":
        raise EvidenceError("unexpected evidence schema version")
    if evidence.get("status") != "succeeded":
        raise EvidenceError("real sample did not succeed")
    if evidence.get("env_file_present") is not True:
        raise EvidenceError("real sample did not use an explicit runtime env file")
    if evidence.get("secret_file_contents_recorded") is not False:
        raise EvidenceError("evidence may record secret file contents")
    if not _is_sha256(evidence.get("input_url_sha256")):
        raise EvidenceError("evidence is missing input URL hash")
    _reject_raw_url(evidence)

    process = evidence.get("process") or {}
    if process.get("returncode") != 0:
        raise EvidenceError("adapter return code was not zero")
    if not isinstance(process.get("elapsed_seconds"), (int, float)) or process["elapsed_seconds"] <= 0:
        raise EvidenceError("elapsed time is missing")
    if process.get("stdout_recorded") is not False or process.get("stderr_recorded") is not False:
        raise EvidenceError("stdout/stderr contents must not be recorded")

    result = evidence.get("result") or {}
    if result.get("schema_version") != "openclaw-video-result.v1":
        raise EvidenceError("result schema was not validated")
    if result.get("platform") != "douyin":
        raise EvidenceError("result platform is not douyin")
    if not _is_sha256(result.get("result_json_sha256")):
        raise EvidenceError("result hash is missing")
    if not isinstance(result.get("result_json_bytes"), int) or result["result_json_bytes"] <= 0:
        raise EvidenceError("result size is missing")


def promoted_payload(source: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(evidence)
    payload.pop("output_dir", None)
    payload.pop("result_json", None)
    payload["promoted_at"] = datetime.now(UTC).isoformat()
    payload["source_evidence_sha256"] = _sha256_file(source)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Promote a sanitized douyin real-sample run into the committed "
            "production-readiness evidence file."
        )
    )
    parser.add_argument("--source", required=True, help="Path to sanitized-run.json")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="Destination evidence JSON")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing destination")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write")
    return parser


def run(args: argparse.Namespace) -> int:
    source = Path(args.source)
    dest = Path(args.dest)
    if not source.is_file():
        raise EvidenceError(f"missing source evidence file: {source}")
    if dest.exists() and not args.force and not args.dry_run:
        raise EvidenceError(f"destination exists; use --force to overwrite: {dest}")

    try:
        evidence = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"source evidence is not valid JSON: {exc}") from exc
    if not isinstance(evidence, dict):
        raise EvidenceError("source evidence must be a JSON object")

    validate_evidence(evidence)
    payload = promoted_payload(source, evidence)

    if args.dry_run:
        print(json.dumps({"status": "validated", "dest": str(dest)}, ensure_ascii=False, indent=2))
        return 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "promoted", "dest": str(dest)}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
