import importlib.util
from pathlib import Path
import tempfile
import unittest


HARNESS = Path(__file__).resolve().parents[1]
SOURCE = HARNESS.parent / "corpus" / "candidates.toml"
spec = importlib.util.spec_from_file_location("candidate_inventory", HARNESS / "candidate_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)
SHORTLIST = SOURCE.read_text()


class CandidateInventoryTests(unittest.TestCase):
    def check_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidates.toml"
            path.write_text(text)
            return inventory.check_shortlist(path)

    def test_all_candidates_remain_unqualified_and_unassigned(self):
        result = inventory.check_shortlist(SOURCE)
        self.assertEqual(result["candidates"], 12)
        self.assertEqual(result["eligibility_unassessed"], 12)
        self.assertEqual(result["allocations_assigned"], 0)
        self.assertFalse(result["remote_revisions_rechecked"])
        self.assertFalse(result["confirmatory_eligible"])

    def test_unverified_qualification_or_allocation_rejected(self):
        for text in (SHORTLIST.replace('eligibility = "unassessed"', 'eligibility = "eligible"', 1),
                     SHORTLIST.replace('allocation = "unassigned"', 'allocation = "holdout"', 1),
                     SHORTLIST.replace('status = "unqualified_shortlist"', 'status = "qualified"', 1)):
            with self.subTest(text=text[:100]), self.assertRaises(inventory.CandidateError):
                self.check_text(text)

    def test_duplicate_invalid_revision_or_url_rejected(self):
        first_candidate = SHORTLIST.split("[[candidates]]", 2)[1]
        cases = [SHORTLIST + "\n[[candidates]]" + first_candidate,
                 SHORTLIST.replace("9d9f94a043de7fc4012459853a4ed597a5577855", "not-a-revision", 1),
                 SHORTLIST.replace("https://github.com/python-attrs/attrs.git",
                                   "https://example.invalid/python-attrs/attrs.git", 1)]
        for text in cases:
            with self.subTest(length=len(text)), self.assertRaises(inventory.CandidateError):
                self.check_text(text)


if __name__ == "__main__":
    unittest.main()
