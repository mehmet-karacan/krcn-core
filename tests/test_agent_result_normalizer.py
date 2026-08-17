from __future__ import annotations

import json
import copy
import sys
import unittest
import tempfile
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
from krcn_core.agent_result_fanin import (  # noqa: E402
    AgentResultFanInError,
    build_agent_result_fan_in,
    build_execution_trace_from_results,
    parse_agent_result_fan_in,
)
from krcn_core.capability_registry import load_capability_registry, select_capability_records  # noqa: E402
from krcn_core.application import KrcnApplicationService  # noqa: E402
from krcn_core.application_contract import ApplicationServiceError, ServiceRequest  # noqa: E402
from krcn_core.cli.app import build_parser  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.effect_ledger import build_effect_claim, build_effect_receipt  # noqa: E402
from krcn_core.agent_execution_identity import create_agent_execution_identity  # noqa: E402
from krcn_core.validation_gate import build_validation_gate  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
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

    def test_generic_dag_non_read_effect_requires_exact_ledger_pair(self) -> None:
        verifier = create_agent_execution_identity(
            task_id="task-one", plan_id=sha("a"), step_id="verify-effect", role="verifier",
            actor_digest=sha("8"), session_digest=sha("9"), assignment_digest=sha("7"),
            runtime_kind="isolated-role",
        )
        gate = build_validation_gate(
            project_id="project-one", work_item_id="work-one", task_id="task-one",
            task_plan_id=sha("a"), worker_step_id="inspect-source", effect_id="execute-check",
            effect_type="execute", effect_digest=sha("6"), effect_authorization_id=sha("5"),
            worker_execution_identity_id=sha("b"), worker_actor_digest=sha("4"),
            verifier_execution_identity=verifier,
            subjects=[{"subject_kind": "acceptance-criterion", "subject_digest": sha("1")}],
            checks=[{"check_id": "state-check", "actor_kind": "verifier", "method": "state-check",
                     "expected_result": "passed", "evidence_required": ["state-observation"],
                     "subject_digests": [sha("1")]}],
            policy_revision=sha("2"), source_revision_digest=sha("f"),
            created_at="2026-08-17T11:59:59.000Z",
        )
        claim = build_effect_claim(
            project_id="project-one", work_item_id="work-one", task_id="task-one",
            task_plan_id=sha("a"), step_id="inspect-source", queue_id="queue-one",
            attempt_id="attempt-one", attempt_number=1, execution_identity_id=sha("b"),
            lease_id="lease-one", fencing_token=1, effect_id="execute-check",
            effect_type="execute", effect_digest=sha("6"), idempotency_key=sha("0"),
            effect_authorization_id=sha("5"), validation_gate=gate,
            host_digest=sha("4"), claimed_at="2026-08-17T12:00:00.000Z",
        )
        receipt = build_effect_receipt(
            claim=claim, outcome="completed", retry_safety="non-replayable",
            result_digest=sha("3"), finished_at="2026-08-17T12:00:00.004Z",
            observed_fencing_token=1,
        )
        payload = {
            "schema_ref": "schemas/generic-dag-execution-result.schema.json#/$defs/adapterResult",
            "schema_version": 1, "status": "completed", "task_id": "task-one",
            "plan_id": sha("a"), "step_id": "inspect-source", "execution_identity_id": sha("b"),
            "evidence_digest": sha("3"), "grants_authority": False,
        }
        normalized = normalize_generic_dag_result(
            payload, context(validation_gate_id=gate.validation_gate_id),
            effect_claim=claim, effect_receipt=receipt,
        )
        effect = normalized.envelope.payload["result"]["effects"][0]
        self.assertEqual((claim.claim_id, receipt.receipt_id), (effect["claim_id"], effect["receipt_id"]))
        with self.assertRaisesRegex(AgentResultNormalizationError, "claim and receipt"):
            normalize_generic_dag_result(
                payload, context(validation_gate_id=gate.validation_gate_id), effect_claim=claim
            )

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
        claimed = semantic(effects=[{
            "effect_id": "write-change", "effect_type": "write",
            "claim_id": sha("4"), "receipt_id": sha("5"), "result_digest": sha("3"),
        }])
        with self.assertRaisesRegex(AgentResultNormalizationError, "exact effect receipts"):
            normalize_native_client_result(
                {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": claimed},
                context(validation_gate_id=sha("6")),
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

        governed_execution = run("execute")
        verifier_identity = create_agent_execution_identity(
            task_id=plan.task_id, plan_id=plan.plan_id, step_id="verify-effect",
            role="verifier", actor_digest=sha("8"), session_digest=sha("9"),
            assignment_digest=sha("7"), runtime_kind="isolated-role",
        )
        gate = build_validation_gate(
            project_id="project-one", work_item_id="work-one", task_id=plan.task_id,
            task_plan_id=plan.plan_id, worker_step_id=worker_step.step_id,
            effect_id="source-read", effect_type="execute", effect_digest=sha("6"),
            effect_authorization_id=sha("5"),
            worker_execution_identity_id=identity.execution_identity_id,
            worker_actor_digest=identity.actor_digest,
            verifier_execution_identity=verifier_identity,
            subjects=[{"subject_kind": "acceptance-criterion", "subject_digest": sha("4")}],
            checks=[{"check_id": "result-check", "actor_kind": "verifier", "method": "state-check",
                     "expected_result": "passed", "evidence_required": ["state-observation"],
                     "subject_digests": [sha("4")]}],
            policy_revision=sha("2"), source_revision_digest=sha("f"),
            created_at="2026-08-17T11:59:59.000Z",
        )
        governed_context = context(
            task_id=plan.task_id, task_plan_id=plan.plan_id, step_id=worker_step.step_id,
            execution_identity_id=identity.execution_identity_id,
            input_digest=governed_execution.journal.input_digest,
            validation_gate_id=gate.validation_gate_id,
        )
        claim = build_effect_claim(
            project_id="project-one", work_item_id="work-one", task_id=plan.task_id,
            task_plan_id=plan.plan_id, step_id=worker_step.step_id, queue_id="queue-one",
            attempt_id="attempt-one", attempt_number=1,
            execution_identity_id=identity.execution_identity_id, lease_id="lease-one",
            fencing_token=1, effect_id="source-read", effect_type="execute",
            effect_digest=sha("6"), idempotency_key=sha("0"),
            effect_authorization_id=sha("5"), validation_gate=gate,
            host_digest=sha("1"), claimed_at="2026-08-17T12:00:00.000Z",
        )
        receipt = build_effect_receipt(
            claim=claim, outcome="completed", retry_safety="non-replayable",
            result_digest=sha("3"), finished_at="2026-08-17T12:00:00.004Z",
            observed_fencing_token=1,
        )
        governed_semantic = semantic(effects=[{
            "effect_id": "source-read", "effect_type": "execute",
            "claim_id": claim.claim_id, "receipt_id": receipt.receipt_id,
            "result_digest": sha("3"),
        }])
        normalized_governed = normalize_worker_execution(
            governed_execution, governed_context, governed_semantic,
            effect_claims=[claim], effect_receipts=[receipt],
        )
        self.assertEqual(claim.claim_id, normalized_governed.envelope.payload["result"]["effects"][0]["claim_id"])

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

    def test_coordinator_fan_in_completed_and_trace_aggregates_receipts(self) -> None:
        first = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()},
            context(),
        )
        second = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()},
            context(
                step_id="verify-output", execution_identity_id=sha("4"),
                attempt_id="attempt-two", sequence=2,
                started_at="2026-08-17T12:00:00.002Z",
                finished_at="2026-08-17T12:00:00.009Z",
                input_tokens=20, output_tokens=8,
            ),
        )
        fan_in = build_agent_result_fan_in(
            [second, first], expected_step_ids=["inspect-source", "verify-output"],
            coordinator_execution_identity_id=sha("5"), caller_role="coordinator",
        )
        self.assertEqual("completed", fan_in.payload["status"])
        self.assertFalse(fan_in.payload["completion_authorized"])
        self.assertEqual(30, fan_in.payload["receipt_aggregate"]["usage"]["input_tokens"])
        self.assertEqual(fan_in.as_dict(), parse_agent_result_fan_in(fan_in.as_dict()).as_dict())
        trace = build_execution_trace_from_results(
            [first, second], request_id="request-one", client_id="codex-cli",
            intent_digest=sha("6"), context_digest=sha("7"), delegation_mode="native-parallel",
        ).as_dict()
        self.assertEqual(30, trace["token_usage"]["input_tokens"])
        self.assertEqual(13, trace["token_usage"]["output_tokens"])
        self.assertEqual(9, trace["duration_ms"])
        self.assertEqual("completed", trace["status"])

    def test_fan_in_partial_is_not_completed_and_only_coordinator_may_summarize(self) -> None:
        partial = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic(status="partial", missing_step_ids=["verify-output"])},
            context(),
        )
        result = build_agent_result_fan_in(
            [partial], expected_step_ids=["inspect-source", "verify-output"],
            coordinator_execution_identity_id=sha("5"), caller_role="coordinator",
        )
        self.assertEqual("partial", result.payload["status"])
        self.assertEqual(["verify-output"], result.payload["missing_step_ids"])
        with self.assertRaisesRegex(AgentResultFanInError, "only coordinator"):
            build_agent_result_fan_in(
                [partial], expected_step_ids=["inspect-source"],
                coordinator_execution_identity_id=sha("5"), caller_role="worker",
            )

    def test_fan_in_rejects_scope_and_duplicate_attempt_conflicts(self) -> None:
        first = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()}, context()
        )
        other = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()},
            context(project_id="project-two"),
        )
        with self.assertRaisesRegex(AgentResultFanInError, "scope"):
            build_agent_result_fan_in(
                [first, other], expected_step_ids=["inspect-source"],
                coordinator_execution_identity_id=sha("5"), caller_role="coordinator",
            )
        with self.assertRaisesRegex(AgentResultFanInError, "duplicate step attempt"):
            build_agent_result_fan_in(
                [first, first], expected_step_ids=["inspect-source"],
                coordinator_execution_identity_id=sha("5"), caller_role="coordinator",
            )

    def test_fan_in_rejects_tampered_receipt_aggregate(self) -> None:
        result = normalize_native_client_result(
            {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()}, context()
        )
        fan_in = build_agent_result_fan_in(
            [result], expected_step_ids=["inspect-source"],
            coordinator_execution_identity_id=sha("5"), caller_role="coordinator",
        ).as_dict()
        tampered = copy.deepcopy(fan_in)
        tampered["receipt_aggregate"]["usage"]["input_tokens"] += 1
        semantic_payload = {key: value for key, value in tampered.items() if key != "fan_in_digest"}
        import hashlib
        from krcn_core.json_documents import canonical_json_bytes
        tampered["fan_in_digest"] = hashlib.sha256(canonical_json_bytes(semantic_payload)).hexdigest()
        with self.assertRaisesRegex(AgentResultFanInError, "receipt aggregate"):
            parse_agent_result_fan_in(tampered)

    def test_application_and_cli_expose_read_only_result_pipeline(self) -> None:
        native = {"schema_ref": "schemas/native-agent-result.schema.json", "schema_version": 1, "result": semantic()}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".krcn"
            home.mkdir()
            (home / "layout.json").write_bytes(user_home_layout_bytes())
            service = KrcnApplicationService(
                REPO_ROOT, LocalWorkspaceStore(home, OwnershipResolver.from_repository(REPO_ROOT))
            )
            normalized_digests = []
            for client in ("cli", "sdk", "mcp", "codex", "claude", "opencode"):
                response = service.execute(ServiceRequest(
                    client, "result.normalize-native", {"native_result": native, "context": context()}
                ))
                self.assertEqual("ok", response.status)
                normalized_digests.append(response.data["normalized_result"]["normalization_digest"])
            self.assertEqual(1, len(set(normalized_digests)))
            normalized = service.execute(ServiceRequest(
                "cli", "result.normalize-native", {"native_result": native, "context": context()}
            )).data["normalized_result"]
            fan_in = service.execute(ServiceRequest(
                "cli", "result.fan-in",
                {"normalized_results": [normalized], "expected_step_ids": ["inspect-source"],
                 "coordinator_execution_identity_id": sha("5"), "caller_role": "coordinator"},
            ))
            self.assertEqual("completed", fan_in.data["fan_in"]["status"])
            trace = service.execute(ServiceRequest(
                "cli", "result.trace",
                {"normalized_results": [normalized], "request_id": "request-one", "client_id": "codex-cli",
                 "intent_digest": sha("6"), "context_digest": sha("7"), "delegation_mode": "direct"},
            ))
            self.assertEqual("completed", trace.data["execution_trace"]["status"])
            with self.assertRaisesRegex(ApplicationServiceError, "read-only"):
                service.execute(ServiceRequest(
                    "cli", "result.normalize-native", {"native_result": native, "context": context()}, apply=True
                ))
            self.assertEqual([], [path for path in home.rglob("*") if path.name != "layout.json"])
        parser = build_parser()
        for command in ("normalize-native", "fan-in", "trace"):
            parsed = parser.parse_args(["result", command, "--request-file", "result.json"])
            self.assertEqual(command, parsed.result_command)


if __name__ == "__main__":
    unittest.main()
