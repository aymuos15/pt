import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "analysis", Path(__file__).resolve().parents[1] / "analysis.py"
)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def sample(block, arm, duration, status="valid_expected_outcome"):
    return {"block": block, "arm": arm, "elapsed_ns": duration, "status": status}


class PairedRatioTests(unittest.TestCase):
    def test_direction_and_geometric_pairing(self):
        samples = [sample("1", "baseline", 400), sample("1", "candidate", 200),
                   sample("2", "baseline", 100), sample("2", "candidate", 100)]
        self.assertAlmostEqual(analysis.paired_geometric_ratio(samples), 2 ** 0.5)
        self.assertAlmostEqual(analysis.paired_geometric_ratio(list(reversed(samples))), 2 ** 0.5)

    def test_slow_candidate_is_below_one(self):
        self.assertAlmostEqual(analysis.paired_geometric_ratio(
            [sample("1", "baseline", 100), sample("1", "candidate", 200)]), 0.5)

    def test_incomplete_duplicate_or_invalid_never_dropped(self):
        valid = [sample("1", "baseline", 1), sample("1", "candidate", 1)]
        invalid_sets = [[], valid[:1], valid + [valid[0]],
                        valid + [sample("2", "baseline", 1)],
                        [valid[0], sample("1", "candidate", 1, "timeout")],
                        [valid[0], sample("1", "candidate", 0)],
                        [valid[0], sample("1", "candidate", True)],
                        [valid[0], sample("1", "other", 1)],
                        [valid[0], sample("", "candidate", 1)]]
        for samples in invalid_sets:
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                analysis.paired_geometric_ratio(samples)


if __name__ == "__main__":
    unittest.main()
