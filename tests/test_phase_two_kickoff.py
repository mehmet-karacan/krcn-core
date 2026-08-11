from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PhaseTwoKickoffTests(unittest.TestCase):
    def test_current_work_points_to_active_phase_two_plan(self) -> None:
        current = json.loads(
            (REPO_ROOT / ".ai" / "current-work.json").read_text(encoding="utf-8")
        )
        self.assertEqual("phase-2", current["phase_id"])
        self.assertEqual("active", current["status"])
        self.assertEqual(
            "docs/plans/PLAN-003-YEREL-CALISMA-ALANI-VE-ENTEGRASYON.md",
            current["plan_ref"],
        )
        self.assertEqual("4a6981d", current["baseline_commit"])
        self.assertIn("docs/progress/PHASE-2-KICKOFF.md", current["progress_refs"])

    def test_phase_two_plan_keeps_live_data_behind_approval(self) -> None:
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-003-YEREL-CALISMA-ALANI-VE-ENTEGRASYON.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Canlı kullanıcı verisinin kaydedilmesi", plan)
        self.assertIn("ayrı dry-run ve açık kullanıcı onayı", plan)
        self.assertIn("kaynak dizinine dosya yazmaz", plan)


if __name__ == "__main__":
    unittest.main()
