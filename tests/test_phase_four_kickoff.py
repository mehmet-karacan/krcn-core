from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.foundation import validate_information_classes  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseFourKickoffTests(unittest.TestCase):
    def test_phase_four_kickoff_and_baseline_remain_versioned(self) -> None:
        kickoff = (
            REPO_ROOT / "docs" / "progress" / "PHASE-4-KICKOFF.md"
        ).read_text(encoding="utf-8")
        baseline = load_json(REPO_ROOT / ".ai" / "phase-4-baseline.json")
        self.assertIn("`6005611`", kickoff)
        self.assertEqual("phase-4", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])

    def test_information_class_registry_is_complete_and_safe(self) -> None:
        registry = load_json(REPO_ROOT / "config" / "information-classes.json")
        self.assertEqual([], validate_information_classes(registry))
        classes = {item["id"]: item for item in registry["classes"]}
        self.assertEqual(
            {
                "authoritative-source",
                "knowledge",
                "memory",
                "state",
                "history",
                "derived",
            },
            set(classes),
        )
        self.assertTrue(classes["authoritative-source"]["source_of_truth"])
        self.assertTrue(classes["memory"]["requires_approval_to_persist"])
        self.assertTrue(classes["derived"]["rebuildable"])
        self.assertNotIn(
            "secrets",
            {
                ownership
                for item in classes.values()
                for ownership in item["allowed_record_ownerships"]
            },
        )

    def test_information_class_validator_rejects_unsafe_semantics(self) -> None:
        registry = load_json(REPO_ROOT / "config" / "information-classes.json")
        changed = copy.deepcopy(registry)
        memory = next(item for item in changed["classes"] if item["id"] == "memory")
        memory["requires_approval_to_persist"] = False
        memory["allowed_record_ownerships"].append("secrets")
        errors = validate_information_classes(changed)
        self.assertTrue(any("durable memory" in item for item in errors))
        self.assertTrue(any("secret ownership" in item for item in errors))

    def test_phase_four_boundary_preserves_authority_and_policy(self) -> None:
        boundary = (
            REPO_ROOT
            / "docs"
            / "specifications"
            / "PHASE-4-CONTEXT-KNOWLEDGE-MEMORY-BOUNDARY.md"
        ).read_text(encoding="utf-8")
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-005-CONTEXT-KNOWLEDGE-MEMORY.md"
        ).read_text(encoding="utf-8")
        self.assertIn("A current authoritative source outranks", boundary)
        self.assertIn("Memory Gate", boundary)
        self.assertIn("database üzerinde yalnız `SELECT` izni", plan)
        self.assertIn("conversation summary", plan)

    def test_repository_context_exposes_phase_four_contracts(self) -> None:
        context = load_json(REPO_ROOT / ".ai" / "repository-context.json")
        canonical = context["canonical"]
        self.assertEqual(
            "docs/specifications/PHASE-4-CONTEXT-KNOWLEDGE-MEMORY-BOUNDARY.md",
            canonical["phase_four_boundary"],
        )
        self.assertEqual(
            "config/information-classes.json",
            canonical["information_classes"],
        )


if __name__ == "__main__":
    unittest.main()
