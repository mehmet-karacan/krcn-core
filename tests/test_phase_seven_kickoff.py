from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseSevenKickoffTests(unittest.TestCase):
    def test_phase_seven_was_started_with_explicit_user_approval(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertIn("docs/progress/PHASE-7-KICKOFF.md", current["progress_refs"])
        baseline = load_json(REPO_ROOT / ".ai" / "phase-7-baseline.json")
        self.assertEqual("phase-7", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])

    def test_learning_boundary_requires_one_exact_plan_and_no_copy(self) -> None:
        boundary = (
            REPO_ROOT
            / "docs"
            / "specifications"
            / "PROJECT-LEARNING-BOUNDARY.md"
        ).read_text(encoding="utf-8")
        self.assertIn("directory as the only required project-specific input", boundary)
        self.assertIn("does not bypass the mutation gate", boundary)
        self.assertIn("not copied, moved, uploaded, rewritten, or marked", boundary)


if __name__ == "__main__":
    unittest.main()
