from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.capability_registry import (  # noqa: E402
    load_capability_registry,
    select_capability_records,
)
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import TaskPlanError, create_task_plan  # noqa: E402
from test_orchestration_intent import extraction  # noqa: E402


def read_only_steps():
    return [
        {
            "step_id": "inspect-policy",
            "title": "Inspect the effective database policy",
            "role": "worker",
            "depends_on": [],
            "required_capabilities": ["plan.execute", "record.read"],
            "capability_record_refs": ["worker-agent", "local-store-reader-tool"],
            "side_effects": ["execute", "read"],
            "ownership_impacts": ["user-data"],
            "provider_mode": "none",
            "approval_triggers": [],
            "acceptance_criteria": [],
            "verification_requirements": [],
            "reversible": True,
            "rollback_strategy": "not-required",
        },
        {
            "step_id": "verify-policy",
            "title": "Verify that DELETE remains denied",
            "role": "verifier",
            "depends_on": ["inspect-policy"],
            "required_capabilities": ["evidence.verify"],
            "capability_record_refs": ["verifier-agent"],
            "side_effects": ["execute", "read"],
            "ownership_impacts": ["user-data"],
            "provider_mode": "none",
            "approval_triggers": [],
            "acceptance_criteria": ["DELETE işlemi reddedilir"],
            "verification_requirements": ["Policy kararı deny olmalıdır"],
            "reversible": True,
            "rollback_strategy": "not-required",
        },
    ]


class OrchestrationPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = create_task_intent(
            "Veritabanında delete istemiyorum, sadece select kullan.",
            extraction(),
        )
        registry = load_capability_registry(REPO_ROOT)
        self.selection = select_capability_records(
            registry,
            [
                "worker-agent",
                "verifier-agent",
                "local-store-reader-tool",
                "local-store-writer-tool",
            ],
            ["plan.execute", "record.read", "record.write", "evidence.verify"],
        )

    def test_plan_is_deterministic_and_topologically_ordered(self) -> None:
        first = create_task_plan(self.intent, self.selection, read_only_steps())
        second = create_task_plan(
            self.intent,
            self.selection,
            reversed(read_only_steps()),
        )
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(
            ["inspect-policy", "verify-policy"],
            [step.step_id for step in first.steps],
        )
        self.assertFalse(first.requires_approval)
        self.assertFalse(first.as_dict()["grants_execution"])

    def test_user_data_write_declares_approval_and_rollback(self) -> None:
        steps = read_only_steps()
        worker = steps[0]
        worker["required_capabilities"].append("record.write")
        worker["capability_record_refs"].append("local-store-writer-tool")
        worker["side_effects"].append("write")
        worker["approval_triggers"] = ["user-data-mutation"]
        worker["rollback_strategy"] = "restore-checkpoint"
        plan = create_task_plan(self.intent, self.selection, steps)
        self.assertTrue(plan.requires_approval)
        self.assertEqual(("user-data-mutation",), plan.approval_triggers)

    def test_clarification_blocks_plan_creation(self) -> None:
        blocked = create_task_intent(
            "Projeyi güncelle.",
            extraction(
                ambiguities=[
                    {
                        "ambiguity_id": "target-project",
                        "question": "Hangi proje?",
                        "impact_categories": ["scope"],
                        "blocking": True,
                    }
                ]
            ),
        )
        with self.assertRaisesRegex(TaskPlanError, "requires clarification"):
            create_task_plan(blocked, self.selection, read_only_steps())

    def test_cycle_unselected_capability_and_side_effect_escalation_are_rejected(self) -> None:
        cycle = read_only_steps()
        cycle[0]["depends_on"] = ["verify-policy"]
        with self.assertRaisesRegex(TaskPlanError, "cycle"):
            create_task_plan(self.intent, self.selection, cycle)

        unselected = read_only_steps()
        unselected[0]["capability_record_refs"] = ["host-tool", "worker-agent"]
        with self.assertRaisesRegex(TaskPlanError, "unselected"):
            create_task_plan(self.intent, self.selection, unselected)

        escalated = read_only_steps()
        escalated[1]["side_effects"].append("write")
        with self.assertRaisesRegex(TaskPlanError, "only worker"):
            create_task_plan(self.intent, self.selection, escalated)

    def test_every_worker_and_acceptance_criterion_requires_verifier_coverage(self) -> None:
        missing_dependency = read_only_steps()
        missing_dependency[1]["depends_on"] = []
        with self.assertRaisesRegex(TaskPlanError, "covered by verification"):
            create_task_plan(self.intent, self.selection, missing_dependency)

        missing_acceptance = read_only_steps()
        missing_acceptance[1]["acceptance_criteria"] = []
        with self.assertRaisesRegex(TaskPlanError, "acceptance criteria"):
            create_task_plan(self.intent, self.selection, missing_acceptance)

    def test_task_plan_schema_is_versioned(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "task-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("urn:krcn:schemas:task-plan:1", schema["$id"])


if __name__ == "__main__":
    unittest.main()
