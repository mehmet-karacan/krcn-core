from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PhaseTwoKickoffTests(unittest.TestCase):
    def test_phase_two_baseline_preserves_completed_phase_identity(self) -> None:
        baseline = json.loads(
            (REPO_ROOT / ".ai" / "phase-2-baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("phase-2", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        kickoff = (
            REPO_ROOT / "docs" / "progress" / "PHASE-2-KICKOFF.md"
        ).read_text(encoding="utf-8")
        self.assertIn("`4a6981d`", kickoff)

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
