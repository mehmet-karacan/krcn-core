from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.agent_execution_identity import (  # noqa: E402
    create_agent_execution_identity,
)
from krcn_core.agent_runtime import AgentRuntimeQueue, load_scheduler_policy  # noqa: E402
from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.capability_registry import (  # noqa: E402
    load_capability_registry,
    select_capability_records,
)
from krcn_core.client_capabilities import (  # noqa: E402
    create_client_capability_profile,
    load_client_capability_policy,
)
from krcn_core.continuity import (  # noqa: E402
    build_continuity_snapshot,
    finalize_handoff,
)
from krcn_core.delegation_policy import (  # noqa: E402
    decide_delegation,
    load_delegation_policy,
)
from krcn_core.execution_coordinator import (  # noqa: E402
    ExecutionCoordinatorAdapters,
    ExecutionCoordinatorError,
    execute_execution_coordination,
    parse_execution_coordination_result,
    finalize_execution_coordination,
    parse_execution_coordination_plan,
    prepare_execution_coordination,
)
from krcn_core.generic_dag_executor import (  # noqa: E402
    DagAdapterSpec,
    DagStepAssignment,
    create_generic_dag_step_result,
    dispatch_generic_dag_execution,
    prepare_generic_dag_execution,
)
from krcn_core.mutation_gate import (  # noqa: E402
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.orchestration_authorization import (  # noqa: E402
    authorize_task_plan,
    create_operation_request,
)
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import create_task_plan  # noqa: E402
from test_database_policy import select_only_policy  # noqa: E402
from test_orchestration_intent import extraction  # noqa: E402


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def task_steps() -> list[dict[str, object]]:
    worker = {
        "title": "Inspect one reviewed input",
        "role": "worker",
        "depends_on": [],
        "required_capabilities": ["plan.execute", "record.read"],
        "capability_record_refs": ["worker-agent", "local-store-reader-tool"],
        "side_effects": ["read"],
        "ownership_impacts": ["user-data"],
        "provider_mode": "none",
        "approval_triggers": [],
        "acceptance_criteria": [],
        "verification_requirements": [],
        "reversible": True,
        "rollback_strategy": "not-required",
    }
    return [
        {**worker, "step_id": "inspect-left"},
        {**worker, "step_id": "inspect-right"},
        {
            **worker,
            "step_id": "merge-findings",
            "depends_on": ["inspect-left", "inspect-right"],
        },
        {
            "step_id": "verify-result",
            "title": "Verify the merged result",
            "role": "verifier",
            "depends_on": ["merge-findings"],
            "required_capabilities": ["evidence.verify"],
            "capability_record_refs": ["verifier-agent"],
            "side_effects": ["read"],
            "ownership_impacts": ["user-data"],
            "provider_mode": "none",
            "approval_triggers": [],
            "acceptance_criteria": ["DELETE işlemi reddedilir"],
            "verification_requirements": ["Policy kararı deny olmalıdır"],
            "reversible": True,
            "rollback_strategy": "not-required",
        },
    ]


class ExecutionCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name) / "home"
        self.data_root.mkdir()
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.queue = AgentRuntimeQueue(
            self.data_root,
            "sample",
            load_scheduler_policy(REPO_ROOT),
        )
        self.request_text = "Keep database access read-only."
        self.intent = create_task_intent(self.request_text, extraction())
        registry = load_capability_registry(REPO_ROOT)
        selection = select_capability_records(
            registry,
            ["worker-agent", "verifier-agent", "local-store-reader-tool"],
            ["plan.execute", "record.read", "evidence.verify"],
        )
        self.task_plan = create_task_plan(self.intent, selection, task_steps())
        worker_ids = [
            step.step_id for step in self.task_plan.steps if step.role == "worker"
        ]
        self.task_authorization = authorize_task_plan(
            REPO_ROOT,
            intent=self.intent,
            selection=selection,
            plan=self.task_plan,
            session_id="coordinator-session",
            policies=[select_only_policy()],
            operations=[
                create_operation_request(
                    step_id=step_id,
                    resource_type="database",
                    operation="select",
                    scope_refs={"integration": "reporting-database"},
                    require_policy_match=True,
                )
                for step_id in worker_ids
            ],
        )
        self.owner_tokens = {
            step.step_id: f"coordinator-owner-{index:02d}-{step.step_id}"
            for index, step in enumerate(self.task_plan.steps, start=1)
        }
        self.assignments = {}
        for step in self.task_plan.steps:
            identity = create_agent_execution_identity(
                task_id=self.task_plan.task_id,
                plan_id=self.task_plan.plan_id,
                step_id=step.step_id,
                role=step.role,
                actor_digest=digest("actor-" + step.step_id),
                session_digest=digest(self.owner_tokens[step.step_id]),
                assignment_digest=digest("assignment-" + step.step_id),
                runtime_kind="local-handler",
            )
            self.assignments[step.step_id] = DagStepAssignment(
                step.step_id,
                "handler-" + step.step_id,
                identity,
                (f"task:sample:{step.step_id}",),
            )
        self.dag_plan = prepare_generic_dag_execution(
            self.queue,
            self.ownership,
            project_id="sample",
            work_item_id="task-one",
            work_item_revision=1,
            work_item_digest="a" * 64,
            task_plan=self.task_plan,
            task_authorization=self.task_authorization,
            assignments=self.assignments,
            max_concurrency=2,
        )
        self.dag_authorization = authorize_mutation(
            self.dag_plan.mutation,
            dry_run=DryRunEvidence(
                self.dag_plan.mutation.plan_id,
                verified=True,
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def delegation(self, *, available: bool = True, work_class: str = "project-analysis"):
        capabilities = {
            "native_subagents": available,
            "parallel_subagents": available,
            "per_agent_model_selection": available,
            "agent_cancellation": available,
            "structured_results": False,
            "isolated_role_execution": False,
        }
        profile = create_client_capability_profile(
            load_client_capability_policy(REPO_ROOT),
            session_id="coordinator-session",
            client_id="codex",
            capabilities=capabilities,
            max_parallel_agents=2 if available else 1,
        )
        return decide_delegation(
            load_delegation_policy(REPO_ROOT),
            profile,
            work_class=work_class,
            project_matched=True,
        )

    def root_plan(self):
        return prepare_execution_coordination(
            request_id="request-one",
            client_id="codex",
            request_text=self.request_text,
            work_class="project-analysis",
            intent=self.intent,
            context_digest="b" * 64,
            delegation=self.delegation(),
            project_id="sample",
            work_item_id="task-one",
            work_item_revision=1,
            work_item_digest="a" * 64,
            task_plan=self.task_plan,
            task_authorization_id=self.task_authorization.authorization_id,
            model_assignment_ids=["model-worker", "model-verifier"],
            dag_execution_plan_id=self.dag_plan.plan_id,
        )

    def dag_dispatch(self, plan_id: str):
        self.assertEqual(self.dag_plan.plan_id, plan_id)

        def callback(unit):
            return create_generic_dag_step_result(
                unit,
                evidence_digest=digest("evidence-" + unit.step.step_id),
            )

        adapters = {
            step_id: DagAdapterSpec(
                assignment.handler_id,
                assignment.execution_identity.actor_digest,
                assignment.execution_identity.runtime_kind,
                callback,
            )
            for step_id, assignment in self.assignments.items()
        }
        return dispatch_generic_dag_execution(
            self.queue,
            self.dag_plan,
            self.dag_authorization,
            adapters=adapters,
            owner_tokens=self.owner_tokens,
            expected_plan_id=self.dag_plan.plan_id,
        )

    @staticmethod
    def continuity(plan, dag_result):
        completed = [item["step_id"] for item in dag_result["step_results"]]
        snapshot = build_continuity_snapshot(
            snapshot_id="snapshot-one",
            project_id=plan.as_dict()["project_id"],
            work_item_id=plan.as_dict()["work_item_id"],
            goal="Complete the reviewed task",
            status="completed",
            updated_at="2026-08-15T18:00:00Z",
            work_item_revision=plan.as_dict()["work_item_revision"],
            completed_steps=completed,
            verification_refs=["verification-result"],
            approval_state="fresh-authorization-required",
        )
        return snapshot, finalize_handoff(
            snapshot,
            handoff_id="handoff-one",
            created_at="2026-08-15T18:00:01Z",
            first_reads=["continuity-snapshot", "work-item"],
        )

    def test_one_root_plan_composes_dag_verifier_continuity_trace_and_status(self) -> None:
        plan = self.root_plan()
        result = execute_execution_coordination(
            plan,
            ExecutionCoordinatorAdapters(self.dag_dispatch, self.continuity),
            started_at="2026-08-15T17:59:00Z",
            ended_at="2026-08-15T18:00:02Z",
            token_usage={
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 25,
                "cache_write_tokens": 0,
            },
        )

        payload = result.as_dict()
        self.assertEqual("completed", payload["status"])
        self.assertEqual("delegated-dag", payload["route"])
        self.assertIsNotNone(payload["verification_id"])
        self.assertEqual("snapshot-one", payload["continuity_snapshot_id"])
        self.assertEqual("handoff-one", payload["handoff_id"])
        self.assertFalse(payload["grants_authority"])
        self.assertEqual("completed", payload["status_projection"]["status"])
        self.assertEqual(4, len(payload["trace"]["agent_execution_ids"]))
        self.assertEqual({"completed": 4}, self.queue.status()["counts"])

    def test_exact_lookup_schedules_zero_agents_and_uses_direct_trace(self) -> None:
        decision = self.delegation(work_class="exact-lookup")
        plan = prepare_execution_coordination(
            request_id="lookup-one",
            client_id="codex",
            request_text=self.request_text,
            work_class="exact-lookup",
            intent=self.intent,
            context_digest="c" * 64,
            delegation=decision,
            project_id="sample",
            work_item_id="task-one",
        )
        self.assertEqual(0, plan.as_dict()["agent_calls_planned"])
        result = finalize_execution_coordination(
            plan,
            started_at="2026-08-15T18:00:00Z",
            ended_at="2026-08-15T18:00:01Z",
            direct_evidence_digest="d" * 64,
        )
        self.assertEqual([], result.as_dict()["trace"]["agent_execution_ids"])
        self.assertEqual("direct", result.as_dict()["trace"]["delegation_mode"])

    def test_unavailable_delegation_is_blocked_without_executable_assignments(self) -> None:
        plan = prepare_execution_coordination(
            request_id="blocked-one",
            client_id="codex",
            request_text=self.request_text,
            work_class="project-analysis",
            intent=self.intent,
            context_digest="b" * 64,
            delegation=self.delegation(available=False),
            project_id="sample",
            work_item_id="task-one",
            work_item_revision=1,
            work_item_digest="a" * 64,
        )
        payload = plan.as_dict()
        self.assertEqual("blocked", payload["route"])
        self.assertEqual([], payload["step_bindings"])
        self.assertEqual([], payload["model_assignment_ids"])
        with self.assertRaisesRegex(ExecutionCoordinatorError, "blocked"):
            finalize_execution_coordination(
                plan,
                started_at="2026-08-15T18:00:00Z",
                ended_at="2026-08-15T18:00:01Z",
            )

    def test_request_dag_and_continuity_tamper_fail_closed(self) -> None:
        with self.assertRaisesRegex(ExecutionCoordinatorError, "does not match"):
            prepare_execution_coordination(
                request_id="request-one",
                client_id="codex",
                request_text="A different request",
                work_class="project-analysis",
                intent=self.intent,
                context_digest="b" * 64,
                delegation=self.delegation(),
                project_id="sample",
                work_item_id="task-one",
                work_item_revision=1,
                work_item_digest="a" * 64,
                task_plan=self.task_plan,
                task_authorization_id=self.task_authorization.authorization_id,
                model_assignment_ids=["model-worker"],
                dag_execution_plan_id=self.dag_plan.plan_id,
            )

        plan = self.root_plan()
        dag_result = self.dag_dispatch(self.dag_plan.plan_id)
        changed = dict(dag_result)
        changed["execution_plan_id"] = "f" * 64
        snapshot, handoff = self.continuity(plan, dag_result)
        with self.assertRaisesRegex(ExecutionCoordinatorError, "DAG result binding"):
            finalize_execution_coordination(
                plan,
                started_at="2026-08-15T18:00:00Z",
                ended_at="2026-08-15T18:00:01Z",
                dag_result=changed,
                continuity_snapshot=snapshot,
                finalized_handoff=handoff,
            )

        incomplete = build_continuity_snapshot(
            snapshot_id="snapshot-two",
            project_id="sample",
            work_item_id="task-one",
            goal="Complete the reviewed task",
            status="completed",
            updated_at="2026-08-15T18:00:00Z",
            work_item_revision=1,
            completed_steps=["inspect-left"],
        )
        incomplete_handoff = finalize_handoff(
            incomplete,
            handoff_id="handoff-two",
            created_at="2026-08-15T18:00:01Z",
        )
        with self.assertRaisesRegex(ExecutionCoordinatorError, "does not cover"):
            finalize_execution_coordination(
                plan,
                started_at="2026-08-15T18:00:00Z",
                ended_at="2026-08-15T18:00:01Z",
                dag_result=dag_result,
                continuity_snapshot=incomplete,
                finalized_handoff=incomplete_handoff,
            )

    def test_plan_and_result_follow_versioned_schemas(self) -> None:
        plan = self.root_plan()
        result = execute_execution_coordination(
            plan,
            ExecutionCoordinatorAdapters(self.dag_dispatch, self.continuity),
            started_at="2026-08-15T18:00:00Z",
            ended_at="2026-08-15T18:00:01Z",
        )
        plan_schema = json.loads(
            (REPO_ROOT / "schemas/execution-coordination-plan.schema.json")
            .read_text(encoding="utf-8")
        )
        result_schema = json.loads(
            (REPO_ROOT / "schemas/execution-coordination-result.schema.json")
            .read_text(encoding="utf-8")
        )
        registry = Registry().with_resources(
            [
                (
                    "urn:krcn:schemas:execution-trace:1",
                    Resource.from_contents(
                        json.loads(
                            (REPO_ROOT / "schemas/execution-trace.schema.json")
                            .read_text(encoding="utf-8")
                        )
                    ),
                ),
                (
                    "urn:krcn:schemas:status-projection:1",
                    Resource.from_contents(
                        json.loads(
                            (REPO_ROOT / "schemas/status-projection.schema.json")
                            .read_text(encoding="utf-8")
                        )
                    ),
                ),
            ]
        )
        self.assertEqual([], list(Draft202012Validator(plan_schema).iter_errors(plan.as_dict())))
        self.assertEqual(
            [],
            list(
                Draft202012Validator(
                    result_schema,
                    registry=registry,
                ).iter_errors(result.as_dict())
            ),
        )
        self.assertEqual(plan, parse_execution_coordination_plan(plan.as_dict()))
        self.assertEqual(
            result,
            parse_execution_coordination_result(result.as_dict()),
        )

    def test_result_tamper_and_coordinator_boundary_fail_closed(self) -> None:
        plan = self.root_plan()
        result = execute_execution_coordination(
            plan,
            ExecutionCoordinatorAdapters(self.dag_dispatch, self.continuity),
            started_at="2026-08-15T18:00:00Z",
            ended_at="2026-08-15T18:00:01Z",
        )
        tampered = result.as_dict()
        tampered["evidence_digest"] = "f" * 64
        with self.assertRaisesRegex(ExecutionCoordinatorError, "binding"):
            parse_execution_coordination_result(tampered)

        source = (
            REPO_ROOT / "src/krcn_core/execution_coordinator.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "mutation_gate",
            "provider_gate",
            "LocalWorkspaceStore",
            "AgentRuntimeQueue",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_application_exposes_the_same_transport_neutral_root_plan(self) -> None:
        expected = self.root_plan()
        arguments = {
            "request_id": "request-one",
            "client_id": "codex",
            "request_text": self.request_text,
            "work_class": "project-analysis",
            "intent": self.intent.as_dict(),
            "context_digest": "b" * 64,
            "delegation": self.delegation().as_dict(),
            "project_id": "sample",
            "work_item_id": "task-one",
            "work_item_revision": 1,
            "work_item_digest": "a" * 64,
            "task_plan": self.task_plan.as_dict(),
            "task_authorization_id": self.task_authorization.authorization_id,
            "model_assignment_ids": ["model-worker", "model-verifier"],
            "dag_execution_plan_id": self.dag_plan.plan_id,
        }
        service = create_application_service(
            REPO_ROOT,
            Path(self.temporary.name) / "application-home",
        )
        response = service.execute(
            ServiceRequest("sdk", "execution.coordinate", arguments)
        )
        self.assertEqual("planned", response.status)
        self.assertEqual(
            expected.as_dict(),
            response.data["coordination_plan"],
        )


if __name__ == "__main__":
    unittest.main()
