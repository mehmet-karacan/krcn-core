from __future__ import annotations

import json
import unittest
from pathlib import Path

from progress_evidence import assert_progress_evidence


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseSixKickoffTests(unittest.TestCase):
    def test_phase_six_preserves_kickoff_and_portability_plan(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        assert_progress_evidence(self, "docs/progress/PHASE-6-KICKOFF.md")
        phase_six = load_json(REPO_ROOT / ".ai" / "phase-6-baseline.json")
        self.assertEqual("phase-6", phase_six["phase_id"])
        self.assertEqual("ready", phase_six["status"])

    def test_portability_boundary_forbids_copying_external_projects(self) -> None:
        boundary = (
            REPO_ROOT
            / "docs"
            / "specifications"
            / "PHASE-6-PORTABILITY-BOUNDARY.md"
        ).read_text(encoding="utf-8")
        self.assertIn("never searches for, copies, moves, uploads, or rewrites", boundary)
        self.assertIn("External project directories remain", boundary)
        self.assertIn("exact-plan approval", boundary)

    def test_repository_context_exposes_phase_six_boundary(self) -> None:
        context = load_json(REPO_ROOT / ".ai" / "repository-context.json")
        self.assertEqual(
            "docs/specifications/PHASE-6-PORTABILITY-BOUNDARY.md",
            context["canonical"]["phase_six_boundary"],
        )

    def test_turkish_plan_records_recovery_limit(self) -> None:
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-007-RELEASE-KALITE-TASINABILIRLIK.md"
        ).read_text(encoding="utf-8")
        self.assertIn("proje dosyaları hiçbir zaman", plan)
        self.assertIn("yeni makinede ayrıca bulunmalıdır", plan)
        self.assertIn("kullanıcı policy'lerini zayıflatmaz", plan)


if __name__ == "__main__":
    unittest.main()
