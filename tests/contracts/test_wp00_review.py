"""Documentation/pin traceability only, not acceptance or security proof.

The authored WP00 review makes the design decision. These guards merely expose
missing rows, stale pins or broken references; they do not qualify a runner.
"""

import json
from pathlib import Path
import re
import unittest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def text(name):
    return (DOCS / name).read_text()


def rows(source, key):
    return [line.split("|")[1:-1] for line in source.splitlines()
            if re.match(rf"^\| {key} \|", line)]


def ids(table):
    return [row[0].strip().strip("`") for row in table]


class WP00ReviewTraceabilityTests(unittest.TestCase):
    def test_acceptance_rows_are_complete_and_do_not_close_product_gates(self):
        review = text("wp00-review.md")
        criteria = rows(review, r"A\d{2}")
        self.assertEqual(ids(criteria), [f"A{number:02}" for number in range(1, 9)])
        for row in criteria:
            self.assertEqual(len(row), 4)
            self.assertTrue(all(value.strip() for value in row))
        normalized = " ".join(review.split())
        self.assertIn("reviewing its own design", normalized)
        self.assertIn("No independent reviewer", normalized)
        self.assertIn("M0, M1 and release are not complete; `pt run` remains unavailable.", normalized)

    def test_selected_versions_match_the_schemas_package_toolchain_and_lock(self):
        matrix = tomllib.loads((ROOT / "support-matrix.toml").read_text())
        schema = json.loads((DOCS / "protocol-v0.schema.json").read_text())
        bridge = tomllib.loads((ROOT / "python/pt_bridge/pyproject.toml").read_text())["project"]
        rust = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]
        lock = tomllib.loads((ROOT / "bench/harness/uv.lock").read_text())
        self.assertEqual(len(matrix["profile"]), 1)
        profile = matrix["profile"][0]
        handshake = schema["$defs"]["handshake"]["properties"]
        python = handshake["python_version"]["const"]
        pytest = handshake["pytest_version"]["const"]
        self.assertEqual(profile["interpreter"], f"CPython {python} (GIL-enabled)")
        self.assertEqual(profile["pytest"], pytest)
        self.assertEqual(profile["os"], "linux")
        self.assertEqual(profile["architecture"], "x86_64")
        self.assertEqual(profile["backend"], "serial real pytest")
        self.assertEqual(set(profile["invocation_profiles"]), {"python -m pytest", "pytest console entrypoint"})
        self.assertEqual(bridge["version"], handshake["bridge_version"]["const"])
        self.assertEqual(bridge["requires-python"], f"=={python}")
        self.assertIn(f"pytest=={pytest}", bridge["dependencies"])
        self.assertEqual([package["version"] for package in lock["package"] if package["name"] == "pytest"], [pytest])
        contracts = text("contracts.md")
        for version in (python, pytest, bridge["version"], rust["channel"]):
            self.assertIn(f"**{version}**", contracts)

    def test_target_matrix_remains_unqualified_and_passthrough_unavailable(self):
        matrix = tomllib.loads((ROOT / "support-matrix.toml").read_text())
        self.assertEqual(matrix["status"], "target-selected-unqualified")
        self.assertEqual(matrix["profile"][0]["status"], "target-selected")
        self.assertIn("no PT conformance", matrix["profile"][0]["evidence"])
        self.assertIn("no implicit or currently implemented passthrough", matrix["unsupported"]["default"])

    def test_nine_permissions_have_reference_contracts_matching_the_spec_and_schema(self):
        spec = text("pt-implementation-spec.md")
        initial = spec.split("Initial capabilities:", 1)[1].split("Capabilities are not inferred", 1)[0]
        names = set(re.findall(r"^(?:collection|execution|fixtures|resources|selection)\.[a-z_]+$", initial, re.MULTILINE))
        schema = json.loads((DOCS / "protocol-v0.schema.json").read_text())
        capability = schema["$defs"]["capability"]["properties"]
        policy = rows(text("capability-policy.md"), r"`[a-z_.]+`")
        self.assertEqual(len(names), 9)
        self.assertEqual(set(ids(policy)), names)
        self.assertEqual(set(capability["capability"]["enum"]), names)
        self.assertEqual(set(capability["decision"]["enum"]), {"deny", "unknown"})
        self.assertEqual(capability["scope"]["const"], "session")
        for row in policy:
            self.assertEqual(len(row), 3)
            self.assertTrue(row[1].strip() and row[2].strip())

    def test_all_test_terminal_outcomes_are_documented_without_process_scope_confusion(self):
        schema = json.loads((DOCS / "final-result-v0.schema.json").read_text())
        outcomes = set(schema["properties"]["outcome"]["enum"])
        documented = ids(rows(text("contracts.md"), r"`[a-z_]+`"))
        self.assertEqual(len(outcomes), 10)
        self.assertEqual(set(documented), outcomes)
        self.assertEqual(len(documented), 10)
        self.assertNotIn("process_exited", outcomes)
        self.assertIn("Diagnostic `process_exited`", text("contracts.md"))

    def test_all_invariants_retain_their_adverse_evidence_rows(self):
        expected = [f"C{number:02}" for number in range(1, 13)]
        self.assertEqual(ids(rows(text("pt-implementation-spec.md"), r"C\d{2}")), expected)
        reviewed = rows(text("invariant-review.md"), r"C\d{2}")
        self.assertEqual(ids(reviewed), expected)
        self.assertTrue(all(len(row) == 3 and row[2].strip() for row in reviewed))

    def test_every_threat_has_a_control_evidence_gate_and_review_disposition(self):
        threats = rows(text("threat-model.md"), r"T\d{2}")
        expected = [f"T{number:02}" for number in range(1, 13)]
        self.assertEqual(ids(threats), expected)
        for row in threats:
            self.assertEqual(len(row), 4)
            self.assertTrue(all(value.strip() for value in row))
            self.assertRegex(row[3], r"WP\d{2}")
        self.assertEqual(set(re.findall(r"\bT\d{2}\b", text("wp00-review.md"))), set(expected))

    def test_all_six_adrs_have_reviewed_alternatives_and_consequences(self):
        expected = [f"ADR{number:03}" for number in range(1, 7)]
        alternatives = rows(text("adr/README.md"), r"ADR\d{3}")
        self.assertEqual(ids(alternatives), expected)
        for row in alternatives:
            self.assertEqual(len(row), 4)
            self.assertTrue(all(value.strip() for value in row))
        paths = sorted((DOCS / "adr").glob("[0-9][0-9][0-9]-*.md"))
        self.assertEqual(len(paths), 6)
        for path, name in zip(paths, expected):
            source = path.read_text()
            self.assertTrue(source.startswith(f"# {name}:"))
            self.assertIn("Status: adopted", source)
            self.assertIn("self-review", source)
        self.assertIn("**deferred**", paths[3].read_text())

    def test_gates_and_all_benchmark_sections_remain_explicit_without_campaign_promotion(self):
        review = text("wp00-review.md")
        gates = rows(review, r"G\d{2}")
        expected = [f"G{number:02}" for number in range(1, 11)]
        self.assertEqual(ids(gates), expected)
        self.assertEqual(set(re.findall(r"\bG\d{2}\b", review)), set(expected))
        self.assertIn("All rows are **open**", review)
        for row in gates:
            self.assertEqual(len(row), 3)
            self.assertRegex(row[1], r"WP\d{2}")
            self.assertTrue(row[2].strip())
        sections = ids(rows(text("benchmark-charter.md"), r"§\d{2}"))
        self.assertEqual(sections, [f"§{number}" for number in range(12, 21)])
        checklist = text("benchmark-review-checklist.md")
        self.assertNotRegex(checklist, r"- \[[xX]\]")
        self.assertIn("Decision: **unreviewed**", checklist)

    def test_reviewed_document_links_resolve_inside_the_repository(self):
        names = ("contracts.md", "wp00-review.md", "threat-model.md", "baseline-contract-v1.md",
                 "protocol-draft.md", "capability-policy.md", "invariant-review.md",
                 "benchmark-charter.md", "adr/README.md")
        paths = [ROOT / "README.md", *(DOCS / name for name in names)]
        paths.extend(sorted((DOCS / "adr").glob("[0-9][0-9][0-9]-*.md")))
        for path in paths:
            for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", path.read_text()):
                if "://" in target:
                    continue
                resolved = (path.parent / target).resolve()
                with self.subTest(path=path.relative_to(ROOT), target=target):
                    self.assertTrue(resolved.is_relative_to(ROOT))
                    self.assertTrue(resolved.exists())


if __name__ == "__main__":
    unittest.main()
