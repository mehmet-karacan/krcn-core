from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseEightKickoffTests(unittest.TestCase):
    def test_phase_eight_started_with_explicit_user_approval(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertIn(current["status"], {"active", "completed"})
        self.assertIn("docs/progress/PHASE-8-KICKOFF.md", current["progress_refs"])
        kickoff = (
            REPO_ROOT / "docs" / "progress" / "PHASE-8-KICKOFF.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Mehmet KARACAN'ın açık isteğiyle", kickoff)
        self.assertIn("2ab1cb1", kickoff)
        baseline = load_json(REPO_ROOT / ".ai" / "phase-8-baseline.json")
        self.assertEqual("phase-8", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])

    def test_project_local_home_boundary_requires_choice_and_git_safety(self) -> None:
        boundary = (
            REPO_ROOT / "docs" / "specifications" / "PROJECT-LOCAL-HOME.md"
        ).read_text(encoding="utf-8")
        self.assertIn("<project-root>/.krcn", boundary)
        self.assertIn("accept the default, choose another parent directory, or cancel", boundary)
        self.assertIn("must not be tracked, staged, committed, pushed", boundary)
        self.assertIn("Git ignore is not backup", boundary)
        self.assertIn("never copies project files", boundary)

    def test_architectural_decision_is_accepted(self) -> None:
        decision = (
            REPO_ROOT / "docs" / "adr" / "ADR-006-PROJE-BAZLI-KRCN-HOME.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Kabul edildi", decision)
        self.assertIn("<proje-kökü>/.krcn", decision)
        self.assertIn("Git clone işlemi", decision)


if __name__ == "__main__":
    unittest.main()
