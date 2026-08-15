from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.capability_registry import (  # noqa: E402
    load_capability_registry,
    select_capability_records,
)
from krcn_core.orchestration_authorization import (  # noqa: E402
    authorize_task_plan,
    create_operation_request,
)
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import create_task_plan  # noqa: E402
from krcn_core.orchestration_worker import (  # noqa: E402
    WorkerEffect,
    WorkerExecutionError,
    WorkerHandlerRegistry,
    WorkerHandlerResult,
    WorkerHandlerSpec,
    create_work_request,
    execute_worker_step,
    parse_worker_execution,
)
from krcn_core.information_records import canonical_json  # noqa: E402
from test_database_policy import select_only_policy  # noqa: E402
from test_orchestration_intent import extraction  # noqa: E402
from test_orchestration_plan import read_only_steps  # noqa: E402
from agent_identity_fixtures import digest, execution_identity  # noqa: E402


class OrchestrationWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = create_task_intent(
            "Veritabanında delete istemiyorum, sadece select kullan.",
            extraction(),
        )
        registry = load_capability_registry(REPO_ROOT)
        self.selection = select_capability_records(
            registry,
            ["worker-agent", "verifier-agent", "local-store-reader-tool"],
            ["plan.execute", "record.read", "evidence.verify"],
        )

    def operation(self, step_id="inspect-policy"):
        return create_operation_request(
            step_id=step_id,
            resource_type="database",
            operation="select",
            scope_refs={"integration": "reporting-database"},
            require_policy_match=True,
        )

    def plan_and_authorization(self, steps=None):
        plan = create_task_plan(
            self.intent,
            self.selection,
            steps if steps is not None else read_only_steps(),
        )
        worker_ids = [item.step_id for item in plan.steps if item.role == "worker"]
        authorization = authorize_task_plan(
            REPO_ROOT,
            intent=self.intent,
            selection=self.selection,
            plan=plan,
            session_id="synthetic-session",
            policies=[select_only_policy()],
            operations=[self.operation(step_id) for step_id in worker_ids],
        )
        return plan, authorization

    def registry(self, callback, *, side_effects=("execute", "read")):
        registry = WorkerHandlerRegistry()
        registry.register(
            WorkerHandlerSpec(
                "inspect-handler",
                ("plan.execute", "record.read"),
                side_effects,
                callback,
                identity_actor_digest=digest("worker-inspect-policy-actor"),
                runtime_kind="local-handler",
            )
        )
        return registry

    def test_completed_checkpoint_replays_without_calling_handler_twice(self) -> None:
        plan, authorization = self.plan_and_authorization()
        calls = []

        def handler(context, payload):
            calls.append((context.idempotency_key, payload["query"]))
            return WorkerHandlerResult(
                {"rows": 1},
                (
                    WorkerEffect("policy-read", "read", None, None, ("a" * 64,)),
                    WorkerEffect("query-run", "execute", None, None, ("b" * 64,)),
                ),
            )

        request = create_work_request(
            plan,
            authorization,
            step_id="inspect-policy",
            handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"},
            execution_identity=execution_identity(plan, "inspect-policy", "worker"),
        )
        first = execute_worker_step(plan, authorization, request, self.registry(handler))
        second = execute_worker_step(
            plan,
            authorization,
            request,
            self.registry(handler),
            history=[first],
        )
        self.assertEqual("completed", first.checkpoint.status)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.checkpoint, second.checkpoint)
        self.assertEqual(1, len(calls))
        payload = first.as_dict()
        schema = json.loads(
            (REPO_ROOT / "schemas" / "worker-execution.schema.json").read_text(
                encoding="utf-8"
            )
        )
        identity_schema = json.loads(
            (
                REPO_ROOT / "schemas" / "agent-execution-identity.schema.json"
            ).read_text(encoding="utf-8")
        )
        registry = Registry().with_resource(
            identity_schema["$id"], Resource.from_contents(identity_schema)
        )
        self.assertEqual(
            [],
            list(Draft202012Validator(schema, registry=registry).iter_errors(payload)),
        )

        legacy = copy.deepcopy(payload)
        legacy["schema_version"] = 1
        legacy.pop("execution_identity")
        legacy["checkpoint"].pop("execution_identity_id")
        legacy["journal"].pop("execution_identity_id")
        journal_identity = dict(legacy["journal"])
        journal_identity.pop("journal_id")
        legacy["journal"]["journal_id"] = hashlib.sha256(
            canonical_json(journal_identity)
        ).hexdigest()
        checkpoint_identity = dict(legacy["checkpoint"])
        checkpoint_identity.pop("checkpoint_id")
        checkpoint_identity["journal_id"] = legacy["journal"]["journal_id"]
        legacy["checkpoint"]["checkpoint_id"] = hashlib.sha256(
            canonical_json(checkpoint_identity)
        ).hexdigest()
        parsed_legacy = parse_worker_execution(legacy)
        self.assertIsNone(parsed_legacy.execution_identity)
        self.assertEqual(legacy, parsed_legacy.as_dict())

    def test_failed_checkpoint_can_retry_with_the_same_idempotency_key(self) -> None:
        plan, authorization = self.plan_and_authorization()
        calls = []

        def handler(context, payload):
            calls.append(context.idempotency_key)
            if len(calls) == 1:
                raise RuntimeError("synthetic interruption")
            return WorkerHandlerResult(
                {"rows": 1},
                (WorkerEffect("policy-read", "read", None, None, ("a" * 64,)),),
            )

        request = create_work_request(
            plan,
            authorization,
            step_id="inspect-policy",
            handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"},
            execution_identity=execution_identity(plan, "inspect-policy", "worker"),
        )
        first = execute_worker_step(plan, authorization, request, self.registry(handler))
        second = execute_worker_step(
            plan,
            authorization,
            request,
            self.registry(handler),
            history=[first],
        )
        self.assertEqual("failed", first.checkpoint.status)
        self.assertIsNotNone(first.checkpoint.failure_digest)
        self.assertEqual("completed", second.checkpoint.status)
        self.assertEqual(2, len(calls))

    def test_dependencies_and_completed_input_binding_are_enforced(self) -> None:
        steps = read_only_steps()
        second_worker = copy.deepcopy(steps[0])
        second_worker["step_id"] = "summarize-policy"
        second_worker["title"] = "Summarize the effective policy"
        second_worker["depends_on"] = ["inspect-policy"]
        steps.insert(1, second_worker)
        steps[2]["depends_on"] = ["summarize-policy"]
        plan, authorization = self.plan_and_authorization(steps)

        def handler(context, payload):
            return WorkerHandlerResult(
                {"step": context.step_id},
                (WorkerEffect("policy-read", "read", None, None, ("a" * 64,)),),
            )

        registry = self.registry(handler)
        second_request = create_work_request(
            plan,
            authorization,
            step_id="summarize-policy",
            handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"},
            execution_identity=execution_identity(
                plan,
                "summarize-policy",
                "worker",
                actor="worker-inspect-policy-actor",
            ),
        )
        with self.assertRaisesRegex(WorkerExecutionError, "dependencies"):
            execute_worker_step(plan, authorization, second_request, registry)
        first_request = create_work_request(
            plan,
            authorization,
            step_id="inspect-policy",
            handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"},
            execution_identity=execution_identity(plan, "inspect-policy", "worker"),
        )
        first = execute_worker_step(plan, authorization, first_request, registry)
        second = execute_worker_step(
            plan,
            authorization,
            second_request,
            registry,
            history=[first],
        )
        self.assertEqual("completed", second.checkpoint.status)

        changed_request = create_work_request(
            plan,
            authorization,
            step_id="summarize-policy",
            handler_id="inspect-handler",
            input_payload={"query": "changed-input"},
            execution_identity=execution_identity(
                plan,
                "summarize-policy",
                "worker",
                actor="worker-inspect-policy-actor",
            ),
        )
        with self.assertRaisesRegex(WorkerExecutionError, "cannot be rebound"):
            execute_worker_step(
                plan,
                authorization,
                changed_request,
                registry,
                history=[first, second],
            )

    def test_unregistered_handler_plan_drift_and_effect_escalation_fail_closed(self) -> None:
        plan, authorization = self.plan_and_authorization()
        request = create_work_request(
            plan,
            authorization,
            step_id="inspect-policy",
            handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"},
            execution_identity=execution_identity(plan, "inspect-policy", "worker"),
        )
        with self.assertRaisesRegex(WorkerExecutionError, "not explicitly registered"):
            execute_worker_step(
                plan,
                authorization,
                request,
                WorkerHandlerRegistry(),
            )

        drifted = replace(authorization, plan_id="f" * 64)
        with self.assertRaisesRegex(WorkerExecutionError, "exact task plan"):
            execute_worker_step(plan, drifted, request, self.registry(lambda *_: None))

        def escalated(context, payload):
            return WorkerHandlerResult(
                {"unexpected": True},
                (WorkerEffect("unexpected-write", "write", None, None, ("a" * 64,)),),
            )

        failed = execute_worker_step(
            plan,
            authorization,
            request,
            self.registry(escalated),
        )
        self.assertEqual("failed", failed.checkpoint.status)
        self.assertEqual((), failed.journal.effects)

    def test_client_identity_cannot_override_registered_handler_identity(self) -> None:
        plan, authorization = self.plan_and_authorization()
        request = create_work_request(
            plan,
            authorization,
            step_id="inspect-policy",
            handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"},
            execution_identity=execution_identity(
                plan,
                "inspect-policy",
                "worker",
                actor="unregistered-worker-actor",
            ),
        )
        calls = []

        with self.assertRaisesRegex(
            WorkerExecutionError, "does not match the registered handler"
        ):
            execute_worker_step(
                plan,
                authorization,
                request,
                self.registry(lambda *_: calls.append("called")),
            )
        self.assertEqual([], calls)

    def test_sensitive_input_is_rejected_and_schema_is_versioned(self) -> None:
        plan, authorization = self.plan_and_authorization()
        with self.assertRaisesRegex(WorkerExecutionError, "sensitive"):
            create_work_request(
                plan,
                authorization,
                step_id="inspect-policy",
                handler_id="inspect-handler",
                input_payload={"token": "synthetic-value"},
                execution_identity=execution_identity(plan, "inspect-policy", "worker"),
            )
        schema = json.loads(
            (REPO_ROOT / "schemas" / "worker-execution.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("urn:krcn:schemas:worker-execution:2", schema["$id"])


if __name__ == "__main__":
    unittest.main()
