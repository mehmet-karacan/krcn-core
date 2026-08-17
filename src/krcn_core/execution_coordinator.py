"""Compose reviewed execution services under one immutable root plan."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .adaptive_routing import (
    AdaptiveRoutingPolicy,
    RouteRequest,
    compare_shadow_route,
    decide_route,
    parse_route_request,
)
from .continuity import (
    ContinuitySnapshot,
    FinalizedHandoff,
    parse_continuity_snapshot,
    parse_finalized_handoff,
)
from .delegation_policy import DelegationDecision
from .execution_observability import (
    ExecutionTrace,
    StatusProjection,
    build_execution_trace,
    parse_execution_trace,
    parse_status_projection,
    project_execution_status,
)
from .information_records import canonical_json
from .orchestration_intent import TaskIntent, parse_task_intent
from .orchestration_plan import TaskPlan, parse_task_plan


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
COORDINATOR_EXCEPTIONS = {"general-chat", "status", "exact-lookup"}
ROUTES = {"coordinator-response", "delegated-dag", "blocked"}
PLAN_STATUSES = {"ready", "awaiting-approval", "blocked"}


class ExecutionCoordinatorError(ValueError):
    """Raised when reviewed execution stages cannot be composed safely."""


@dataclass(frozen=True)
class ExecutionCoordinationPlan:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)

    @property
    def plan_id(self) -> str:
        return str(self.payload["plan_id"])

    @property
    def route(self) -> str:
        return str(self.payload["route"])


@dataclass(frozen=True)
class ExecutionCoordinationResult:
    payload: Mapping[str, object]
    trace: ExecutionTrace
    status: StatusProjection

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


@dataclass(frozen=True)
class ExecutionCoordinatorAdapters:
    """Existing services supplied to the thin coordinator facade."""

    dag_dispatcher: Callable[[str], Mapping[str, object]]
    continuity_finalizer: Callable[
        [ExecutionCoordinationPlan, Mapping[str, object]],
        tuple[ContinuitySnapshot, FinalizedHandoff],
    ]


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _identifier(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ExecutionCoordinatorError(f"{label} is invalid")
    return value


def _sha256(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ExecutionCoordinatorError(f"{label} is invalid")
    return value


def _identifiers(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ExecutionCoordinatorError(f"{label} must be a list")
    result = tuple(_identifier(value, f"{label} entry") for value in values)
    if len(set(result)) != len(result):
        raise ExecutionCoordinatorError(f"{label} must not contain duplicates")
    return tuple(sorted(str(value) for value in result))


def _request_digest(request_text: object) -> str:
    if not isinstance(request_text, str):
        raise ExecutionCoordinatorError("request text must be text")
    normalized = unicodedata.normalize("NFC", request_text).strip()
    if not normalized:
        raise ExecutionCoordinatorError("request text must not be empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_delegation(decision: DelegationDecision) -> DelegationDecision:
    try:
        payload = decision.as_dict()
    except AttributeError as exc:
        raise ExecutionCoordinatorError("delegation decision is invalid") from exc
    expected = {
        "schema_ref",
        "schema_version",
        "session_id",
        "client_id",
        "work_class",
        "project_matched",
        "delegation_required",
        "selected_mode",
        "execution_allowed",
        "parallel_preferred",
        "coordinator_only",
        "decision_basis",
        "profile_digest",
        "policy_digest",
        "decision_digest",
        "client_declaration_grants_authority",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ExecutionCoordinatorError("delegation decision fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/delegation-decision.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("client_declaration_grants_authority") is not False
        or not isinstance(payload.get("execution_allowed"), bool)
        or not isinstance(payload.get("delegation_required"), bool)
        or not isinstance(payload.get("coordinator_only"), bool)
    ):
        raise ExecutionCoordinatorError("delegation decision contract is invalid")
    for field in ("profile_digest", "policy_digest", "decision_digest"):
        _sha256(payload.get(field), f"delegation {field}")
    return decision


def prepare_execution_coordination(
    *,
    request_id: str,
    client_id: str,
    request_text: str,
    work_class: str,
    intent: TaskIntent,
    context_digest: str,
    delegation: DelegationDecision,
    project_id: str | None = None,
    work_item_id: str | None = None,
    work_item_revision: int | None = None,
    work_item_digest: str | None = None,
    task_plan: TaskPlan | None = None,
    task_authorization_id: str | None = None,
    model_assignment_ids: Sequence[str] = (),
    dag_execution_plan_id: str | None = None,
    route_request: RouteRequest | None = None,
    adaptive_routing_policy: AdaptiveRoutingPolicy | None = None,
) -> ExecutionCoordinationPlan:
    """Bind existing stage decisions without replacing their policy owners."""

    request_id = str(_identifier(request_id, "request id"))
    client_id = str(_identifier(client_id, "client id"))
    work_class = str(_identifier(work_class, "work class"))
    context_digest = str(_sha256(context_digest, "context digest"))
    try:
        checked_intent = parse_task_intent(intent.as_dict())
    except (AttributeError, ValueError) as exc:
        raise ExecutionCoordinatorError("task intent is invalid") from exc
    if checked_intent.request_digest != _request_digest(request_text):
        raise ExecutionCoordinatorError("task intent does not match the request")
    if checked_intent.clarification_required:
        raise ExecutionCoordinatorError("task intent still requires clarification")
    checked_delegation = _parse_delegation(delegation)
    delegation_payload = checked_delegation.as_dict()
    if (
        delegation_payload["client_id"] != client_id
        or delegation_payload["work_class"] != work_class
    ):
        raise ExecutionCoordinatorError(
            "delegation decision does not match the request"
        )

    direct = work_class in COORDINATOR_EXCEPTIONS
    project_id = _identifier(project_id, "project id", nullable=True)
    work_item_id = _identifier(work_item_id, "work item id", nullable=True)
    model_ids = _identifiers(model_assignment_ids, "model assignment ids")
    checked_plan: TaskPlan | None = None
    route: str
    status: str
    if direct:
        if delegation_payload["delegation_required"] is not False:
            raise ExecutionCoordinatorError(
                "coordinator exception cannot require delegation"
            )
        if any(
            value is not None
            for value in (
                work_item_revision,
                work_item_digest,
                task_plan,
                task_authorization_id,
                dag_execution_plan_id,
            )
        ) or model_ids:
            raise ExecutionCoordinatorError(
                "coordinator exception cannot schedule agents"
            )
        route = "coordinator-response"
        status = "ready"
    else:
        if (
            project_id is None
            or work_item_id is None
            or not isinstance(work_item_revision, int)
            or isinstance(work_item_revision, bool)
            or work_item_revision < 1
        ):
            raise ExecutionCoordinatorError(
                "meaningful project work requires an authoritative work identity"
            )
        work_item_digest = str(
            _sha256(work_item_digest, "work item digest")
        )
        if delegation_payload["delegation_required"] is not True:
            raise ExecutionCoordinatorError(
                "meaningful project work must require delegation"
            )
        if delegation_payload["execution_allowed"] is not True:
            if any(
                value is not None
                for value in (
                    task_plan,
                    task_authorization_id,
                    dag_execution_plan_id,
                )
            ) or model_ids:
                raise ExecutionCoordinatorError(
                    "blocked delegation cannot carry executable assignments"
                )
            route = "blocked"
            status = "blocked"
        else:
            if delegation_payload["coordinator_only"] is not True:
                raise ExecutionCoordinatorError(
                    "meaningful project work requires a coordinator-only main agent"
                )
            try:
                checked_plan = parse_task_plan(task_plan.as_dict())
            except (AttributeError, ValueError) as exc:
                raise ExecutionCoordinatorError("task plan is invalid") from exc
            if (
                checked_plan.intent_digest != checked_intent.intent_digest
                or checked_plan.task_id != checked_intent.task_id
            ):
                raise ExecutionCoordinatorError(
                    "task plan does not match the exact task intent"
                )
            if not any(step.role == "verifier" for step in checked_plan.steps):
                raise ExecutionCoordinatorError(
                    "task plan requires an independent verifier step"
                )
            task_authorization_id = str(
                _sha256(task_authorization_id, "task authorization id")
            )
            dag_execution_plan_id = str(
                _sha256(dag_execution_plan_id, "DAG execution plan id")
            )
            if not model_ids:
                raise ExecutionCoordinatorError(
                    "delegated execution requires model assignments"
                )
            route = "delegated-dag"
            status = (
                "awaiting-approval" if checked_plan.requires_approval else "ready"
            )

    task_plan_id = checked_plan.plan_id if checked_plan is not None else None
    step_bindings = (
        [
            {"step_id": step.step_id, "role": step.role}
            for step in checked_plan.steps
        ]
        if checked_plan is not None
        else []
    )
    approval_triggers = (
        list(checked_plan.approval_triggers) if checked_plan is not None else []
    )
    route_decision_id: str | None = None
    route_shadow_comparison_digest: str | None = None
    route_shadow_status = "not-observed"
    if route_request is not None or adaptive_routing_policy is not None:
        if route_request is None or adaptive_routing_policy is None:
            raise ExecutionCoordinatorError(
                "adaptive routing shadow inputs are incomplete"
            )
        try:
            checked_route_request = parse_route_request(
                route_request.as_dict(), adaptive_routing_policy
            )
            route_request_payload = checked_route_request.as_dict()
            if (
                route_request_payload["request_id"] != request_id
                or route_request_payload["client_id"] != client_id
                or route_request_payload["project_id"] != project_id
                or route_request_payload["work_item_id"] != work_item_id
                or route_request_payload["intent_digest"]
                != checked_intent.intent_digest
                or route_request_payload["context_digest"] != context_digest
            ):
                raise ExecutionCoordinatorError(
                    "adaptive route request does not match coordination"
                )
            shadow_decision = decide_route(
                adaptive_routing_policy, checked_route_request
            )
            comparison = compare_shadow_route(
                adaptive_routing_policy,
                shadow_decision,
                observed_route=route,
            )
        except ExecutionCoordinatorError:
            raise
        except ValueError as exc:
            raise ExecutionCoordinatorError(
                "adaptive routing shadow decision is invalid"
            ) from exc
        route_decision_id = shadow_decision.decision_digest
        comparison_payload = comparison.as_dict()
        route_shadow_comparison_digest = str(
            comparison_payload["comparison_digest"]
        )
        route_shadow_status = str(comparison_payload["comparison_status"])
    identity = {
        "request_id": request_id,
        "client_id": client_id,
        "request_digest": checked_intent.request_digest,
        "work_class": work_class,
        "project_id": project_id,
        "work_item_id": work_item_id,
        "work_item_revision": work_item_revision,
        "work_item_digest": work_item_digest,
        "intent_digest": checked_intent.intent_digest,
        "context_digest": context_digest,
        "delegation_decision_digest": delegation_payload["decision_digest"],
        "delegation_mode": delegation_payload["selected_mode"],
        "task_plan_id": task_plan_id,
        "task_authorization_id": task_authorization_id,
        "model_assignment_ids": list(model_ids),
        "dag_execution_plan_id": dag_execution_plan_id,
        "step_bindings": step_bindings,
        "approval_triggers": approval_triggers,
        "route": route,
        "status": status,
        "route_decision_id": route_decision_id,
        "route_shadow_comparison_digest": route_shadow_comparison_digest,
        "route_shadow_status": route_shadow_status,
        "route_shadow_behavior_changed": False,
    }
    correlation_id = "execution-" + _digest(identity)[:24]
    payload: dict[str, object] = {
        "schema_ref": "schemas/execution-coordination-plan.schema.json",
        "schema_version": 1,
        "correlation_id": correlation_id,
        **identity,
        "agent_calls_planned": len(step_bindings),
        "provider_calls_implicit": False,
        "coordinator_performs_project_work": False,
        "grants_authority": False,
        "plan_id": "",
    }
    payload["plan_id"] = _digest(payload)
    return parse_execution_coordination_plan(payload)


def parse_execution_coordination_plan(payload: object) -> ExecutionCoordinationPlan:
    expected = {
        "schema_ref",
        "schema_version",
        "correlation_id",
        "request_id",
        "client_id",
        "request_digest",
        "work_class",
        "project_id",
        "work_item_id",
        "work_item_revision",
        "work_item_digest",
        "intent_digest",
        "context_digest",
        "delegation_decision_digest",
        "delegation_mode",
        "task_plan_id",
        "task_authorization_id",
        "model_assignment_ids",
        "dag_execution_plan_id",
        "step_bindings",
        "approval_triggers",
        "route",
        "status",
        "agent_calls_planned",
        "provider_calls_implicit",
        "coordinator_performs_project_work",
        "grants_authority",
        "plan_id",
    }
    route_fields = {
        "route_decision_id",
        "route_shadow_comparison_digest",
        "route_shadow_status",
        "route_shadow_behavior_changed",
    }
    if not isinstance(payload, Mapping) or set(payload) not in {
        frozenset(expected),
        frozenset(expected | route_fields),
    }:
        raise ExecutionCoordinatorError(
            "execution coordination plan fields are invalid"
        )
    legacy_without_route = set(payload) == expected
    if (
        payload.get("schema_ref")
        != "schemas/execution-coordination-plan.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("route") not in ROUTES
        or payload.get("status") not in PLAN_STATUSES
        or payload.get("provider_calls_implicit") is not False
        or payload.get("coordinator_performs_project_work") is not False
        or payload.get("grants_authority") is not False
    ):
        raise ExecutionCoordinatorError(
            "execution coordination plan contract is invalid"
        )
    for field in ("correlation_id", "request_id", "client_id", "work_class"):
        _identifier(payload.get(field), field)
    for field in (
        "request_digest",
        "intent_digest",
        "context_digest",
        "delegation_decision_digest",
    ):
        _sha256(payload.get(field), field)
    for field in ("project_id", "work_item_id"):
        _identifier(payload.get(field), field, nullable=True)
    for field in (
        "work_item_digest",
        "task_plan_id",
        "task_authorization_id",
        "dag_execution_plan_id",
    ):
        _sha256(payload.get(field), field, nullable=True)
    if not legacy_without_route:
        route_decision_id = _sha256(
            payload.get("route_decision_id"), "route decision id", nullable=True
        )
        comparison_digest = _sha256(
            payload.get("route_shadow_comparison_digest"),
            "route shadow comparison digest",
            nullable=True,
        )
        shadow_status = payload.get("route_shadow_status")
        if shadow_status not in {
            "matched",
            "mismatch",
            "not-comparable",
            "not-observed",
        } or payload.get("route_shadow_behavior_changed") is not False:
            raise ExecutionCoordinatorError(
                "execution coordination route shadow fields are invalid"
            )
        if shadow_status == "not-observed":
            if route_decision_id is not None or comparison_digest is not None:
                raise ExecutionCoordinatorError(
                    "unobserved route shadow cannot carry evidence"
                )
        elif route_decision_id is None or comparison_digest is None:
            raise ExecutionCoordinatorError(
                "observed route shadow evidence is incomplete"
            )
    _identifiers(payload.get("model_assignment_ids"), "model assignment ids")
    _identifiers(payload.get("approval_triggers"), "approval triggers")
    steps = payload.get("step_bindings")
    if not isinstance(steps, list) or any(
        not isinstance(item, Mapping)
        or set(item) != {"step_id", "role"}
        or _identifier(item.get("step_id"), "step id") is None
        or item.get("role") not in {"worker", "verifier"}
        for item in steps
    ):
        raise ExecutionCoordinatorError("execution step bindings are invalid")
    if len({item["step_id"] for item in steps}) != len(steps):
        raise ExecutionCoordinatorError("execution step bindings are duplicated")
    agent_calls = payload.get("agent_calls_planned")
    if (
        not isinstance(agent_calls, int)
        or isinstance(agent_calls, bool)
        or agent_calls != len(steps)
    ):
        raise ExecutionCoordinatorError("agent call count is invalid")
    if payload.get("route") == "coordinator-response" and (steps or agent_calls):
        raise ExecutionCoordinatorError(
            "coordinator response cannot schedule agents"
        )
    executable_fields = (
        payload.get("task_plan_id"),
        payload.get("task_authorization_id"),
        payload.get("dag_execution_plan_id"),
    )
    if payload.get("route") == "coordinator-response" and (
        any(value is not None for value in executable_fields)
        or payload.get("model_assignment_ids")
        or payload.get("approval_triggers")
    ):
        raise ExecutionCoordinatorError(
            "coordinator response carries executable fields"
        )
    if payload.get("route") == "blocked" and (
        any(value is not None for value in executable_fields)
        or payload.get("model_assignment_ids")
        or steps
        or payload.get("status") != "blocked"
    ):
        raise ExecutionCoordinatorError("blocked coordination is executable")
    if payload.get("route") == "delegated-dag" and (
        any(value is None for value in executable_fields)
        or not payload.get("model_assignment_ids")
        or not steps
        or not any(item["role"] == "verifier" for item in steps)
        or payload.get("project_id") is None
        or payload.get("work_item_id") is None
        or payload.get("work_item_revision") is None
        or payload.get("work_item_digest") is None
        or payload.get("status") not in {"ready", "awaiting-approval"}
    ):
        raise ExecutionCoordinatorError(
            "delegated coordination fields are incomplete"
        )
    plan_id = _sha256(payload.get("plan_id"), "plan id")
    identity = dict(payload)
    identity["plan_id"] = ""
    if plan_id != _digest(identity):
        raise ExecutionCoordinatorError(
            "execution coordination plan digest does not match"
        )
    return ExecutionCoordinationPlan(dict(payload))


def _validate_dag_result(
    plan: ExecutionCoordinationPlan,
    payload: object,
) -> tuple[list[str], list[str], str]:
    expected = {
        "schema_ref",
        "schema_version",
        "status",
        "project_id",
        "work_item_id",
        "task_id",
        "task_plan_id",
        "execution_plan_id",
        "step_results",
        "executed_step_ids",
        "resumed",
        "max_concurrency",
        "queue_control_serial",
        "handler_execution_parallel",
        "runtime_completion",
        "grants_authority",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ExecutionCoordinatorError("DAG result fields are invalid")
    plan_payload = plan.as_dict()
    if (
        payload.get("schema_ref")
        != "schemas/generic-dag-execution-result.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("status") not in {"completed", "already-completed"}
        or payload.get("project_id") != plan_payload["project_id"]
        or payload.get("work_item_id") != plan_payload["work_item_id"]
        or payload.get("task_plan_id") != plan_payload["task_plan_id"]
        or payload.get("execution_plan_id")
        != plan_payload["dag_execution_plan_id"]
        or payload.get("queue_control_serial") is not True
        or payload.get("handler_execution_parallel") is not True
        or payload.get("runtime_completion") is not True
        or payload.get("grants_authority") is not False
    ):
        raise ExecutionCoordinatorError("DAG result binding is invalid")
    expected_steps = {
        item["step_id"]: item["role"] for item in plan_payload["step_bindings"]
    }
    results = payload.get("step_results")
    if not isinstance(results, list) or len(results) != len(expected_steps):
        raise ExecutionCoordinatorError("DAG step results are incomplete")
    by_step: dict[str, Mapping[str, object]] = {}
    for item in results:
        if not isinstance(item, Mapping) or set(item) != {
            "step_id",
            "execution_identity_id",
            "evidence_digest",
            "status",
        }:
            raise ExecutionCoordinatorError("DAG step result is invalid")
        step_id = str(_identifier(item.get("step_id"), "DAG step id"))
        if step_id in by_step or step_id not in expected_steps:
            raise ExecutionCoordinatorError("DAG step result identity is invalid")
        _sha256(item.get("execution_identity_id"), "execution identity id")
        _sha256(item.get("evidence_digest"), "step evidence digest")
        if item.get("status") != "completed":
            raise ExecutionCoordinatorError("DAG step is not completed")
        by_step[step_id] = item
    if set(by_step) != set(expected_steps):
        raise ExecutionCoordinatorError("DAG step result coverage is invalid")
    verifier_steps = [
        step_id for step_id, role in expected_steps.items() if role == "verifier"
    ]
    worker_ids = [
        str(item["execution_identity_id"])
        for step_id, item in by_step.items()
        if expected_steps[step_id] == "worker"
    ]
    verifier_ids = [
        str(by_step[step_id]["execution_identity_id"])
        for step_id in verifier_steps
    ]
    if set(worker_ids) & set(verifier_ids):
        raise ExecutionCoordinatorError("verifier execution is not independent")
    evidence_digest = _digest(
        [by_step[step_id]["evidence_digest"] for step_id in sorted(by_step)]
    )
    return worker_ids + verifier_ids, verifier_ids, evidence_digest


def finalize_execution_coordination(
    plan: ExecutionCoordinationPlan,
    *,
    started_at: str,
    ended_at: str,
    direct_evidence_digest: str | None = None,
    dag_result: Mapping[str, object] | None = None,
    continuity_snapshot: ContinuitySnapshot | None = None,
    finalized_handoff: FinalizedHandoff | None = None,
    approval_envelope_id: str | None = None,
    token_usage: Mapping[str, int] | None = None,
    estimated_cost: Mapping[str, object] | None = None,
    retry_count: int = 0,
    cache_hit: bool = False,
) -> ExecutionCoordinationResult:
    """Build one trace and status from already verified domain results."""

    checked_plan = parse_execution_coordination_plan(plan.as_dict())
    payload = checked_plan.as_dict()
    if checked_plan.route == "blocked":
        raise ExecutionCoordinatorError("blocked coordination cannot be finalized")
    queue_ids: list[str] = []
    agent_ids: list[str] = []
    verification_id: str | None = None
    handoff_id: str | None = None
    snapshot_id: str | None = None
    if checked_plan.route == "coordinator-response":
        evidence_digest = str(
            _sha256(direct_evidence_digest, "direct evidence digest")
        )
        if any(
            value is not None
            for value in (
                dag_result,
                continuity_snapshot,
                finalized_handoff,
                approval_envelope_id,
            )
        ):
            raise ExecutionCoordinatorError(
                "coordinator response cannot claim delegated evidence"
            )
        delegation_mode = "direct"
    else:
        if payload["status"] == "awaiting-approval":
            approval_envelope_id = str(
                _identifier(approval_envelope_id, "approval envelope id")
            )
        elif approval_envelope_id is not None:
            approval_envelope_id = str(
                _identifier(approval_envelope_id, "approval envelope id")
            )
        agent_ids, verifier_ids, evidence_digest = _validate_dag_result(
            checked_plan,
            dag_result,
        )
        snapshot = parse_continuity_snapshot(continuity_snapshot.as_dict())
        handoff = parse_finalized_handoff(finalized_handoff.as_dict())
        if (
            snapshot.project_id != payload["project_id"]
            or snapshot.work_item_id != payload["work_item_id"]
            or snapshot.work_item_revision != payload["work_item_revision"]
            or handoff.project_id != payload["project_id"]
            or handoff.work_item_id != payload["work_item_id"]
            or handoff.snapshot_digest != snapshot.snapshot_digest
        ):
            raise ExecutionCoordinatorError(
                "continuity and handoff do not match the root plan"
            )
        completed = set(snapshot.sections["completed_steps"].entries)
        expected = {item["step_id"] for item in payload["step_bindings"]}
        if not expected.issubset(completed):
            raise ExecutionCoordinatorError(
                "continuity snapshot does not cover every completed step"
            )
        verification_id = "verification-" + _digest(verifier_ids)[:24]
        snapshot_id = snapshot.snapshot_id
        handoff_id = handoff.handoff_id
        delegation_mode = str(payload["delegation_mode"])

    trace = build_execution_trace(
        correlation_id=str(payload["correlation_id"]),
        request_id=str(payload["request_id"]),
        client_id=str(payload["client_id"]),
        project_id=payload["project_id"],
        work_item_id=payload["work_item_id"],
        intent_digest=str(payload["intent_digest"]),
        context_digest=str(payload["context_digest"]),
        plan_id=checked_plan.plan_id,
        route_decision_id=payload.get("route_decision_id"),
        approval_envelope_id=approval_envelope_id,
        delegation_mode=delegation_mode,
        model_assignment_ids=payload["model_assignment_ids"],
        queue_ids=queue_ids,
        agent_execution_ids=agent_ids,
        verification_id=verification_id,
        evidence_digest=evidence_digest,
        status="completed",
        started_at=started_at,
        ended_at=ended_at,
        token_usage=token_usage,
        estimated_cost=estimated_cost,
        retry_count=retry_count,
        cache_hit=cache_hit,
    )
    status = project_execution_status(
        correlation_id=str(payload["correlation_id"]),
        project_id=payload["project_id"],
        work_item_id=payload["work_item_id"],
        source_statuses={
            "coordination": "completed",
            "execution": "completed",
            "verification": "completed",
        },
        summary="Execution completed with verified evidence",
        updated_at=ended_at,
        trace_digest=str(trace.as_dict()["trace_digest"]),
    )
    result_payload: dict[str, object] = {
        "schema_ref": "schemas/execution-coordination-result.schema.json",
        "schema_version": 1,
        "correlation_id": payload["correlation_id"],
        "plan_id": checked_plan.plan_id,
        "route": checked_plan.route,
        "route_decision_id": payload.get("route_decision_id"),
        "route_shadow_comparison_digest": payload.get(
            "route_shadow_comparison_digest"
        ),
        "status": "completed",
        "evidence_digest": evidence_digest,
        "verification_id": verification_id,
        "continuity_snapshot_id": snapshot_id,
        "handoff_id": handoff_id,
        "trace": trace.as_dict(),
        "status_projection": status.as_dict(),
        "grants_authority": False,
        "result_digest": "",
    }
    result_payload["result_digest"] = _digest(result_payload)
    return parse_execution_coordination_result(result_payload)


def parse_execution_coordination_result(
    payload: object,
) -> ExecutionCoordinationResult:
    """Parse one durable result and revalidate all nested bindings."""

    expected = {
        "schema_ref",
        "schema_version",
        "correlation_id",
        "plan_id",
        "route",
        "status",
        "evidence_digest",
        "verification_id",
        "continuity_snapshot_id",
        "handoff_id",
        "trace",
        "status_projection",
        "grants_authority",
        "result_digest",
    }
    route_fields = {
        "route_decision_id",
        "route_shadow_comparison_digest",
    }
    if not isinstance(payload, Mapping) or set(payload) not in {
        frozenset(expected),
        frozenset(expected | route_fields),
    }:
        raise ExecutionCoordinatorError(
            "execution coordination result fields are invalid"
        )
    legacy_without_route = set(payload) == expected
    if (
        payload.get("schema_ref")
        != "schemas/execution-coordination-result.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("route")
        not in {"coordinator-response", "delegated-dag"}
        or payload.get("status") != "completed"
        or payload.get("grants_authority") is not False
    ):
        raise ExecutionCoordinatorError(
            "execution coordination result contract is invalid"
        )
    correlation_id = str(
        _identifier(payload.get("correlation_id"), "correlation id")
    )
    plan_id = str(_sha256(payload.get("plan_id"), "plan id"))
    evidence_digest = str(
        _sha256(payload.get("evidence_digest"), "evidence digest")
    )
    route_decision_id = None
    route_shadow_comparison_digest = None
    if not legacy_without_route:
        route_decision_id = _sha256(
            payload.get("route_decision_id"), "route decision id", nullable=True
        )
        route_shadow_comparison_digest = _sha256(
            payload.get("route_shadow_comparison_digest"),
            "route shadow comparison digest",
            nullable=True,
        )
        if (route_decision_id is None) != (
            route_shadow_comparison_digest is None
        ):
            raise ExecutionCoordinatorError(
                "execution coordination route evidence is incomplete"
            )
    for field in (
        "verification_id",
        "continuity_snapshot_id",
        "handoff_id",
    ):
        _identifier(payload.get(field), field, nullable=True)
    try:
        trace = parse_execution_trace(payload.get("trace"))
        status = parse_status_projection(payload.get("status_projection"))
    except ValueError as exc:
        raise ExecutionCoordinatorError(
            "execution coordination observability is invalid"
        ) from exc
    trace_payload = trace.as_dict()
    status_payload = status.as_dict()
    if (
        trace_payload["correlation_id"] != correlation_id
        or trace_payload["plan_id"] != plan_id
        or trace_payload.get("route_decision_id") != route_decision_id
        or trace_payload["evidence_digest"] != evidence_digest
        or trace_payload["status"] != "completed"
        or status_payload["correlation_id"] != correlation_id
        or status_payload["status"] != "completed"
        or status_payload["trace_digest"] != trace_payload["trace_digest"]
    ):
        raise ExecutionCoordinatorError(
            "execution coordination observability binding is invalid"
        )
    delegated = payload.get("route") == "delegated-dag"
    linked = (
        payload.get("verification_id"),
        payload.get("continuity_snapshot_id"),
        payload.get("handoff_id"),
    )
    if (delegated and any(value is None for value in linked)) or (
        not delegated and any(value is not None for value in linked)
    ):
        raise ExecutionCoordinatorError(
            "execution coordination result route binding is invalid"
        )
    result_digest = str(
        _sha256(payload.get("result_digest"), "result digest")
    )
    identity = dict(payload)
    identity["result_digest"] = ""
    if result_digest != _digest(identity):
        raise ExecutionCoordinatorError(
            "execution coordination result digest does not match"
        )
    return ExecutionCoordinationResult(dict(payload), trace, status)


def execute_execution_coordination(
    plan: ExecutionCoordinationPlan,
    adapters: ExecutionCoordinatorAdapters,
    *,
    started_at: str,
    ended_at: str,
    approval_envelope_id: str | None = None,
    token_usage: Mapping[str, int] | None = None,
    estimated_cost: Mapping[str, object] | None = None,
) -> ExecutionCoordinationResult:
    """Invoke only the reviewed DAG and continuity service boundaries."""

    checked_plan = parse_execution_coordination_plan(plan.as_dict())
    if checked_plan.route != "delegated-dag":
        raise ExecutionCoordinatorError(
            "only a delegated DAG plan can enter coordinator execution"
        )
    if not callable(adapters.dag_dispatcher) or not callable(
        adapters.continuity_finalizer
    ):
        raise ExecutionCoordinatorError("coordinator adapters are invalid")
    dag_result = adapters.dag_dispatcher(
        str(checked_plan.as_dict()["dag_execution_plan_id"])
    )
    snapshot, handoff = adapters.continuity_finalizer(
        checked_plan,
        dag_result,
    )
    return finalize_execution_coordination(
        checked_plan,
        started_at=started_at,
        ended_at=ended_at,
        dag_result=dag_result,
        continuity_snapshot=snapshot,
        finalized_handoff=handoff,
        approval_envelope_id=approval_envelope_id,
        token_usage=token_usage,
        estimated_cost=estimated_cost,
    )
