from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseThreeKickoffTests(unittest.TestCase):
    def test_phase_three_baseline_preserves_plan_identity(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-3-baseline.json")
        self.assertEqual("phase-3", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        kickoff = (
            REPO_ROOT / "docs" / "progress" / "PHASE-3-KICKOFF.md"
        ).read_text(encoding="utf-8")
        self.assertIn("`cce08b7`", kickoff)
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-004-GUVENLI-MERGE-INTO-MOTORU.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Tamamlandı", plan)

    def test_release_and_installation_schemas_are_versioned(self) -> None:
        release = load_json(REPO_ROOT / "schemas" / "release-manifest.schema.json")
        installation = load_json(
            REPO_ROOT / "schemas" / "installation-state.schema.json"
        )
        self.assertEqual("urn:krcn:schemas:release-manifest:1", release["$id"])
        self.assertEqual("urn:krcn:schemas:installation-state:1", installation["$id"])

    def test_phase_three_plan_preserves_local_data(self) -> None:
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-004-GUVENLI-MERGE-INTO-MOTORU.md"
        ).read_text(encoding="utf-8")
        self.assertIn("User-data, secrets, runtime ve unmanaged", plan)
        self.assertIn("otomatik rollback", plan)
        self.assertIn("güvenilen manifest digest'i", plan)


if __name__ == "__main__":
    unittest.main()
