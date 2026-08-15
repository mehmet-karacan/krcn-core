from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.application import OPERATIONS  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402
from progress_evidence import assert_progress_evidence  # noqa: E402


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseEightCompletionTests(unittest.TestCase):
    def test_phase_eight_baseline_is_complete_and_versioned(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-8-baseline.json")
        schema = load_json(REPO_ROOT / "schemas" / "phase-8-baseline.schema.json")
        self.assertEqual("urn:krcn:schemas:phase-8-baseline:1", schema["$id"])
        self.assertEqual("phase-8", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertEqual(10, len(baseline["capabilities"]))
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        guarantees = baseline["guarantees"]
        self.assertTrue(guarantees["project_local_home_default"])
        self.assertTrue(guarantees["custom_local_home_supported"])
        self.assertFalse(guarantees["local_data_tracked"])
        self.assertFalse(guarantees["external_source_copied"])
        self.assertFalse(guarantees["external_source_mutated"])
        self.assertFalse(guarantees["database_mutation_effect"])
        self.assertFalse(guarantees["secret_value_disclosed"])
        self.assertTrue(guarantees["user_policy_preserved"])
        self.assertTrue(guarantees["clean_clone_recovery"])
        self.assertTrue(guarantees["coverage_threshold_enforced"])
        self.assertTrue(baseline["maintenance"]["new_phase_requires_user_approval"])

    def test_all_ten_progress_steps_and_completion_are_canonical(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        expected = {
            "docs/progress/PHASE-8-KICKOFF.md",
            "docs/progress/PHASE-8-RESEARCH-EVALUATION.md",
            "docs/progress/PHASE-8-PROJECT-HOME-RESOLUTION.md",
            "docs/progress/PHASE-8-PROJECT-HOME-INITIALIZATION.md",
            "docs/progress/PHASE-8-PROJECT-HOME-CLIENT-INTEGRATION.md",
            "docs/progress/PHASE-8-PROJECT-HOME-PORTABILITY.md",
            "docs/progress/PHASE-8-DATA-INTEGRITY.md",
            "docs/progress/PHASE-8-RUNTIME-INTEGRATION.md",
            "docs/progress/PHASE-8-HYBRID-RETRIEVAL.md",
            "docs/progress/PHASE-8-QUALITY-OBSERVABILITY-UX.md",
            "docs/progress/PHASE-8-COMPLETION.md",
        }
        assert_progress_evidence(self, *sorted(expected))
        self.assertIn(current["status"], {"active", "completed"})
        baseline = load_json(REPO_ROOT / ".ai" / "phase-8-baseline.json")
        self.assertEqual("ready", baseline["maintenance"]["status"])
        self.assertTrue(baseline["maintenance"]["new_phase_requires_user_approval"])

    def test_doctor_recognizes_completed_phase_eight(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-eight-baseline", checks)
        self.assertTrue(checks["phase-eight-baseline"].passed)

    def test_acceptance_runner_covers_every_phase_eight_workstream(self) -> None:
        runner = (
            REPO_ROOT / "tools" / "run_phase_eight_acceptance.py"
        ).read_text(encoding="utf-8")
        for module in (
            "test_project_home_client_integration",
            "test_project_home_portability",
            "test_deployment",
            "test_local_store",
            "test_phase_eight_runtime_integration",
            "test_hybrid_retrieval",
            "test_phase_eight_quality_ux",
        ):
            self.assertIn(module, runner)


if __name__ == "__main__":
    unittest.main()
