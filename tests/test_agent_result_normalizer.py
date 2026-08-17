from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from agent_identity_fixtures import digest, execution_identity  # noqa: E402
from krcn_core.agent_result_normalizer import (  # noqa: E402
    AgentResultNormalizationError,
    normalize_generic_dag_result,
    normalize_native_client_result,
    normalize_worker_execution,
    parse_normalized_agent_result,
)
from krcn_core.capability_registry import load_capability_registry, select_capability_records  # noqa: E402
from krcn_core.orchestration_authorization import authorize_task_plan, create_operation_request  # noqa: E402
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import create_task_plan  # noqa: E402
from krcn_core.orchestration_worker import (  # noqa: E402
    WorkerEffect,
    WorkerHandlerRegistry,
    WorkerHandlerResult,
    WorkerHandlerSpec,
    create_work_request,
    execute_worker_step,
)
from test_database_policy import select_only_policy  # noqa: E402
from test_orchestration_intent import extraction  # noqa: E402
from test_orchestration_plan import read_only_steps  # noqa: E402


def sha(character: str) -> str:
    return character * 64


def context(**overrides):
    values = {
        "correlation_id": "correlation-one", "project_id": "project-one",
        "work_item_id": "work-one", "task_id": "task-one", "task_plan_id": sha("a"),
        "step_id": "inspect-source", "queue_id": "queue-one",
        "execution_identity_id": sha("b"), "role": "worker",
        "route_decision_id": sha("c"), "delegation_decision_id": None,
        "model_assignment_id": "assignment-one", "admission_decision_id": None,
        "attempt_id": "attempt-one", "sequence": 1, "attempt_number": 1,
        "input_digest": sha("d"), "context_snapshot_digest": sha("e"),
        "source_revision_digest": sha("f"), "validation_gate_id": None,
        "started_at": "2026-08-17T12:00:00.000Z",
        "finished_at": "2026-08-17T12:00:00.005Z",
        "harness_revision": sha("1"), "policy_revision": sha("2"),
        "client_id": "codex-cli", "input_tokens": 10, "output_tokens": 5,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
        "cost_microunits": 0, "currency": None,
    }
    values.update(overrides)
    return values


def semantic(**overrides):
    values = {
        "status": "completed", "headline": "Inspection completed", "findings": [],
        "artifacts": [],
        "evidence": [{"evidence_id": "source-evidence", "evidence_type": "state-observation", "evidence_digest": sha("3")}],
        "effects": [{"effect_id": "source-read", "effect_type": "read", "claim_id": None, "receipt_id": None, "result_digest": sha("3")}],
        "risks": [], "failure": None, "missing_step_ids": [],
        "recommended_next_action": {"action_code": "CONTINUE_PLAN", "statement": "Continue with the reviewed plan", "required_role": "coordinator"},
        "verification": {"required": True, "validation_gate_id": None, "verification_id": None, "covered_worker_step_ids": [], "verdict": None},
    }
    values.update(overrides)
    return values


