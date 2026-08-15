"""Closed-loop model assignment from existing routing and evidence services."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .foundation import load_json
from .information_records import canonical_json
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .model_benchmark import parse_model_benchmark_suite
from .model_health import (
    health_effective_state,
    load_model_health_policy,
    parse_model_health_record,
)
from .model_inventory import parse_model_inventory_record
from .model_routing import load_model_routing_policy
from .mutation_gate import MutationAuthorization
from .orchestration_plan import TaskPlan, parse_task_plan


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ROLES = {"planner", "worker", "verifier"}
WORKLOADS = {
    "analysis",
    "architecture",
    "code-review",
    "database-analysis",
    "discovery",
    "embedding",
    "general",
    "implementation",
    "performance-analysis",
    "planning",
    "reranking",
    "security-review",
    "verification",
}
ROUTING_WORKLOADS = {
    "general",
    "planning",
    "implementation",
    "verification",
    "discovery",
    "embedding",
}
DECISION_INVARIANTS = {
    "stale_evidence_allowed": False,
    "quarantined_model_allowed": False,
    "static_price_embedded_in_core": False,
    "provider_call_during_decision": False,
    "verifier_model_reuse_allowed": False,
    "unknown_client_default_blocks_assignment": False,
    "model_decision_grants_authority": False,
}


class ModelDecisionError(ValueError):
    """Raised when model evidence is unsafe, stale, or inconsistent."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _identifier(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ModelDecisionError(f"{label} is invalid")
    return value


def _sha256(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ModelDecisionError(f"{label} is invalid")
    return value


def _nonnegative(value: object, label: str, *, maximum: int | None = None) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or (maximum is not None and value > maximum)
    ):
        raise ModelDecisionError(f"{label} is invalid")
    return value


def _positive(value: object, label: str, *, maximum: int | None = None) -> int:
    checked = _nonnegative(value, label, maximum=maximum)
    if checked < 1:
        raise ModelDecisionError(f"{label} is invalid")
    return checked


def _timestamp(value: object, label: str) -> tuple[str, datetime]:
    if not isinstance(value, str):
        raise ModelDecisionError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelDecisionError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ModelDecisionError(f"{label} must carry a timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat().replace("+00:00", "Z"), utc


def _now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ModelDecisionError("decision time must carry a timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ModelDecisionPolicy:
    revision: int
    maximum_health_age_seconds: int
    maximum_benchmark_age_seconds: int
    minimum_benchmark_score_basis_points: int
    minimum_runtime_observations: int
    default_success_basis_points: int
    latency_reference_ms: int
    cost_reference_microunits: int
    score_weights: Mapping[str, int]
    workload_route_map: Mapping[str, str]
    policy_digest: str


@dataclass(frozen=True)
class ModelDecision:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)

    @property
    def assignment_id(self) -> str:
        return str(self.payload["model_assignment_id"])


@dataclass(frozen=True)
class ModelEvidencePlan:
    record_type: str
    record_id: str
    record: Mapping[str, object]
    effect_plan: RecordWritePlan | None
    plan_id: str

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "record_digest": _digest(self.record),
            "effect": (
                self.effect_plan.public_summary() if self.effect_plan else None
            ),
            "no_op": self.effect_plan is None,
            "raw_content_included": False,
            "provider_call_performed": False,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class TaskModelAssignments:
    payload: Mapping[str, object]
    decisions: tuple[ModelDecision, ...]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)

    @property
    def assignment_ids(self) -> tuple[str, ...]:
        return tuple(
            str(item["model_assignment_id"])
            for item in self.payload["assignments"]
        )


def parse_model_decision_policy(payload: object) -> ModelDecisionPolicy:
    expected = {
        "schema_ref",
        "schema_version",
        "policy_revision",
        "maximum_health_age_seconds",
        "maximum_benchmark_age_seconds",
        "minimum_benchmark_score_basis_points",
        "minimum_runtime_observations",
        "default_success_basis_points",
        "latency_reference_ms",
        "cost_reference_microunits",
        "score_weights",
        "workload_route_map",
        "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ModelDecisionError("model decision policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-decision-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants") != DECISION_INVARIANTS
    ):
        raise ModelDecisionError("model decision policy contract is invalid")
    revision = _positive(payload.get("policy_revision"), "policy revision")
    maximum_health_age = _positive(
        payload.get("maximum_health_age_seconds"),
        "maximum health age",
        maximum=2592000,
    )
    maximum_benchmark_age = _positive(
        payload.get("maximum_benchmark_age_seconds"),
        "maximum benchmark age",
        maximum=31536000,
    )
    minimum_benchmark = _nonnegative(
        payload.get("minimum_benchmark_score_basis_points"),
        "minimum benchmark score",
        maximum=10000,
    )
    minimum_observations = _positive(
        payload.get("minimum_runtime_observations"),
        "minimum runtime observations",
        maximum=1000,
    )
    default_success = _nonnegative(
        payload.get("default_success_basis_points"),
        "default success",
        maximum=10000,
    )
    latency_reference = _positive(
        payload.get("latency_reference_ms"),
        "latency reference",
        maximum=3600000,
    )
    cost_reference = _positive(
        payload.get("cost_reference_microunits"),
        "cost reference",
    )
    weights = payload.get("score_weights")
    weight_keys = {"benchmark", "success", "latency", "cost"}
    if not isinstance(weights, Mapping) or set(weights) != weight_keys:
        raise ModelDecisionError("model decision weights are invalid")
    checked_weights = {
        key: _nonnegative(weights[key], f"{key} weight", maximum=100)
        for key in sorted(weight_keys)
    }
    if sum(checked_weights.values()) != 100:
        raise ModelDecisionError("model decision weights must total 100")
    routes = payload.get("workload_route_map")
    if not isinstance(routes, Mapping) or set(routes) != WORKLOADS:
        raise ModelDecisionError("model decision workload map is incomplete")
    checked_routes = {}
    for workload, route in routes.items():
        _identifier(workload, "workload")
        if route not in ROUTING_WORKLOADS:
            raise ModelDecisionError("model decision route workload is invalid")
        checked_routes[str(workload)] = str(route)
    return ModelDecisionPolicy(
        revision,
        maximum_health_age,
        maximum_benchmark_age,
        minimum_benchmark,
        minimum_observations,
        default_success,
        latency_reference,
        cost_reference,
        checked_weights,
        checked_routes,
        _digest(payload),
    )


def load_model_decision_policy(repo_root: Path) -> ModelDecisionPolicy:
    return parse_model_decision_policy(
        load_json(repo_root / "config" / "model-decision.json")
    )


