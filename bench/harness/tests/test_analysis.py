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

    def test_bootstrap_resamples_pairs_reproducibly(self):
        # Baseline and candidate each vary tenfold, but every paired ratio is 2.
        samples = [sample("b", "baseline", 20), sample("b", "candidate", 10),
                   sample("a", "baseline", 200), sample("a", "candidate", 100)]
        result = analysis.bootstrap_paired_ratio(samples, seed=4, resamples=100)
        self.assertEqual(result, analysis.bootstrap_paired_ratio(
            list(reversed(samples)), seed=4, resamples=100))
        self.assertAlmostEqual(result["point_estimate"], 2)
        self.assertAlmostEqual(result["interval_lower"], 2)
        self.assertAlmostEqual(result["interval_upper"], 2)
        self.assertEqual(result["mode"], "exploratory_unqualified")
        self.assertEqual(result["ratio_direction"], "baseline_over_candidate")

    def test_bootstrap_rejects_invalid_inputs_and_incomplete_blocks(self):
        one = [sample("1", "baseline", 1), sample("1", "candidate", 1)]
        two = one + [sample("2", "baseline", 1), sample("2", "candidate", 1)]
        for samples, options in [
            (one, {"seed": 1, "resamples": 10}),
            (two[:-1], {"seed": 1, "resamples": 10}),
            (two, {"seed": True, "resamples": 10}),
            (two, {"seed": 1, "resamples": 1}),
            (two, {"seed": 1, "resamples": True}),
            (two, {"seed": 1, "resamples": 10, "confidence": float("nan")}),
            (two, {"seed": 1, "resamples": 10, "confidence": 1}),
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                analysis.bootstrap_paired_ratio(samples, **options)

    def test_bootstrap_covers_distinct_block_ratios(self):
        samples = [sample("1", "baseline", 1), sample("1", "candidate", 1),
                   sample("2", "baseline", 4), sample("2", "candidate", 1)]
        result = analysis.bootstrap_paired_ratio(samples, seed=1, resamples=1000,
                                                 confidence=0.8)
        self.assertAlmostEqual(result["point_estimate"], 2)
        self.assertAlmostEqual(result["interval_lower"], 1)
        self.assertAlmostEqual(result["interval_upper"], 4)


if __name__ == "__main__":
    unittest.main()
