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


class PhaseElevenCompletionTests(unittest.TestCase):
    def test_phase_eleven_baseline_is_complete_and_current(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-11-baseline.json")
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-11", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(9, baseline["completed_steps"])
        self.assertEqual(9, len(baseline["capabilities"]))
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertGreaterEqual(int(str(current["phase_id"]).split("-")[1]), 11)
        self.assertIn(current["status"], {"active", "completed"})
        self.assertIn(
            "docs/progress/PHASE-11-COMPLETION.md",
            current["progress_refs"],
        )

    def test_phase_eleven_guarantees_preserve_boundaries(self) -> None:
        guarantees = load_json(
            REPO_ROOT / ".ai" / "phase-11-baseline.json"
        )["guarantees"]
        self.assertFalse(guarantees["external_source_copied"])
        self.assertFalse(guarantees["external_source_mutated"])
        self.assertFalse(guarantees["secret_values_exported"])
        self.assertFalse(guarantees["active_locks_exported"])
        self.assertFalse(guarantees["machine_locator_trusted_after_import"])
        self.assertTrue(guarantees["verified_backup_before_migration"])
        self.assertTrue(guarantees["automatic_rollback_on_failure"])
        self.assertTrue(guarantees["legacy_read_compatible"])

    def test_doctor_recognizes_phase_eleven(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-eleven-baseline", checks)
        self.assertTrue(checks["phase-eleven-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