def build_model_price_catalog(
    *,
    catalog_id: str,
    catalog_revision: int,
    currency: str,
    observed_at: str,
    expires_at: str,
    entries: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build a dated local catalog without provider calls or endpoints."""

    catalog_id = str(_identifier(catalog_id, "catalog id"))
    catalog_revision = _positive(catalog_revision, "catalog revision")
    observed_text, observed = _timestamp(observed_at, "observed_at")
    expires_text, expires = _timestamp(expires_at, "expires_at")
    if expires <= observed:
        raise ModelDecisionError("price catalog expiry is invalid")
    if not isinstance(currency, str) or not re.fullmatch(r"^[A-Z]{3}$", currency):
        raise ModelDecisionError("price catalog currency is invalid")
    if isinstance(entries, Mapping) or not isinstance(entries, Sequence) or not entries:
        raise ModelDecisionError("price catalog entries are invalid")
    checked = []
    for entry in entries:
        expected = {
            "model_ref",
            "input_microunits_per_million",
            "output_microunits_per_million",
            "fixed_microunits",
        }
        if not isinstance(entry, Mapping) or set(entry) != expected:
            raise ModelDecisionError("price catalog entry fields are invalid")
        checked.append(
            {
                "model_ref": str(_identifier(entry["model_ref"], "model ref")),
                "input_microunits_per_million": _nonnegative(
                    entry["input_microunits_per_million"], "input price"
                ),
                "output_microunits_per_million": _nonnegative(
                    entry["output_microunits_per_million"], "output price"
                ),
                "fixed_microunits": _nonnegative(
                    entry["fixed_microunits"], "fixed price"
                ),
            }
        )
    if len({entry["model_ref"] for entry in checked}) != len(checked):
        raise ModelDecisionError("price catalog model refs are duplicated")
    payload: dict[str, object] = {
        "schema_ref": "schemas/model-price-catalog.schema.json",
        "schema_version": 1,
        "catalog_id": catalog_id,
        "catalog_revision": catalog_revision,
        "currency": currency,
        "observed_at": observed_text,
        "expires_at": expires_text,
        "entries": sorted(checked, key=lambda item: str(item["model_ref"])),
        "catalog_digest": "",
        "invariants": {
            "credentials_included": False,
            "endpoints_included": False,
            "provider_call_performed": False,
            "grants_authority": False,
        },
    }
    payload["catalog_digest"] = _digest(
        {key: value for key, value in payload.items() if key != "catalog_digest"}
    )
    return parse_model_price_catalog(payload)


def parse_model_price_catalog(payload: object) -> dict[str, object]:
    expected = {
        "schema_ref",
        "schema_version",
        "catalog_id",
        "catalog_revision",
        "currency",
        "observed_at",
        "expires_at",
        "entries",
        "catalog_digest",
        "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ModelDecisionError("price catalog fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-price-catalog.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants")
        != {
            "credentials_included": False,
            "endpoints_included": False,
            "provider_call_performed": False,
            "grants_authority": False,
        }
    ):
        raise ModelDecisionError("price catalog contract is invalid")
    _identifier(payload.get("catalog_id"), "catalog id")
    _positive(payload.get("catalog_revision"), "catalog revision")
    if not isinstance(payload.get("currency"), str) or not re.fullmatch(
        r"^[A-Z]{3}$", str(payload.get("currency"))
    ):
        raise ModelDecisionError("price catalog currency is invalid")
    _, observed = _timestamp(payload.get("observed_at"), "observed_at")
    _, expires = _timestamp(payload.get("expires_at"), "expires_at")
    if expires <= observed:
        raise ModelDecisionError("price catalog expiry is invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ModelDecisionError("price catalog entries are invalid")
    refs = []
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "model_ref",
            "input_microunits_per_million",
            "output_microunits_per_million",
            "fixed_microunits",
        }:
            raise ModelDecisionError("price catalog entry fields are invalid")
        refs.append(str(_identifier(entry.get("model_ref"), "model ref")))
        for field in (
            "input_microunits_per_million",
            "output_microunits_per_million",
            "fixed_microunits",
        ):
            _nonnegative(entry.get(field), field)
    if refs != sorted(refs) or len(set(refs)) != len(refs):
        raise ModelDecisionError("price catalog entries are not deterministic")
    digest = str(_sha256(payload.get("catalog_digest"), "catalog digest"))
    identity = {key: value for key, value in payload.items() if key != "catalog_digest"}
    if digest != _digest(identity):
        raise ModelDecisionError("price catalog digest is invalid")
    return dict(payload)


def build_model_benchmark_result(
    suite: Mapping[str, object],
    model: Mapping[str, object],
    *,
    workload_id: str,
    observed_at: str,
    quality_score_basis_points: int,
    reliability_score_basis_points: int,
    latency_ms: int,
    passed: bool,
) -> dict[str, object]:
    suite = parse_model_benchmark_suite(suite)
    model = parse_model_inventory_record(model)
    workload_id = str(_identifier(workload_id, "workload id"))
    case = next(
        (item for item in suite["cases"] if item["workload_id"] == workload_id),
        None,
    )
    if case is None:
        raise ModelDecisionError("benchmark workload was not found")
    observed_text, _ = _timestamp(observed_at, "observed_at")
    quality = _nonnegative(
        quality_score_basis_points, "quality score", maximum=10000
    )
    reliability = _nonnegative(
        reliability_score_basis_points, "reliability score", maximum=10000
    )
    latency = _nonnegative(latency_ms, "benchmark latency", maximum=3600000)
    if not isinstance(passed, bool):
        raise ModelDecisionError("benchmark passed flag is invalid")
    semantic = {
        "project_id": suite["project_id"],
        "model_ref": model["model_ref"],
        "inventory_digest": model["inventory_digest"],
        "suite_digest": suite["suite_digest"],
        "workload_id": workload_id,
        "case_digest": case["case_digest"],
        "observed_at": observed_text,
        "quality_score_basis_points": quality,
        "reliability_score_basis_points": reliability,
        "latency_ms": latency,
        "passed": passed,
    }
    payload: dict[str, object] = {
        "schema_ref": "schemas/model-benchmark-result.schema.json",
        "schema_version": 1,
        "result_id": "benchmark-result-" + _digest(semantic)[:24],
        **semantic,
        "result_digest": _digest(semantic),
        "invariants": {
            "prompt_content_included": False,
            "response_content_included": False,
            "source_content_included": False,
            "grants_authority": False,
        },
    }
    return parse_model_benchmark_result(payload)


def parse_model_benchmark_result(payload: object) -> dict[str, object]:
    expected = {
        "schema_ref",
        "schema_version",
        "result_id",
        "project_id",
        "model_ref",
        "inventory_digest",
        "suite_digest",
        "workload_id",
        "case_digest",
        "observed_at",
        "quality_score_basis_points",
        "reliability_score_basis_points",
        "latency_ms",
        "passed",
        "result_digest",
        "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ModelDecisionError("benchmark result fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-benchmark-result.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants")
        != {
            "prompt_content_included": False,
            "response_content_included": False,
            "source_content_included": False,
            "grants_authority": False,
        }
        or not isinstance(payload.get("passed"), bool)
    ):
        raise ModelDecisionError("benchmark result contract is invalid")
    for field in ("result_id", "project_id", "model_ref", "workload_id"):
        _identifier(payload.get(field), field)
    for field in ("inventory_digest", "suite_digest", "case_digest", "result_digest"):
        _sha256(payload.get(field), field)
    _timestamp(payload.get("observed_at"), "observed_at")
    _nonnegative(payload.get("quality_score_basis_points"), "quality", maximum=10000)
    _nonnegative(
        payload.get("reliability_score_basis_points"),
        "reliability",
        maximum=10000,
    )
    _nonnegative(payload.get("latency_ms"), "latency", maximum=3600000)
    semantic_keys = (
        "project_id",
        "model_ref",
        "inventory_digest",
        "suite_digest",
        "workload_id",
        "case_digest",
        "observed_at",
        "quality_score_basis_points",
        "reliability_score_basis_points",
        "latency_ms",
        "passed",
    )
    semantic = {key: payload[key] for key in semantic_keys}
    if payload["result_digest"] != _digest(semantic):
        raise ModelDecisionError("benchmark result digest is invalid")
    if payload["result_id"] != "benchmark-result-" + _digest(semantic)[:24]:
        raise ModelDecisionError("benchmark result identity is invalid")
    return dict(payload)


def build_model_runtime_observation(
    model: Mapping[str, object],
    *,
    project_id: str,
    workload: str,
    model_assignment_id: str,
    trace_digest: str,
    observed_at: str,
    successful: bool,
    verifier_passed: bool,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    actual_cost_microunits: int,
) -> dict[str, object]:
    model = parse_model_inventory_record(model)
    project_id = str(_identifier(project_id, "project id"))
    workload = str(_identifier(workload, "workload"))
    if workload not in WORKLOADS:
        raise ModelDecisionError("runtime workload is unsupported")
    model_assignment_id = str(
        _identifier(model_assignment_id, "model assignment id")
    )
    trace_digest = str(_sha256(trace_digest, "trace digest"))
    observed_text, _ = _timestamp(observed_at, "observed_at")
    if not isinstance(successful, bool) or not isinstance(verifier_passed, bool):
        raise ModelDecisionError("runtime outcome flags are invalid")
    semantic = {
        "project_id": project_id,
        "model_ref": model["model_ref"],
        "inventory_digest": model["inventory_digest"],
        "workload": workload,
        "model_assignment_id": model_assignment_id,
        "trace_digest": trace_digest,
        "observed_at": observed_text,
        "successful": successful,
        "verifier_passed": verifier_passed,
        "latency_ms": _nonnegative(latency_ms, "runtime latency", maximum=3600000),
        "input_tokens": _nonnegative(input_tokens, "input tokens"),
        "output_tokens": _nonnegative(output_tokens, "output tokens"),
        "actual_cost_microunits": _nonnegative(
            actual_cost_microunits, "actual cost"
        ),
    }
    payload: dict[str, object] = {
        "schema_ref": "schemas/model-runtime-observation.schema.json",
        "schema_version": 1,
        "observation_id": "model-observation-" + _digest(semantic)[:24],
        **semantic,
        "observation_digest": _digest(semantic),
        "invariants": {
            "prompt_content_included": False,
            "response_content_included": False,
            "physical_paths_included": False,
            "grants_authority": False,
        },
    }
    return parse_model_runtime_observation(payload)


def parse_model_runtime_observation(payload: object) -> dict[str, object]:
    expected = {
        "schema_ref",
        "schema_version",
        "observation_id",
        "project_id",
        "model_ref",
        "inventory_digest",
        "workload",
        "model_assignment_id",
        "trace_digest",
        "observed_at",
        "successful",
        "verifier_passed",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "actual_cost_microunits",
        "observation_digest",
        "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ModelDecisionError("runtime observation fields are invalid")
    if (
        payload.get("schema_ref")
        != "schemas/model-runtime-observation.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants")
        != {
            "prompt_content_included": False,
            "response_content_included": False,
            "physical_paths_included": False,
            "grants_authority": False,
        }
    ):
        raise ModelDecisionError("runtime observation contract is invalid")
    for field in (
        "observation_id",
        "project_id",
        "model_ref",
        "workload",
        "model_assignment_id",
    ):
        _identifier(payload.get(field), field)
    if payload.get("workload") not in WORKLOADS:
        raise ModelDecisionError("runtime observation workload is unsupported")
    for field in ("inventory_digest", "trace_digest", "observation_digest"):
        _sha256(payload.get(field), field)
    _timestamp(payload.get("observed_at"), "observed_at")
    if not isinstance(payload.get("successful"), bool) or not isinstance(
        payload.get("verifier_passed"), bool
    ):
        raise ModelDecisionError("runtime observation outcome is invalid")
    _nonnegative(payload.get("latency_ms"), "latency", maximum=3600000)
    for field in ("input_tokens", "output_tokens", "actual_cost_microunits"):
        _nonnegative(payload.get(field), field)
    semantic_keys = (
        "project_id",
        "model_ref",
        "inventory_digest",
        "workload",
        "model_assignment_id",
        "trace_digest",
        "observed_at",
        "successful",
        "verifier_passed",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "actual_cost_microunits",
    )
    semantic = {key: payload[key] for key in semantic_keys}
    if payload["observation_digest"] != _digest(semantic):
        raise ModelDecisionError("runtime observation digest is invalid")
    if payload["observation_id"] != "model-observation-" + _digest(semantic)[:24]:
        raise ModelDecisionError("runtime observation identity is invalid")
    return dict(payload)


def prepare_model_evidence(
    store: LocalWorkspaceStore,
    payload: Mapping[str, object],
    *,
    project_id: str | None = None,
) -> ModelEvidencePlan:
    """Prepare one exact local evidence write without running a model."""

    schema_ref = payload.get("schema_ref") if isinstance(payload, Mapping) else None
    if schema_ref == "schemas/model-price-catalog.schema.json":
        record = parse_model_price_catalog(payload)
        record_type = "model-price-catalogs"
        record_id = str(record["catalog_id"])
        scoped_project = None
    elif schema_ref == "schemas/model-benchmark-result.schema.json":
        record = parse_model_benchmark_result(payload)
        record_type = "model-benchmark-results"
        record_id = str(record["result_id"])
        scoped_project = str(_identifier(project_id, "project id"))
        if record["project_id"] != scoped_project:
            raise ModelDecisionError("benchmark result project does not match")
    elif schema_ref == "schemas/model-runtime-observation.schema.json":
        record = parse_model_runtime_observation(payload)
        record_type = "model-runtime-observations"
        record_id = str(record["observation_id"])
        scoped_project = str(_identifier(project_id, "project id"))
        if record["project_id"] != scoped_project:
            raise ModelDecisionError("runtime observation project does not match")
    else:
        raise ModelDecisionError("model evidence schema is unsupported")
    current = store.read(record_type, record_id)
    effect = None
    if current is not None:
        if record_type == "model-price-catalogs":
            if _digest(current.payload) == _digest(record):
                if int(record["catalog_revision"]) != current.revision:
                    raise ModelDecisionError("price catalog revision is stale")
            elif int(record["catalog_revision"]) != current.revision + 1:
                raise ModelDecisionError("price catalog revision is stale")
            else:
                effect = store.prepare_put(
                    record_type,
                    record_id,
                    record,
                    expected_revision=current.revision,
                )
        elif _digest(current.payload) != _digest(record):
            raise ModelDecisionError("model evidence identity collision")
    else:
        if record_type == "model-price-catalogs" and int(
            record["catalog_revision"]
        ) != 1:
            raise ModelDecisionError("new price catalog revision must be 1")
        effect = store.prepare_put(
            record_type,
            record_id,
            record,
            expected_revision=0,
            project_id=scoped_project,
        )
    identity = {
        "record_type": record_type,
        "record_id": record_id,
        "record_digest": _digest(record),
        "effect_plan_id": effect.mutation.plan_id if effect else None,
    }
    return ModelEvidencePlan(
        record_type,
        record_id,
        record,
        effect,
        _digest(identity),
    )


def apply_model_evidence(
    store: LocalWorkspaceStore,
    plan: ModelEvidencePlan,
    authorization: MutationAuthorization | None,
    *,
    expected_plan_id: str,
) -> dict[str, object]:
    """Apply only the exact prepared evidence plan."""

    if expected_plan_id != plan.plan_id:
        raise ModelDecisionError("model evidence exact plan does not match")
    if plan.effect_plan is None:
        if authorization is not None:
            raise ModelDecisionError("no-op model evidence accepts no authorization")
        return dict(plan.record)
    if authorization is None:
        raise ModelDecisionError("model evidence authorization is required")
    stored = store.apply_put(plan.effect_plan, authorization)
    if plan.record_type == "model-price-catalogs":
        return parse_model_price_catalog(stored.payload)
    if plan.record_type == "model-benchmark-results":
        return parse_model_benchmark_result(stored.payload)
    return parse_model_runtime_observation(stored.payload)


def decide_model_assignment_from_store(
    repo_root: Path,
    store: LocalWorkspaceStore,
    *,
    project_id: str,
    client_id: str,
    workload: str,
    role: str,
    available_bindings: Mapping[str, str],
    price_catalog_id: str | None,
    now: datetime,
    input_token_budget: int,
    output_token_budget: int,
    maximum_cost_microunits: int | None = None,
    maximum_latency_ms: int | None = None,
    excluded_model_refs: Sequence[str] = (),
) -> ModelDecision:
    """Resolve one decision from durable sanitized local records."""

    project_id = str(_identifier(project_id, "project id"))
    inventory = [
        item.payload for item in store.list_records("model-inventory")
    ]
    health = [item.payload for item in store.list_records("model-health")]
    suite_record = store.read(
        "model-benchmark-suites",
        f"{project_id}-micro-benchmark",
    )
    suite = suite_record.payload if suite_record is not None else None
    benchmark_results = [
        item.payload
        for item in store.list_records("model-benchmark-results")
        if item.payload.get("project_id") == project_id
    ]
    observations = [
        item.payload
        for item in store.list_records("model-runtime-observations")
        if item.payload.get("project_id") == project_id
    ]
    catalog = None
    if price_catalog_id is not None:
        price_catalog_id = str(_identifier(price_catalog_id, "price catalog id"))
        stored_catalog = store.read("model-price-catalogs", price_catalog_id)
        if stored_catalog is None:
            raise ModelDecisionError("price catalog was not found")
        catalog = stored_catalog.payload
    return decide_model_assignment(
        repo_root,
        project_id=project_id,
        client_id=client_id,
        workload=workload,
        role=role,
        available_bindings=available_bindings,
        inventory_records=inventory,
        health_records=health,
        benchmark_suite=suite,
        benchmark_results=benchmark_results,
        runtime_observations=observations,
        price_catalog=catalog,
        now=now,
        input_token_budget=input_token_budget,
        output_token_budget=output_token_budget,
        maximum_cost_microunits=maximum_cost_microunits,
        maximum_latency_ms=maximum_latency_ms,
        excluded_model_refs=excluded_model_refs,
    )


def decide_task_plan_model_assignments_from_store(
    repo_root: Path,
    store: LocalWorkspaceStore,
    *,
    project_id: str,
    client_id: str,
    task_plan: TaskPlan,
    step_workloads: Mapping[str, str],
    available_bindings: Mapping[str, str],
    price_catalog_id: str | None,
    now: datetime,
    input_token_budget: int,
    output_token_budget: int,
    maximum_cost_microunits: int | None = None,
    maximum_latency_ms: int | None = None,
) -> TaskModelAssignments:
    """Bind one closed-loop decision to every executable TaskPlan step."""

    checked_plan = parse_task_plan(task_plan.as_dict())
    if not isinstance(step_workloads, Mapping) or set(step_workloads) != {
        step.step_id for step in checked_plan.steps
    }:
        raise ModelDecisionError("step workload coverage is incomplete")
    decisions: list[ModelDecision] = []
    assignments = []
    worker_refs: set[str] = set()
    worker_ids: set[str] = set()
    unknown_default = False
    for step in checked_plan.steps:
        workload = step_workloads[step.step_id]
        if not isinstance(workload, str) or workload not in WORKLOADS:
            raise ModelDecisionError("step workload is unsupported")
        excluded = sorted(worker_refs) if step.role == "verifier" else []
        decision = decide_model_assignment_from_store(
            repo_root,
            store,
            project_id=project_id,
            client_id=client_id,
            workload=workload,
            role=step.role,
            available_bindings=available_bindings,
            price_catalog_id=price_catalog_id,
            now=now,
            input_token_budget=input_token_budget,
            output_token_budget=output_token_budget,
            maximum_cost_microunits=maximum_cost_microunits,
            maximum_latency_ms=maximum_latency_ms,
            excluded_model_refs=excluded,
        )
        decision_payload = decision.as_dict()
        selected_ref = decision_payload["selected_model_ref"]
        selected_id = decision_payload["selected_model_id"]
        if step.role == "verifier" and (
            (selected_ref is not None and selected_ref in worker_refs)
            or (selected_id is not None and selected_id in worker_ids)
        ):
            raise ModelDecisionError("verifier model reuse is not allowed")
        if step.role == "worker":
            if selected_ref is not None:
                worker_refs.add(str(selected_ref))
            if selected_id is not None:
                worker_ids.add(str(selected_id))
        if selected_ref is None:
            unknown_default = True
        assignment_id = "model-assignment-" + _digest(
            {
                "task_plan_id": checked_plan.plan_id,
                "step_id": step.step_id,
                "decision_digest": decision_payload["decision_digest"],
            }
        )[:24]
        assignments.append(
            {
                "step_id": step.step_id,
                "role": step.role,
                "workload": workload,
                "decision_id": decision_payload["decision_id"],
                "decision_digest": decision_payload["decision_digest"],
                "model_assignment_id": assignment_id,
                "model_ref": selected_ref,
                "model_id": selected_id,
                "selection_basis": decision_payload["selection_basis"],
            }
        )
        decisions.append(decision)
    payload: dict[str, object] = {
        "schema_ref": "schemas/task-model-assignments.schema.json",
        "schema_version": 1,
        "task_id": checked_plan.task_id,
        "task_plan_id": checked_plan.plan_id,
        "project_id": str(_identifier(project_id, "project id")),
        "client_id": str(_identifier(client_id, "client id")),
        "assignments": assignments,
        "worker_model_refs": sorted(worker_refs),
        "verifier_model_reuse_detected": False,
        "unknown_client_default_used": unknown_default,
        "assignment_digest": "",
        "provider_call_performed": False,
        "grants_authority": False,
    }
    payload["assignment_digest"] = _digest(
        {key: value for key, value in payload.items() if key != "assignment_digest"}
    )
    return parse_task_model_assignments(payload, decisions=tuple(decisions))


def parse_task_model_assignments(
    payload: object,
    *,
    decisions: Sequence[ModelDecision] = (),
) -> TaskModelAssignments:
    expected = {
        "schema_ref",
        "schema_version",
        "task_id",
        "task_plan_id",
        "project_id",
        "client_id",
        "assignments",
        "worker_model_refs",
        "verifier_model_reuse_detected",
        "unknown_client_default_used",
        "assignment_digest",
        "provider_call_performed",
        "grants_authority",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ModelDecisionError("task model assignment fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/task-model-assignments.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("verifier_model_reuse_detected") is not False
        or not isinstance(payload.get("unknown_client_default_used"), bool)
        or payload.get("provider_call_performed") is not False
        or payload.get("grants_authority") is not False
    ):
        raise ModelDecisionError("task model assignment contract is invalid")
    for field in ("task_id", "project_id", "client_id"):
        _identifier(payload.get(field), field)
    task_plan_id = str(_sha256(payload.get("task_plan_id"), "task plan id"))
    assignments = payload.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        raise ModelDecisionError("task model assignments are invalid")
    step_ids = []
    assignment_ids = []
    decision_digests = []
    worker_refs = set()
    worker_model_ids = set()
    unknown = False
    for item in assignments:
        if not isinstance(item, Mapping) or set(item) != {
            "step_id",
            "role",
            "workload",
            "decision_id",
            "decision_digest",
            "model_assignment_id",
            "model_ref",
            "model_id",
            "selection_basis",
        }:
            raise ModelDecisionError("task model assignment entry is invalid")
        step_id = str(_identifier(item.get("step_id"), "step id"))
        step_ids.append(step_id)
        if item.get("role") not in {"worker", "verifier"}:
            raise ModelDecisionError("task model assignment role is invalid")
        if item.get("workload") not in WORKLOADS:
            raise ModelDecisionError("task model assignment workload is invalid")
        _identifier(item.get("decision_id"), "decision id")
        decision_digest = str(
            _sha256(item.get("decision_digest"), "decision digest")
        )
        decision_digests.append(decision_digest)
        assignment_id = str(
            _identifier(item.get("model_assignment_id"), "model assignment id")
        )
        assignment_ids.append(assignment_id)
        expected_assignment_id = "model-assignment-" + _digest(
            {
                "task_plan_id": task_plan_id,
                "step_id": step_id,
                "decision_digest": decision_digest,
            }
        )[:24]
        if assignment_id != expected_assignment_id:
            raise ModelDecisionError("task model assignment identity is invalid")
        model_ref = _identifier(item.get("model_ref"), "model ref", nullable=True)
        model_id = item.get("model_id")
        if model_id is not None and (
            not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id)
        ):
            raise ModelDecisionError("task model id is invalid")
        if not isinstance(item.get("selection_basis"), str):
            raise ModelDecisionError("task model selection basis is invalid")
        if item["role"] == "worker":
            if model_ref is not None:
                worker_refs.add(str(model_ref))
            if model_id is not None:
                worker_model_ids.add(str(model_id))
        elif (
            (model_ref is not None and model_ref in worker_refs)
            or (model_id is not None and model_id in worker_model_ids)
        ):
            raise ModelDecisionError("verifier model reuse is not allowed")
        if model_ref is None:
            unknown = True
    if len(set(step_ids)) != len(step_ids) or len(set(assignment_ids)) != len(
        assignment_ids
    ):
        raise ModelDecisionError("task model assignments are duplicated")
    refs = payload.get("worker_model_refs")
    if not isinstance(refs, list) or refs != sorted(worker_refs):
        raise ModelDecisionError("worker model refs are inconsistent")
    if payload["unknown_client_default_used"] != unknown:
        raise ModelDecisionError("unknown client default state is inconsistent")
    checked_decisions = tuple(
        parse_model_decision(decision.as_dict()) for decision in decisions
    )
    if checked_decisions and {
        decision.as_dict()["decision_digest"] for decision in checked_decisions
    } != set(decision_digests):
        raise ModelDecisionError("task model decisions do not match assignments")
    digest = str(_sha256(payload.get("assignment_digest"), "assignment digest"))
    identity = {key: value for key, value in payload.items() if key != "assignment_digest"}
    if digest != _digest(identity):
        raise ModelDecisionError("task model assignment digest is invalid")
    return TaskModelAssignments(dict(payload), checked_decisions)


def _age_seconds(now: datetime, value: object, label: str) -> int:
    _, observed = _timestamp(value, label)
    age = int((now - observed).total_seconds())
    if age < 0:
        raise ModelDecisionError(f"{label} is in the future")
    return age


def _estimated_cost(
    entry: Mapping[str, object],
    input_tokens: int,
    output_tokens: int,
) -> int:
    return (
        int(entry["fixed_microunits"])
        + (input_tokens * int(entry["input_microunits_per_million"]) + 999999)
        // 1000000
        + (output_tokens * int(entry["output_microunits_per_million"]) + 999999)
        // 1000000
    )


def _score(
    policy: ModelDecisionPolicy,
    *,
    benchmark: int,
    success: int,
    latency_ms: int,
    cost_microunits: int,
) -> int:
    latency_value = 10000 - min(
        10000,
        latency_ms * 10000 // policy.latency_reference_ms,
    )
    cost_value = 10000 - min(
        10000,
        cost_microunits * 10000 // policy.cost_reference_microunits,
    )
    values = {
        "benchmark": benchmark,
        "success": success,
        "latency": latency_value,
        "cost": cost_value,
    }
    return sum(
        values[key] * policy.score_weights[key] for key in values
    ) // 100


def decide_model_assignment(
    repo_root: Path,
    *,
    project_id: str,
    client_id: str,
    workload: str,
    role: str,
    available_bindings: Mapping[str, str],
    inventory_records: Sequence[Mapping[str, object]],
    health_records: Sequence[Mapping[str, object]],
    benchmark_suite: Mapping[str, object] | None,
    benchmark_results: Sequence[Mapping[str, object]],
    runtime_observations: Sequence[Mapping[str, object]],
    price_catalog: Mapping[str, object] | None,
    now: datetime,
    input_token_budget: int,
    output_token_budget: int,
    maximum_cost_microunits: int | None = None,
    maximum_latency_ms: int | None = None,
    excluded_model_refs: Sequence[str] = (),
) -> ModelDecision:
    """Choose one assignment without performing a provider or model call."""

    project_id = str(_identifier(project_id, "project id"))
    client_id = str(_identifier(client_id, "client id"))
    workload = str(_identifier(workload, "workload"))
    if workload not in WORKLOADS:
        raise ModelDecisionError("decision workload is unsupported")
    if role not in ROLES:
        raise ModelDecisionError("decision role is invalid")
    input_token_budget = _nonnegative(input_token_budget, "input token budget")
    output_token_budget = _nonnegative(output_token_budget, "output token budget")
    if maximum_cost_microunits is not None:
        maximum_cost_microunits = _nonnegative(
            maximum_cost_microunits, "maximum cost"
        )
    if maximum_latency_ms is not None:
        maximum_latency_ms = _positive(
            maximum_latency_ms, "maximum latency", maximum=3600000
        )
    now = _now(now)
    policy = load_model_decision_policy(repo_root)
    routing = load_model_routing_policy(repo_root)
    health_policy = load_model_health_policy(repo_root)
    route_workload = policy.workload_route_map[workload]
    profile = routing.profile_for_workload(route_workload)
    if role in routing.role_defaults and route_workload != "embedding":
        role_profile = routing.profile(routing.role_defaults[role])
        if role_profile.workload == route_workload:
            profile = role_profile

    bindings = dict(available_bindings)
    if any(
        ref not in {candidate.candidate_ref for candidate in routing.candidates}
        or not isinstance(model_id, str)
        or not MODEL_ID.fullmatch(model_id)
        for ref, model_id in bindings.items()
    ):
        raise ModelDecisionError("available bindings are invalid")
    excluded_refs = {
        str(_identifier(value, "excluded model ref")) for value in excluded_model_refs
    }
    inventory = [parse_model_inventory_record(item) for item in inventory_records]
    by_model_id: dict[str, Mapping[str, object]] = {}
    for model in inventory:
        model_id = str(model["model_id"])
        if model_id in by_model_id:
            raise ModelDecisionError("inventory model ids must be unique")
        by_model_id[model_id] = model
    health_by_ref = {}
    for item in health_records:
        parsed = parse_model_health_record(item)
        ref = str(parsed["model_ref"])
        if ref in health_by_ref:
            raise ModelDecisionError("health model refs must be unique")
        health_by_ref[ref] = parsed
    suite = parse_model_benchmark_suite(benchmark_suite) if benchmark_suite else None
    if suite is not None and suite["project_id"] != project_id:
        raise ModelDecisionError("benchmark suite project does not match")
    benchmark_by_ref = {}
    for item in benchmark_results:
        parsed = parse_model_benchmark_result(item)
        if parsed["project_id"] != project_id or parsed["workload_id"] != workload:
            continue
        ref = str(parsed["model_ref"])
        if ref in benchmark_by_ref:
            raise ModelDecisionError("benchmark result model refs must be unique")
        benchmark_by_ref[ref] = parsed
    observations = [parse_model_runtime_observation(item) for item in runtime_observations]
    catalog = parse_model_price_catalog(price_catalog) if price_catalog else None
    price_by_ref = {
        str(entry["model_ref"]): entry for entry in catalog["entries"]
    } if catalog else {}
    if catalog is not None:
        _, expires = _timestamp(catalog["expires_at"], "expires_at")
        if now >= expires:
            raise ModelDecisionError("price catalog is stale")

    eligible: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    evidence_digests: set[str] = set()
    candidates = {candidate.candidate_ref: candidate for candidate in routing.candidates}
    for preference_index, candidate_ref in enumerate(profile.preferred_refs):
        candidate = candidates[candidate_ref]
        if candidate_ref == "client-default" and candidate_ref not in bindings:
            continue
        if candidate.kind == "offline":
            if workload != "embedding":
                continue
            eligible.append(
                {
                    "candidate_ref": candidate_ref,
                    "model_ref": None,
                    "model_id": candidate_ref,
                    "score_basis_points": 0,
                    "estimated_latency_ms": 0,
                    "estimated_cost_microunits": 0,
                    "preference_index": preference_index,
                    "basis": "offline-fallback",
                }
            )
            continue
        model_id = bindings.get(candidate_ref)
        if model_id is None:
            continue
        reasons = []
        model = by_model_id.get(model_id)
        if model is None:
            reasons.append("inventory-missing")
        if model is not None:
            model_ref = str(model["model_ref"])
            if model_ref in excluded_refs:
                reasons.append("verifier-independence")
            if model["enabled"] is not True:
                reasons.append("inventory-disabled")
            if workload not in model["supported_workloads"]:
                reasons.append("workload-unsupported")
            if client_id not in model["client_refs"]:
                reasons.append("client-unsupported")
            health = health_by_ref.get(model_ref)
            if health is None:
                reasons.append("health-missing")
            else:
                evidence_digests.add(str(health["result_digest"]))
                if (
                    health["inventory_digest"] != model["inventory_digest"]
                    or health["policy_digest"] != health_policy.policy_digest
                ):
                    reasons.append("health-stale")
                elif _age_seconds(now, health["checked_at"], "health checked_at") > policy.maximum_health_age_seconds:
                    reasons.append("health-stale")
                elif health_effective_state(health, now) != "health-passed":
                    reasons.append("health-unavailable")
            benchmark = benchmark_by_ref.get(model_ref)
            if suite is None or benchmark is None:
                reasons.append("benchmark-missing")
            else:
                evidence_digests.add(str(benchmark["result_digest"]))
                case = next(
                    (item for item in suite["cases"] if item["workload_id"] == workload),
                    None,
                )
                if (
                    case is None
                    or benchmark["suite_digest"] != suite["suite_digest"]
                    or benchmark["case_digest"] != case["case_digest"]
                    or benchmark["inventory_digest"] != model["inventory_digest"]
                ):
                    reasons.append("benchmark-stale")
                elif _age_seconds(now, benchmark["observed_at"], "benchmark observed_at") > policy.maximum_benchmark_age_seconds:
                    reasons.append("benchmark-stale")
                elif (
                    benchmark["passed"] is not True
                    or (
                        int(benchmark["quality_score_basis_points"])
                        + int(benchmark["reliability_score_basis_points"])
                    )
                    // 2
                    < policy.minimum_benchmark_score_basis_points
                ):
                    reasons.append("benchmark-failed")
            price = price_by_ref.get(model_ref)
            if model["remote"] is True and price is None:
                reasons.append("price-missing")
            matching_observations = [
                item
                for item in observations
                if item["project_id"] == project_id
                and item["model_ref"] == model_ref
                and item["workload"] == workload
                and item["inventory_digest"] == model["inventory_digest"]
            ]
            for observation in matching_observations:
                evidence_digests.add(str(observation["observation_digest"]))
            if not reasons and benchmark is not None and health is not None:
                benchmark_score = (
                    int(benchmark["quality_score_basis_points"])
                    + int(benchmark["reliability_score_basis_points"])
                ) // 2
                if len(matching_observations) >= policy.minimum_runtime_observations:
                    successes = sum(
                        item["successful"] and item["verifier_passed"]
                        for item in matching_observations
                    )
                    success_score = successes * 10000 // len(matching_observations)
                    latency = sum(
                        int(item["latency_ms"]) for item in matching_observations
                    ) // len(matching_observations)
                else:
                    success_score = policy.default_success_basis_points
                    latency = (
                        int(benchmark["latency_ms"]) + int(health["latency_ms"])
                    ) // 2
                cost = (
                    _estimated_cost(price, input_token_budget, output_token_budget)
                    if price is not None
                    else 0
                )
                if maximum_cost_microunits is not None and cost > maximum_cost_microunits:
                    reasons.append("cost-budget-exceeded")
                if maximum_latency_ms is not None and latency > maximum_latency_ms:
                    reasons.append("latency-budget-exceeded")
                if not reasons:
                    eligible.append(
                        {
                            "candidate_ref": candidate_ref,
                            "model_ref": model_ref,
                            "model_id": model_id,
                            "score_basis_points": _score(
                                policy,
                                benchmark=benchmark_score,
                                success=success_score,
                                latency_ms=latency,
                                cost_microunits=cost,
                            ),
                            "estimated_latency_ms": latency,
                            "estimated_cost_microunits": cost,
                            "preference_index": preference_index,
                            "basis": "qualified-net-value",
                        }
                    )
        if reasons:
            excluded.append(
                {
                    "candidate_ref": candidate_ref,
                    "reason_codes": sorted(set(reasons)),
                }
            )

    eligible.sort(
        key=lambda item: (
            -int(item["score_basis_points"]),
            int(item["preference_index"]),
            str(item["candidate_ref"]),
        )
    )
    if eligible:
        selected = eligible[0]
    else:
        default_model_id = bindings.get("client-default")
        selected = {
            "candidate_ref": "client-default",
            "model_ref": None,
            "model_id": default_model_id,
            "score_basis_points": None,
            "estimated_latency_ms": None,
            "estimated_cost_microunits": None,
            "preference_index": len(profile.preferred_refs),
            "basis": "client-default-fallback",
        }
    fallback_entries = []
    for item in eligible:
        if item is selected:
            continue
        fallback_entries.append(
            {
                "candidate_ref": item["candidate_ref"],
                "model_ref": item["model_ref"],
                "model_id": item["model_id"],
                "score_basis_points": item["score_basis_points"],
            }
        )
    if (
        selected["candidate_ref"] != "client-default"
        and not any(
            item["candidate_ref"] == "client-default"
            for item in fallback_entries
        )
    ):
        fallback_entries.append(
            {
                "candidate_ref": "client-default",
                "model_ref": None,
                "model_id": bindings.get("client-default"),
                "score_basis_points": None,
            }
        )
    decision_identity = {
        "project_id": project_id,
        "client_id": client_id,
        "workload": workload,
        "routing_workload": route_workload,
        "role": role,
        "selected_candidate_ref": selected["candidate_ref"],
        "selected_model_ref": selected["model_ref"],
        "selected_model_id": selected["model_id"],
        "score_basis_points": selected["score_basis_points"],
        "estimated_latency_ms": selected["estimated_latency_ms"],
        "estimated_cost_microunits": selected["estimated_cost_microunits"],
        "fallbacks": fallback_entries,
        "excluded_candidates": sorted(
            excluded, key=lambda item: str(item["candidate_ref"])
        ),
        "evidence_digests": sorted(evidence_digests),
        "policy_digest": policy.policy_digest,
        "routing_policy_digest": routing.policy_digest,
        "price_catalog_digest": catalog["catalog_digest"] if catalog else None,
    }
    decision_id = "model-decision-" + _digest(decision_identity)[:24]
    assignment_id = "model-assignment-" + _digest(
        {"decision_id": decision_id, "selected": selected["candidate_ref"]}
    )[:24]
    payload: dict[str, object] = {
        "schema_ref": "schemas/model-decision.schema.json",
        "schema_version": 1,
        "decision_id": decision_id,
        **decision_identity,
        "model_assignment_id": assignment_id,
        "selection_basis": selected["basis"],
        "decision_digest": "",
        "provider_call_performed": False,
        "grants_authority": False,
    }
    payload["decision_digest"] = _digest(
        {key: value for key, value in payload.items() if key != "decision_digest"}
    )
    return parse_model_decision(payload)


def parse_model_decision(payload: object) -> ModelDecision:
    expected = {
        "schema_ref",
        "schema_version",
        "decision_id",
        "project_id",
        "client_id",
        "workload",
        "routing_workload",
        "role",
        "selected_candidate_ref",
        "selected_model_ref",
        "selected_model_id",
        "model_assignment_id",
        "selection_basis",
        "score_basis_points",
        "estimated_latency_ms",
        "estimated_cost_microunits",
        "fallbacks",
        "excluded_candidates",
        "evidence_digests",
        "policy_digest",
        "routing_policy_digest",
        "price_catalog_digest",
        "decision_digest",
        "provider_call_performed",
        "grants_authority",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ModelDecisionError("model decision fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-decision.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("role") not in ROLES
        or payload.get("workload") not in WORKLOADS
        or payload.get("routing_workload") not in ROUTING_WORKLOADS
        or payload.get("selection_basis")
        not in {
            "qualified-net-value",
            "client-default-fallback",
            "offline-fallback",
        }
        or payload.get("provider_call_performed") is not False
        or payload.get("grants_authority") is not False
    ):
        raise ModelDecisionError("model decision contract is invalid")
    for field in (
        "decision_id",
        "project_id",
        "client_id",
        "workload",
        "routing_workload",
        "selected_candidate_ref",
        "model_assignment_id",
    ):
        _identifier(payload.get(field), field)
    _identifier(payload.get("selected_model_ref"), "selected model ref", nullable=True)
    selected_model_id = payload.get("selected_model_id")
    if selected_model_id is not None and (
        not isinstance(selected_model_id, str)
        or not MODEL_ID.fullmatch(selected_model_id)
    ):
        raise ModelDecisionError("selected model id is invalid")
    score = payload.get("score_basis_points")
    if score is not None:
        _nonnegative(score, "decision score", maximum=10000)
    for field in ("estimated_latency_ms", "estimated_cost_microunits"):
        value = payload.get(field)
        if value is not None:
            _nonnegative(value, field)
    fallbacks = payload.get("fallbacks")
    if not isinstance(fallbacks, list):
        raise ModelDecisionError("model decision fallbacks are invalid")
    fallback_refs = []
    for fallback in fallbacks:
        if not isinstance(fallback, Mapping) or set(fallback) != {
            "candidate_ref",
            "model_ref",
            "model_id",
            "score_basis_points",
        }:
            raise ModelDecisionError("model decision fallback fields are invalid")
        fallback_refs.append(
            str(_identifier(fallback.get("candidate_ref"), "fallback candidate"))
        )
        _identifier(fallback.get("model_ref"), "fallback model", nullable=True)
        fallback_model_id = fallback.get("model_id")
        if fallback_model_id is not None and (
            not isinstance(fallback_model_id, str)
            or not MODEL_ID.fullmatch(fallback_model_id)
        ):
            raise ModelDecisionError("fallback model id is invalid")
        if fallback.get("score_basis_points") is not None:
            _nonnegative(
                fallback.get("score_basis_points"),
                "fallback score",
                maximum=10000,
            )
    if len(set(fallback_refs)) != len(fallback_refs):
        raise ModelDecisionError("model decision fallbacks are duplicated")
    exclusions = payload.get("excluded_candidates")
    if not isinstance(exclusions, list):
        raise ModelDecisionError("model decision exclusions are invalid")
    exclusion_refs = []
    for exclusion in exclusions:
        if not isinstance(exclusion, Mapping) or set(exclusion) != {
            "candidate_ref",
            "reason_codes",
        }:
            raise ModelDecisionError("model decision exclusion fields are invalid")
        exclusion_refs.append(
            str(_identifier(exclusion.get("candidate_ref"), "excluded candidate"))
        )
        reasons = exclusion.get("reason_codes")
        if not isinstance(reasons, list) or not reasons:
            raise ModelDecisionError("model decision exclusion reasons are invalid")
        for reason in reasons:
            _identifier(reason, "exclusion reason")
        if reasons != sorted(set(reasons)):
            raise ModelDecisionError("model decision exclusion reasons are not deterministic")
    if exclusion_refs != sorted(set(exclusion_refs)):
        raise ModelDecisionError("model decision exclusions are not deterministic")
    evidence = payload.get("evidence_digests")
    if not isinstance(evidence, list):
        raise ModelDecisionError("model decision evidence is invalid")
    for digest in evidence:
        _sha256(digest, "evidence digest")
    if evidence != sorted(set(evidence)):
        raise ModelDecisionError("model decision evidence is not deterministic")
    for field in (
        "policy_digest",
        "routing_policy_digest",
        "decision_digest",
    ):
        _sha256(payload.get(field), field)
    _sha256(payload.get("price_catalog_digest"), "price catalog digest", nullable=True)
    decision_digest = str(payload["decision_digest"])
    identity = {key: value for key, value in payload.items() if key != "decision_digest"}
    if decision_digest != _digest(identity):
        raise ModelDecisionError("model decision digest is invalid")
    decision_id = "model-decision-" + _digest(
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "schema_ref",
                "schema_version",
                "decision_id",
                "model_assignment_id",
                "selection_basis",
                "decision_digest",
                "provider_call_performed",
                "grants_authority",
            }
        }
    )[:24]
    if payload["decision_id"] != decision_id:
        raise ModelDecisionError("model decision identity is invalid")
    expected_assignment = "model-assignment-" + _digest(
        {
            "decision_id": decision_id,
            "selected": payload["selected_candidate_ref"],
        }
    )[:24]
    if payload["model_assignment_id"] != expected_assignment:
        raise ModelDecisionError("model assignment identity is invalid")
    fallback = payload["selection_basis"] in {
        "client-default-fallback",
        "offline-fallback",
    }
    if fallback != (payload["score_basis_points"] in {None, 0}):
        raise ModelDecisionError("model decision fallback score is inconsistent")
    return ModelDecision(dict(payload))
