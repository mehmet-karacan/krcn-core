from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import OPERATIONS  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402
from progress_evidence import assert_progress_evidence  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseSevenCompletionTests(unittest.TestCase):
    def test_phase_seven_baseline_is_complete_and_versioned(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-7-baseline.json")
        schema = load_json(REPO_ROOT / "schemas" / "phase-7-baseline.schema.json")
        self.assertEqual("urn:krcn:schemas:phase-7-baseline:1", schema["$id"])
        self.assertEqual("phase-7", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(7, baseline["completed_steps"])
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertFalse(
            baseline["guarantees"]["technical_identifiers_required_from_user"]
        )
        self.assertFalse(baseline["guarantees"]["external_source_copied"])
        self.assertFalse(baseline["guarantees"]["external_source_mutated"])
        self.assertTrue(baseline["guarantees"]["user_policy_preserved"])
        self.assertTrue(baseline["guarantees"]["single_user_approval"])
        self.assertTrue(baseline["maintenance"]["new_phase_requires_user_approval"])

    def test_phase_seven_completion_evidence_is_preserved(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        baseline = load_json(REPO_ROOT / ".ai" / "phase-7-baseline.json")
        self.assertEqual("ready", baseline["status"])
        for reference in (
            "docs/progress/PHASE-7-INTEGRATION-TESTS.md",
            "docs/progress/PHASE-7-COMPLETION.md",
        ):
            assert_progress_evidence(self, reference)
        completion = (
            REPO_ROOT / "docs" / "progress" / "PHASE-7-COMPLETION.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Faz 7 tamamlandı", completion)
        self.assertIn("yalnızca proje dizinini", completion)

    def test_doctor_includes_completed_phase_seven_baseline(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-seven-baseline", checks)
        self.assertTrue(checks["phase-seven-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
