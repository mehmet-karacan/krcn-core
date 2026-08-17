"""Client-neutral normalization into one envelope and one step receipt."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from .agent_result_envelope import (
    AgentResultEnvelope,
    build_agent_result_envelope,
    parse_agent_result_envelope,
)
from .json_documents import canonical_json_bytes
from .orchestration_worker import WorkerExecution, parse_worker_execution
from .workflow_step_receipt import (
    WorkflowStepReceipt,
    build_workflow_step_receipt,
    parse_workflow_step_receipt,
)


class AgentResultNormalizationError(ValueError):
    """Raised when an adapter result cannot be normalized safely."""


CONTEXT_FIELDS = {
    "correlation_id", "project_id", "work_item_id", "task_id", "task_plan_id",
    "step_id", "queue_id", "execution_identity_id", "role", "route_decision_id",
    "delegation_decision_id", "model_assignment_id", "admission_decision_id",
    "attempt_id", "sequence", "attempt_number", "input_digest",
    "context_snapshot_digest", "source_revision_digest", "validation_gate_id",
    "started_at", "finished_at", "harness_revision", "policy_revision", "client_id",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "cost_microunits", "currency",
}
RESULT_FIELDS = {
    "status", "headline", "findings", "artifacts", "evidence", "effects", "risks",
    "failure", "missing_step_ids", "recommended_next_action", "verification",
}


@dataclass(frozen=True)
class NormalizedAgentResult:
    source_format: str
    envelope: AgentResultEnvelope
    receipt: WorkflowStepReceipt

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_ref": "schemas/agent-result-normalization.schema.json",
            "schema_version": 1,
            "source_format": self.source_format,
            "envelope": self.envelope.as_dict(),
            "receipt": self.receipt.as_dict(),
            "grants_authority": False,
            "normalization_digest": "",
        }
        payload["normalization_digest"] = hashlib.sha256(
            canonical_json_bytes({key: value for key, value in payload.items() if key != "normalization_digest"})
        ).hexdigest()
        return payload


def _object(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise AgentResultNormalizationError(f"{label} fields are invalid")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _semantic(payload: object) -> dict[str, object]:
    data = _object(payload, RESULT_FIELDS, "structured agent result")
    action = _object(
        data["recommended_next_action"],
        {"action_code", "statement", "required_role"},
        "recommended next action",
    )
    verification = _object(
        data["verification"],
        {"required", "validation_gate_id", "verification_id", "covered_worker_step_ids", "verdict"},
        "agent verification",
    )
    data["recommended_next_action"] = action
    data["verification"] = verification
    return data


def parse_native_agent_result(payload: object) -> dict[str, object]:
    data = _object(payload, {"schema_ref", "schema_version", "result"}, "native agent result")
    if data["schema_ref"] != "schemas/native-agent-result.schema.json" or data["schema_version"] != 1:
        raise AgentResultNormalizationError("native agent result contract is invalid")
    data["result"] = _semantic(data["result"])
    return data


def _normalize(
    source_format: str,
    context: Mapping[str, object],
    semantic: Mapping[str, object],
    *,
    receipt_status: str,
    output_digest: str | None,
    failure_category: str | None,
    failure_digest: str | None,
) -> NormalizedAgentResult:
    ctx = _object(context, CONTEXT_FIELDS, "agent result adapter context")
    result = _semantic(semantic)
    action = result["recommended_next_action"]
    verification = result["verification"]
    try:
        envelope = build_agent_result_envelope(
            correlation_id=ctx["correlation_id"], project_id=ctx["project_id"],
            work_item_id=ctx["work_item_id"], task_id=ctx["task_id"],
            task_plan_id=ctx["task_plan_id"], step_id=ctx["step_id"],
            queue_id=ctx["queue_id"], execution_identity_id=ctx["execution_identity_id"],
            role=ctx["role"], route_decision_id=ctx["route_decision_id"],
            delegation_decision_id=ctx["delegation_decision_id"],
            model_assignment_id=ctx["model_assignment_id"],
            admission_decision_id=ctx["admission_decision_id"], status=result["status"],
            headline=result["headline"], findings=result["findings"], artifacts=result["artifacts"],
            evidence=result["evidence"], effects=result["effects"], risks=result["risks"],
            failure=result["failure"], missing_step_ids=result["missing_step_ids"],
            recommended_action_code=action["action_code"],
            recommended_action_statement=action["statement"],
            recommended_action_role=action["required_role"],
            verification_required=verification["required"],
            validation_gate_id=verification["validation_gate_id"],
            verification_id=verification["verification_id"],
            covered_worker_step_ids=verification["covered_worker_step_ids"],
            verdict=verification["verdict"],
        )
        receipt = build_workflow_step_receipt(
            correlation_id=ctx["correlation_id"], project_id=ctx["project_id"],
            work_item_id=ctx["work_item_id"], task_id=ctx["task_id"],
            task_plan_id=ctx["task_plan_id"], step_id=ctx["step_id"], queue_id=ctx["queue_id"],
            attempt_id=ctx["attempt_id"], sequence=ctx["sequence"],
            attempt_number=ctx["attempt_number"], actor_kind="agent", role=ctx["role"],
            execution_identity_id=ctx["execution_identity_id"],
            model_assignment_id=ctx["model_assignment_id"], client_id=ctx["client_id"],
            status=receipt_status, input_digest=ctx["input_digest"], output_digest=output_digest,
            failure_category=failure_category, failure_digest=failure_digest,
            input_tokens=ctx["input_tokens"], output_tokens=ctx["output_tokens"],
            cache_read_tokens=ctx["cache_read_tokens"], cache_write_tokens=ctx["cache_write_tokens"],
            cost_microunits=ctx["cost_microunits"], currency=ctx["currency"],
            harness_revision=ctx["harness_revision"], policy_revision=ctx["policy_revision"],
            source_revision_digest=ctx["source_revision_digest"],
            context_snapshot_digest=ctx["context_snapshot_digest"],
            route_decision_id=ctx["route_decision_id"], validation_gate_id=ctx["validation_gate_id"],
            started_at=ctx["started_at"], finished_at=ctx["finished_at"],
        )
    except (TypeError, ValueError) as exc:
        raise AgentResultNormalizationError("agent result normalization failed") from exc
    return NormalizedAgentResult(source_format, envelope, receipt)


def normalize_native_client_result(
    payload: object, context: Mapping[str, object]
) -> NormalizedAgentResult:
    native = parse_native_agent_result(payload)
    result = native["result"]
    status = result["status"]
    failure = result["failure"] if isinstance(result["failure"], Mapping) else None
    receipt_status = {
        "completed": "completed", "partial": "completed", "failed": "failed",
        "blocked": "denied", "recovery-required": "recovery-required", "abstained": "denied",
    }[status]
    output = hashlib.sha256(canonical_json_bytes(result)).hexdigest() if receipt_status == "completed" else None
    return _normalize(
        "native-client-v1", context, result, receipt_status=receipt_status,
        output_digest=output,
        failure_category=None if failure is None else failure["category"],
        failure_digest=None if failure is None else failure["failure_digest"],
    )


def normalize_worker_execution(
    execution: WorkerExecution | Mapping[str, object],
    context: Mapping[str, object],
    semantic_result: Mapping[str, object],
) -> NormalizedAgentResult:
    try:
        checked = parse_worker_execution(
            execution.as_dict() if isinstance(execution, WorkerExecution) else execution
        )
    except ValueError as exc:
        raise AgentResultNormalizationError("worker execution is invalid") from exc
    ctx = _object(context, CONTEXT_FIELDS, "agent result adapter context")
    if (
        checked.checkpoint.task_id != ctx["task_id"]
        or checked.checkpoint.plan_id != ctx["task_plan_id"]
        or checked.checkpoint.step_id != ctx["step_id"]
        or checked.checkpoint.execution_identity_id != ctx["execution_identity_id"]
        or ctx["role"] != "worker"
    ):
        raise AgentResultNormalizationError("worker execution binding is invalid")
    semantic = _semantic(semantic_result)
    expected_status = "completed" if checked.checkpoint.status == "completed" else "failed"
    if semantic["status"] != expected_status:
        raise AgentResultNormalizationError("worker result status does not match execution")
    # Existing worker v1/v2 lacks generalized claim/receipt fields. Until the
    # Phase 25 ledger exists, completed non-read effects cannot be upgraded.
    if checked.checkpoint.status == "completed" and any(
        effect.effect_type != "read" for effect in checked.journal.effects
    ):
        raise AgentResultNormalizationError("worker mutation result requires effect receipts")
    return _normalize(
        "worker-execution-v2" if checked.execution_identity is not None else "worker-execution-v1",
        ctx, semantic,
        receipt_status=checked.checkpoint.status,
        output_digest=checked.checkpoint.result_digest,
        failure_category="WORKER_FAILED" if checked.checkpoint.status == "failed" else None,
        failure_digest=checked.checkpoint.failure_digest,
    )


def normalize_generic_dag_result(
    payload: object, context: Mapping[str, object]
) -> NormalizedAgentResult:
    expected = {"schema_ref", "schema_version", "status", "task_id", "plan_id", "step_id", "execution_identity_id", "evidence_digest", "grants_authority"}
    data = _object(payload, expected, "generic DAG adapter result")
    if (
        data["schema_ref"] != "schemas/generic-dag-execution-result.schema.json#/$defs/adapterResult"
        or data["schema_version"] != 1 or data["status"] != "completed"
        or data["grants_authority"] is not False
    ):
        raise AgentResultNormalizationError("generic DAG adapter result is invalid")
    ctx = _object(context, CONTEXT_FIELDS, "agent result adapter context")
    if (
        data["task_id"] != ctx["task_id"] or data["plan_id"] != ctx["task_plan_id"]
        or data["step_id"] != ctx["step_id"]
        or data["execution_identity_id"] != ctx["execution_identity_id"]
        or ctx["role"] != "worker"
    ):
        raise AgentResultNormalizationError("generic DAG adapter binding is invalid")
    evidence = data["evidence_digest"]
    semantic = {
        "status": "completed", "headline": "DAG step completed", "findings": [],
        "artifacts": [],
        "evidence": [{"evidence_id": "dag-step-evidence", "evidence_type": "state-observation", "evidence_digest": evidence}],
        "effects": [{"effect_id": "dag-step-read", "effect_type": "read", "claim_id": None, "receipt_id": None, "result_digest": evidence}],
        "risks": [], "failure": None, "missing_step_ids": [],
        "recommended_next_action": {"action_code": "CONTINUE_DAG", "statement": "Continue with dependent steps", "required_role": "coordinator"},
        "verification": {"required": True, "validation_gate_id": ctx["validation_gate_id"], "verification_id": None, "covered_worker_step_ids": [], "verdict": None},
    }
    return _normalize(
        "generic-dag-adapter-v1", ctx, semantic, receipt_status="completed",
        output_digest=evidence, failure_category=None, failure_digest=None,
    )


def parse_normalized_agent_result(payload: object) -> NormalizedAgentResult:
    fields = {"schema_ref", "schema_version", "source_format", "envelope", "receipt", "grants_authority", "normalization_digest"}
    data = _object(payload, fields, "normalized agent result")
    if data["schema_ref"] != "schemas/agent-result-normalization.schema.json" or data["schema_version"] != 1 or data["grants_authority"] is not False:
        raise AgentResultNormalizationError("normalized agent result contract is invalid")
    if data["source_format"] not in {"worker-execution-v1", "worker-execution-v2", "generic-dag-adapter-v1", "native-client-v1"}:
        raise AgentResultNormalizationError("normalized agent result source is invalid")
    envelope = parse_agent_result_envelope(data["envelope"])
    receipt = parse_workflow_step_receipt(data["receipt"])
    if envelope.as_dict()["identity"]["step_id"] != receipt.as_dict()["identity"]["step_id"]:
        raise AgentResultNormalizationError("normalized agent result step binding is invalid")
    digest = hashlib.sha256(canonical_json_bytes({key: value for key, value in data.items() if key != "normalization_digest"})).hexdigest()
    if data["normalization_digest"] != digest:
        raise AgentResultNormalizationError("normalized agent result digest is invalid")
    return NormalizedAgentResult(str(data["source_format"]), envelope, receipt)