class AgentResultNormalizerTests(unittest.TestCase):
    def test_native_and_dag_results_share_the_same_contract(self) -> None:
        native = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()},
            context(),
        )
        dag = normalize_generic_dag_result(
            {
                "schema_ref": "schemas/generic-dag-execution-result.schema.json#/$defs/adapterResult",
                "schema_version": 1, "status": "completed", "task_id": "task-one",
                "plan_id": sha("a"), "step_id": "inspect-source",
                "execution_identity_id": sha("b"), "evidence_digest": sha("3"),
                "grants_authority": False,
            },
            context(),
        )
        for normalized in (native, dag):
            parsed = parse_normalized_agent_result(normalized.as_dict())
            self.assertEqual("completed", parsed.envelope.status)
            self.assertEqual("completed", parsed.receipt.status)
            self.assertFalse(parsed.as_dict()["grants_authority"])

    def test_native_free_text_unknown_fields_and_unsafe_content_fail_closed(self) -> None:
        with self.assertRaisesRegex(AgentResultNormalizationError, "fields"):
            normalize_native_client_result("completed", context())
        with self.assertRaisesRegex(AgentResultNormalizationError, "fields"):
            normalize_native_client_result(
                {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic(), "raw": "x"},
                context(),
            )
        unsafe = semantic(headline="Read " + "C:" + "\\private\\note.txt")
        with self.assertRaisesRegex(AgentResultNormalizationError, "normalization"):
            normalize_native_client_result(
                {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": unsafe},
                context(),
            )

    def test_partial_native_result_is_not_completed_semantically(self) -> None:
        partial = semantic(status="partial", missing_step_ids=["verify-output"])
        result = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": partial},
            context(),
        )
        self.assertEqual("partial", result.envelope.status)
        self.assertEqual("completed", result.receipt.status)

    def test_direct_read_worker_normalizes_and_mutation_waits_for_phase_25_receipt(self) -> None:
        intent = create_task_intent("Yalnız select kullan.", extraction())
        selection = select_capability_records(
            load_capability_registry(REPO_ROOT),
            ["worker-agent", "verifier-agent", "local-store-reader-tool"],
            ["plan.execute", "record.read", "evidence.verify"],
        )
        plan = create_task_plan(intent, selection, read_only_steps())
        worker_step = next(item for item in plan.steps if item.role == "worker")
        authorization = authorize_task_plan(
            REPO_ROOT, intent=intent, selection=selection, plan=plan,
            session_id="normalizer-session", policies=[select_only_policy()],
            operations=[create_operation_request(
                step_id=worker_step.step_id, resource_type="database", operation="select",
                scope_refs={"integration": "reporting-database"}, require_policy_match=True,
            )],
        )
        identity = execution_identity(plan, worker_step.step_id, "worker")
        request = create_work_request(
            plan, authorization, step_id=worker_step.step_id, handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"}, execution_identity=identity,
        )

        def run(effect_type):
            registry = WorkerHandlerRegistry()
            registry.register(WorkerHandlerSpec(
                "inspect-handler", tuple(worker_step.required_capabilities), (effect_type,),
                lambda _ctx, _payload: WorkerHandlerResult(
                    {"rows": 1}, (WorkerEffect("source-read", effect_type, None, None, (sha("3"),)),)
                ),
                identity_actor_digest=digest(f"worker-{worker_step.step_id}-actor"), runtime_kind="local-handler",
            ))
            return execute_worker_step(plan, authorization, request, registry)

        execution = run("read")
        worker_context = context(
            task_id=plan.task_id, task_plan_id=plan.plan_id, step_id=worker_step.step_id,
            execution_identity_id=identity.execution_identity_id,
            input_digest=execution.journal.input_digest,
        )
        normalized = normalize_worker_execution(execution, worker_context, semantic())
        self.assertEqual("worker-execution-v2", normalized.source_format)
        with self.assertRaisesRegex(AgentResultNormalizationError, "effect receipts"):
            normalize_worker_execution(run("execute"), worker_context, semantic())

    def test_normalized_payload_schemas_validate(self) -> None:
        normalized = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()}, context()
        ).as_dict()
        schemas = {}
        for name in ("agent-result-envelope.schema.json", "workflow-step-receipt.schema.json"):
            data = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            schemas[data["$id"]] = Resource.from_contents(data)
        registry = Registry().with_resources(list(schemas.items()))
        schema = json.loads((REPO_ROOT / "schemas/agent-result-normalization.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([], list(Draft202012Validator(schema, registry=registry).iter_errors(normalized)))
        native_schema = json.loads((REPO_ROOT / "schemas/native-agent-result.schema.json").read_text(encoding="utf-8"))
        native = {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()}
        self.assertEqual([], list(Draft202012Validator(native_schema, registry=registry).iter_errors(native)))


if __name__ == "__main__":
    unittest.main()
