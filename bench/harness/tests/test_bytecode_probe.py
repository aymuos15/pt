import json
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = (Path(__file__).resolve().parents[2] / "corpus" / "probes" /
         "bytecode_integrity_probe.py")


class BytecodeProbeTests(unittest.TestCase):
    @unittest.skipUnless(sys.implementation.name == "cpython", "CPython bytecode behavior")
    def test_same_stat_edit_exposes_stale_timestamp_pyc(self):
        result = subprocess.run([sys.executable, str(PROBE)], capture_output=True,
                                text=True, timeout=30, check=True)
        report = json.loads(result.stdout)
        for scenario in report.values():
            self.assertTrue(scenario["same_size"])
            self.assertTrue(scenario["same_mtime_ns"])
            self.assertEqual(scenario["source_value"], "new")
        self.assertEqual(report["timestamp_pyc"]["observed_value"], "old")
        self.assertEqual(report["checked_hash_pyc"]["observed_value"], "new")


if __name__ == "__main__":
    unittest.main()
