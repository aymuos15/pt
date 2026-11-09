from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location("blob_store", Path(__file__).resolve().parents[1] / "blob_store.py")
blobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blobs)


@unittest.skipUnless(sys.platform == "linux" and hasattr(os, "O_NOFOLLOW"),
                     "requires Linux no-replace publication and safe existing-blob lookup")
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

    def test_creator_finishing_during_duplicate_verification_does_not_change_blob(self):
        # Pause the successful publisher after namespace publication. The
        # follower begins verification before allowing the creator to finish.
        # No sleeps or ctime clock-resolution assumptions select this window.
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            payload = b"shared evidence"
            target = root / hashlib.sha256(payload).hexdigest()
            published, finish_creator, creator_done = Event(), Event(), Event()
            publish = blobs._publish_noreplace
            read = os.read
            links_at_read = []

            def publish_and_pause(source, destination):
                publish(source, destination)
                published.set()
                if not finish_creator.wait(5):
                    raise TimeoutError("follower did not release the creator")

            def create():
                try:
                    return blobs.publish(io.BytesIO(payload), root, max_bytes=100)
                finally:
                    creator_done.set()

            def read_during_finish(fd, size):
                chunk = read(fd, size)
                if chunk and not links_at_read:
                    links_at_read.append(os.fstat(fd).st_nlink)
                    finish_creator.set()
                    if not creator_done.wait(5):
                        raise TimeoutError("creator did not finish during verification")
                return chunk

            with mock.patch.object(blobs, "_publish_noreplace", side_effect=publish_and_pause):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    creator = pool.submit(create)
                    try:
                        self.assertTrue(published.wait(5), "creator did not publish")
                        with mock.patch.object(blobs.os, "read", side_effect=read_during_finish):
                            follower = blobs.publish(io.BytesIO(payload), root, max_bytes=100)
                        self.assertEqual(creator.result(timeout=5)["publication"], "created")
                        self.assertEqual(follower["publication"], "already_present")
                        self.assertEqual(links_at_read, [1], "publication exposed a staging hardlink")
                        self.assertEqual(target.read_bytes(), payload)
                        self.assertEqual([path.name for path in root.iterdir()], [target.name])
                    finally:
                        finish_creator.set()

    def test_verification_still_rejects_every_fingerprint_change_even_with_matching_bytes(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            target = Path(directory) / "blob"
            payload = b"unchanged evidence"
            target.write_bytes(payload)
            observed = target.stat()
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
            before = {field: getattr(observed, field) for field in fields}
            for field in fields[:-1]:
                with self.subTest(field=field):
                    after = {**before, field: before[field] + 1}
                    with mock.patch.object(blobs.os, "fstat", side_effect=[SimpleNamespace(**before), SimpleNamespace(**after)]) as fstat:
                        with self.assertRaisesRegex(blobs.BlobError, "existing blob changed"):
                            blobs._verify_existing(target, hashlib.sha256(payload).hexdigest(), len(payload))
                        self.assertEqual(fstat.call_count, 2, "verification must fail, not retry away a change")
                    self.assertEqual(target.read_bytes(), payload)

    def test_concurrent_processes_share_one_immutable_publication(self):
        program = (
            "import io,json,sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from blob_store import publish\n"
            "assert sys.stdin.buffer.read(1) == b'x'\n"
            "print(json.dumps(publish(io.BytesIO(b'shared across processes'), Path(sys.argv[2]), max_bytes=100)))\n"
        )
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            children = []
            try:
                for _ in range(4):
                    children.append(subprocess.Popen(
                        [sys.executable, "-c", program, str(Path(blobs.__file__).parent), directory],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    ))
                for child in children:
                    child.stdin.write(b"x")
                    child.stdin.close()
                    child.stdin = None
                results = []
                for child in children:
                    stdout, stderr = child.communicate(timeout=10)
                    self.assertEqual(child.returncode, 0, stderr)
                    results.append(json.loads(stdout))
                self.assertEqual(sum(result["publication"] == "created" for result in results), 1)
                self.assertEqual(sum(result["publication"] == "already_present" for result in results), 3)
                payload = b"shared across processes"
                target = Path(directory) / hashlib.sha256(payload).hexdigest()
                self.assertEqual(target.read_bytes(), payload)
                self.assertEqual(target.stat().st_nlink, 1)
                self.assertEqual(list(Path(directory).iterdir()), [target])
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=10)

    def test_fsync_failure_cannot_publish_partial_evidence(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            with mock.patch.object(blobs.os, "fsync", side_effect=OSError(errno.ENOSPC, "injected disk full")):
                with mock.patch.object(blobs, "_publish_noreplace") as publish:
                    with self.assertRaises(OSError):
                        blobs.publish(io.BytesIO(b"evidence"), Path(directory), max_bytes=100)
                    publish.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_existing_wrong_size_directory_and_fifo_are_not_overwritten(self):
        for kind in ("wrong_size", "directory", "fifo"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                payload = b"expected bytes"
                target = root / hashlib.sha256(payload).hexdigest()
                if kind == "directory":
                    target.mkdir()
                elif kind == "fifo":
                    os.mkfifo(target)
                else:
                    target.write_bytes(b"wrong")
                before = target.lstat()
                with self.assertRaises(blobs.BlobError):
                    blobs.publish(io.BytesIO(payload), root, max_bytes=100)
                after = target.lstat()
                self.assertEqual((before.st_dev, before.st_ino, before.st_mode),
                                 (after.st_dev, after.st_ino, after.st_mode))
                self.assertEqual(list(root.iterdir()), [target])

    def test_native_publication_preserves_os_path_bytes_and_consumes_staging(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = root / os.fsdecode(b"staging-\xff")
            destination = root / os.fsdecode(b"destination-\xfe")
            source.write_bytes(b"evidence")
            before = source.stat()
            blobs._publish_noreplace(source, destination)
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_bytes(), b"evidence")
            after = destination.stat()
            self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))
            self.assertEqual(after.st_nlink, 1)


