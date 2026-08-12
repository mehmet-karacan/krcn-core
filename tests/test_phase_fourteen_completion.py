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


class PhaseFourteenCompletionTests(unittest.TestCase):
    def test_phase_fourteen_baseline_is_complete_and_current(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-14-baseline.json")
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-14", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(9, baseline["completed_steps"])
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertGreaterEqual(int(str(current["phase_id"]).split("-")[1]), 14)
        self.assertIn(current["status"], {"active", "completed"})
        self.assertIn(
            "docs/progress/PHASE-14-COMPLETION.md",
            current["progress_refs"],
        )

    def test_phase_fourteen_guarantees_exclude_rows_and_secrets(self) -> None:
        guarantees = load_json(
            REPO_ROOT / ".ai" / "phase-14-baseline.json"
        )["guarantees"]
        self.assertFalse(guarantees["row_data_collected"])
        self.assertFalse(guarantees["free_sql_allowed"])
        self.assertFalse(guarantees["select_only_overridden"])
        self.assertFalse(guarantees["execute_deny_overridden"])
        self.assertFalse(guarantees["raw_database_link_ddl_persisted"])
        self.assertFalse(guarantees["partial_snapshot_retires_objects"])
        self.assertTrue(guarantees["project_scoped_index"])

    def test_doctor_recognizes_phase_fourteen(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-fourteen-baseline", checks)
        self.assertTrue(checks["phase-fourteen-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
