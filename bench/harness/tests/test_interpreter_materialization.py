"""Offline archive/prefix and synthetic loss controls; not runtime qualification."""

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("private_interpreter_materializer", ROOT / "bench/corpus/interpreter/materialize.py")
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)
spec = importlib.util.spec_from_file_location("private_interpreter_corpus_driver", ROOT / "bench/corpus/interpreter/check_serial_core.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class _ArchiveFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / "input.tar.gz"
        self.output = self.root / "prefix"

    def archive_rows(self, rows):
        with tarfile.open(self.archive, "w:gz") as tar:
            for row in rows:
                item = tarfile.TarInfo(row["path"])
                item.mode = row.get("mode", 0o644)
                item.mtime = 1704067200
                item.type = row.get("type", tarfile.REGTYPE)
                item.linkname = row.get("target", "")
                raw = row.get("raw", b"synthetic file\n")
                item.size = len(raw) if item.isfile() else 0
                tar.addfile(item, io.BytesIO(raw) if item.isfile() else None)

    def good_archive(self):
        self.archive_rows([{"path": "python/bin/python3.12", "mode": 0o755},
                           {"path": "python/bin/python", "type": tarfile.SYMTYPE, "mode": 0o777, "target": "python3.12"},
                           {"path": "python/lib/pkg/config.py", "raw": b"EXACT = 1\n"},
                           {"path": "python/lib/alias", "type": tarfile.SYMTYPE, "target": "../bin/python"}])


@unittest.skipUnless(os.name == "posix", "private interpreter preparation requires POSIX file operations")
class InterpreterArchiveControls(_ArchiveFixture):
    def test_actual_pin_records_identity_evidence_without_inventing_signed_attestation(self):
        pin, raw = preparation.load_pin()
        self.assertEqual(json.loads(raw), pin)
        self.assertEqual(pin["archive"]["bytes"], 33887801)
        self.assertEqual(pin["archive"]["sha256"], "1dbaa624a09e15afe7efbdac08d42993135a68db8d34f986ef6977a6d77bdc3c")
        self.assertIsNone(pin["source"]["signed_build_attestation"])
        self.assertIn("not signed", pin["source"]["identity_evidence"])

    def test_implicit_directories_exact_file_modes_timestamps_and_internal_links_are_verified(self):
        self.good_archive()
        manifest = preparation.plan_archive(self.archive)
        result = preparation.extract_prefix(self.archive, self.output, manifest)
        self.assertEqual(result["status"], "matched_exact_prefix")
        self.assertEqual(result["entries"], 7)
        self.assertEqual({row["path"] for row in manifest if row["kind"] == "directory"}, {"bin", "lib", "lib/pkg"})
        self.assertEqual((self.output / "lib/pkg/config.py").read_bytes(), b"EXACT = 1\n")
        self.assertEqual(os.readlink(self.output / "lib/alias"), "../bin/python")
        self.assertEqual(stat.S_IMODE((self.output / "bin/python3.12").stat().st_mode), 0o755)
        self.assertEqual((self.output / "bin/python3.12").stat().st_mtime_ns, 1704067200000000000)

    def test_traversal_absolute_noncanonical_and_foreign_roots_fail_before_prefix_creation(self):
        for name in ("/python/file", "python/../escape", "python//file", "python/./file", "other/file", "python", "python/a\\b"):
            with self.subTest(name=name):
                self.archive_rows([{"path": name}])
                with self.assertRaises(ValueError):
                    preparation.plan_archive(self.archive)
                self.assertFalse(self.output.exists())

    def test_duplicate_members_and_descendants_beneath_file_or_symlink_are_rejected(self):
        for rows in ([{"path": "python/a"}, {"path": "python/a"}],
                     [{"path": "python/a"}, {"path": "python/a/child"}],
                     [{"path": "python/a", "type": tarfile.SYMTYPE, "target": "b"}, {"path": "python/b"}, {"path": "python/a/child"}]):
            with self.subTest(rows=rows):
                self.archive_rows(rows)
                with self.assertRaises(ValueError):
                    preparation.plan_archive(self.archive)

    def test_external_dangling_cyclic_and_directory_symlinks_are_not_extracted(self):
        for target in ("/tmp/outside", "../../outside", "missing", "a", "../", "./b", "b//c", "dir"):
            rows = [{"path": "python/a", "type": tarfile.SYMTYPE, "target": target},
                    {"path": "python/b"}, {"path": "python/dir/file"}]
            self.archive_rows(rows)
            with self.subTest(target=target), self.assertRaises(ValueError):
                preparation.plan_archive(self.archive)

    def test_hardlinks_devices_fifos_special_modes_and_world_writable_files_fail_closed(self):
        for kind in (tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE):
            self.archive_rows([{"path": "python/file", "type": kind, "target": "python/other"}])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                preparation.plan_archive(self.archive)
        for mode in (0o4755, 0o2755, 0o1755, 0o777):
            self.archive_rows([{"path": "python/file", "mode": mode}])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                preparation.plan_archive(self.archive)

    def test_member_tree_depth_count_and_byte_bounds_cannot_silently_trim_work(self):
        self.good_archive()
        for name, limit in (("MAX_ENTRIES", 2), ("MAX_FILE_BYTES", 1), ("MAX_TREE_BYTES", 1), ("MAX_PATH_DEPTH", 2),
                            ("MAX_EXPANDED_ARCHIVE_BYTES", 1)):
            with mock.patch.object(preparation, name, limit), self.subTest(bound=name), self.assertRaises(ValueError):
                preparation.plan_archive(self.archive)

    def test_truncated_gzip_trailer_is_not_accepted_as_a_complete_archive(self):
        self.good_archive()
        self.archive.write_bytes(self.archive.read_bytes()[:-4])
        with self.assertRaises((EOFError, OSError, tarfile.TarError)):
            preparation.plan_archive(self.archive)

    def test_prefix_comparison_preserves_extra_directories_same_stat_edits_modes_and_link_changes(self):
        self.good_archive()
        manifest = preparation.plan_archive(self.archive)
        preparation.extract_prefix(self.archive, self.output, manifest)
        (self.output / "extra-empty").mkdir()
        (self.output / "extra.py").write_text("extra")
        target = self.output / "lib/pkg/config.py"
        before = target.stat()
        target.write_bytes(b"EXACT = 2\n")
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        (self.output / "bin/python3.12").chmod(0o644)
        (self.output / "lib/alias").unlink()
        (self.output / "lib/alias").symlink_to("../bin/python3.12")
        result = preparation.verify_prefix(self.output, manifest)
        self.assertEqual(result["status"], "prefix_mismatch")
        self.assertEqual(result["extra"], ["extra-empty", "extra.py"])
        self.assertEqual(result["changed"], ["bin/python3.12", "lib/alias", "lib/pkg/config.py"])
        self.assertEqual((self.output / "extra.py").read_text(), "extra")

    def test_fifo_or_hardlinked_installed_file_and_linked_prefix_are_refused(self):
        self.output.mkdir()
        os.mkfifo(self.output / "pipe")
        with self.assertRaises(ValueError):
            preparation.prefix_inventory(self.output)
        (self.output / "pipe").unlink()
        (self.output / "original").write_bytes(b"value")
        os.link(self.output / "original", self.output / "alias")
        with self.assertRaises(ValueError):
            preparation.prefix_inventory(self.output)
        alias = self.root / "linked-prefix"
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises(ValueError):
            preparation.prefix_inventory(alias)

    def test_copy_requires_exact_archive_size_digest_regular_input_and_no_overwrite(self):
        self.good_archive()
        raw = self.archive.read_bytes()
        descriptor = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        destination = self.root / "private.tar.gz"
        self.assertEqual(preparation.copy_archive(self.archive, destination, descriptor), descriptor)
        with self.assertRaises(FileExistsError):
            preparation.copy_archive(self.archive, destination, descriptor)
        for changes in ({"bytes": len(raw) + 1}, {"sha256": "0" * 64}):
            with self.assertRaises(ValueError):
                preparation.copy_archive(self.archive, self.root / ("wrong-" + next(iter(changes))), {**descriptor, **changes})
        alias = self.root / "linked.tar.gz"
        alias.symlink_to(self.archive)
        with self.assertRaises(OSError):
            preparation.copy_archive(alias, self.root / "linked-copy", descriptor)
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(ValueError):
            preparation.copy_archive(self.root / "pipe", self.root / "fifo-copy", descriptor)

    def test_mutated_member_and_preexisting_prefix_are_not_repaired(self):
        self.good_archive()
        manifest = preparation.plan_archive(self.archive)
        self.archive_rows([{"path": "python/bin/python3.12", "mode": 0o755, "raw": b"CHANGED"}])
        with self.assertRaises(ValueError):
            preparation.extract_prefix(self.archive, self.output, manifest)
        self.assertTrue(self.output.exists())
        (self.output / "user-work").write_text("keep")
        with self.assertRaises(FileExistsError):
            preparation.extract_prefix(self.archive, self.output, manifest)
        self.assertEqual((self.output / "user-work").read_text(), "keep")


@unittest.skipUnless(os.name == "posix", "private interpreter preparation requires POSIX file operations")
class InterpreterPreparationLedgerControls(_ArchiveFixture):
    def setUp(self):
        super().setUp()
        self.output = self.root / "run"
        self.good_archive()
        self.pin, _ = preparation.load_pin()
        self.raw = self.archive.read_bytes()
        self.pin["archive"].update(bytes=len(self.raw), sha256=hashlib.sha256(self.raw).hexdigest())
        self.pin["executable"].update(bytes=len(b"synthetic file\n"), sha256=hashlib.sha256(b"synthetic file\n").hexdigest())
        self.calls = []
        self.tools = preparation._tools()

    @contextmanager
    def synthetic(self, effect=None):
        raw_pin = (preparation.HERE / "artifact.json").read_bytes()
        with (mock.patch.object(preparation, "load_pin", return_value=(self.pin, raw_pin)),
              mock.patch.object(preparation, "_tools", return_value=self.tools),
              mock.patch.object(self.tools, "_command", side_effect=effect or self.command)):
            yield

    def command(self, output, name, argv, cwd, env):
        self.calls.append((name, argv, env))
        prefix = Path(argv[0]).parent.parent
        runtime = {"target": copy.deepcopy(self.pin["target"]), "prefix": str(prefix), "base_prefix": str(prefix),
                   "executable": str(prefix / "bin/python3.12"), "qualified": False,
                   "flags": {"no_site": 0, "isolated": 0, "ignore_environment": 0, "no_user_site": 0, "dont_write_bytecode": 1},
                   "site_loaded": True, "user_site_exists": False, "soabi": "cpython-312-x86_64-linux-gnu"}
        (output / (name + "-complete-looking.json")).write_text(json.dumps(runtime))
        return {"returncode": 0, "synthetic_test_control": True}, {"stdout": json.dumps(runtime).encode(), "stderr": b""}

    def produce(self):
        return preparation.prepare(self.archive, self.output, execute=True)

    def test_requires_explicit_execution_and_separate_new_output(self):
        with self.assertRaisesRegex(ValueError, "--execute"):
            preparation.prepare(self.archive, self.output)
        with self.synthetic(), self.assertRaisesRegex(ValueError, "outside"):
            preparation.prepare(self.archive, ROOT / "not-created", execute=True)
        self.output.mkdir()
        (self.output / "user-work").write_text("keep")
        with self.synthetic(), self.assertRaises(FileExistsError):
            self.produce()
        self.assertEqual((self.output / "user-work").read_text(), "keep")
        self.assertEqual(self.calls, [])

    def test_synthetic_preparation_keeps_both_planned_rows_and_all_qualification_gates_null(self):
        with self.synthetic():
            report = self.produce()
        self.assertEqual(report["status"], "matched_two_private_prefixes_unqualified", report["errors"])
        self.assertEqual(len(report["planned_prefixes"]), 2)
        self.assertTrue(all(row["status"] == "matched_prefix_and_startup_diagnostic_unqualified" for row in report["planned_prefixes"]))
        self.assertTrue(all(row["observation"]["synthetic_test_control"] for row in report["planned_prefixes"]))
        self.assertTrue(all(value is None for value in report["qualification"].values()))
        self.assertFalse(report["confirmatory_eligible"])
        self.assertEqual(json.loads((self.output / "result.json").read_text()), report)

    def test_lost_probe_return_cannot_be_recovered_from_complete_looking_runtime_output(self):
        def lost(*args):
            self.command(*args)
            raise OSError("explicit synthetic return loss after a complete-looking diagnostic")

        with self.synthetic(lost):
            report = self.produce()
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["planned_prefixes"][0]["status"], "unknown_execution_return")
        self.assertIsNone(report["planned_prefixes"][0]["observation"])
        self.assertIsNone(report["planned_prefixes"][0]["runtime"])
        self.assertEqual(report["planned_prefixes"][1]["status"], "not_run_prior_failure")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((self.output / "probe-1-complete-looking.json").exists())

    def test_nonzero_probe_keeps_its_return_and_does_not_run_second_prefix(self):
        def failed(*args):
            observation, raw = self.command(*args)
            observation["returncode"] = 1
            return observation, raw

        with self.synthetic(failed):
            report = self.produce()
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["planned_prefixes"][0]["observation"]["returncode"], 1)
        self.assertEqual(report["planned_prefixes"][1]["status"], "not_run_prior_failure")
        self.assertEqual(len(self.calls), 1)

    def test_startup_mutation_is_retained_not_ignored_or_repaired(self):
        def mutate(*args):
            result = self.command(*args)
            (self.output / "prefix-1/lib/unknown.py").write_text("changed")
            return result

        with self.synthetic(mutate):
            report = self.produce()
        self.assertEqual(report["status"], "aborted")
        self.assertEqual(report["planned_prefixes"][0]["after"]["extra"], ["lib/unknown.py"])
        self.assertEqual((self.output / "prefix-1/lib/unknown.py").read_text(), "changed")
        self.assertEqual(len(self.calls), 1)

    def test_changed_python_target_or_disabled_site_is_not_a_supported_ordinary_startup(self):
        def suppress(*args):
            observation, raw = self.command(*args)
            value = json.loads(raw["stdout"])
            value["flags"]["no_site"] = 1
            raw["stdout"] = json.dumps(value).encode()
            return observation, raw

        with self.synthetic(suppress):
            report = self.produce()
        self.assertEqual(report["status"], "aborted")
        self.assertIn("ordinary-startup", report["errors"][0]["error"])

    def test_changed_frozen_pin_or_manifest_cannot_upgrade_returned_success(self):
        def change(*args):
            result = self.command(*args)
            if args[1] == "probe-2":
                (self.output / "prefix-manifest.json").write_text("changed")
            return result

        with self.synthetic(change):
            report = self.produce()
        self.assertEqual(report["status"], "aborted")
        self.assertIn("inputs changed", report["errors"][0]["error"])

    def test_result_publication_return_loss_is_not_recovered_from_a_result_file(self):
        original = self.tools._save

        def lost(path, value):
            original(path, value)
            if path.name == "result.json":
                raise OSError("explicit synthetic publication return loss")

        with self.synthetic(), mock.patch.object(self.tools, "_save", side_effect=lost), self.assertRaises(OSError):
            self.produce()
        self.assertTrue((self.output / "result.json").exists())