class NativePublicationFailureTests(unittest.TestCase):
    def test_unsupported_platform_and_missing_wrapper_never_use_a_weaker_fallback(self):
        cases = (
            mock.patch.object(blobs.sys, "platform", "unsupported"),
            mock.patch.object(blobs.ctypes, "CDLL", side_effect=OSError("wrapper unavailable")),
            mock.patch.object(blobs.ctypes, "CDLL", return_value=object()),
        )
        for unsupported in cases:
            with self.subTest(unsupported=unsupported), tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                payload = b"expected"
                target = root / hashlib.sha256(payload).hexdigest()
                target.write_bytes(b"existing evidence")
                with unsupported, mock.patch.object(blobs.os, "link") as link, mock.patch.object(blobs.os, "rename") as rename:
                    with self.assertRaises(blobs.BlobError):
                        blobs.publish(io.BytesIO(payload), root, max_bytes=100)
                    link.assert_not_called()
                    rename.assert_not_called()
                self.assertEqual(target.read_bytes(), b"existing evidence")
                self.assertEqual(list(root.iterdir()), [target])

    def test_native_error_preserves_errno_and_evidence_and_removes_staging(self):
        for error in (errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL, errno.EPERM, errno.EXDEV, errno.EIO):
            with self.subTest(error=error), tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
                root = Path(directory)
                payload = b"expected"
                target = root / hashlib.sha256(payload).hexdigest()
                target.write_bytes(b"existing evidence")
                native = mock.Mock(return_value=-1)
                with (
                    mock.patch.object(blobs.sys, "platform", "linux"),
                    mock.patch.object(blobs.ctypes, "CDLL", return_value=SimpleNamespace(renameat2=native)),
                    mock.patch.object(blobs.ctypes, "get_errno", return_value=error),
                    mock.patch.object(blobs.os, "link") as link,
                    mock.patch.object(blobs.os, "rename") as rename,
                ):
                    with self.assertRaises(OSError) as failure:
                        blobs.publish(io.BytesIO(payload), root, max_bytes=100)
                    self.assertEqual(failure.exception.errno, error)
                    native.assert_called_once()
                    self.assertEqual(native.call_args.args[0], blobs.AT_FDCWD)
                    self.assertEqual(native.call_args.args[2], blobs.AT_FDCWD)
                    self.assertEqual(native.call_args.args[4], blobs.RENAME_NOREPLACE)
                    link.assert_not_called()
                    rename.assert_not_called()
                self.assertEqual(target.read_bytes(), b"existing evidence")
                self.assertEqual(list(root.iterdir()), [target])

    def test_nul_in_native_path_is_rejected_before_calling_libc(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as directory:
            root = Path(directory)
            source = root / "staging"
            source.write_bytes(b"evidence")
            with mock.patch.object(blobs.sys, "platform", "linux"), mock.patch.object(blobs.ctypes, "CDLL") as libc:
                with self.assertRaises(ValueError):
                    blobs._publish_noreplace(source, root / "destination\0suffix")
                libc.assert_not_called()
            self.assertEqual(source.read_bytes(), b"evidence")


if __name__ == "__main__":
    unittest.main()
