from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openclaw_video.video_limits import MAX_VIDEO_BYTES
from openclaw_video.upload_store import (
    ALLOWED_VIDEO_EXTENSIONS,
    UploadNotFound,
    UploadStoreError,
    delete_upload_uri,
    is_upload_uri,
    resolve_upload_uri,
    store_upload_bytes,
    store_upload_chunks,
)


class UploadStoreTests(unittest.TestCase):
    def test_default_upload_limit_uses_shared_500mb_boundary(self):
        self.assertEqual(store_upload_chunks.__kwdefaults__["max_bytes"], MAX_VIDEO_BYTES)
        self.assertEqual(store_upload_bytes.__kwdefaults__["max_bytes"], MAX_VIDEO_BYTES)
        self.assertEqual(ALLOWED_VIDEO_EXTENSIONS, {".mp4", ".avi", ".mov"})

    def test_stores_sanitized_video_file_and_resolves_private_uri(self):
        with TemporaryDirectory() as tmp:
            stored = store_upload_bytes(
                b"video bytes",
                filename="../sample clip.mp4",
                upload_dir=Path(tmp),
            )

            self.assertEqual(stored.filename, "sample_clip.mp4")
            self.assertTrue(is_upload_uri(stored.uri))
            self.assertEqual(stored.size_bytes, len(b"video bytes"))
            self.assertEqual(len(stored.sha256), 64)
            self.assertEqual(resolve_upload_uri(stored.uri, upload_dir=Path(tmp)), stored.path)
            self.assertEqual(stored.path.read_bytes(), b"video bytes")
            self.assertEqual(delete_upload_uri(stored.uri, upload_dir=Path(tmp)), True)
            self.assertFalse(stored.path.exists())
            self.assertEqual(delete_upload_uri(stored.uri, upload_dir=Path(tmp)), False)
            self.assertEqual(delete_upload_uri("https://example.com/video.mp4", upload_dir=Path(tmp)), False)

    def test_stores_official_files_api_video_formats(self):
        with TemporaryDirectory() as tmp:
            upload_root = Path(tmp)
            for filename in ["clip.mp4", "clip.avi", "clip.mov"]:
                with self.subTest(filename=filename):
                    stored = store_upload_bytes(b"video bytes", filename=filename, upload_dir=upload_root)
                    self.assertEqual(stored.filename, filename)
                    self.assertEqual(resolve_upload_uri(stored.uri, upload_dir=upload_root), stored.path)

    def test_rejects_unsupported_empty_and_oversized_uploads_without_leftover_files(self):
        with TemporaryDirectory() as tmp:
            upload_root = Path(tmp)
            with self.assertRaisesRegex(UploadStoreError, "mp4、avi、mov"):
                store_upload_bytes(b"video", filename="sample.txt", upload_dir=upload_root)
            with self.assertRaisesRegex(UploadStoreError, "uploaded video is empty"):
                store_upload_bytes(b"", filename="sample.mp4", upload_dir=upload_root)
            with self.assertRaisesRegex(UploadStoreError, "uploaded video exceeds size limit"):
                store_upload_chunks([b"123", b"456"], filename="sample.mp4", upload_dir=upload_root, max_bytes=4)
            self.assertEqual(list(upload_root.glob("*")), [])

    def test_resolve_rejects_invalid_or_missing_upload_uri(self):
        with TemporaryDirectory() as tmp:
            upload_root = Path(tmp)
            with self.assertRaisesRegex(UploadStoreError, "invalid upload URI"):
                resolve_upload_uri("https://example.com/video.mp4", upload_dir=upload_root)
            with self.assertRaisesRegex(UploadStoreError, "mp4、avi、mov"):
                resolve_upload_uri("upload://00000000-0000-0000-0000-000000000000/bad.txt", upload_dir=upload_root)
            with self.assertRaises(UploadNotFound):
                resolve_upload_uri("upload://00000000-0000-0000-0000-000000000000/sample.mp4", upload_dir=upload_root)


if __name__ == "__main__":
    unittest.main()
