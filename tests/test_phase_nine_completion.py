from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import OPERATIONS  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseNineCompletionTests(unittest.TestCase):
    def test_phase_nine_baseline_is_complete_and_current(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-9-baseline.json")
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-9", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(8, baseline["completed_steps"])
        self.assertEqual(8, len(baseline["capabilities"]))
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertIn(current["status"], {"active", "completed"})
        self.assertIn(
            "docs/progress/PHASE-9-COMPLETION.md",
            current["progress_refs"],
        )

    def test_phase_nine_guarantees_are_safe(self) -> None:
        guarantees = load_json(
            REPO_ROOT / ".ai" / "phase-9-baseline.json"
        )["guarantees"]
        self.assertTrue(guarantees["manual_scan_visible"])
        self.assertTrue(guarantees["automatic_scan_visible"])
        self.assertTrue(guarantees["fresh_complete_no_op"])
        self.assertTrue(guarantees["missing_stage_repair"])
        self.assertFalse(guarantees["external_source_copied"])
        self.assertFalse(guarantees["external_source_mutated"])
        self.assertFalse(guarantees["remote_provider_implicit"])
        self.assertTrue(guarantees["exact_plan_required"])
        self.assertTrue(guarantees["user_policy_preserved"])

    def test_doctor_recognizes_phase_nine(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-nine-baseline", checks)
        self.assertTrue(checks["phase-nine-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
