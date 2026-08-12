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


class PhaseTwelveCompletionTests(unittest.TestCase):
    def test_phase_twelve_baseline_is_complete_and_current(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-12-baseline.json")
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-12", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(7, baseline["completed_steps"])
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertGreaterEqual(int(str(current["phase_id"]).split("-")[1]), 12)
        self.assertEqual("completed", current["status"])
        self.assertIn("docs/progress/PHASE-12-COMPLETION.md", current["progress_refs"])

    def test_phase_twelve_guarantees_make_json_authoritative(self) -> None:
        guarantees = load_json(REPO_ROOT / ".ai" / "phase-12-baseline.json")["guarantees"]
        self.assertFalse(guarantees["status_from_vector_similarity"])
        self.assertFalse(guarantees["source_content_copied"])
        self.assertFalse(guarantees["derived_projection_authoritative"])
        self.assertTrue(guarantees["completion_requires_evidence"])
        self.assertTrue(guarantees["dependency_cycles_rejected"])
        self.assertTrue(guarantees["append_only_history"])

    def test_doctor_recognizes_phase_twelve(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-twelve-baseline", checks)
        self.assertTrue(checks["phase-twelve-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
