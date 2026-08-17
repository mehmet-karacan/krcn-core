"""Append-only persistence for verified workflow step receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from .json_documents import canonical_json_bytes
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .mutation_gate import MutationAuthorization
from .workflow_step_receipt import (
    WorkflowStepReceipt,
    WorkflowStepReceiptError,
    parse_workflow_step_receipt,
)


class WorkflowStepReceiptStoreError(ValueError):
    """Raised when receipt persistence is stale, conflicting, or unsafe."""


def _digest(payload: Mapping[str, object], omitted: str) -> str:
    semantic = {key: value for key, value in payload.items() if key != omitted}
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def _slot_digest(receipt: Mapping[str, object]) -> str:
    identity = receipt["identity"]
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "correlation_id": identity["correlation_id"],
                "project_id": identity["project_id"],
                "work_item_id": identity["work_item_id"],
                "task_id": identity["task_id"],
                "task_plan_id": identity["task_plan_id"],
                "step_id": identity["step_id"],
                "attempt_id": identity["attempt_id"],
                "attempt_number": identity["attempt_number"],
            }
        )
    ).hexdigest()


def parse_workflow_step_receipt_record(payload: object) -> dict[str, object]:
    fields = {
        "schema_ref",
        "schema_version",
        "workflow_step_receipt_record_id",
        "project_id",
        "work_item_id",
        "step_id",
        "attempt_id",
        "receipt",
        "append_only",
        "grants_authority",
        "record_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise WorkflowStepReceiptStoreError("workflow step receipt record fields are invalid")
    data = json.loads(json.dumps(payload, ensure_ascii=False))
    try:
        receipt = parse_workflow_step_receipt(data.get("receipt")).as_dict()
    except WorkflowStepReceiptError as exc:
        raise WorkflowStepReceiptStoreError("stored workflow step receipt is invalid") from exc
    identity = receipt["identity"]
    record_id = "step-receipt-" + _slot_digest(receipt)
    if (
        data.get("schema_ref") != "schemas/workflow-step-receipt-record.schema.json"
        or data.get("schema_version") != 1
        or data.get("workflow_step_receipt_record_id") != record_id
        or data.get("project_id") != identity["project_id"]
        or data.get("work_item_id") != identity["work_item_id"]
        or data.get("step_id") != identity["step_id"]
        or data.get("attempt_id") != identity["attempt_id"]
        or data.get("receipt") != receipt
        or data.get("append_only") is not True
        or data.get("grants_authority") is not False
        or data.get("record_digest") != _digest(data, "record_digest")
    ):
        raise WorkflowStepReceiptStoreError("workflow step receipt record contract is invalid")
    return data


@dataclass(frozen=True)
class WorkflowStepReceiptRecordPlan:
    record: Mapping[str, object]
    write_plan: RecordWritePlan | None
    no_op: bool
    plan_id: str

    @property
    def effect_plans(self):
        return () if self.write_plan is None else (self.write_plan.mutation,)

    def public_summary(self) -> dict[str, object]:
        receipt = self.record["receipt"]
        return {
            "schema_ref": "schemas/workflow-step-receipt-record-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "workflow_step_receipt_record_id": self.record[
                "workflow_step_receipt_record_id"
            ],
            "receipt_digest": receipt["receipt_digest"],
            "project_id": self.record["project_id"],
            "work_item_id": self.record["work_item_id"],
            "step_id": self.record["step_id"],
            "attempt_id": self.record["attempt_id"],
            "record_digest": self.record["record_digest"],
            "no_op": self.no_op,
            "append_only": True,
            "grants_authority": False,
            "effects": [item.as_dict() for item in self.effect_plans],
        }


def prepare_workflow_step_receipt_record(
    store: LocalWorkspaceStore,
    receipt: WorkflowStepReceipt | Mapping[str, object],
) -> WorkflowStepReceiptRecordPlan:
    candidate = receipt.as_dict() if isinstance(receipt, WorkflowStepReceipt) else receipt
    try:
        checked = parse_workflow_step_receipt(candidate).as_dict()
    except WorkflowStepReceiptError as exc:
        raise WorkflowStepReceiptStoreError("workflow step receipt is invalid") from exc
    identity = checked["identity"]
    record_id = "step-receipt-" + _slot_digest(checked)
    record: dict[str, object] = {
        "schema_ref": "schemas/workflow-step-receipt-record.schema.json",
        "schema_version": 1,
        "workflow_step_receipt_record_id": record_id,
        "project_id": identity["project_id"],
        "work_item_id": identity["work_item_id"],
        "step_id": identity["step_id"],
        "attempt_id": identity["attempt_id"],
        "receipt": checked,
        "append_only": True,
        "grants_authority": False,
        "record_digest": "",
    }
    record["record_digest"] = _digest(record, "record_digest")
    record = parse_workflow_step_receipt_record(record)
    current = store.read("workflow-step-receipts", record_id)
    if current is not None:
        existing = parse_workflow_step_receipt_record(current.payload)
        if existing["receipt"] != record["receipt"]:
            raise WorkflowStepReceiptStoreError(
                "workflow step attempt already has a conflicting receipt"
            )
        return WorkflowStepReceiptRecordPlan(
            existing, None, True, str(existing["record_digest"])
        )
    write_plan = store.prepare_put(
        "workflow-step-receipts",
        record_id,
        record,
        expected_revision=0,
        project_id=str(identity["project_id"]),
    )
    if write_plan.mutation.ownership != "runtime" or write_plan.mutation.approval_required:
        raise WorkflowStepReceiptStoreError("workflow step receipt must stay in runtime")
    plan_id = hashlib.sha256(
        canonical_json_bytes(
            {
                "record_digest": record["record_digest"],
                "mutation_plan_id": write_plan.mutation.plan_id,
            }
        )
    ).hexdigest()
    return WorkflowStepReceiptRecordPlan(record, write_plan, False, plan_id)


def apply_workflow_step_receipt_record(
    store: LocalWorkspaceStore,
    plan: WorkflowStepReceiptRecordPlan,
    authorizations: Mapping[str, MutationAuthorization],
    *,
    expected_plan_id: str,
) -> dict[str, object]:
    if expected_plan_id != plan.plan_id:
        raise WorkflowStepReceiptStoreError("workflow step receipt exact plan changed")
    if plan.no_op:
        return {"status": "current", "record": dict(plan.record), "no_op": True}
    if plan.write_plan is None:
        raise WorkflowStepReceiptStoreError("workflow step receipt write plan is missing")
    # Rebuild the slot view immediately before the atomic record write. The
    # record id is slot-derived, so a concurrent conflicting writer shares the
    # same LocalWorkspaceStore lock and stale revision boundary.
    authorization = authorizations.get(plan.write_plan.mutation.plan_id)
    if authorization is None:
        raise WorkflowStepReceiptStoreError("workflow step receipt authorization is missing")
    stored = store.apply_put(plan.write_plan, authorization)
    record = parse_workflow_step_receipt_record(stored.payload)
    return {"status": "recorded", "record": record, "no_op": False}

