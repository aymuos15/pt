"""Read-only required-JUnit readiness controls; not report/runner qualification."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/pt_bridge/src"))
from pt_bridge._artifacts import ArtifactObservationError, DeclaredJunit, DirectoryPin, declaration
from pt_bridge._observer import Observer, ObserverError, configuration
sys.path.pop(0)


def output_declaration(**changes):
    return {"artifact_id": "junit", "source": "requested.xml", "max_bytes": 1024*1024, "required": True, **changes}


def bootstrap():
    return {"schema_version": 2, "fd": 3, "identity": {"request_id": "r", "run_id": "r", "generation_id": "g", "session_id": "s", "producer_id": "b"},
            "invocation_profile": "pytest_module", "mode": "run", "max_items": 256, "max_collection_reports": 1024,
            "max_nodeid_bytes": 1024*1024, "byte_budget": 8*1024*1024, "event_budget": 25000, "timeout_seconds": 30,
            "junit_artifact": output_declaration()}


@unittest.skipUnless(sys.platform == "linux", "native no-follow readiness targets Linux")
class RequiredJunitReadinessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="pt-observer-junit-", dir="/tmp/opencode")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "work"
        self.root.mkdir(mode=0o700)
        self.deadline = time.monotonic() + 10

    def write(self, path="requested.xml", raw=b"bounded output"):
        target = self.root / path
        with target.open("xb") as output:
            output.write(raw)
        target.chmod(0o600)
        return target

    def observer(self, **changes):
        value = DeclaredJunit(output_declaration(**changes), self.root, self.deadline)
        self.addCleanup(value.close)
        return value

    def test_version_one_stays_closed_and_version_two_requires_exact_explicit_declaration(self):
        original = bootstrap()
        self.assertEqual(configuration(json.dumps(original)), original)
        old = {key: value for key, value in original.items() if key != "junit_artifact"}
        old["schema_version"] = 1
        self.assertEqual(configuration(json.dumps(old)), old)
        for invalid in ({**old, "junit_artifact": output_declaration()}, {**original, "schema_version": 1},
                        {**old, "schema_version": 2}, {**original, "schema_version": 3}):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, ObserverError)):
                configuration(json.dumps(invalid))
        for key in output_declaration():
            invalid = output_declaration()
            del invalid[key]
            with self.subTest(missing=key), self.assertRaises(ArtifactObservationError):
                declaration(invalid)
        oversized = bootstrap()
        oversized["junit_artifact"]["source"] = "λ"*2000
        raw = json.dumps(oversized, ensure_ascii=False) + " "*4000
        self.assertLess(len(raw), 8192)
        self.assertGreater(len(raw.encode()), 8192)
        with self.assertRaises(ObserverError):
            configuration(raw)

    def test_ids_paths_optional_outputs_and_counts_are_not_repaired_or_coerced(self):
        for key, values in (("source", ("", "/absolute", "a//b", "a/./b", "../a", "a/../b", "a/", "x\0y", "x/"*25+"a", "x"*4097, "\ud800")),
                            ("artifact_id", ("", "../x", "λ", "x/", "x"*129, True)),
                            ("max_bytes", (0, -1, True, 1.5, 128*1024*1024+1)), ("required", (False, None, 1))):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises((ValueError, UnicodeError)):
                    declaration(output_declaration(**{key: value}))
        with self.assertRaises(ArtifactObservationError):
            declaration({**output_declaration(), "unknown": None})

    def test_binary_empty_unicode_and_partial_assertions_hash_exact_bytes_without_inferred_valid_xml(self):
        for index, raw in enumerate((b"", b"\0\xff raw\n", "λ 🐍".encode())):
            name = f"report-{index}-λ.xml"
            target = self.write(name, raw)
            observer = self.observer(source=name)
            for complete in (False, True):
                self.assertEqual(observer.ready(complete=complete), {"artifact_id": "junit", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "complete": complete})
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(target.stat().st_mode & 0o7777, 0o600)

    def test_nested_output_parents_are_pinned_without_creating_any_directory(self):
        (self.root / "nested").mkdir(mode=0o700)
        self.write("nested/report.xml", b"report")
        observer = self.observer(source="nested/report.xml")
        self.assertEqual(observer.ready(complete=True)["bytes"], 6)
        absent = self.observer(source="missing/report.xml")
        with self.assertRaises(FileNotFoundError):
            absent.ready(complete=True)
        self.assertFalse((self.root / "missing").exists())

    def test_symlinks_hardlinks_fifo_directory_and_other_writable_outputs_never_become_ready(self):
        original = self.write("original", b"foreign bytes remain")
        for kind in ("symlink", "hardlink", "fifo", "directory", "writable"):
            path = self.root / kind
            if kind == "symlink": path.symlink_to("original")
            elif kind == "hardlink": os.link(original, path)
            elif kind == "fifo": os.mkfifo(path, 0o600)
            elif kind == "directory": path.mkdir(mode=0o700)
            else:
                self.write(kind)
                path.chmod(0o664)
            observer = self.observer(source=kind)
            with self.subTest(kind=kind), self.assertRaises((OSError, ArtifactObservationError)):
                observer.ready(complete=True)
        self.assertEqual(original.read_bytes(), b"foreign bytes remain")
        self.assertEqual((self.root / "writable").stat().st_mode & 0o7777, 0o664)

    def test_symlinked_root_or_output_parent_is_not_followed_or_repaired(self):
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            DeclaredJunit(output_declaration(), alias, self.deadline)
        (self.root / "real").mkdir(mode=0o700)
        self.write("real/report.xml", b"report")
        (self.root / "alias").symlink_to("real", target_is_directory=True)
        with self.assertRaises(OSError):
            self.observer(source="alias/report.xml").ready(complete=True)
        self.assertTrue((self.root / "alias").is_symlink())

    def test_root_replacement_and_leaf_substitution_during_read_cannot_publish_readiness(self):
        self.write(raw=b"original report")
        observer = self.observer()
        actual_read = os.read
        changed = False

        def read_and_replace(fd, length):
            nonlocal changed
            raw = actual_read(fd, length)
            if raw and not changed:
                changed = True
                (self.root / "requested.xml").rename(self.root / "old-report")
                self.write(raw=b"original report")
            return raw

        with mock.patch("pt_bridge._artifacts.os.read", side_effect=read_and_replace), self.assertRaises(ArtifactObservationError):
            observer.ready(complete=True)
        self.assertTrue(changed)
        observer = self.observer()
        self.root.rename(self.root.with_name("old-work"))
        self.root.mkdir(mode=0o700)
        self.write(raw=b"different root must remain")
        with self.assertRaises(ArtifactObservationError):
            observer.ready(complete=True)
        self.assertEqual((self.root / "requested.xml").read_bytes(), b"different root must remain")

    def test_limits_deadlines_and_closed_roots_fail_instead_of_resetting_or_inferring_completion(self):
        self.write(raw=b"abc")
        with self.assertRaises(ArtifactObservationError):
            self.observer(max_bytes=2).ready(complete=True)
        observer = self.observer()
        with mock.patch("pt_bridge._artifacts.time.monotonic", return_value=self.deadline), self.assertRaises(ArtifactObservationError):
            observer.ready(complete=True)
        observer.close()
        observer.close()
        with self.assertRaises(ArtifactObservationError):
            observer.ready(complete=True)
        with self.assertRaises(ArtifactObservationError):
            DirectoryPin(self.root, time.monotonic()-1)
        with self.assertRaises(ArtifactObservationError):
            self.observer().ready(complete=1)
        for deadline in (float("inf"), float("nan"), None, True):
            with self.subTest(deadline=deadline), self.assertRaises(ArtifactObservationError):
                DirectoryPin(self.root, deadline)

    def test_failed_directory_setup_closes_only_owned_fds_and_every_open_is_non_inheritable(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        opened, closed = [], []
        actual_open, actual_close = os.open, os.close

        def tracked_open(*args, **kwargs):
            fd = actual_open(*args, **kwargs)
            self.assertFalse(os.get_inheritable(fd))
            opened.append(fd)
            return fd

        def tracked_close(fd):
            actual_close(fd)
            closed.append(fd)

        with mock.patch("pt_bridge._artifacts.os.open", side_effect=tracked_open), mock.patch("pt_bridge._artifacts.os.close", side_effect=tracked_close):
            with self.assertRaises(OSError):
                DirectoryPin(alias, self.deadline)
        self.assertTrue(opened)
        self.assertCountEqual(opened, closed)
        self.assertTrue(alias.is_symlink())

    def test_missing_or_wrong_formatter_is_unsupported_without_enabling_or_redirecting_it(self):
        from _pytest.junitxml import LogXML, xml_key
        from _pytest.stash import Stash
        from types import SimpleNamespace
        for actual in (None, LogXML(str(self.root / "other.xml"), None)):
            settings = bootstrap()
            channel = mock.Mock()
            with mock.patch("pt_bridge._observer.os.getcwd", return_value=str(self.root)):
                observer = Observer(settings, channel)
            self.addCleanup(observer.close_artifacts)
            stash = Stash()
            if actual is not None:
                stash[xml_key] = actual
            session = SimpleNamespace(config=SimpleNamespace(stash=stash))
            with self.subTest(actual=type(actual)), self.assertRaises(ObserverError):
                observer.session_start(session)
            self.assertTrue(observer.unsupported)
            self.assertEqual(channel.send.call_args.args[0], "session_error")
            self.assertEqual(channel.send.call_args.args[1]["code"], "junit_artifact_request_mismatch")
            self.assertFalse((self.root / "other.xml").exists())
            self.assertFalse((self.root / "requested.xml").exists())


if __name__ == "__main__":
    unittest.main()
