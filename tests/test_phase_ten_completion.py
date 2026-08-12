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


class PhaseTenCompletionTests(unittest.TestCase):
    def test_phase_ten_baseline_is_complete_and_current(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-10-baseline.json")
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-10", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertEqual(10, len(baseline["capabilities"]))
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertGreaterEqual(int(str(current["phase_id"]).split("-")[1]), 10)
        self.assertIn(current["status"], {"active", "completed"})
        self.assertIn(
            "docs/progress/PHASE-10-COMPLETION.md",
            current["progress_refs"],
        )

    def test_phase_ten_guarantees_preserve_source_boundaries(self) -> None:
        guarantees = load_json(
            REPO_ROOT / ".ai" / "phase-10-baseline.json"
        )["guarantees"]
        self.assertFalse(guarantees["external_source_copied"])
        self.assertFalse(guarantees["external_source_mutated"])
        self.assertFalse(guarantees["source_content_persisted"])
        self.assertFalse(guarantees["physical_source_root_persisted"])
        self.assertFalse(guarantees["remote_provider_implicit"])
        self.assertTrue(guarantees["incremental_refresh"])
        self.assertTrue(guarantees["stale_index_fails_closed"])
        self.assertTrue(guarantees["derived_index_integrity_verified"])

    def test_doctor_recognizes_phase_ten(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-ten-baseline", checks)
        self.assertTrue(checks["phase-ten-baseline"].passed)


if __name__ == "__main__":
    unittest.main()
