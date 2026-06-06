from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class UploadStoreError(ValueError):
    pass


class UploadNotFound(FileNotFoundError):
    pass


ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
UPLOAD_URI_RE = re.compile(r"^upload://([0-9a-fA-F-]{36})/([^/]+)$")


@dataclass(frozen=True)
class StoredUpload:
    upload_id: str
    filename: str
    uri: str
    path: Path
    size_bytes: int
    sha256: str


def _default_upload_dir() -> Path:
    return Path(os.environ.get("BRIDGE_UPLOAD_DIR", "/data/uploads"))


def _safe_filename(filename: str) -> str:
    candidate = Path(filename or "video.mp4").name.strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate)
    candidate = candidate.strip("._") or "video.mp4"
    suffix = Path(candidate).suffix.lower()
    if suffix not in ALLOWED_VIDEO_EXTENSIONS:
        raise UploadStoreError("unsupported video file type")
    return candidate[:120]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_upload_chunks(
    chunks: Iterable[bytes],
    *,
    filename: str,
    upload_dir: Path | None = None,
    max_bytes: int = 512 * 1024 * 1024,
) -> StoredUpload:
    safe_name = _safe_filename(filename)
    upload_id = str(uuid.uuid4())
    root = upload_dir or _default_upload_dir()
    target_dir = root / upload_id
    target_dir.mkdir(parents=True, exist_ok=False)
    target = target_dir / safe_name
    total = 0
    digest = hashlib.sha256()
    try:
        with target.open("xb") as handle:
            for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise UploadStoreError("uploaded video exceeds size limit")
                digest.update(chunk)
                handle.write(chunk)
        if total <= 0:
            raise UploadStoreError("uploaded video is empty")
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return StoredUpload(
        upload_id=upload_id,
        filename=safe_name,
        uri=f"upload://{upload_id}/{safe_name}",
        path=target,
        size_bytes=total,
        sha256=digest.hexdigest(),
    )


def store_upload_fileobj(
    fileobj: BinaryIO,
    *,
    filename: str,
    upload_dir: Path | None = None,
    max_bytes: int = 512 * 1024 * 1024,
) -> StoredUpload:
    return store_upload_chunks(
        iter(lambda: fileobj.read(1024 * 1024), b""),
        filename=filename,
        upload_dir=upload_dir,
        max_bytes=max_bytes,
    )


def store_upload_bytes(
    data: bytes,
    *,
    filename: str,
    upload_dir: Path | None = None,
    max_bytes: int = 512 * 1024 * 1024,
) -> StoredUpload:
    return store_upload_chunks(
        [data],
        filename=filename,
        upload_dir=upload_dir,
        max_bytes=max_bytes,
    )


def resolve_upload_uri(uri: str, *, upload_dir: Path | None = None) -> Path:
    match = UPLOAD_URI_RE.match(uri)
    if not match:
        raise UploadStoreError("invalid upload URI")
    upload_id, filename = match.groups()
    safe_name = _safe_filename(filename)
    root = upload_dir or _default_upload_dir()
    path = (root / upload_id / safe_name).resolve()
    root_resolved = root.resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise UploadStoreError("upload path escapes storage root") from exc
    if not path.is_file():
        raise UploadNotFound("uploaded video was not found")
    return path


def delete_upload_uri(uri: str, *, upload_dir: Path | None = None) -> bool:
    if not is_upload_uri(uri):
        return False
    try:
        path = resolve_upload_uri(uri, upload_dir=upload_dir)
    except UploadNotFound:
        return False
    upload_root = path.parent
    root = (upload_dir or _default_upload_dir()).resolve()
    try:
        upload_root.resolve().relative_to(root)
    except ValueError as exc:
        raise UploadStoreError("upload path escapes storage root") from exc
    shutil.rmtree(upload_root, ignore_errors=True)
    return True


def is_upload_uri(value: str) -> bool:
    return bool(UPLOAD_URI_RE.match(value))
