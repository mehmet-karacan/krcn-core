"""Append-only runtime persistence for authority-free adaptive route decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .adaptive_routing import (
    AdaptiveRoutingPolicy,
    RouteDecision,
    parse_route_decision,
)
from .json_documents import canonical_json_bytes
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .mutation_gate import MutationAuthorization


class AdaptiveRoutingStoreError(ValueError):
    """Raised when a route decision record is stale, conflicting, or unsafe."""


def _digest(payload: Mapping[str, object]) -> str:
    identity = {key: value for key, value in payload.items() if key != "record_digest"}
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AdaptiveRoutingStoreError("route decision recorded_at is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AdaptiveRoutingStoreError(
            "route decision recorded_at is invalid"
        ) from exc
    if parsed.utcoffset() is None or parsed.isoformat().replace("+00:00", "Z") != value:
        raise AdaptiveRoutingStoreError("route decision recorded_at is not canonical")
    return value


def parse_route_decision_record(
    payload: object,
    policy: AdaptiveRoutingPolicy,
) -> dict[str, object]:
    fields = {
        "schema_ref",
        "schema_version",
        "route_decision_record_id",
        "project_id",
        "work_item_id",
        "recorded_at",
        "decision",
        "append_only",
        "grants_authority",
        "record_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise AdaptiveRoutingStoreError("route decision record fields are invalid")
    data = json.loads(json.dumps(payload, ensure_ascii=False))
    try:
        decision = parse_route_decision(data.get("decision"), policy)
    except ValueError as exc:
        raise AdaptiveRoutingStoreError("stored route decision is invalid") from exc
    decision_payload = decision.as_dict()
    record_id = "route-" + decision.decision_digest
    bindings = decision_payload["bindings"]
    if (
        data.get("schema_ref") != "schemas/route-decision-record.schema.json"
        or data.get("schema_version") != 1
        or data.get("route_decision_record_id") != record_id
        or data.get("project_id") != bindings["project_id"]
        or data.get("work_item_id") != bindings["work_item_id"]
        or data.get("append_only") is not True
        or data.get("grants_authority") is not False
        or data.get("record_digest") != _digest(data)
    ):
        raise AdaptiveRoutingStoreError("route decision record contract is invalid")
    _timestamp(data.get("recorded_at"))
    return data


@dataclass(frozen=True)
class RouteDecisionRecordPlan:
    record: Mapping[str, object]
    write_plan: RecordWritePlan | None
    no_op: bool
    plan_id: str

    @property
    def effect_plans(self):
        return () if self.write_plan is None else (self.write_plan.mutation,)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/route-decision-record-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "route_decision_record_id": self.record["route_decision_record_id"],
            "route_decision_id": self.record["decision"]["route_decision_id"],
            "project_id": self.record["project_id"],
            "work_item_id": self.record["work_item_id"],
            "record_digest": self.record["record_digest"],
            "no_op": self.no_op,
            "append_only": True,
            "grants_authority": False,
            "effects": [item.as_dict() for item in self.effect_plans],
        }


def prepare_route_decision_record(
    store: LocalWorkspaceStore,
    policy: AdaptiveRoutingPolicy,
    decision: RouteDecision,
    *,
    recorded_at: str,
) -> RouteDecisionRecordPlan:
    checked = parse_route_decision(decision.as_dict(), policy)
    decision_payload = checked.as_dict()
    bindings = decision_payload["bindings"]
    record_id = "route-" + checked.decision_digest
    record: dict[str, object] = {
        "schema_ref": "schemas/route-decision-record.schema.json",
        "schema_version": 1,
        "route_decision_record_id": record_id,
        "project_id": bindings["project_id"],
        "work_item_id": bindings["work_item_id"],
        "recorded_at": _timestamp(recorded_at),
        "decision": decision_payload,
        "append_only": True,
        "grants_authority": False,
        "record_digest": "",
    }
    record["record_digest"] = _digest(record)
    record = parse_route_decision_record(record, policy)
    current = store.read("route-decisions", record_id)
    if current is not None:
        existing = parse_route_decision_record(current.payload, policy)
        if existing["decision"] != record["decision"]:
            raise AdaptiveRoutingStoreError("route decision record conflicts")
        return RouteDecisionRecordPlan(
            existing,
            None,
            True,
            str(existing["record_digest"]),
        )
    write_plan = store.prepare_put(
        "route-decisions",
        record_id,
        record,
        expected_revision=0,
        project_id=bindings["project_id"],
    )
    if write_plan.mutation.ownership != "runtime" or write_plan.mutation.approval_required:
        raise AdaptiveRoutingStoreError("route decision record must stay in runtime")
    plan_id = hashlib.sha256(
        canonical_json_bytes(
            {
                "record_digest": record["record_digest"],
                "mutation_plan_id": write_plan.mutation.plan_id,
            }
        )
    ).hexdigest()
    return RouteDecisionRecordPlan(record, write_plan, False, plan_id)


def apply_route_decision_record(
    store: LocalWorkspaceStore,
    policy: AdaptiveRoutingPolicy,
    plan: RouteDecisionRecordPlan,
    authorizations: Mapping[str, MutationAuthorization],
    *,
    expected_plan_id: str,
) -> dict[str, object]:
    if expected_plan_id != plan.plan_id:
        raise AdaptiveRoutingStoreError("route decision exact plan changed")
    if plan.no_op:
        return {
            "status": "current",
            "record": dict(plan.record),
            "persisted": True,
            "no_op": True,
        }
    if plan.write_plan is None:
        raise AdaptiveRoutingStoreError("route decision write plan is missing")
    authorization = authorizations.get(plan.write_plan.mutation.plan_id)
    if authorization is None:
        raise AdaptiveRoutingStoreError("route decision authorization is missing")
    stored = store.apply_put(plan.write_plan, authorization)
    record = parse_route_decision_record(stored.payload, policy)
    return {
        "status": "recorded",
        "record": record,
        "persisted": True,
        "no_op": False,
    }
