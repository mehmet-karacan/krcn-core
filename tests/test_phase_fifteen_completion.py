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


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseFifteenCompletionTests(unittest.TestCase):
    def test_phase_fifteen_baseline_is_complete_and_current(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-15-baseline.json")
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-15", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(8, baseline["completed_steps"])
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertGreaterEqual(int(str(current["phase_id"]).split("-")[1]), 15)
        self.assertIn(current["status"], {"active", "completed"})
        assert_progress_evidence(self, "docs/progress/PHASE-15-COMPLETION.md")

    def test_phase_fifteen_guarantees_preserve_exact_authority(self) -> None:
        guarantees = load_json(
            REPO_ROOT / ".ai" / "phase-15-baseline.json"
        )["guarantees"]
        self.assertFalse(guarantees["semantic_overrides_exact"])
        self.assertFalse(guarantees["implicit_remote_provider_call"])
        self.assertFalse(guarantees["stale_index_used"])
        self.assertFalse(guarantees["physical_paths_disclosed"])
        self.assertFalse(guarantees["default_multi_project_scope"])
        self.assertTrue(guarantees["authoritative_work_first"])
        self.assertTrue(guarantees["token_budget_enforced"])
        self.assertTrue(guarantees["domain_failures_reported"])

    def test_doctor_recognizes_phase_fifteen(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-fifteen-baseline", checks)
        self.assertTrue(checks["phase-fifteen-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
