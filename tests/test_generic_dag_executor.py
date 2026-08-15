from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
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
from krcn_core.agent_runtime import (  # noqa: E402
    AgentRuntimeQueue,
    SchedulerPolicy,
    load_scheduler_policy,
)
from krcn_core.capability_registry import (  # noqa: E402
    load_capability_registry,
    select_capability_records,
)
from krcn_core.generic_dag_executor import (  # noqa: E402
    DagAdapterSpec,
    DagStepAssignment,
    GenericDagExecutionError,
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


def steps() -> list[dict[str, object]]:
    common_worker = {
        "title": "Inspect one independent policy input",
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
        {**common_worker, "step_id": "inspect-left"},
        {**common_worker, "step_id": "inspect-right"},
        {
            **common_worker,
            "step_id": "merge-findings",
            "depends_on": ["inspect-left", "inspect-right"],
        },
        {
            "step_id": "verify-result",
            "title": "Verify the merged policy result",
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


class GenericDagExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name) / "home"
        self.data_root.mkdir()
        self.queue = AgentRuntimeQueue(
            self.data_root,
            "sample",
            load_scheduler_policy(REPO_ROOT),
        )
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        intent = create_task_intent("Keep database access read-only.", extraction())
        registry = load_capability_registry(REPO_ROOT)
        selection = select_capability_records(
            registry,
            ["worker-agent", "verifier-agent", "local-store-reader-tool"],
            ["plan.execute", "record.read", "evidence.verify"],
        )
        self.task_plan = create_task_plan(intent, selection, steps())
        worker_ids = [
            step.step_id for step in self.task_plan.steps if step.role == "worker"
        ]
        self.task_authorization = authorize_task_plan(
            REPO_ROOT,
            intent=intent,
            selection=selection,
            plan=self.task_plan,
            session_id="generic-dag-session",
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
            step.step_id: f"owner-token-{index:04d}-{step.step_id}"
            for index, step in enumerate(self.task_plan.steps, start=1)
        }
        self.assignments = self.make_assignments()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_assignments(self, *, shared_root_resource: bool = False):
        assignments = {}
        for step in self.task_plan.steps:
            actor = f"{step.role}-{step.step_id}-actor"
            assignment = f"{step.role}-{step.step_id}-assignment"
            resource = (
                "task:sample:shared-root"
                if shared_root_resource
                and step.step_id in {"inspect-left", "inspect-right"}
                else f"task:sample:{step.step_id}"
            )
            identity = create_agent_execution_identity(
                task_id=self.task_plan.task_id,
                plan_id=self.task_plan.plan_id,
                step_id=step.step_id,
                role=step.role,
                actor_digest=digest(actor),
                session_digest=digest(self.owner_tokens[step.step_id]),
                assignment_digest=digest(assignment),
                runtime_kind="local-handler",
            )
            assignments[step.step_id] = DagStepAssignment(
                step.step_id,
                f"handler-{step.step_id}",
                identity,
                (resource,),
            )
        return assignments

    def prepare(self, assignments=None, *, max_concurrency=2):
        plan = prepare_generic_dag_execution(
            self.queue,
            self.ownership,
            project_id="sample",
            work_item_id="task-one",
            work_item_revision=1,
            work_item_digest="a" * 64,
            task_plan=self.task_plan,
            task_authorization=self.task_authorization,
            assignments=assignments or self.assignments,
            max_concurrency=max_concurrency,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        return plan, authorization

    def adapter_specs(self, callback):
        return {
            step_id: DagAdapterSpec(
                assignment.handler_id,
                assignment.execution_identity.actor_digest,
                assignment.execution_identity.runtime_kind,
                callback,
            )
            for step_id, assignment in self.assignments.items()
        }

    @staticmethod
    def completed(unit):
        evidence = digest("evidence-" + unit.step.step_id)
        return create_generic_dag_step_result(unit, evidence_digest=evidence)

    def dispatch(self, callback=None, *, assignments=None, max_concurrency=2):
        if assignments is not None:
            self.assignments = assignments
        plan, authorization = self.prepare(
            self.assignments,
            max_concurrency=max_concurrency,
        )
        return dispatch_generic_dag_execution(
            self.queue,
            plan,
            authorization,
            adapters=self.adapter_specs(callback or self.completed),
            owner_tokens=self.owner_tokens,
            expected_plan_id=plan.plan_id,
        )

    def test_ready_roots_run_in_parallel_and_dependencies_are_checkpointed(self) -> None:
        barrier = threading.Barrier(2, timeout=2)
        observed_dependencies = {}

        def callback(unit):
            if not unit.step.depends_on:
                barrier.wait()
            observed_dependencies[unit.step.step_id] = dict(unit.dependency_evidence)
            return self.completed(unit)

        result = self.dispatch(callback)
        self.assertEqual("completed", result["status"])
        self.assertEqual(4, len(result["step_results"]))
        self.assertEqual(
            {"inspect-left", "inspect-right"},
            set(observed_dependencies["merge-findings"]),
        )
        self.assertEqual(
            {"merge-findings"},
            set(observed_dependencies["verify-result"]),
        )
        self.assertEqual({"completed": 4}, self.queue.status()["counts"])
        self.assertTrue(result["runtime_completion"])
        self.assertFalse(result["grants_authority"])

    def test_conflicting_resources_are_serialized(self) -> None:
        assignments = self.make_assignments(shared_root_resource=True)
        active = 0
        maximum = 0
        lock = threading.Lock()

        def callback(unit):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            threading.Event().wait(0.01)
            with lock:
                active -= 1
            return self.completed(unit)

        self.dispatch(callback, assignments=assignments)
        self.assertEqual(1, maximum)

    def test_failed_read_step_can_resume_without_replaying_completed_step(self) -> None:
        calls = []
        failed = False

        def first_callback(unit):
            nonlocal failed
            calls.append(unit.step.step_id)
            if unit.step.step_id == "inspect-right" and not failed:
                failed = True
                raise RuntimeError("synthetic failure")
            return self.completed(unit)

        with self.assertRaisesRegex(GenericDagExecutionError, "adapter failed"):
            self.dispatch(first_callback)
        self.assertEqual(1, calls.count("inspect-left"))

        second_plan, second_authorization = self.prepare(self.assignments)
        result = dispatch_generic_dag_execution(
            self.queue,
            second_plan,
            second_authorization,
            adapters=self.adapter_specs(
                lambda unit: calls.append(unit.step.step_id) or self.completed(unit)
            ),
            owner_tokens=self.owner_tokens,
            expected_plan_id=second_plan.plan_id,
        )
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["resumed"])
        self.assertEqual(1, calls.count("inspect-left"))
        self.assertEqual(2, calls.count("inspect-right"))

    def test_stale_queue_and_wrong_exact_plan_fail_closed(self) -> None:
        plan, authorization = self.prepare()
        identity = {
            "project_id": "sample",
            "work_item_id": "other-task",
            "work_item_revision": 1,
            "work_item_digest": "b" * 64,
            "task_id": "other-run",
            "parent_task_id": None,
            "plan_id": "c" * 64,
            "step_id": "other-step",
            "required_role": "worker",
            "required_capabilities": ["other-capability"],
            "side_effects": ["read"],
            "resource_refs": ["task:sample:other-task"],
            "idempotency_key": "d" * 64,
            "queue_id": "queue-" + "d" * 24,
            "max_attempts": 3,
        }
        self.queue.apply("enqueue", identity, self.queue.state_digest())
        with self.assertRaisesRegex(GenericDagExecutionError, "changed after planning"):
            dispatch_generic_dag_execution(
                self.queue,
                plan,
                authorization,
                adapters=self.adapter_specs(self.completed),
                owner_tokens=self.owner_tokens,
                expected_plan_id=plan.plan_id,
            )

        fresh_plan, fresh_authorization = self.prepare()
        with self.assertRaisesRegex(GenericDagExecutionError, "exact execution plan"):
            dispatch_generic_dag_execution(
                self.queue,
                fresh_plan,
                fresh_authorization,
                adapters=self.adapter_specs(self.completed),
                owner_tokens=self.owner_tokens,
                expected_plan_id="e" * 64,
            )

    def test_owner_token_and_cancellation_are_fail_closed(self) -> None:
        plan, authorization = self.prepare()
        wrong_tokens = dict(self.owner_tokens)
        wrong_tokens["inspect-left"] = "different-owner-token-0001"
        with self.assertRaisesRegex(GenericDagExecutionError, "trusted execution"):
            dispatch_generic_dag_execution(
                self.queue,
                plan,
                authorization,
                adapters=self.adapter_specs(self.completed),
                owner_tokens=wrong_tokens,
                expected_plan_id=plan.plan_id,
            )
        with self.assertRaisesRegex(GenericDagExecutionError, "cancelled"):
            dispatch_generic_dag_execution(
                self.queue,
                plan,
                authorization,
                adapters=self.adapter_specs(self.completed),
                owner_tokens=self.owner_tokens,
                expected_plan_id=plan.plan_id,
                cancellation=lambda: True,
            )
        self.assertEqual([], self.queue.status()["items"])

    def test_long_handler_execution_renews_its_lease(self) -> None:
        now = [1000.0]
        heartbeat_count = [0]
        heartbeat_seen = threading.Event()
        base = load_scheduler_policy(REPO_ROOT)
        self.queue = AgentRuntimeQueue(
            self.data_root,
            "sample",
            SchedulerPolicy(
                2,
                1,
                10,
                1,
                base.default_max_attempts,
                base.maximum_attempts,
                base.claim_busy_timeout_ms,
            ),
            clock=lambda: now[0],
        )
        plan, authorization = self.prepare(max_concurrency=1)

        def heartbeat_wait(signal, seconds):
            now[0] += seconds
            heartbeat_count[0] += 1
            if heartbeat_count[0] >= 2:
                heartbeat_seen.set()
            return signal.wait(0.001)

        def callback(unit):
            self.assertTrue(heartbeat_seen.wait(1))
            return self.completed(unit)

        result = dispatch_generic_dag_execution(
            self.queue,
            plan,
            authorization,
            adapters=self.adapter_specs(callback),
            owner_tokens=self.owner_tokens,
            expected_plan_id=plan.plan_id,
            heartbeat_wait=heartbeat_wait,
        )
        self.assertEqual("completed", result["status"])
        self.assertGreaterEqual(heartbeat_count[0], 2)

    def test_identity_adapter_and_result_tamper_are_rejected(self) -> None:
        assignments = self.make_assignments()
        worker = assignments["merge-findings"]
        verifier = assignments["verify-result"]
        assignments["verify-result"] = DagStepAssignment(
            verifier.step_id,
            verifier.handler_id,
            create_agent_execution_identity(
                task_id=self.task_plan.task_id,
                plan_id=self.task_plan.plan_id,
                step_id=verifier.step_id,
                role="verifier",
                actor_digest=worker.execution_identity.actor_digest,
                session_digest=verifier.execution_identity.session_digest,
                assignment_digest=verifier.execution_identity.assignment_digest,
                runtime_kind="local-handler",
            ),
            verifier.resource_refs,
        )
        with self.assertRaisesRegex(GenericDagExecutionError, "not independent"):
            self.prepare(assignments)

        self.assignments = self.make_assignments()
        plan, authorization = self.prepare()
        adapters = self.adapter_specs(self.completed)
        left = adapters["inspect-left"]
        adapters["inspect-left"] = DagAdapterSpec(
            left.handler_id,
            digest("wrong-actor"),
            left.runtime_kind,
            left.callback,
        )
        with self.assertRaisesRegex(GenericDagExecutionError, "trusted execution"):
            dispatch_generic_dag_execution(
                self.queue,
                plan,
                authorization,
                adapters=adapters,
                owner_tokens=self.owner_tokens,
                expected_plan_id=plan.plan_id,
            )

        tamper_plan, tamper_authorization = self.prepare()

        def tampered(unit):
            result = self.completed(unit)
            result["execution_identity_id"] = "f" * 64
            return result

        with self.assertRaisesRegex(GenericDagExecutionError, "result binding"):
            dispatch_generic_dag_execution(
                self.queue,
                tamper_plan,
                tamper_authorization,
                adapters=self.adapter_specs(tampered),
                owner_tokens=self.owner_tokens,
                expected_plan_id=tamper_plan.plan_id,
            )

    def test_tampered_persisted_checkpoint_fails_closed(self) -> None:
        self.dispatch()
        connection = sqlite3.connect(self.queue.path)
        try:
            connection.execute(
                "UPDATE queue_items SET work_item_digest=? WHERE step_id=?",
                ("b" * 64, "inspect-left"),
            )
            connection.commit()
        finally:
            connection.close()
        plan, authorization = self.prepare()
        with self.assertRaisesRegex(GenericDagExecutionError, "checkpoint identity"):
            dispatch_generic_dag_execution(
                self.queue,
                plan,
                authorization,
                adapters=self.adapter_specs(self.completed),
                owner_tokens=self.owner_tokens,
                expected_plan_id=plan.plan_id,
            )

    def test_plan_and_result_schemas_validate_public_contracts(self) -> None:
        plan, authorization = self.prepare()
        plan_schema = json.loads(
            (REPO_ROOT / "schemas" / "generic-dag-execution-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        identity_schema = json.loads(
            (REPO_ROOT / "schemas" / "agent-execution-identity.schema.json").read_text(
                encoding="utf-8"
            )
        )
        mutation_schema = json.loads(
            (REPO_ROOT / "schemas" / "mutation-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        registry = Registry().with_resources(
            [
                (
                    identity_schema["$id"],
                    Resource.from_contents(identity_schema),
                ),
                (
                    "mutation-plan.schema.json",
                    Resource.from_contents(mutation_schema),
                ),
            ]
        )
        self.assertEqual(
            [],
            list(
                Draft202012Validator(plan_schema, registry=registry).iter_errors(
                    plan.public_summary()
                )
            ),
        )
        result = dispatch_generic_dag_execution(
            self.queue,
            plan,
            authorization,
            adapters=self.adapter_specs(self.completed),
            owner_tokens=self.owner_tokens,
            expected_plan_id=plan.plan_id,
        )
        result_schema = json.loads(
            (REPO_ROOT / "schemas" / "generic-dag-execution-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [],
            list(Draft202012Validator(result_schema).iter_errors(result)),
        )


if __name__ == "__main__":
    unittest.main()
