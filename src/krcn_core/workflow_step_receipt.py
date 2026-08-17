"""Append-only, content-free telemetry receipts for one workflow step attempt."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from .json_documents import canonical_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
PORTABLE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ABSOLUTE_PATH = re.compile(r"(?i)(?:[A-Z]:[\\/]|(?:^|\s)/[^\s]+|(?:^|\s)~[\\/])")
SECRET_TEXT = re.compile(
    r"(?i)(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]|"
    r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"
)
ACTOR_KINDS = {"agent", "code", "human"}
ROLES = {"worker", "verifier", "coordinator", "test"}
STATUSES = {"completed", "failed", "denied", "timed-out", "cancelled", "recovery-required"}
CURRENCIES = {"TRY", "USD", "EUR"}


class WorkflowStepReceiptError(ValueError):
    """Raised when a workflow step receipt is unsafe or inconsistent."""


def _strict(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise WorkflowStepReceiptError(f"{label} fields are invalid")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _id(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise WorkflowStepReceiptError(f"{label} is invalid")
    return value


def _sha(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise WorkflowStepReceiptError(f"{label} is invalid")
    return value


def _ref(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not PORTABLE_REF.fullmatch(value)
        or ABSOLUTE_PATH.search(value)
        or SECRET_TEXT.search(value)
    ):
        raise WorkflowStepReceiptError(f"{label} is invalid")
    return value


def _positive(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise WorkflowStepReceiptError(f"{label} is invalid")
    return value


def _nonnegative(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise WorkflowStepReceiptError(f"{label} is invalid")
    return value


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise WorkflowStepReceiptError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise WorkflowStepReceiptError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise WorkflowStepReceiptError(f"{label} must use UTC")
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise WorkflowStepReceiptError(f"{label} is not canonical")
    return parsed


def _identity_digest(payload: Mapping[str, object]) -> str:
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    normalized["identity"]["receipt_id"] = ""
    normalized["receipt_digest"] = ""
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


@dataclass(frozen=True)
class WorkflowStepReceipt:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))

    @property
    def receipt_digest(self) -> str:
        return str(self.payload["receipt_digest"])

    @property
    def status(self) -> str:
        return str(self.payload["outcome"]["status"])


def build_workflow_step_receipt(
    *,
    correlation_id: str,
    project_id: str,
    work_item_id: str,
    task_id: str,
    task_plan_id: str,
    step_id: str,
    attempt_id: str,
    sequence: int,
    attempt_number: int,
    actor_kind: str,
    role: str,
    status: str,
    input_digest: str,
    context_snapshot_digest: str,
    route_decision_id: str,
    started_at: str,
    finished_at: str,
    harness_revision: str,
    policy_revision: str,
    queue_id: str | None = None,
    execution_identity_id: str | None = None,
    model_assignment_id: str | None = None,
    client_id: str | None = None,
    output_digest: str | None = None,
    failure_category: str | None = None,
    failure_digest: str | None = None,
    duration_ms: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_microunits: int = 0,
    currency: str | None = None,
    source_revision_digest: str | None = None,
    validation_gate_id: str | None = None,
) -> WorkflowStepReceipt:
    started = _time(started_at, "receipt started_at")
    finished = _time(finished_at, "receipt finished_at")
    derived_duration = int((finished - started).total_seconds() * 1000)
    if derived_duration < 0:
        raise WorkflowStepReceiptError("receipt time is reversed")
    if duration_ms is not None and duration_ms != derived_duration:
        raise WorkflowStepReceiptError("receipt duration does not match timestamps")
    payload: dict[str, object] = {
        "schema_ref": "schemas/workflow-step-receipt.schema.json",
        "schema_version": 1,
        "identity": {
            "receipt_id": "",
            "correlation_id": correlation_id,
            "project_id": project_id,
            "work_item_id": work_item_id,
            "task_id": task_id,
            "task_plan_id": task_plan_id,
            "step_id": step_id,
            "queue_id": queue_id,
            "attempt_id": attempt_id,
            "sequence": sequence,
            "attempt_number": attempt_number,
        },
        "actor": {
            "actor_kind": actor_kind,
            "role": role,
            "execution_identity_id": execution_identity_id,
            "model_assignment_id": model_assignment_id,
            "client_id": client_id,
        },
        "outcome": {
            "status": status,
            "input_digest": input_digest,
            "output_digest": output_digest,
            "failure_category": failure_category,
            "failure_digest": failure_digest,
        },
        "usage": {
            "duration_ms": derived_duration,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens,
            "cost_microunits": cost_microunits,
            "currency": currency,
        },
        "provenance": {
            "harness_revision": harness_revision,
            "policy_revision": policy_revision,
            "source_revision_digest": source_revision_digest,
            "context_snapshot_digest": context_snapshot_digest,
            "route_decision_id": route_decision_id,
            "validation_gate_id": validation_gate_id,
        },
        "time": {"started_at": started_at, "finished_at": finished_at},
        "safety": {
            "grants_authority": False,
            "contains_raw_payload": False,
            "contains_physical_paths": False,
            "contains_credentials": False,
        },
        "receipt_digest": "",
    }
    digest = _identity_digest(payload)
    payload["identity"]["receipt_id"] = digest
    payload["receipt_digest"] = digest
    return parse_workflow_step_receipt(payload)


def parse_workflow_step_receipt(payload: object) -> WorkflowStepReceipt:
    data = _strict(payload, {"schema_ref", "schema_version", "identity", "actor", "outcome", "usage", "provenance", "time", "safety", "receipt_digest"}, "workflow step receipt")
    if data.get("schema_ref") != "schemas/workflow-step-receipt.schema.json" or data.get("schema_version") != 1:
        raise WorkflowStepReceiptError("workflow step receipt contract is invalid")
    identity = _strict(data.get("identity"), {"receipt_id", "correlation_id", "project_id", "work_item_id", "task_id", "task_plan_id", "step_id", "queue_id", "attempt_id", "sequence", "attempt_number"}, "receipt identity")
    _sha(identity.get("receipt_id"), "receipt id")
    for field in ("correlation_id", "project_id", "work_item_id", "task_id", "step_id", "attempt_id"):
        _id(identity.get(field), field.replace("_", " "))
    _id(identity.get("queue_id"), "queue id", nullable=True)
    _sha(identity.get("task_plan_id"), "task plan id")
    _positive(identity.get("sequence"), "receipt sequence")
    _positive(identity.get("attempt_number"), "receipt attempt number")

    actor = _strict(data.get("actor"), {"actor_kind", "role", "execution_identity_id", "model_assignment_id", "client_id"}, "receipt actor")
    if actor.get("actor_kind") not in ACTOR_KINDS or actor.get("role") not in ROLES:
        raise WorkflowStepReceiptError("receipt actor classification is invalid")
    execution_identity_id = _sha(actor.get("execution_identity_id"), "execution identity id", nullable=True)
    _id(actor.get("model_assignment_id"), "model assignment id", nullable=True)
    _id(actor.get("client_id"), "client id", nullable=True)
    if actor.get("actor_kind") == "agent" and execution_identity_id is None:
        raise WorkflowStepReceiptError("agent receipt lacks execution identity")

    outcome = _strict(data.get("outcome"), {"status", "input_digest", "output_digest", "failure_category", "failure_digest"}, "receipt outcome")
    status = outcome.get("status")
    if status not in STATUSES:
        raise WorkflowStepReceiptError("receipt outcome status is invalid")
    _sha(outcome.get("input_digest"), "receipt input digest")
    output_digest = _sha(outcome.get("output_digest"), "receipt output digest", nullable=True)
    failure_category = outcome.get("failure_category")
    failure_digest = _sha(outcome.get("failure_digest"), "receipt failure digest", nullable=True)
    if status == "completed":
        if output_digest is None or failure_category is not None or failure_digest is not None:
            raise WorkflowStepReceiptError("completed receipt outcome is invalid")
    else:
        if not isinstance(failure_category, str) or not CODE.fullmatch(failure_category) or failure_digest is None:
            raise WorkflowStepReceiptError("terminal failure receipt is incomplete")

    usage = _strict(data.get("usage"), {"duration_ms", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_microunits", "currency"}, "receipt usage")
    for field in ("duration_ms", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_microunits"):
        _nonnegative(usage.get(field), field.replace("_", " "))
    currency = usage.get("currency")
    if (usage["cost_microunits"] == 0 and currency is not None) or (usage["cost_microunits"] > 0 and currency not in CURRENCIES):
        raise WorkflowStepReceiptError("receipt cost currency is invalid")

    provenance = _strict(data.get("provenance"), {"harness_revision", "policy_revision", "source_revision_digest", "context_snapshot_digest", "route_decision_id", "validation_gate_id"}, "receipt provenance")
    _ref(provenance.get("harness_revision"), "harness revision")
    _ref(provenance.get("policy_revision"), "policy revision")
    _sha(provenance.get("source_revision_digest"), "source revision digest", nullable=True)
    _sha(provenance.get("context_snapshot_digest"), "context snapshot digest")
    _sha(provenance.get("route_decision_id"), "route decision id")
    _sha(provenance.get("validation_gate_id"), "validation gate id", nullable=True)

    times = _strict(data.get("time"), {"started_at", "finished_at"}, "receipt time")
    started = _time(times.get("started_at"), "receipt started_at")
    finished = _time(times.get("finished_at"), "receipt finished_at")
    if finished < started or int((finished - started).total_seconds() * 1000) != usage["duration_ms"]:
        raise WorkflowStepReceiptError("receipt duration is invalid")

    safety = _strict(data.get("safety"), {"grants_authority", "contains_raw_payload", "contains_physical_paths", "contains_credentials"}, "receipt safety")
    if any(safety.get(field) is not False for field in safety):
        raise WorkflowStepReceiptError("receipt safety assertions are invalid")
    digest = _identity_digest(data)
    if identity["receipt_id"] != digest or data.get("receipt_digest") != digest:
        raise WorkflowStepReceiptError("workflow step receipt digest is invalid")
    return WorkflowStepReceipt(data)


def aggregate_step_receipts(receipts: list[WorkflowStepReceipt]) -> dict[str, object]:
    if not receipts:
        raise WorkflowStepReceiptError("receipt aggregation requires input")
    checked = [parse_workflow_step_receipt(item.as_dict()) for item in receipts]
    correlation_ids = {item.payload["identity"]["correlation_id"] for item in checked}
    currencies = {item.payload["usage"]["currency"] for item in checked if item.payload["usage"]["currency"] is not None}
    if len(correlation_ids) != 1 or len(currencies) > 1:
        raise WorkflowStepReceiptError("receipt aggregation scope is invalid")
    receipt_ids = [str(item.payload["identity"]["receipt_id"]) for item in checked]
    if len(set(receipt_ids)) != len(receipt_ids):
        raise WorkflowStepReceiptError("receipt aggregation contains duplicates")
    usage_fields = ("duration_ms", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_microunits")
    usage = {field: sum(int(item.payload["usage"][field]) for item in checked) for field in usage_fields}
    usage["currency"] = next(iter(currencies), None)
    payload: dict[str, object] = {
        "correlation_id": next(iter(correlation_ids)),
        "receipt_ids": sorted(receipt_ids),
        "receipt_count": len(checked),
        "status_counts": {
            status: sum(1 for item in checked if item.status == status)
            for status in sorted(STATUSES)
            if any(item.status == status for item in checked)
        },
        "usage": usage,
        "aggregation_digest": "",
        "grants_authority": False,
    }
    payload["aggregation_digest"] = hashlib.sha256(
        canonical_json_bytes({key: value for key, value in payload.items() if key != "aggregation_digest"})
    ).hexdigest()
    return parse_step_receipt_aggregate(payload)


def parse_step_receipt_aggregate(payload: object) -> dict[str, object]:
    data = _strict(
        payload,
        {"correlation_id", "receipt_ids", "receipt_count", "status_counts", "usage", "aggregation_digest", "grants_authority"},
        "receipt aggregate",
    )
    _id(data.get("correlation_id"), "aggregate correlation id")
    receipt_ids = data.get("receipt_ids")
    if (
        not isinstance(receipt_ids, list)
        or not receipt_ids
        or receipt_ids != sorted(receipt_ids)
        or len(set(receipt_ids)) != len(receipt_ids)
        or any(_sha(item, "aggregate receipt id") is None for item in receipt_ids)
        or data.get("receipt_count") != len(receipt_ids)
    ):
        raise WorkflowStepReceiptError("receipt aggregate identities are invalid")
    counts = data.get("status_counts")
    if (
        not isinstance(counts, Mapping)
        or not counts
        or any(key not in STATUSES or _positive(value, "aggregate status count") < 1 for key, value in counts.items())
        or sum(int(value) for value in counts.values()) != len(receipt_ids)
    ):
        raise WorkflowStepReceiptError("receipt aggregate status counts are invalid")
    usage = _strict(data.get("usage"), {"duration_ms", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_microunits", "currency"}, "receipt aggregate usage")
    for field in ("duration_ms", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_microunits"):
        _nonnegative(usage.get(field), "aggregate " + field.replace("_", " "))
    currency = usage.get("currency")
    if (usage["cost_microunits"] == 0 and currency is not None) or (usage["cost_microunits"] > 0 and currency not in CURRENCIES):
        raise WorkflowStepReceiptError("receipt aggregate currency is invalid")
    if data.get("grants_authority") is not False:
        raise WorkflowStepReceiptError("receipt aggregate cannot grant authority")
    expected = hashlib.sha256(
        canonical_json_bytes({key: value for key, value in data.items() if key != "aggregation_digest"})
    ).hexdigest()
    if data.get("aggregation_digest") != expected:
        raise WorkflowStepReceiptError("receipt aggregate digest is invalid")
    return data