@unittest.skipUnless(os.name == "posix", "private interpreter preparation requires POSIX file operations")
class PrivateBaseCoreLedgerControls(_ArchiveFixture):
    def setUp(self):
        super().setUp()
        self.good_archive()
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        self.output = self.root / "run"
        raw = self.archive.read_bytes()
        self.pin, self.raw_pin = preparation.load_pin()
        self.pin["archive"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        (self.prepared / "interpreter.tar.gz").write_bytes(raw)
        manifest = preparation.plan_archive(self.archive)
        (self.prepared / "prefix-manifest.json").write_text(json.dumps({"profile": self.pin["profile"], "entries": manifest}))
        (self.prepared / "result.json").write_text(json.dumps({"status": "matched_two_private_prefixes_unqualified", "profile": self.pin["profile"]}))
        (self.prepared / "frozen").mkdir()
        (self.prepared / "frozen/artifact.json").write_bytes(self.raw_pin)
        for index in (1, 2):
            preparation.extract_prefix(self.archive, self.prepared / f"prefix-{index}", manifest)
        self.tools = preparation._tools()
        self.calls = []

    @contextmanager
    def synthetic(self, effect=None):
        def module(name, path):
            return preparation if Path(path).parent.name == "interpreter" else self.tools

        with (mock.patch.object(driver, "_load", side_effect=module),
              mock.patch.object(preparation, "load_pin", return_value=(self.pin, self.raw_pin)),
              mock.patch.object(self.tools, "materialize", side_effect=effect or self.corpus)):
            yield

    def corpus(self, output, **kwargs):
        self.calls.append(kwargs)
        output.mkdir()
        value = {"status": "reproduced_declared_mechanism_profile", "synthetic_test_control": True,
                 "cases": [{"status": "matched_declared_process_and_probe_outcomes", "exit": code} for code in (0, 1, 2, 5)]}
        (output / "result.json").write_text(json.dumps(value))
        return value

    def produce(self):
        return driver.check(self.prepared, self.output, execute=True)

    def test_explicit_private_bases_are_forwarded_and_never_turn_known_adverse_exits_into_passes(self):
        with self.synthetic():
            report = self.produce()
        self.assertEqual(report["status"], "matched_core_on_two_pinned_private_bases_unqualified", report["errors"])
        self.assertEqual(self.calls[0]["interpreters"], [self.prepared / f"prefix-{index}/bin/python3.12" for index in (1, 2)])
        self.assertEqual([row["exit"] for row in report["corpus"]["cases"]], [0, 1, 2, 5])
        self.assertTrue(all(value is None for value in report["qualification"].values()))
        self.assertFalse(report["confirmatory_eligible"])

    def test_saved_success_flags_cannot_waive_actual_prefix_or_manifest_changes(self):
        (self.prepared / "prefix-1/unlisted.py").write_text("keep this difference")
        with self.synthetic(), self.assertRaisesRegex(ValueError, "prefix changed"):
            self.produce()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_lost_corpus_return_is_not_reconstructed_from_complete_looking_result(self):
        def lost(*args, **kwargs):
            self.corpus(*args, **kwargs)
            raise OSError("explicit synthetic corpus API return loss")

        with self.synthetic(lost):
            report = self.produce()
        self.assertEqual(report["status"], "unknown_corpus_return")
        self.assertIsNone(report["corpus"])
        self.assertIsNone(report["after"])
        self.assertTrue((self.output / "corpus/result.json").exists())
        self.assertEqual(len(self.calls), 1)

    def test_returned_failed_corpus_remains_visible_even_when_base_prefixes_still_match(self):
        def failed(*args, **kwargs):
            result = self.corpus(*args, **kwargs)
            result["status"] = "aborted"
            return result

        with self.synthetic(failed):
            report = self.produce()
        self.assertEqual(report["status"], "incomplete_corpus_or_interpreter_check")
        self.assertEqual(report["corpus"]["status"], "aborted")
        self.assertTrue(all(row["status"] == "matched_exact_prefix" for row in report["after"]))
        self.assertEqual(len(self.calls), 1)

    def test_changed_base_after_corpus_is_retained_and_cannot_be_hidden_by_test_success(self):
        def changed(*args, **kwargs):
            result = self.corpus(*args, **kwargs)
            (self.prepared / "prefix-2/extra-directory").mkdir()
            return result

        with self.synthetic(changed):
            report = self.produce()
        self.assertEqual(report["status"], "incomplete_corpus_or_interpreter_check")
        self.assertEqual(report["after"][1]["extra"], ["extra-directory"])
        self.assertTrue((self.prepared / "prefix-2/extra-directory").exists())


if __name__ == "__main__":
    unittest.main()
