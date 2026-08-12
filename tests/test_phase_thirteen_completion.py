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


class PhaseThirteenCompletionTests(unittest.TestCase):
    def test_phase_thirteen_baseline_is_complete_and_current(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-13-baseline.json")
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-13", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertEqual("phase-13", current["phase_id"])
        self.assertEqual("completed", current["status"])
        self.assertIn("docs/progress/PHASE-13-COMPLETION.md", current["progress_refs"])

    def test_phase_thirteen_guarantees_reject_stale_ownership(self) -> None:
        guarantees = load_json(REPO_ROOT / ".ai" / "phase-13-baseline.json")["guarantees"]
        self.assertFalse(guarantees["owner_token_persisted"])
        self.assertFalse(guarantees["stale_worker_completion_allowed"])
        self.assertFalse(guarantees["write_retry_implicit"])
        self.assertFalse(guarantees["active_runtime_portable"])
        self.assertTrue(guarantees["atomic_claim"])
        self.assertTrue(guarantees["fencing_monotonic"])

    def test_doctor_recognizes_phase_thirteen(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-thirteen-baseline", checks)
        self.assertTrue(checks["phase-thirteen-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
