from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.capability_registry import (  # noqa: E402
    CapabilitySelection,
    capability_record_digest,
    load_capability_registry,
    parse_capability_record,
    select_capability_records,
)
from krcn_core.mutation_gate import (  # noqa: E402
    DryRunEvidence,
    OwnershipResolver,
    plan_mutation,
)
from krcn_core.orchestration_authorization import (  # noqa: E402
    TaskApproval,
    TaskAuthorizationError,
    TaskMutationRequest,
    TaskProviderRequest,
    authorize_task_plan,
    create_operation_request,
)
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import create_task_plan  # noqa: E402
from krcn_core.policies import parse_user_policy  # noqa: E402
from krcn_core.provider_gate import create_provider_request  # noqa: E402
from test_database_policy import select_only_policy  # noqa: E402
from test_orchestration_intent import extraction  # noqa: E402
from test_orchestration_plan import read_only_steps  # noqa: E402
from test_policy_engine import policy_payload  # noqa: E402


def remote_record():
    payload = {
        "record_id": "synthetic-remote-tool",
        "kind": "tool",
        "role": None,
        "revision": 1,
        "capabilities": ["provider.query"],
        "side_effects": ["network", "read"],
        "read_ownership": ["user-data"],
        "write_ownership": [],
        "provider_mode": "remote",
        "approval_triggers": ["remote-provider-use"],
        "status": "active",
    }
    payload["record_digest"] = capability_record_digest(payload)
    return parse_capability_record(payload)


