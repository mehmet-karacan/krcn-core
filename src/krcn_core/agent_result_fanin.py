"""Coordinator-only fan-in and receipt-derived execution trace aggregation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .agent_result_normalizer import NormalizedAgentResult, parse_normalized_agent_result
from .execution_observability import ExecutionTrace, build_execution_trace
from .json_documents import canonical_json_bytes
from .workflow_step_receipt import aggregate_step_receipts, parse_step_receipt_aggregate


SHA256 = re.compile(r"^[a-f0-9]{64}$")


class AgentResultFanInError(ValueError):
    """Raised when child results cannot be safely joined."""


@dataclass(frozen=True)
class AgentResultFanIn:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))


def _digest(payload: Mapping[str, object]) -> str:
    semantic = {key: value for key, value in payload.items() if key != "fan_in_digest"}
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def _checked(results: Sequence[NormalizedAgentResult | Mapping[str, object]]) -> list[NormalizedAgentResult]:
    if not results:
        raise AgentResultFanInError("fan-in requires at least one normalized result")
    checked = []
    for item in results:
        try:
            checked.append(
                parse_normalized_agent_result(item.as_dict() if isinstance(item, NormalizedAgentResult) else item)
            )
        except ValueError as exc:
            raise AgentResultFanInError("fan-in child result is invalid") from exc
    return checked


def build_agent_result_fan_in(
    results: Sequence[NormalizedAgentResult | Mapping[str, object]],
    *,
    expected_step_ids: Sequence[str],
    coordinator_execution_identity_id: str,
    caller_role: str,
) -> AgentResultFanIn:
    if caller_role != "coordinator":
        raise AgentResultFanInError("only coordinator may build a final fan-in summary")
    if not isinstance(coordinator_execution_identity_id, str) or not SHA256.fullmatch(coordinator_execution_identity_id):
        raise AgentResultFanInError("coordinator execution identity is invalid")
    expected = tuple(sorted(expected_step_ids))
    if not expected or len(set(expected)) != len(expected):
        raise AgentResultFanInError("expected fan-in steps are invalid")
    checked = _checked(results)
    envelopes = [item.envelope.as_dict() for item in checked]
    receipts = [item.receipt.as_dict() for item in checked]
    first_identity = envelopes[0]["identity"]
    scope = tuple(first_identity[key] for key in ("correlation_id", "project_id", "work_item_id", "task_id", "task_plan_id"))
    seen_attempts: set[tuple[str, str]] = set()
    latest: dict[str, tuple[int, dict[str, object], dict[str, object]]] = {}
    for envelope, receipt in zip(envelopes, receipts, strict=True):
        identity = envelope["identity"]
        receipt_identity = receipt["identity"]
        if tuple(identity[key] for key in ("correlation_id", "project_id", "work_item_id", "task_id", "task_plan_id")) != scope:
            raise AgentResultFanInError("fan-in result scope is inconsistent")
        if any(identity[key] != receipt_identity[key] for key in ("correlation_id", "project_id", "work_item_id", "task_id", "task_plan_id", "step_id")) or identity["execution_identity_id"] != receipt["actor"]["execution_identity_id"]:
            raise AgentResultFanInError("fan-in envelope and receipt binding is inconsistent")
        slot = (str(identity["step_id"]), str(receipt_identity["attempt_id"]))
        if slot in seen_attempts:
            raise AgentResultFanInError("fan-in contains a duplicate step attempt")
        seen_attempts.add(slot)
        attempt = int(receipt_identity["attempt_number"])
        if identity["step_id"] not in latest or attempt > latest[str(identity["step_id"])][0]:
            latest[str(identity["step_id"])] = (attempt, envelope, receipt)
    unexpected = sorted(set(latest) - set(expected))
    if unexpected:
        raise AgentResultFanInError("fan-in contains unexpected steps")
    missing = sorted(set(expected) - set(latest))
    completed = sorted(step for step, (_, env, _) in latest.items() if env["result"]["status"] == "completed")
    failed = sorted(step for step, (_, env, _) in latest.items() if env["result"]["status"] in {"failed", "blocked", "recovery-required"})
    statuses = {env["result"]["status"] for _, env, _ in latest.values()}
    if "recovery-required" in statuses:
        status = "recovery-required"
    elif "blocked" in statuses and not completed:
        status = "blocked"
    elif missing or "partial" in statuses or (failed and completed):
        status = "partial"
    elif failed:
        status = "failed"
    else:
        status = "completed"
    aggregate = aggregate_step_receipts([item.receipt for item in checked])
    evidence_digest = hashlib.sha256(
        canonical_json_bytes(
            sorted(
                evidence["evidence_digest"]
                for envelope in envelopes
                for evidence in envelope["result"]["evidence"]
            )
        )
    ).hexdigest()
    headline = {
        "completed": "All expected workflow steps completed",
        "partial": "Workflow produced a partial result",
        "failed": "Workflow steps failed",
        "blocked": "Workflow is blocked",
        "recovery-required": "Workflow requires reconciliation",
    }[status]
    payload: dict[str, object] = {
        "schema_ref": "schemas/agent-result-fan-in.schema.json",
        "schema_version": 1,
        "correlation_id": scope[0], "project_id": scope[1], "work_item_id": scope[2],
        "task_id": scope[3], "task_plan_id": scope[4],
        "coordinator_execution_identity_id": coordinator_execution_identity_id,
        "status": status, "headline": headline,
        "expected_step_ids": list(expected), "completed_step_ids": completed,
        "missing_step_ids": missing, "failed_step_ids": failed,
        "envelope_ids": sorted(env["identity"]["envelope_id"] for env in envelopes),
        "envelope_digests": sorted(env["envelope_digest"] for env in envelopes),
        "receipt_digests": sorted(receipt["receipt_digest"] for receipt in receipts),
        "evidence_digest": evidence_digest,
        "receipt_aggregate": aggregate,
        "completion_authorized": False,
        "grants_authority": False,
        "fan_in_digest": "",
    }
    payload["fan_in_digest"] = _digest(payload)
    return parse_agent_result_fan_in(payload)


def parse_agent_result_fan_in(payload: object) -> AgentResultFanIn:
    fields = {"schema_ref", "schema_version", "correlation_id", "project_id", "work_item_id", "task_id", "task_plan_id", "coordinator_execution_identity_id", "status", "headline", "expected_step_ids", "completed_step_ids", "missing_step_ids", "failed_step_ids", "envelope_ids", "envelope_digests", "receipt_digests", "evidence_digest", "receipt_aggregate", "completion_authorized", "grants_authority", "fan_in_digest"}
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise AgentResultFanInError("agent result fan-in fields are invalid")
    data = json.loads(json.dumps(payload, ensure_ascii=False))
    if data["schema_ref"] != "schemas/agent-result-fan-in.schema.json" or data["schema_version"] != 1 or data["completion_authorized"] is not False or data["grants_authority"] is not False:
        raise AgentResultFanInError("agent result fan-in contract is invalid")
    for field in ("task_plan_id", "coordinator_execution_identity_id", "evidence_digest", "fan_in_digest"):
        if not isinstance(data[field], str) or not SHA256.fullmatch(data[field]):
            raise AgentResultFanInError("agent result fan-in digest is invalid")
    if data["fan_in_digest"] != _digest(data):
        raise AgentResultFanInError("agent result fan-in was tampered")
    try:
        parse_step_receipt_aggregate(data["receipt_aggregate"])
    except ValueError as exc:
        raise AgentResultFanInError("agent result fan-in receipt aggregate is invalid") from exc
    for field in ("expected_step_ids", "completed_step_ids", "missing_step_ids", "failed_step_ids"):
        values = data[field]
        if not isinstance(values, list) or values != sorted(values) or len(set(values)) != len(values) or any(not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,127}", item) for item in values):
            raise AgentResultFanInError("agent result fan-in step identities are invalid")
    projected = set(data["completed_step_ids"]) | set(data["missing_step_ids"]) | set(data["failed_step_ids"])
    if not projected.issubset(set(data["expected_step_ids"])):
        raise AgentResultFanInError("agent result fan-in step projection is invalid")
    if data["status"] == "completed" and (data["missing_step_ids"] or data["failed_step_ids"]):
        raise AgentResultFanInError("completed fan-in cannot have missing or failed steps")
    return AgentResultFanIn(data)


def build_execution_trace_from_results(
    results: Sequence[NormalizedAgentResult | Mapping[str, object]],
    *,
    request_id: str,
    client_id: str,
    intent_digest: str,
    context_digest: str,
    delegation_mode: str,
    approval_envelope_id: str | None = None,
) -> ExecutionTrace:
    checked = _checked(results)
    envelopes = [item.envelope.as_dict() for item in checked]
    receipts = [item.receipt.as_dict() for item in checked]
    aggregate = aggregate_step_receipts([item.receipt for item in checked])
    starts = sorted(item["time"]["started_at"] for item in receipts)
    ends = sorted(item["time"]["finished_at"] for item in receipts)
    statuses = {item.envelope.status for item in checked}
    status = "completed" if statuses == {"completed"} else (
        "recovery-required" if "recovery-required" in statuses else "partially-completed"
    )
    first = envelopes[0]
    identity = first["identity"]
    currencies = {item["usage"]["currency"] for item in receipts if item["usage"]["cost_microunits"] > 0}
    estimated_cost = None
    aggregate_usage = aggregate["usage"]
    if aggregate_usage["cost_microunits"] > 0:
        if len(currencies) != 1:
            raise AgentResultFanInError("receipt currencies cannot be aggregated")
        estimated_cost = {"amount_microunits": aggregate_usage["cost_microunits"], "currency": next(iter(currencies))}
    evidence_digest = hashlib.sha256(canonical_json_bytes(sorted(item["envelope_digest"] for item in envelopes))).hexdigest()
    try:
        return build_execution_trace(
            correlation_id=identity["correlation_id"], request_id=request_id, client_id=client_id,
            project_id=identity["project_id"], work_item_id=identity["work_item_id"],
            intent_digest=intent_digest, context_digest=context_digest, plan_id=identity["task_plan_id"],
            route_decision_id=first["decision_bindings"]["route_decision_id"],
            approval_envelope_id=approval_envelope_id, delegation_mode=delegation_mode,
            model_assignment_ids=sorted({item["actor"]["model_assignment_id"] for item in receipts if item["actor"]["model_assignment_id"] is not None}),
            queue_ids=sorted({item["identity"]["queue_id"] for item in receipts if item["identity"]["queue_id"] is not None}),
            agent_execution_ids=sorted({item["identity"]["execution_identity_id"] for item in envelopes}),
            evidence_digest=evidence_digest, status=status, started_at=starts[0], ended_at=ends[-1],
            token_usage={key: aggregate_usage[key] for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")},
            estimated_cost=estimated_cost,
            retry_count=len(receipts) - len({item["identity"]["step_id"] for item in receipts}),
            cache_hit=aggregate_usage["cache_read_tokens"] > 0,
            failure_code=None if status == "completed" else "partial-result",
        )
    except ValueError as exc:
        raise AgentResultFanInError("receipt-derived execution trace is invalid") from exc
