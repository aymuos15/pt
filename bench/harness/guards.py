"""Exploratory observation guards, not proof of equivalent test execution."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


def check_observation(result: Mapping[str, Any], *, expected_exit_code: int,
                      expected_stdout_bytes: int, expected_stdout_sha256: str) -> dict[str, Any]:
    """Compare a completed timer observation with explicit expected evidence.

    Expected stdout is a lightweight sentinel only: it may be spoofed, may not
    reflect individual test outcomes, and does not prove equivalent work or a
    valid generation. No result from this function qualifies a benchmark sample.
    """
    if type(expected_exit_code) is not int:
        raise ValueError("expected_exit_code must be an integer")
    if type(expected_stdout_bytes) is not int or expected_stdout_bytes < 0:
        raise ValueError("expected_stdout_bytes must be a nonnegative integer")
    if (not isinstance(expected_stdout_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_stdout_sha256) is None):
        raise ValueError("expected_stdout_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(result, Mapping):
        raise ValueError("result must be a mapping")

    mismatches = []
    if result.get("status") != "exited_unqualified":
        mismatches.append("not_completed")
    if result.get("process_reaped") is not True:
        mismatches.append("process_not_reaped")
    if result.get("output_complete") is not True:
        mismatches.append("incomplete_output")
    if type(result.get("returncode")) is not int or result["returncode"] != expected_exit_code:
        mismatches.append("exit_code")
    if type(result.get("stdout_bytes")) is not int or result["stdout_bytes"] != expected_stdout_bytes:
        mismatches.append("stdout_size")
    if result.get("stdout_sha256") != expected_stdout_sha256:
        mismatches.append("stdout_digest")
    return {
        "matched_expected_observations": not mismatches,
        "mismatches": mismatches,
        "mode": "exploratory_unqualified",
        "confirmatory_eligible": False,
        "limitations": ["sentinels do not prove equal work", "generation not checked",
                        "environment and artifacts not qualified"],
    }
