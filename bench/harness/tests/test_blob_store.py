from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("blob_store", Path(__file__).resolve().parents[1] / "blob_store.py")
blobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blobs)


@unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires safe existing-blob lookup")
class BlobStoreTests(unittest.TestCase):
    def test_publish_and_reuse_matching_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"observed evidence\n"
            digest = hashlib.sha256(payload).hexdigest()
            first = blobs.publish(io.BytesIO(payload), root, max_bytes=100)
            second = blobs.publish(io.BytesIO(payload), root, max_bytes=100)
            self.assertEqual(first, {"sha256": digest, "stored_bytes": len(payload), "publication": "created"})
            self.assertEqual(second["publication"], "already_present")
            self.assertEqual((root / digest).read_bytes(), payload)
            self.assertEqual([path.name for path in root.iterdir()], [digest])

    def test_limit_or_bad_source_never_publishes_partial_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source, limit in ((io.BytesIO(b"long"), 3), (io.StringIO("text"), 100)):
                with self.subTest(limit=limit), self.assertRaises(blobs.BlobError):
                    blobs.publish(source, root, max_bytes=limit)
                self.assertEqual(list(root.iterdir()), [])
            empty = blobs.publish(io.BytesIO(b""), root, max_bytes=0)
            self.assertEqual(empty["stored_bytes"], 0)

    def test_corrupt_existing_entry_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"abcd"
            target = root / hashlib.sha256(payload).hexdigest()
            target.write_bytes(b"wxyz")
            with self.assertRaises(blobs.BlobError):
                blobs.publish(io.BytesIO(payload), root, max_bytes=100)
            self.assertEqual(target.read_bytes(), b"wxyz")
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_source_failure_removes_temporary_file(self):
        class BrokenSource:
            def __init__(self):
                self.calls = 0

            def read(self, size):
                self.calls += 1
                if self.calls == 1:
                    return b"partial"
                raise OSError("injected read failure")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(OSError, "injected read failure"):
                blobs.publish(BrokenSource(), root, max_bytes=100)
            self.assertEqual(list(root.iterdir()), [])

    def test_existing_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"contents"
            real = root / "real"
            real.write_bytes(payload)
            (root / hashlib.sha256(payload).hexdigest()).symlink_to(real)
            with self.assertRaises(blobs.BlobError):
                blobs.publish(io.BytesIO(payload), root, max_bytes=100)
            self.assertEqual(real.read_bytes(), payload)

    def test_concurrent_publishers_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"shared blob"
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: blobs.publish(io.BytesIO(payload), root, max_bytes=100), range(8)))
            self.assertEqual(sum(result["publication"] == "created" for result in results), 1)
            self.assertEqual(sum(result["publication"] == "already_present" for result in results), 7)
            self.assertEqual(len(list(root.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
