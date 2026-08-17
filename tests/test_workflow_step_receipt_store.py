from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.workflow_step_receipt import build_workflow_step_receipt  # noqa: E402
from krcn_core.workflow_step_receipt_store import (  # noqa: E402
    WorkflowStepReceiptStoreError,
    apply_workflow_step_receipt_record,
    parse_workflow_step_receipt_record,
    prepare_workflow_step_receipt_record,
)


def sha(character: str) -> str:
    return character * 64


def make_receipt(**overrides):
    values = {
        "correlation_id": "correlation-one",
        "project_id": "project-one",
        "work_item_id": "work-one",
        "task_id": "task-one",
        "task_plan_id": sha("a"),
        "step_id": "inspect-source",
        "attempt_id": "attempt-one",
        "sequence": 1,
        "attempt_number": 1,
        "actor_kind": "agent",
        "role": "worker",
        "status": "completed",
        "input_digest": sha("b"),
        "context_snapshot_digest": sha("c"),
        "route_decision_id": sha("d"),
        "started_at": "2026-08-17T12:00:00.000Z",
        "finished_at": "2026-08-17T12:00:00.005Z",
        "harness_revision": sha("e"),
        "policy_revision": sha("f"),
        "execution_identity_id": sha("0"),
        "model_assignment_id": "assignment-one",
        "client_id": "codex-cli",
        "output_digest": sha("2"),
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_microunits": 0,
        "currency": None,
    }
    values.update(overrides)
    return build_workflow_step_receipt(**values)


class WorkflowStepReceiptStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.home = root / ".krcn"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.store = LocalWorkspaceStore(
            self.home, OwnershipResolver.from_repository(REPO_ROOT)
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def authorize(self, plan):
        mutation = plan.write_plan.mutation
        return authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(plan_id=mutation.plan_id, verified=True),
        )

    def test_prepare_apply_and_idempotent_replay(self) -> None:
        plan = prepare_workflow_step_receipt_record(self.store, make_receipt())
        self.assertFalse(plan.no_op)
        self.assertEqual("runtime", plan.effect_plans[0].ownership)
        self.assertFalse(plan.effect_plans[0].approval_required)
        result = apply_workflow_step_receipt_record(
            self.store,
            plan,
            {plan.write_plan.mutation.plan_id: self.authorize(plan)},
            expected_plan_id=plan.plan_id,
        )
        self.assertEqual("recorded", result["status"])
        self.assertEqual(
            result["record"], parse_workflow_step_receipt_record(result["record"])
        )
        replay = prepare_workflow_step_receipt_record(self.store, make_receipt())
        self.assertTrue(replay.no_op)
        current = apply_workflow_step_receipt_record(
            self.store, replay, {}, expected_plan_id=replay.plan_id
        )
        self.assertEqual("current", current["status"])
        self.assertEqual(1, len(self.store.list_records("workflow-step-receipts")))

    def test_same_step_attempt_conflicting_receipt_is_rejected(self) -> None:
        first = prepare_workflow_step_receipt_record(self.store, make_receipt())
        apply_workflow_step_receipt_record(
            self.store,
            first,
            {first.write_plan.mutation.plan_id: self.authorize(first)},
            expected_plan_id=first.plan_id,
        )
        with self.assertRaisesRegex(WorkflowStepReceiptStoreError, "conflicting"):
            prepare_workflow_step_receipt_record(
                self.store, make_receipt(output_digest=sha("3"))
            )

    def test_stale_parallel_plan_cannot_overwrite_slot(self) -> None:
        first = prepare_workflow_step_receipt_record(self.store, make_receipt())
        second = prepare_workflow_step_receipt_record(
            self.store, make_receipt(output_digest=sha("3"))
        )
        apply_workflow_step_receipt_record(
            self.store,
            first,
            {first.write_plan.mutation.plan_id: self.authorize(first)},
            expected_plan_id=first.plan_id,
        )
        with self.assertRaisesRegex(ValueError, "revision changed"):
            apply_workflow_step_receipt_record(
                self.store,
                second,
                {second.write_plan.mutation.plan_id: self.authorize(second)},
                expected_plan_id=second.plan_id,
            )

    def test_exact_plan_authorization_and_append_only_guard(self) -> None:
        plan = prepare_workflow_step_receipt_record(self.store, make_receipt())
        with self.assertRaisesRegex(WorkflowStepReceiptStoreError, "exact plan"):
            apply_workflow_step_receipt_record(
                self.store, plan, {}, expected_plan_id=sha("9")
            )
        with self.assertRaisesRegex(WorkflowStepReceiptStoreError, "authorization"):
            apply_workflow_step_receipt_record(
                self.store, plan, {}, expected_plan_id=plan.plan_id
            )
        apply_workflow_step_receipt_record(
            self.store,
            plan,
            {plan.write_plan.mutation.plan_id: self.authorize(plan)},
            expected_plan_id=plan.plan_id,
        )
        with self.assertRaisesRegex(ValueError, "append-only"):
            self.store.prepare_put(
                "workflow-step-receipts",
                plan.record["workflow_step_receipt_record_id"],
                plan.record,
                expected_revision=1,
                project_id="project-one",
            )

    def test_record_and_plan_validate_against_schemas(self) -> None:
        plan = prepare_workflow_step_receipt_record(self.store, make_receipt())
        receipt_schema = json.loads(
            (REPO_ROOT / "schemas/workflow-step-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        mutation_schema = json.loads(
            (REPO_ROOT / "schemas/mutation-plan.schema.json").read_text(encoding="utf-8")
        )
        registry = Registry().with_resources(
            [
                (receipt_schema["$id"], Resource.from_contents(receipt_schema)),
                (mutation_schema["$id"], Resource.from_contents(mutation_schema)),
            ]
        )
        for name, payload in (
            ("workflow-step-receipt-record.schema.json", plan.record),
            ("workflow-step-receipt-record-plan.schema.json", plan.public_summary()),
        ):
            schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(
                [], list(Draft202012Validator(schema, registry=registry).iter_errors(payload))
            )


if __name__ == "__main__":
    unittest.main()
