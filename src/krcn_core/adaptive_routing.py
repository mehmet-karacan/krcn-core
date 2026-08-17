"""Authority-free adaptive routing decisions for shadow evaluation.

The router classifies how reviewed work would be executed. It does not grant
authority, enqueue work, select a model, invoke a provider, or mutate domain
state. Delegation, model assignment, admission, and authorization remain
separate decisions owned by their existing services.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .json_documents import canonical_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")

ROUTE_MODES = {
    "blocked",
    "coordinator-response",
    "direct-read",
    "parallel-dag",
    "recovery-required",
    "review-only",
    "sequential-dag",
    "single-worker",
}
TASK_TYPES = {
    "analysis",
    "exact-lookup",
    "governance",
    "implementation",
    "recovery",
    "research",
    "status",
    "verification",
}
RISK_LEVELS = {"critical", "high", "low", "medium"}
MUTATION_LEVELS = {"core", "external", "none", "runtime", "user-data"}
DATA_CLASSIFICATIONS = {"confidential-ip", "internal", "public", "secret"}
ACCESS_MODES = {"read", "write"}
COMPARISON_STATUSES = {"matched", "mismatch", "not-comparable"}


class AdaptiveRoutingError(ValueError):
    """Raised when routing evidence is unsafe, stale, or inconsistent."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _strict(payload: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise AdaptiveRoutingError(f"{label} fields are invalid")
    return payload