class OrchestrationAuthorizationTests(unittest.TestCase):
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

    def operation(self, operation="select", *, resource_type="database"):
        return create_operation_request(
            step_id="inspect-policy",
            resource_type=resource_type,
            operation=operation,
            scope_refs={"integration": "reporting-database"}
            if resource_type == "database"
            else {},
            require_policy_match=resource_type == "database",
        )

    def write_fixture(self):
        steps = read_only_steps()
        worker = steps[0]
        worker["required_capabilities"].append("record.write")
        worker["capability_record_refs"].append("local-store-writer-tool")
        worker["side_effects"].append("write")
        worker["approval_triggers"] = ["user-data-mutation"]
        worker["rollback_strategy"] = "restore-checkpoint"
        plan = create_task_plan(self.intent, self.selection, steps)
        mutation = plan_mutation(
            OwnershipResolver.from_repository(REPO_ROOT),
            operation="create",
            target_ref=".krcn/memory/synthetic-record.json",
            expected_ownership="user-data",
            change_digest="a" * 64,
            reversible=True,
        )
        binding = TaskMutationRequest(
            "inspect-policy",
            mutation,
            DryRunEvidence(mutation.plan_id, True),
        )
        approval = TaskApproval(
            plan.plan_id,
            plan.task_id,
            "synthetic-session",
            "synthetic-user-approval",
            True,
            plan.approval_triggers,
            (mutation.plan_id,),
            (),
        )
        return plan, binding, approval

    def test_select_only_policy_authorizes_read_without_user_approval(self) -> None:
        plan = create_task_plan(self.intent, self.selection, read_only_steps())
        result = authorize_task_plan(
            REPO_ROOT,
            intent=self.intent,
            selection=self.selection,
            plan=plan,
            session_id="synthetic-session",
            policies=[select_only_policy()],
            operations=[self.operation()],
        )
        self.assertTrue(result.as_dict()["authorized"])
        self.assertIsNone(result.approval_id)
        self.assertEqual("allow", result.steps[0].operations[0].policy_effect)

    def test_policy_deny_cannot_be_overridden_by_allow_or_task_approval(self) -> None:
        restrictive = parse_user_policy(policy_payload())
        permissive_payload = policy_payload("lower-priority-allow")
        permissive_payload["rules"] = [
            {
                "rule_id": "allow-delete",
                "resource_type": "database",
                "operations": ["delete"],
                "effect": "allow",
                "provenance": {"kind": "approved-import"},
                "active": True,
            }
        ]
        plan, mutation, approval = self.write_fixture()
        with self.assertRaisesRegex(TaskAuthorizationError, "policy denies"):
            authorize_task_plan(
                REPO_ROOT,
                intent=self.intent,
                selection=self.selection,
                plan=plan,
                session_id="synthetic-session",
                policies=[restrictive, parse_user_policy(permissive_payload)],
                operations=[self.operation("delete")],
                mutations=[mutation],
                approval=approval,
            )

    def test_write_requires_exact_task_and_mutation_approval(self) -> None:
        plan, mutation, approval = self.write_fixture()
        operation = self.operation("create", resource_type="local-record")
        result = authorize_task_plan(
            REPO_ROOT,
            intent=self.intent,
            selection=self.selection,
            plan=plan,
            session_id="synthetic-session",
            operations=[operation],
            mutations=[mutation],
            approval=approval,
        )
        self.assertEqual("synthetic-user-approval", result.approval_id)
        self.assertEqual((mutation.mutation.plan_id,), result.steps[0].mutation_plan_ids)

        wrong_plan = TaskApproval(
            "f" * 64,
            approval.task_id,
            approval.session_id,
            approval.approval_id,
            True,
            approval.approved_triggers,
            approval.mutation_plan_ids,
            approval.provider_request_ids,
        )
        with self.assertRaisesRegex(TaskAuthorizationError, "exact-plan"):
            authorize_task_plan(
                REPO_ROOT,
                intent=self.intent,
                selection=self.selection,
                plan=plan,
                session_id="synthetic-session",
                operations=[operation],
                mutations=[mutation],
                approval=wrong_plan,
            )

    def test_remote_provider_requires_exact_disclosure_request_and_session(self) -> None:
        selected = tuple(sorted((*self.selection.selected, remote_record()), key=lambda item: (item.kind, item.record_id)))
        selection = CapabilitySelection(
            selected,
            tuple(sorted((*self.selection.required_capabilities, "provider.query"))),
            tuple(sorted({item for record in selected for item in record.approval_triggers})),
            self.selection.registry_digest,
        )
        steps = read_only_steps()
        worker = steps[0]
        worker["required_capabilities"].append("provider.query")
        worker["capability_record_refs"].append("synthetic-remote-tool")
        worker["side_effects"].append("network")
        worker["provider_mode"] = "remote"
        worker["approval_triggers"] = ["remote-provider-use"]
        plan = create_task_plan(self.intent, selection, steps)
        provider = create_provider_request(
            provider="approved-remote",
            endpoint="https://synthetic.invalid",
            data_categories=("synthetic-metadata",),
            operation_scope="task-read",
            retention_assumptions="Synthetic test payload is not retained",
            session_id="synthetic-session",
            remote=True,
        )
        approval = TaskApproval(
            plan.plan_id,
            plan.task_id,
            "synthetic-session",
            "synthetic-provider-approval",
            True,
            plan.approval_triggers,
            (),
            (provider.request_id,),
        )
        result = authorize_task_plan(
            REPO_ROOT,
            intent=self.intent,
            selection=selection,
            plan=plan,
            session_id="synthetic-session",
            operations=[self.operation("read", resource_type="local-record")],
            providers=[TaskProviderRequest("inspect-policy", provider)],
            approval=approval,
        )
        self.assertEqual((provider.request_id,), result.steps[0].provider_request_ids)

        wrong_session = TaskApproval(
            approval.plan_id,
            approval.task_id,
            "another-session",
            approval.approval_id,
            True,
            approval.approved_triggers,
            approval.mutation_plan_ids,
            approval.provider_request_ids,
        )
        with self.assertRaisesRegex(TaskAuthorizationError, "exact-plan"):
            authorize_task_plan(
                REPO_ROOT,
                intent=self.intent,
                selection=selection,
                plan=plan,
                session_id="synthetic-session",
                operations=[self.operation("read", resource_type="local-record")],
                providers=[TaskProviderRequest("inspect-policy", provider)],
                approval=wrong_session,
            )

    def test_all_workers_need_operations_and_schema_is_versioned(self) -> None:
        plan = create_task_plan(self.intent, self.selection, read_only_steps())
        with self.assertRaisesRegex(TaskAuthorizationError, "every worker"):
            authorize_task_plan(
                REPO_ROOT,
                intent=self.intent,
                selection=self.selection,
                plan=plan,
                session_id="synthetic-session",
                operations=[],
            )
        schema = json.loads(
            (REPO_ROOT / "schemas" / "task-authorization.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("urn:krcn:schemas:task-authorization:1", schema["$id"])


if __name__ == "__main__":
    unittest.main()
