from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import OPERATIONS  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseSixCompletionTests(unittest.TestCase):
    def test_phase_six_baseline_is_complete_and_versioned(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-6-baseline.json")
        schema = load_json(REPO_ROOT / "schemas" / "phase-6-baseline.schema.json")
        self.assertEqual("urn:krcn:schemas:phase-6-baseline:1", schema["$id"])
        self.assertEqual("phase-6", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertFalse(baseline["guarantees"]["external_source_copied"])
        self.assertFalse(baseline["guarantees"]["external_source_mutated"])
        self.assertFalse(baseline["guarantees"]["secret_values_archived"])
        self.assertTrue(baseline["guarantees"]["user_policy_preserved"])
        self.assertTrue(baseline["guarantees"]["repo_local_source_preserved"])
        self.assertTrue(baseline["guarantees"]["clean_clone_recovery"])
        self.assertTrue(baseline["maintenance"]["new_phase_requires_user_approval"])

    def test_current_work_and_completion_evidence_are_closed(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-6", current["phase_id"])
        self.assertEqual("completed", current["status"])
        for reference in (
            "docs/progress/PHASE-6-INTEGRATION-TESTS.md",
            "docs/progress/PHASE-6-COMPLETION.md",
        ):
            self.assertIn(reference, current["progress_refs"])
        completion = (
            REPO_ROOT / "docs" / "progress" / "PHASE-6-COMPLETION.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Faz 6 - release, kalite ve taşınabilirlik tamamlandı", completion)
        self.assertIn("Proje kaynakları bilinçli olarak", completion)

    def test_doctor_includes_completed_phase_six_baseline(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-six-baseline", checks)
        self.assertTrue(checks["phase-six-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
