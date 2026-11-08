import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "schedule", Path(__file__).resolve().parents[1] / "schedule.py"
)
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)


class PairedScheduleTests(unittest.TestCase):
    def test_reproducible_balanced_orders(self):
        first = schedule.paired_schedule(30, 42017)
        self.assertEqual(first, schedule.paired_schedule(30, 42017))
        self.assertEqual([item["block"] for item in first], list(range(1, 31)))
        self.assertEqual(sum(item["order"][0] == "baseline" for item in first), 15)
        for item in first:
            self.assertEqual(set(item["order"]), {"baseline", "candidate"})
            self.assertEqual(len(item["order"]), 2)

    def test_odd_count_differs_by_at_most_one(self):
        for blocks in (1, 3, 31):
            for seed in range(10):
                result = schedule.paired_schedule(blocks, seed)
                ab = sum(item["order"][0] == "baseline" for item in result)
                self.assertLessEqual(abs(ab - (blocks - ab)), 1)

    def test_seed_changes_order(self):
        self.assertNotEqual(schedule.paired_schedule(30, 1), schedule.paired_schedule(30, 2))

    def test_invalid_inputs_rejected(self):
        for blocks, seed in [(0, 1), (-1, 1), (1.5, 1), (True, 1), (1, True), (1, 1.5)]:
            with self.subTest(blocks=blocks, seed=seed), self.assertRaises(ValueError):
                schedule.paired_schedule(blocks, seed)


if __name__ == "__main__":
    unittest.main()