def _identifier(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise AdaptiveRoutingError(f"{label} must be a portable identifier")
    return value


def _sha(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise AdaptiveRoutingError(f"{label} must be a SHA-256 digest")
    return value


def _nonnegative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdaptiveRoutingError(f"{label} must be a non-negative integer")
    return value


def _positive(value: object, label: str) -> int:
    value = _nonnegative(value, label)
    if value < 1:
        raise AdaptiveRoutingError(f"{label} must be positive")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise AdaptiveRoutingError(f"{label} must be boolean")
    return value


def _enum(value: object, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise AdaptiveRoutingError(f"{label} is invalid")
    return value


def _identifiers(value: object, label: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AdaptiveRoutingError(f"{label} must be a list")
    result = sorted(str(_identifier(item, f"{label} entry")) for item in value)
    if len(result) != len(set(result)):
        raise AdaptiveRoutingError(f"{label} must not contain duplicates")
    return result


def _ordered_identifiers(value: object, label: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AdaptiveRoutingError(f"{label} must be a list")
    result = [str(_identifier(item, f"{label} entry")) for item in value]
    if len(result) != len(set(result)):
        raise AdaptiveRoutingError(f"{label} must not contain duplicates")
    return result


def _reason_codes(value: object, label: str, *, nonempty: bool = False) -> list[str]:
    result = _identifiers(value, label)
    if nonempty and not result:
        raise AdaptiveRoutingError(f"{label} must not be empty")
    return result


@dataclass(frozen=True)
class AdaptiveRoutingPolicy:
    payload: Mapping[str, object]

    @property
    def policy_digest(self) -> str:
        return _digest(self.payload)

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


@dataclass(frozen=True)
class RouteRequest:
    payload: Mapping[str, object]

    @property
    def request_digest(self) -> str:
        return str(self.payload["request_digest"])

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


@dataclass(frozen=True)
class RouteDecision:
    payload: Mapping[str, object]

    @property
    def decision_digest(self) -> str:
        return str(self.payload["decision_digest"])

    @property
    def route_mode(self) -> str:
        return str(self.payload["selected"]["route_mode"])

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


@dataclass(frozen=True)
class ShadowRouteComparison:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


def parse_adaptive_routing_policy(payload: object) -> AdaptiveRoutingPolicy:
    fields = {
        "schema_ref",
        "schema_version",
        "revision",
        "mode",
        "route_modes",
        "task_types",
        "risk_levels",
        "mutation_levels",
        "data_classifications",
        "thresholds",
        "invariants",
    }
    data = _strict(payload, fields, "adaptive routing policy")
    if (
        data.get("schema_ref") != "schemas/adaptive-routing-policy.schema.json"
        or data.get("schema_version") != 1
        or _positive(data.get("revision"), "policy revision") < 1
        or data.get("mode") != "shadow"
        or data.get("route_modes") != sorted(ROUTE_MODES)
        or data.get("task_types") != sorted(TASK_TYPES)
        or data.get("risk_levels") != sorted(RISK_LEVELS)
        or data.get("mutation_levels") != sorted(MUTATION_LEVELS)
        or data.get("data_classifications") != sorted(DATA_CLASSIFICATIONS)
    ):
        raise AdaptiveRoutingError("adaptive routing policy identity is invalid")

    thresholds = _strict(
        data.get("thresholds"),
        {
            "direct_read_max_work_units",
            "direct_read_max_context_tokens",
            "parallel_min_subproblems",
            "parallel_min_concurrency",
        },
        "adaptive routing thresholds",
    )
    _positive(thresholds.get("direct_read_max_work_units"), "direct work threshold")
    _positive(thresholds.get("direct_read_max_context_tokens"), "direct context threshold")
    if _positive(thresholds.get("parallel_min_subproblems"), "parallel problem threshold") < 2:
        raise AdaptiveRoutingError("parallel problem threshold is unsafe")
    if _positive(thresholds.get("parallel_min_concurrency"), "parallel concurrency threshold") < 2:
        raise AdaptiveRoutingError("parallel concurrency threshold is unsafe")

    invariants = _strict(
        data.get("invariants"),
        {
            "decision_grants_authority",
            "enforcement_enabled",
            "hard_gates_override_soft_routes",
            "decision_axes_separate",
            "unknown_fields_allowed",
            "raw_content_allowed",
        },
        "adaptive routing invariants",
    )
    if (
        invariants.get("decision_grants_authority") is not False
        or invariants.get("enforcement_enabled") is not False
        or invariants.get("hard_gates_override_soft_routes") is not True
        or invariants.get("decision_axes_separate") is not True
        or invariants.get("unknown_fields_allowed") is not False
        or invariants.get("raw_content_allowed") is not False
    ):
        raise AdaptiveRoutingError("adaptive routing policy is unsafe")
    return AdaptiveRoutingPolicy(json.loads(json.dumps(data)))


def load_adaptive_routing_policy(repo_root: Path) -> AdaptiveRoutingPolicy:
    try:
        payload = json.loads(
            (repo_root / "config" / "adaptive-routing.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise AdaptiveRoutingError("adaptive routing policy cannot be loaded") from exc
    return parse_adaptive_routing_policy(payload)


def _parse_resources(value: object) -> list[dict[str, object]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AdaptiveRoutingError("resources must be a list")
    result: list[dict[str, object]] = []
    identities: set[tuple[str, str, str]] = set()
    for item in value:
        data = _strict(item, {"node_id", "resource_ref", "access"}, "resource")
        node_id = str(_identifier(data.get("node_id"), "resource node id"))
        resource_ref = data.get("resource_ref")
        if not isinstance(resource_ref, str) or not LOGICAL_REF.fullmatch(resource_ref):
            raise AdaptiveRoutingError("resource ref must be a logical reference")
        access = _enum(data.get("access"), ACCESS_MODES, "resource access")
        identity = (node_id, resource_ref.casefold(), access)
        if identity in identities:
            raise AdaptiveRoutingError("resources must not contain duplicates")
        identities.add(identity)
        result.append(
            {"node_id": node_id, "resource_ref": resource_ref, "access": access}
        )
    return sorted(
        result,
        key=lambda item: (
            str(item["resource_ref"]).casefold(),
            str(item["node_id"]),
            str(item["access"]),
        ),
    )


def _request_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in payload
        if key not in {"schema_ref", "schema_version", "request_digest"}
    }


def create_route_request(
    policy: AdaptiveRoutingPolicy,
    *,
    request_id: str,
    correlation_id: str,
    client_id: str,
    intent_digest: str,
    context_digest: str,
    task_type: str,
    risk_level: str,
    mutation_level: str,
    data_classification: str,
    estimated_work_units: int,
    context_size_tokens: int,
    context_pressure_millis: int,
    independent_subproblem_count: int,
    dependency_depth: int,
    required_capabilities: Sequence[str],
    available_capabilities: Sequence[str],
    deterministic_validator_available: bool,
    verifier_available: bool,
    sandbox_available: bool,
    resources: Sequence[Mapping[str, object]],
    approval_required: bool,
    approval_verified: bool,
    pending_claim_without_receipt: bool,
    input_tokens: int,
    output_tokens: int,
    cost_microunits: int,
    latency_seconds: int,
    maximum_concurrency: int,
    remote_required: bool,
    provider_assurance_available: bool,
    source_revision_current: bool,
    authoritative_context_required: bool,
    project_id: str | None = None,
    work_item_id: str | None = None,
    source_revision_digest: str | None = None,
) -> RouteRequest:
    payload: dict[str, object] = {
        "schema_ref": "schemas/route-request.schema.json",
        "schema_version": 1,
        "policy_digest": policy.policy_digest,
        "request_id": request_id,
        "correlation_id": correlation_id,
        "client_id": client_id,
        "project_id": project_id,
        "work_item_id": work_item_id,
        "source_revision_digest": source_revision_digest,
        "intent_digest": intent_digest,
        "context_digest": context_digest,
        "task_type": task_type,
        "risk_level": risk_level,
        "mutation_level": mutation_level,
        "data_classification": data_classification,
        "complexity": {
            "estimated_work_units": estimated_work_units,
            "context_size_tokens": context_size_tokens,
            "context_pressure_millis": context_pressure_millis,
            "independent_subproblem_count": independent_subproblem_count,
            "dependency_depth": dependency_depth,
        },
        "capabilities": {
            "required": list(required_capabilities),
            "available": list(available_capabilities),
            "deterministic_validator_available": deterministic_validator_available,
            "verifier_available": verifier_available,
            "sandbox_available": sandbox_available,
        },
        "resources": list(resources),
        "authority": {
            "approval_required": approval_required,
            "approval_verified": approval_verified,
            "pending_claim_without_receipt": pending_claim_without_receipt,
        },
        "budgets": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_microunits": cost_microunits,
            "latency_seconds": latency_seconds,
            "maximum_concurrency": maximum_concurrency,
        },
        "provider": {
            "remote_required": remote_required,
            "assurance_available": provider_assurance_available,
        },
        "source_revision_current": source_revision_current,
        "authoritative_context_required": authoritative_context_required,
        "contains_raw_content": False,
        "contains_physical_paths": False,
        "contains_credentials": False,
        "grants_authority": False,
    }
    payload["request_digest"] = _digest(_request_identity(payload))
    return parse_route_request(payload, policy)


def parse_route_request(
    payload: object, policy: AdaptiveRoutingPolicy
) -> RouteRequest:
    fields = {
        "schema_ref",
        "schema_version",
        "policy_digest",
        "request_id",
        "correlation_id",
        "client_id",
        "project_id",
        "work_item_id",
        "source_revision_digest",
        "intent_digest",
        "context_digest",
        "task_type",
        "risk_level",
        "mutation_level",
        "data_classification",
        "complexity",
        "capabilities",
        "resources",
        "authority",
        "budgets",
        "provider",
        "source_revision_current",
        "authoritative_context_required",
        "contains_raw_content",
        "contains_physical_paths",
        "contains_credentials",
        "grants_authority",
        "request_digest",
    }
    data = _strict(payload, fields, "route request")
    if (
        data.get("schema_ref") != "schemas/route-request.schema.json"
        or data.get("schema_version") != 1
        or data.get("policy_digest") != policy.policy_digest
        or any(
            data.get(field) is not False
            for field in (
                "contains_raw_content",
                "contains_physical_paths",
                "contains_credentials",
                "grants_authority",
            )
        )
    ):
        raise AdaptiveRoutingError("route request contract is invalid")
    for field in ("request_id", "correlation_id", "client_id"):
        _identifier(data.get(field), field.replace("_", " "))
    _identifier(data.get("project_id"), "project id", nullable=True)
    _identifier(data.get("work_item_id"), "work item id", nullable=True)
    _sha(data.get("source_revision_digest"), "source revision digest", nullable=True)
    _sha(data.get("intent_digest"), "intent digest")
    _sha(data.get("context_digest"), "context digest")
    _enum(data.get("task_type"), TASK_TYPES, "task type")
    _enum(data.get("risk_level"), RISK_LEVELS, "risk level")
    _enum(data.get("mutation_level"), MUTATION_LEVELS, "mutation level")
    _enum(
        data.get("data_classification"),
        DATA_CLASSIFICATIONS,
        "data classification",
    )

    complexity = _strict(
        data.get("complexity"),
        {
            "estimated_work_units",
            "context_size_tokens",
            "context_pressure_millis",
            "independent_subproblem_count",
            "dependency_depth",
        },
        "route complexity",
    )
    for field in complexity:
        _nonnegative(complexity.get(field), field.replace("_", " "))

    capabilities = _strict(
        data.get("capabilities"),
        {
            "required",
            "available",
            "deterministic_validator_available",
            "verifier_available",
            "sandbox_available",
        },
        "route capabilities",
    )
    required = _identifiers(capabilities.get("required"), "required capabilities")
    available = _identifiers(capabilities.get("available"), "available capabilities")
    for field in (
        "deterministic_validator_available",
        "verifier_available",
        "sandbox_available",
    ):
        _boolean(capabilities.get(field), field.replace("_", " "))

    resources = _parse_resources(data.get("resources"))
    authority = _strict(
        data.get("authority"),
        {"approval_required", "approval_verified", "pending_claim_without_receipt"},
        "route authority observation",
    )
    for field in authority:
        _boolean(authority.get(field), field.replace("_", " "))
    if authority["approval_verified"] and not authority["approval_required"]:
        raise AdaptiveRoutingError("approval cannot be verified when it is not required")

    budgets = _strict(
        data.get("budgets"),
        {
            "input_tokens",
            "output_tokens",
            "cost_microunits",
            "latency_seconds",
            "maximum_concurrency",
        },
        "route budgets",
    )
    for field in budgets:
        _nonnegative(budgets.get(field), field.replace("_", " "))

    provider = _strict(
        data.get("provider"),
        {"remote_required", "assurance_available"},
        "route provider observation",
    )
    _boolean(provider.get("remote_required"), "remote required")
    _boolean(provider.get("assurance_available"), "provider assurance available")
    _boolean(data.get("source_revision_current"), "source revision current")
    _boolean(
        data.get("authoritative_context_required"),
        "authoritative context required",
    )

    normalized = json.loads(json.dumps(data))
    normalized["capabilities"]["required"] = required
    normalized["capabilities"]["available"] = available
    normalized["resources"] = resources
    if normalized != data:
        raise AdaptiveRoutingError("route request values are not canonical")
    if _sha(data.get("request_digest"), "request digest") != _digest(
        _request_identity(data)
    ):
        raise AdaptiveRoutingError("route request digest is invalid")
    return RouteRequest(normalized)


def _resource_refs_overlap(first: str, second: str) -> bool:
    first_kind, first_value = first.casefold().split(":", 1)
    second_kind, second_value = second.casefold().split(":", 1)
    if first_kind != second_kind:
        return False
    first_parts = tuple(part for part in first_value.split("/") if part)
    second_parts = tuple(part for part in second_value.split("/") if part)
    shorter = min(len(first_parts), len(second_parts))
    return first_parts[:shorter] == second_parts[:shorter]


def _resource_conflict(resources: Sequence[Mapping[str, object]]) -> bool:
    for index, first in enumerate(resources):
        for second in resources[index + 1 :]:
            if first["node_id"] == second["node_id"]:
                continue
            if not _resource_refs_overlap(
                str(first["resource_ref"]), str(second["resource_ref"])
            ):
                continue
            if first["access"] == "write" or second["access"] == "write":
                return True
    return False


def _hard_gate(request: RouteRequest) -> tuple[str, list[str]] | None:
    data = request.payload
    capabilities = data["capabilities"]
    required = set(capabilities["required"])
    available = set(capabilities["available"])
    authority = data["authority"]
    budgets = data["budgets"]
    provider = data["provider"]
    mutation = data["mutation_level"] != "none"

    if authority["pending_claim_without_receipt"]:
        return "recovery-required", ["effect-reconciliation-required"]
    if required - available:
        return "blocked", ["capability-missing"]
    if data["data_classification"] == "secret" and provider["remote_required"]:
        return "blocked", ["secret-remote-denied"]
    if provider["remote_required"] and not provider["assurance_available"]:
        return "blocked", ["provider-assurance-required"]
    if any(
        budgets[field] == 0
        for field in (
            "input_tokens",
            "output_tokens",
            "cost_microunits",
            "latency_seconds",
            "maximum_concurrency",
        )
    ):
        return "blocked", ["budget-exhausted"]
    if data["authoritative_context_required"] and (
        data["project_id"] is None or data["work_item_id"] is None
    ):
        return "blocked", ["work-context-required"]
    if not data["source_revision_current"]:
        return "blocked", ["source-revision-stale"]
    if mutation and not capabilities["sandbox_available"]:
        return "blocked", ["sandbox-required"]
    if data["risk_level"] in {"high", "critical"} and not capabilities[
        "verifier_available"
    ]:
        return "blocked", ["independent-verifier-required"]
    if mutation and authority["approval_required"] and not authority[
        "approval_verified"
    ]:
        return "review-only", ["approval-required"]
    return None


def _roles(route_mode: str) -> list[str]:
    if route_mode in {"coordinator-response", "direct-read", "review-only", "blocked", "recovery-required"}:
        return ["coordinator"]
    if route_mode == "single-worker":
        return ["worker", "verifier"]
    return ["worker", "verifier"]


def _exclusions(selected: str, reasons: Mapping[str, str]) -> list[dict[str, object]]:
    return [
        {"mode": mode, "reason_codes": [reasons.get(mode, "not-selected")]}
        for mode in sorted(ROUTE_MODES - {selected})
    ]


def _decision_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in payload
        if key not in {
            "schema_ref",
            "schema_version",
            "route_decision_id",
            "decision_digest",
        }
    }


def decide_route(
    policy: AdaptiveRoutingPolicy, request: RouteRequest
) -> RouteDecision:
    checked = parse_route_request(request.as_dict(), policy)
    data = checked.payload
    thresholds = policy.payload["thresholds"]
    complexity = data["complexity"]
    budgets = data["budgets"]
    conflict = _resource_conflict(data["resources"])
    hard = _hard_gate(checked)

    if hard is not None:
        route_mode, reasons = hard
    elif data["task_type"] == "recovery":
        route_mode, reasons = "recovery-required", ["recovery-work-requested"]
    elif data["task_type"] in {"status", "exact-lookup"}:
        route_mode, reasons = "coordinator-response", ["coordinator-exception"]
    elif (
        data["mutation_level"] == "none"
        and complexity["estimated_work_units"]
        <= thresholds["direct_read_max_work_units"]
        and complexity["context_size_tokens"]
        <= thresholds["direct_read_max_context_tokens"]
        and complexity["independent_subproblem_count"] <= 1
        and complexity["dependency_depth"] == 0
        and data["capabilities"]["deterministic_validator_available"]
    ):
        route_mode, reasons = "direct-read", ["bounded-read-only-work"]
    elif conflict:
        route_mode, reasons = "sequential-dag", ["resource-conflict"]
    elif complexity["dependency_depth"] > 0:
        route_mode, reasons = "sequential-dag", ["dependency-order-required"]
    elif (
        complexity["independent_subproblem_count"]
        >= thresholds["parallel_min_subproblems"]
        and budgets["maximum_concurrency"]
        >= thresholds["parallel_min_concurrency"]
    ):
        route_mode, reasons = "parallel-dag", [
            "independent-subproblems",
            "resource-scopes-disjoint",
            "budget-available",
        ]
    else:
        route_mode, reasons = "single-worker", ["single-bounded-problem"]

    maximum_concurrency = 1
    if route_mode == "parallel-dag":
        maximum_concurrency = min(
            budgets["maximum_concurrency"],
            max(2, complexity["independent_subproblem_count"]),
        )
    payload: dict[str, object] = {
        "schema_ref": "schemas/route-decision.schema.json",
        "schema_version": 1,
        "policy_revision": policy.payload["revision"],
        "policy_digest": policy.policy_digest,
        "mode": "shadow",
        "request_digest": checked.request_digest,
        "bindings": {
            "request_id": data["request_id"],
            "correlation_id": data["correlation_id"],
            "project_id": data["project_id"],
            "work_item_id": data["work_item_id"],
            "intent_digest": data["intent_digest"],
            "context_digest": data["context_digest"],
        },
        "selected": {
            "route_mode": route_mode,
            "role_sequence": _roles(route_mode),
            "maximum_concurrency": maximum_concurrency,
        },
        "reason_codes": sorted(reasons),
        "exclusions": _exclusions(route_mode, {}),
        "estimated": {
            "input_tokens": budgets["input_tokens"],
            "output_tokens": budgets["output_tokens"],
            "cost_microunits": budgets["cost_microunits"],
            "latency_seconds": budgets["latency_seconds"],
        },
        "resource_conflict_observed": conflict,
        "delegation_decision_id": None,
        "model_assignment_ids": [],
        "admission_decision_id": None,
        "enforcement_applied": False,
        "grants_authority": False,
    }
    digest = _digest(_decision_identity(payload))
    payload["route_decision_id"] = digest
    payload["decision_digest"] = digest
    return parse_route_decision(payload, policy, request=checked)


def parse_route_decision(
    payload: object,
    policy: AdaptiveRoutingPolicy,
    *,
    request: RouteRequest | None = None,
) -> RouteDecision:
    fields = {
        "schema_ref",
        "schema_version",
        "route_decision_id",
        "policy_revision",
        "policy_digest",
        "mode",
        "request_digest",
        "bindings",
        "selected",
        "reason_codes",
        "exclusions",
        "estimated",
        "resource_conflict_observed",
        "delegation_decision_id",
        "model_assignment_ids",
        "admission_decision_id",
        "enforcement_applied",
        "grants_authority",
        "decision_digest",
    }
    data = _strict(payload, fields, "route decision")
    if (
        data.get("schema_ref") != "schemas/route-decision.schema.json"
        or data.get("schema_version") != 1
        or data.get("policy_revision") != policy.payload["revision"]
        or data.get("policy_digest") != policy.policy_digest
        or data.get("mode") != "shadow"
        or data.get("enforcement_applied") is not False
        or data.get("grants_authority") is not False
        or data.get("delegation_decision_id") is not None
        or data.get("model_assignment_ids") != []
        or data.get("admission_decision_id") is not None
    ):
        raise AdaptiveRoutingError("route decision contract is invalid")
    _sha(data.get("request_digest"), "route request digest")
    _boolean(data.get("resource_conflict_observed"), "resource conflict observed")

    bindings = _strict(
        data.get("bindings"),
        {
            "request_id",
            "correlation_id",
            "project_id",
            "work_item_id",
            "intent_digest",
            "context_digest",
        },
        "route decision bindings",
    )
    for field in ("request_id", "correlation_id"):
        _identifier(bindings.get(field), field.replace("_", " "))
    _identifier(bindings.get("project_id"), "project id", nullable=True)
    _identifier(bindings.get("work_item_id"), "work item id", nullable=True)
    _sha(bindings.get("intent_digest"), "intent digest")
    _sha(bindings.get("context_digest"), "context digest")

    selected = _strict(
        data.get("selected"),
        {"route_mode", "role_sequence", "maximum_concurrency"},
        "selected route",
    )
    route_mode = _enum(selected.get("route_mode"), ROUTE_MODES, "route mode")
    roles = _ordered_identifiers(selected.get("role_sequence"), "role sequence")
    concurrency = _positive(selected.get("maximum_concurrency"), "maximum concurrency")
    if roles != _roles(route_mode):
        raise AdaptiveRoutingError("route role sequence is invalid")
    if route_mode != "parallel-dag" and concurrency != 1:
        raise AdaptiveRoutingError("non-parallel route concurrency is invalid")
    if route_mode == "parallel-dag" and concurrency < 2:
        raise AdaptiveRoutingError("parallel route concurrency is invalid")
    reasons = _reason_codes(data.get("reason_codes"), "route reasons", nonempty=True)

    exclusions = data.get("exclusions")
    if isinstance(exclusions, (str, bytes)) or not isinstance(exclusions, Sequence):
        raise AdaptiveRoutingError("route exclusions must be a list")
    parsed_exclusions: list[dict[str, object]] = []
    excluded_modes: set[str] = set()
    for item in exclusions:
        exclusion = _strict(item, {"mode", "reason_codes"}, "route exclusion")
        mode = _enum(exclusion.get("mode"), ROUTE_MODES, "excluded route mode")
        if mode == route_mode or mode in excluded_modes:
            raise AdaptiveRoutingError("route exclusions are invalid")
        excluded_modes.add(mode)
        parsed_exclusions.append(
            {
                "mode": mode,
                "reason_codes": _reason_codes(
                    exclusion.get("reason_codes"), "exclusion reasons", nonempty=True
                ),
            }
        )
    if excluded_modes != ROUTE_MODES - {route_mode}:
        raise AdaptiveRoutingError("route exclusions are incomplete")
    parsed_exclusions.sort(key=lambda item: str(item["mode"]))

    estimated = _strict(
        data.get("estimated"),
        {"input_tokens", "output_tokens", "cost_microunits", "latency_seconds"},
        "route estimate",
    )
    for field in estimated:
        _nonnegative(estimated.get(field), field.replace("_", " "))

    normalized = json.loads(json.dumps(data))
    normalized["reason_codes"] = reasons
    normalized["exclusions"] = parsed_exclusions
    if normalized != data:
        raise AdaptiveRoutingError("route decision values are not canonical")
    expected_digest = _digest(_decision_identity(data))
    if (
        _sha(data.get("route_decision_id"), "route decision id") != expected_digest
        or _sha(data.get("decision_digest"), "decision digest") != expected_digest
    ):
        raise AdaptiveRoutingError("route decision digest is invalid")
    if request is not None:
        checked_request = parse_route_request(request.as_dict(), policy)
        expected_bindings = {
            "request_id": checked_request.payload["request_id"],
            "correlation_id": checked_request.payload["correlation_id"],
            "project_id": checked_request.payload["project_id"],
            "work_item_id": checked_request.payload["work_item_id"],
            "intent_digest": checked_request.payload["intent_digest"],
            "context_digest": checked_request.payload["context_digest"],
        }
        if data["request_digest"] != checked_request.request_digest or bindings != expected_bindings:
            raise AdaptiveRoutingError("route decision does not match the request")
    return RouteDecision(normalized)


def compare_shadow_route(
    policy: AdaptiveRoutingPolicy,
    decision: RouteDecision,
    *,
    observed_route: str,
) -> ShadowRouteComparison:
    checked = parse_route_decision(decision.as_dict(), policy)
    observed = _identifier(observed_route, "observed route")
    mapping = {
        "blocked": "blocked",
        "coordinator-response": "coordinator-response",
        "delegated-dag": "delegated-dag",
    }
    selected = checked.route_mode
    selected_family = (
        "delegated-dag"
        if selected in {"single-worker", "sequential-dag", "parallel-dag"}
        else selected
    )
    if observed not in mapping:
        status = "not-comparable"
        reasons = ["observed-route-unsupported"]
    elif observed == selected_family:
        status = "matched"
        reasons = ["route-family-matched"]
    else:
        status = "mismatch"
        reasons = ["route-family-mismatch"]
    payload: dict[str, object] = {
        "schema_ref": "schemas/route-shadow-comparison.schema.json",
        "schema_version": 1,
        "route_decision_id": checked.decision_digest,
        "observed_route": observed,
        "selected_route": selected,
        "comparison_status": status,
        "reason_codes": reasons,
        "behavior_changed": False,
        "grants_authority": False,
    }
    payload["comparison_digest"] = _digest(payload)
    return parse_shadow_route_comparison(payload)


def parse_shadow_route_comparison(payload: object) -> ShadowRouteComparison:
    fields = {
        "schema_ref",
        "schema_version",
        "route_decision_id",
        "observed_route",
        "selected_route",
        "comparison_status",
        "reason_codes",
        "behavior_changed",
        "grants_authority",
        "comparison_digest",
    }
    data = _strict(payload, fields, "route shadow comparison")
    if (
        data.get("schema_ref") != "schemas/route-shadow-comparison.schema.json"
        or data.get("schema_version") != 1
        or data.get("comparison_status") not in COMPARISON_STATUSES
        or data.get("behavior_changed") is not False
        or data.get("grants_authority") is not False
    ):
        raise AdaptiveRoutingError("route shadow comparison is invalid")
    _sha(data.get("route_decision_id"), "route decision id")
    _identifier(data.get("observed_route"), "observed route")
    _enum(data.get("selected_route"), ROUTE_MODES, "selected route")
    reasons = _reason_codes(data.get("reason_codes"), "comparison reasons", nonempty=True)
    normalized = json.loads(json.dumps(data))
    normalized["reason_codes"] = reasons
    if normalized != data:
        raise AdaptiveRoutingError("route shadow comparison is not canonical")
    expected = _digest({key: value for key, value in data.items() if key != "comparison_digest"})
    if _sha(data.get("comparison_digest"), "comparison digest") != expected:
        raise AdaptiveRoutingError("route shadow comparison digest is invalid")
    return ShadowRouteComparison(normalized)
