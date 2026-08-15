from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.foundation import validate_orchestration_boundary  # noqa: E402
from progress_evidence import assert_progress_evidence  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseFiveKickoffTests(unittest.TestCase):
    def test_phase_five_artifacts_preserve_kickoff_and_completed_plan(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        assert_progress_evidence(self, "docs/progress/PHASE-5-KICKOFF.md")
        assert_progress_evidence(self, "docs/progress/PHASE-5-COMPLETION.md")
        phase_five = load_json(REPO_ROOT / ".ai" / "phase-5-baseline.json")
        self.assertEqual("phase-5", phase_five["phase_id"])
        self.assertEqual("ready", phase_five["status"])
        phase_four = load_json(REPO_ROOT / ".ai" / "phase-4-baseline.json")
        self.assertEqual("ready", phase_four["status"])

    def test_orchestration_boundary_separates_roles_and_authority(self) -> None:
        boundary = load_json(REPO_ROOT / "config" / "orchestration-boundary.json")
        self.assertEqual([], validate_orchestration_boundary(boundary))
        roles = {item["id"]: item for item in boundary["roles"]}
        self.assertFalse(roles["planner"]["may_mutate"])
        self.assertTrue(roles["worker"]["may_mutate"])
        self.assertFalse(roles["verifier"]["may_mutate"])
        self.assertTrue(all(not item["may_approve"] for item in roles.values()))
        self.assertFalse(boundary["invariants"]["plan_grants_execution"])
        self.assertTrue(boundary["invariants"]["verification_required"])
        self.assertTrue(
            boundary["invariants"]["critical_change_requires_user_approval"]
        )

    def test_orchestration_validator_rejects_role_and_approval_bypasses(self) -> None:
        boundary = load_json(REPO_ROOT / "config" / "orchestration-boundary.json")
        changed = copy.deepcopy(boundary)
        roles = {item["id"]: item for item in changed["roles"]}
        roles["planner"]["may_mutate"] = True
        roles["worker"]["may_approve"] = True
        changed["approval_triggers"].remove("policy-change")
        changed["invariants"]["plan_grants_execution"] = True
        errors = validate_orchestration_boundary(changed)
        self.assertTrue(any("planner must not mutate" in item for item in errors))
        self.assertTrue(any("self-approve" in item for item in errors))
        self.assertTrue(any("approval triggers" in item for item in errors))
        self.assertTrue(any("safety invariants" in item for item in errors))

    def test_phase_five_boundary_preserves_prior_safety_gates(self) -> None:
        boundary = (
            REPO_ROOT
            / "docs"
            / "specifications"
            / "PHASE-5-ORCHESTRATION-BOUNDARY.md"
        ).read_text(encoding="utf-8")
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-006-ORCHESTRATOR-DOGAL-DIL-GOREV-AKISI.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Planning never grants execution", boundary)
        self.assertIn("Chat history is not orchestration state", boundary)
        self.assertIn("yalnız `SELECT`", plan)
        self.assertIn("Verification geçmeden", plan)

    def test_repository_context_exposes_phase_five_contracts(self) -> None:
        context = load_json(REPO_ROOT / ".ai" / "repository-context.json")
        canonical = context["canonical"]
        self.assertEqual(
            "docs/specifications/PHASE-5-ORCHESTRATION-BOUNDARY.md",
            canonical["phase_five_boundary"],
        )
        self.assertEqual(
            "config/orchestration-boundary.json",
            canonical["orchestration_boundary"],
        )
        self.assertEqual(
            "schemas/orchestration-boundary.schema.json",
            canonical["orchestration_boundary_schema"],
        )


if __name__ == "__main__":
    unittest.main()
