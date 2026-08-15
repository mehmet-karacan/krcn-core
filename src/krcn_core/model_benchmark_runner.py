"""Offline-first, injected-adapter execution for project model benchmarks.

The runner deliberately owns no provider discovery and persists nothing.  It
turns an already reviewed benchmark suite, inventory record, health record,
execution profile, and exact plan into sanitized provenance records.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .information_records import canonical_json
from .model_benchmark import parse_model_benchmark_suite
from .model_decision import (
    build_model_benchmark_result,
    build_model_runtime_observation,
    parse_model_benchmark_result,
    parse_model_runtime_observation,
)
from .model_health import health_effective_state, parse_model_health_record
from .model_inventory import parse_model_inventory_record
from .provider_gate import ProviderAuthorization


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
FAILURE_CATEGORIES = {
    "adapter-error",
    "evidence-failed",
    "format-failed",
    "parse-failed",
    "timeout",
    "verifier-failed",
}
FIXTURE_POLICIES = {"synthetic-only", "sanitized-derived", "local-only"}
PROFILE_INVARIANTS = {
    "credential_values_included": False,
    "endpoint_included": False,
    "physical_paths_included": False,
    "grants_authority": False,
}
PLAN_INVARIANTS = {
    "adapter_discovered": False,
    "provider_call_performed": False,
    "prompt_content_included": False,
    "source_content_included": False,
    "credential_values_included": False,
    "physical_paths_included": False,
    "grants_authority": False,
}
RESULT_INVARIANTS = {
    "prompt_content_included": False,
    "response_content_included": False,
    "source_content_included": False,
    "credential_values_included": False,
    "physical_paths_included": False,
    "grants_authority": False,
}


class ModelBenchmarkRunnerError(ValueError):
    """Raised when execution provenance is unsafe, stale, or inconsistent."""


class BenchmarkAdapter(Protocol):
    """A caller-injected adapter; the runner never discovers one implicitly."""

    def __call__(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class ModelBenchmarkRunnerPolicy:
    policy_revision: int
    minimum_repetitions: int
    maximum_repetitions: int
    minimum_confidence_samples: int
    default_timeout_ms: int
    maximum_timeout_ms: int
    minimum_quality_basis_points: int
    minimum_reliability_basis_points: int
    require_all_trials_verifier_approved: bool
    policy_digest: str


@dataclass(frozen=True)
class BenchmarkRunOutput:
    """Compatibility-friendly, non-persisted result from one exact run."""

    plan: Mapping[str, object]
    trials: tuple[Mapping[str, object], ...]
    aggregate: Mapping[str, object]
    benchmark_records: tuple[Mapping[str, object], ...]
    runtime_observations: tuple[Mapping[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "plan": dict(self.plan),
            "trials": [dict(item) for item in self.trials],
            "aggregate": dict(self.aggregate),
            "benchmark_records": [dict(item) for item in self.benchmark_records],
            "runtime_observations": [dict(item) for item in self.runtime_observations],
            "store_mutated": False,
            "grants_authority": False,
        }


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ModelBenchmarkRunnerError(f"{label} is invalid")
    return value


def _revision(value: object, label: str) -> str:
    if not isinstance(value, str) or not REVISION.fullmatch(value):
        raise ModelBenchmarkRunnerError(f"{label} is invalid")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ModelBenchmarkRunnerError(f"{label} is invalid")
    return value


def _integer(value: object, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ModelBenchmarkRunnerError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ModelBenchmarkRunnerError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelBenchmarkRunnerError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelBenchmarkRunnerError(f"{label} requires a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelBenchmarkRunnerError("current time requires a timezone")
    return value.astimezone(timezone.utc)


def _safe(payload: object, label: str) -> None:
    """Reject physical paths and common credential shapes without echoing them."""

    try:
        text = canonical_json(payload).decode("utf-8")
    except ValueError as exc:
        raise ModelBenchmarkRunnerError(f"{label} is not JSON compatible") from exc
    patterns = (
        re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/]"),
        re.compile(r"/(?:Users|home)/[^/\s]+/"),
        re.compile(r"\\\\[^\\\s]+\\"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"(?i)(?:password|passwd|api[_-]?key|client[_-]?secret|access[_-]?token)\s*[:=]"),
        re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+"),
    )
    if any(pattern.search(text) for pattern in patterns):
        raise ModelBenchmarkRunnerError(f"{label} contains prohibited sensitive or path data")


def load_model_benchmark_runner_policy(repo_root: Path) -> ModelBenchmarkRunnerPolicy:
    path = repo_root / "config" / "model-benchmark-runner.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelBenchmarkRunnerError("model benchmark runner policy is unreadable") from exc
    expected = {
        "schema_version",
        "policy_revision",
        "minimum_repetitions",
        "maximum_repetitions",
        "minimum_confidence_samples",
        "default_timeout_ms",
        "maximum_timeout_ms",
        "minimum_quality_basis_points",
        "minimum_reliability_basis_points",
        "require_all_trials_verifier_approved",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelBenchmarkRunnerError("model benchmark runner policy fields are invalid")
    if payload.get("schema_version") != 1 or payload.get("invariants") != {
        "offline_by_default": True,
        "injected_adapter_only": True,
        "store_mutation": False,
        "raw_content_persisted": False,
    }:
        raise ModelBenchmarkRunnerError("model benchmark runner policy is unsafe")
    values = {
        key: _integer(payload.get(key), key, minimum=1)
        for key in (
            "policy_revision",
            "minimum_repetitions",
            "maximum_repetitions",
            "minimum_confidence_samples",
            "default_timeout_ms",
            "maximum_timeout_ms",
        )
    }
    quality = _integer(payload.get("minimum_quality_basis_points"), "minimum quality", maximum=10000)
    reliability = _integer(payload.get("minimum_reliability_basis_points"), "minimum reliability", maximum=10000)
    if (
        values["minimum_repetitions"] < 2
        or values["minimum_repetitions"] > values["minimum_confidence_samples"]
        or values["minimum_confidence_samples"] > values["maximum_repetitions"]
        or values["default_timeout_ms"] > values["maximum_timeout_ms"]
        or payload.get("require_all_trials_verifier_approved") is not True
    ):
        raise ModelBenchmarkRunnerError("model benchmark runner policy limits are inconsistent")
    return ModelBenchmarkRunnerPolicy(
        values["policy_revision"],
        values["minimum_repetitions"],
        values["maximum_repetitions"],
        values["minimum_confidence_samples"],
        values["default_timeout_ms"],
        values["maximum_timeout_ms"],
        quality,
        reliability,
        True,
        _digest(payload),
    )


def build_benchmark_execution_profile(
    model: Mapping[str, object],
    *,
    client_id: str,
    harness_id: str,
    harness_revision: str,
    model_revision: str,
    model_family: str,
    execution_ref: str,
    provider_route_ref: str,
    quantization: str,
    reasoning_effort: str,
    reasoning_budget_tokens: int | None,
    environment_digest: str,
    verifier_execution_ref: str,
    verifier_model_family: str,
) -> dict[str, object]:
    """Build provenance that makes model runs comparable only when identical."""

    parsed_model = parse_model_inventory_record(dict(model))
    semantic = {
        "model_ref": parsed_model["model_ref"],
        "inventory_digest": parsed_model["inventory_digest"],
        "client_id": _id(client_id, "client id"),
        "harness_id": _id(harness_id, "harness id"),
        "harness_revision": _revision(harness_revision, "harness revision"),
        "model_revision": _revision(model_revision, "model revision"),
        "model_family": _id(model_family, "model family"),
        "execution_ref": _id(execution_ref, "execution ref"),
        "provider_ref": parsed_model["provider_ref"],
        "provider_route_ref": _id(provider_route_ref, "provider route ref"),
        "remote": parsed_model["remote"],
        "quantization": _revision(quantization, "quantization"),
        "reasoning": {
            "effort": _revision(reasoning_effort, "reasoning effort"),
            "budget_tokens": None if reasoning_budget_tokens is None else _integer(
                reasoning_budget_tokens, "reasoning budget", minimum=1
            ),
        },
        "environment_digest": _sha(environment_digest, "environment digest"),
        "verifier_execution_ref": _id(verifier_execution_ref, "verifier execution ref"),
        "verifier_model_family": _id(verifier_model_family, "verifier model family"),
    }
    if semantic["execution_ref"] == semantic["verifier_execution_ref"]:
        raise ModelBenchmarkRunnerError("verifier execution must be independent")
    if semantic["model_family"] == semantic["verifier_model_family"]:
        raise ModelBenchmarkRunnerError("verifier model family must be independent")
    _safe(semantic, "execution profile")
    return parse_benchmark_execution_profile(
        {
            "schema_ref": "schemas/model-benchmark-execution-profile.schema.json",
            "schema_version": 1,
            **semantic,
            "profile_digest": _digest(semantic),
            "invariants": dict(PROFILE_INVARIANTS),
        }
    )


def parse_benchmark_execution_profile(payload: object) -> dict[str, object]:
    fields = {
        "schema_ref", "schema_version", "model_ref", "inventory_digest",
        "client_id", "harness_id", "harness_revision", "model_revision",
        "model_family", "execution_ref", "provider_ref", "provider_route_ref",
        "remote", "quantization", "reasoning", "environment_digest",
        "verifier_execution_ref", "verifier_model_family", "profile_digest", "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ModelBenchmarkRunnerError("execution profile fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-benchmark-execution-profile.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants") != PROFILE_INVARIANTS
        or not isinstance(payload.get("remote"), bool)
    ):
        raise ModelBenchmarkRunnerError("execution profile contract is invalid")
    for key in (
        "model_ref", "client_id", "harness_id", "model_family", "execution_ref",
        "provider_ref", "provider_route_ref", "verifier_execution_ref", "verifier_model_family",
    ):
        _id(payload.get(key), key)
    for key in ("harness_revision", "model_revision", "quantization"):
        _revision(payload.get(key), key)
    for key in ("inventory_digest", "environment_digest", "profile_digest"):
        _sha(payload.get(key), key)
    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, Mapping) or set(reasoning) != {"effort", "budget_tokens"}:
        raise ModelBenchmarkRunnerError("reasoning profile is invalid")
    _revision(reasoning.get("effort"), "reasoning effort")
    if reasoning.get("budget_tokens") is not None:
        _integer(reasoning.get("budget_tokens"), "reasoning budget", minimum=1)
    if payload["execution_ref"] == payload["verifier_execution_ref"]:
        raise ModelBenchmarkRunnerError("verifier execution must be independent")
    if payload["model_family"] == payload["verifier_model_family"]:
        raise ModelBenchmarkRunnerError("verifier model family must be independent")
    semantic = {key: payload[key] for key in fields - {"schema_ref", "schema_version", "profile_digest", "invariants"}}
    if payload["profile_digest"] != _digest(semantic):
        raise ModelBenchmarkRunnerError("execution profile digest is invalid")
    _safe(payload, "execution profile")
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _case(suite: Mapping[str, object], workload_id: str) -> Mapping[str, object]:
    match = next((item for item in suite["cases"] if item["workload_id"] == workload_id), None)
    if match is None:
        raise ModelBenchmarkRunnerError("benchmark workload was not found")
    return match


def _authorization_binding(
    model: Mapping[str, object],
    profile: Mapping[str, object],
    authorization: ProviderAuthorization | None,
    authorization_ref: str | None,
) -> tuple[str | None, str | None]:
    if not model["remote"]:
        if authorization is not None or authorization_ref is not None:
            raise ModelBenchmarkRunnerError("local benchmark accepts no provider authorization")
        return None, None
    if authorization is None or authorization_ref is None:
        raise ModelBenchmarkRunnerError("remote benchmark requires exact provider authorization")
    request = authorization.request
    if (
        not authorization.approval_verified
        or not request.remote
        or request.provider != model["provider_ref"]
        or request.operation_scope != "model-benchmark"
        or request.session_id.strip() == ""
    ):
        raise ModelBenchmarkRunnerError("remote provider authorization does not match benchmark")
    return _sha(request.request_id, "provider request id"), _id(authorization_ref, "provider authorization ref")


def prepare_model_benchmark_run(
    repo_root: Path,
    *,
    suite: Mapping[str, object],
    model: Mapping[str, object],
    health_record: Mapping[str, object],
    execution_profile: Mapping[str, object],
    current_source_digest: str,
    workload_id: str,
    repetitions: int,
    model_assignment_id: str,
    timeout_ms: int | None,
    now: datetime,
    provider_authorization: ProviderAuthorization | None = None,
    provider_authorization_ref: str | None = None,
) -> dict[str, object]:
    """Prepare an exact run without discovering/calling an adapter or provider."""

    policy = load_model_benchmark_runner_policy(repo_root)
    suite = parse_model_benchmark_suite(suite)
    model = parse_model_inventory_record(dict(model))
    health = parse_model_health_record(dict(health_record))
    profile = parse_benchmark_execution_profile(execution_profile)
    current_source_digest = _sha(current_source_digest, "current source digest")
    if suite["source_digest"] != current_source_digest:
        raise ModelBenchmarkRunnerError("benchmark suite source is stale")
    workload_id = _id(workload_id, "workload id")
    case = _case(suite, workload_id)
    repetitions = _integer(
        repetitions,
        "repetitions",
        minimum=policy.minimum_repetitions,
        maximum=policy.maximum_repetitions,
    )
    if repetitions < policy.minimum_confidence_samples:
        raise ModelBenchmarkRunnerError("benchmark sample count is not confidence-safe")
    selected_timeout = policy.default_timeout_ms if timeout_ms is None else _integer(
        timeout_ms, "timeout", minimum=1, maximum=policy.maximum_timeout_ms
    )
    if selected_timeout > policy.maximum_timeout_ms:
        raise ModelBenchmarkRunnerError("benchmark timeout exceeds policy")
    if (
        not model["enabled"]
        or health_effective_state(health, _utc(now)) != "health-passed"
        or health["model_ref"] != model["model_ref"]
        or health["inventory_digest"] != model["inventory_digest"]
        or profile["model_ref"] != model["model_ref"]
        or profile["inventory_digest"] != model["inventory_digest"]
        or profile["provider_ref"] != model["provider_ref"]
        or profile["remote"] is not model["remote"]
    ):
        raise ModelBenchmarkRunnerError("model is not health-passed for this execution profile")
    if workload_id not in model["supported_workloads"]:
        # Workload ids are profile-specific; the case kind is the inventory capability.
        if case["workload_kind"] not in model["supported_workloads"]:
            raise ModelBenchmarkRunnerError("model does not support the benchmark workload")
    fixture_policy = str(case["fixture_policy"])
    if fixture_policy not in FIXTURE_POLICIES:
        raise ModelBenchmarkRunnerError("fixture policy is invalid")
    if model["remote"] and (fixture_policy == "local-only" or case["remote_eligible"] is not True):
        raise ModelBenchmarkRunnerError("local-only benchmark fixture cannot use a remote model")
    request_id, authorization_ref = _authorization_binding(
        model, profile, provider_authorization, provider_authorization_ref
    )
    identity = {
        "policy_digest": policy.policy_digest,
        "project_id": suite["project_id"],
        "suite_digest": suite["suite_digest"],
        "source_digest": suite["source_digest"],
        "workload_id": workload_id,
        "workload_kind": case["workload_kind"],
        "workload_digest": case["workload_digest"],
        "case_digest": case["case_digest"],
        "fixture_policy": fixture_policy,
        "model_ref": model["model_ref"],
        "inventory_digest": model["inventory_digest"],
        "health_result_digest": health["result_digest"],
        "execution_profile_digest": profile["profile_digest"],
        "model_assignment_id": _id(model_assignment_id, "model assignment id"),
        "repetitions": repetitions,
        "timeout_ms": selected_timeout,
        "provider_request_id": request_id,
        "provider_authorization_ref": authorization_ref,
    }
    seed = _digest(identity)
    trial_ids = [f"benchmark-trial-{_digest({'plan_seed': seed, 'repetition': index})[:24]}" for index in range(1, repetitions + 1)]
    semantic = {**identity, "trial_ids": trial_ids}
    payload = {
        "schema_ref": "schemas/model-benchmark-run-plan.schema.json",
        "schema_version": 1,
        **semantic,
        "plan_id": "benchmark-run-" + _digest(semantic)[:24],
        "plan_digest": _digest(semantic),
        "invariants": dict(PLAN_INVARIANTS),
    }
    return parse_model_benchmark_run_plan(payload, policy=policy)


def parse_model_benchmark_run_plan(
    payload: object,
    *,
    policy: ModelBenchmarkRunnerPolicy | None = None,
) -> dict[str, object]:
    fields = {
        "schema_ref", "schema_version", "policy_digest", "project_id", "suite_digest",
        "source_digest", "workload_id", "workload_kind", "workload_digest", "case_digest",
        "fixture_policy", "model_ref", "inventory_digest", "health_result_digest",
        "execution_profile_digest", "model_assignment_id", "repetitions", "timeout_ms",
        "provider_request_id", "provider_authorization_ref", "trial_ids", "plan_id",
        "plan_digest", "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ModelBenchmarkRunnerError("benchmark run plan fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-benchmark-run-plan.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants") != PLAN_INVARIANTS
        or payload.get("fixture_policy") not in FIXTURE_POLICIES
    ):
        raise ModelBenchmarkRunnerError("benchmark run plan contract is invalid")
    for key in ("project_id", "workload_id", "workload_kind", "model_ref", "model_assignment_id", "plan_id"):
        _id(payload.get(key), key)
    for key in (
        "policy_digest", "suite_digest", "source_digest", "workload_digest", "case_digest",
        "inventory_digest", "health_result_digest", "execution_profile_digest", "plan_digest",
    ):
        _sha(payload.get(key), key)
    repetitions = _integer(payload.get("repetitions"), "repetitions", minimum=5)
    _integer(payload.get("timeout_ms"), "timeout", minimum=1)
    trial_ids = payload.get("trial_ids")
    if (
        not isinstance(trial_ids, list)
        or len(trial_ids) != repetitions
        or len(set(trial_ids)) != repetitions
        or any(not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in trial_ids)
    ):
        raise ModelBenchmarkRunnerError("benchmark trial identities are invalid")
    request_id = payload.get("provider_request_id")
    auth_ref = payload.get("provider_authorization_ref")
    if (request_id is None) != (auth_ref is None):
        raise ModelBenchmarkRunnerError("provider authorization binding is incomplete")
    if request_id is not None:
        _sha(request_id, "provider request id")
        _id(auth_ref, "provider authorization ref")
    semantic = {key: payload[key] for key in fields - {"schema_ref", "schema_version", "plan_id", "plan_digest", "invariants"}}
    if payload["plan_digest"] != _digest(semantic) or payload["plan_id"] != "benchmark-run-" + _digest(semantic)[:24]:
        raise ModelBenchmarkRunnerError("benchmark run plan digest is invalid")
    seed_identity = {key: semantic[key] for key in semantic if key != "trial_ids"}
    seed = _digest(seed_identity)
    expected_trials = [f"benchmark-trial-{_digest({'plan_seed': seed, 'repetition': index})[:24]}" for index in range(1, repetitions + 1)]
    if trial_ids != expected_trials:
        raise ModelBenchmarkRunnerError("benchmark trial identities were tampered")
    if policy is not None and (
        payload["policy_digest"] != policy.policy_digest
        or repetitions < policy.minimum_confidence_samples
        or repetitions > policy.maximum_repetitions
        or payload["timeout_ms"] > policy.maximum_timeout_ms
    ):
        raise ModelBenchmarkRunnerError("benchmark run plan policy is stale")
    _safe(payload, "benchmark run plan")
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _adapter_outcome(payload: object) -> dict[str, object]:
    fields = {
        "quality_score_basis_points", "reliability_score_basis_points", "latency_ms",
        "input_tokens", "output_tokens", "retry_count", "human_corrections",
        "estimated_cost_microunits", "actual_cost_microunits", "parse_passed",
        "format_passed", "evidence_passed", "verifier_passed", "timed_out",
        "failure_category", "verifier_execution_ref", "verifier_model_family",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ModelBenchmarkRunnerError("adapter outcome fields are invalid")
    for key in ("quality_score_basis_points", "reliability_score_basis_points"):
        _integer(payload.get(key), key, maximum=10000)
    _integer(payload.get("latency_ms"), "latency", maximum=3600000)
    for key in (
        "input_tokens", "output_tokens", "retry_count", "human_corrections",
        "estimated_cost_microunits", "actual_cost_microunits",
    ):
        _integer(payload.get(key), key)
    for key in ("parse_passed", "format_passed", "evidence_passed", "verifier_passed", "timed_out"):
        if not isinstance(payload.get(key), bool):
            raise ModelBenchmarkRunnerError("adapter outcome flags are invalid")
    if payload.get("failure_category") not in FAILURE_CATEGORIES | {None}:
        raise ModelBenchmarkRunnerError("adapter failure category is invalid")
    _id(payload.get("verifier_execution_ref"), "verifier execution ref")
    _id(payload.get("verifier_model_family"), "verifier model family")
    _safe(payload, "adapter outcome")
    return dict(payload)


def _trial_result(
    plan: Mapping[str, object],
    profile: Mapping[str, object],
    *,
    repetition: int,
    observed_at: str,
    outcome: Mapping[str, object],
) -> dict[str, object]:
    if outcome["verifier_execution_ref"] != profile["verifier_execution_ref"] or outcome["verifier_model_family"] != profile["verifier_model_family"]:
        raise ModelBenchmarkRunnerError("trial verifier provenance does not match execution profile")
    if outcome["verifier_execution_ref"] == profile["execution_ref"] or outcome["verifier_model_family"] == profile["model_family"]:
        raise ModelBenchmarkRunnerError("trial verifier is not independent")
    timed_out = bool(outcome["timed_out"] or outcome["latency_ms"] > plan["timeout_ms"])
    parse_passed = bool(outcome["parse_passed"] and not timed_out)
    format_passed = bool(outcome["format_passed"] and parse_passed)
    evidence_passed = bool(outcome["evidence_passed"] and format_passed)
    verifier_passed = bool(outcome["verifier_passed"] and evidence_passed)
    failure = outcome["failure_category"]
    if timed_out:
        failure = "timeout"
    elif failure == "adapter-error":
        parse_passed = False
        format_passed = False
        evidence_passed = False
        verifier_passed = False
    elif not parse_passed:
        failure = "parse-failed"
    elif not format_passed:
        failure = "format-failed"
    elif not evidence_passed:
        failure = "evidence-failed"
    elif not verifier_passed:
        failure = "verifier-failed"
    elif failure is not None:
        raise ModelBenchmarkRunnerError("successful trial cannot retain a failure category")
    semantic = {
        "plan_digest": plan["plan_digest"],
        "trial_id": plan["trial_ids"][repetition - 1],
        "repetition": repetition,
        "execution_profile_digest": profile["profile_digest"],
        "project_id": plan["project_id"],
        "suite_digest": plan["suite_digest"],
        "source_digest": plan["source_digest"],
        "workload_id": plan["workload_id"],
        "workload_digest": plan["workload_digest"],
        "case_digest": plan["case_digest"],
        "model_ref": plan["model_ref"],
        "inventory_digest": plan["inventory_digest"],
        "observed_at": _timestamp(observed_at, "observed at"),
        "quality_score_basis_points": outcome["quality_score_basis_points"],
        "reliability_score_basis_points": outcome["reliability_score_basis_points"],
        "latency_ms": outcome["latency_ms"],
        "input_tokens": outcome["input_tokens"],
        "output_tokens": outcome["output_tokens"],
        "retry_count": outcome["retry_count"],
        "human_corrections": outcome["human_corrections"],
        "estimated_cost_microunits": outcome["estimated_cost_microunits"],
        "actual_cost_microunits": outcome["actual_cost_microunits"],
        "timed_out": timed_out,
        "parse_passed": parse_passed,
        "format_passed": format_passed,
        "evidence_passed": evidence_passed,
        "verifier_passed": verifier_passed,
        "failure_category": failure,
        "verifier_execution_ref": outcome["verifier_execution_ref"],
        "verifier_model_family": outcome["verifier_model_family"],
    }
    return parse_model_benchmark_trial_result({
        "schema_ref": "schemas/model-benchmark-trial-result.schema.json",
        "schema_version": 1,
        **semantic,
        "trial_digest": _digest(semantic),
        "invariants": dict(RESULT_INVARIANTS),
    })


def parse_model_benchmark_trial_result(payload: object) -> dict[str, object]:
    fields = {
        "schema_ref", "schema_version", "plan_digest", "trial_id", "repetition",
        "execution_profile_digest", "project_id", "suite_digest", "source_digest",
        "workload_id", "workload_digest", "case_digest", "model_ref", "inventory_digest",
        "observed_at", "quality_score_basis_points", "reliability_score_basis_points",
        "latency_ms", "input_tokens", "output_tokens", "retry_count", "human_corrections",
        "estimated_cost_microunits", "actual_cost_microunits", "timed_out", "parse_passed",
        "format_passed", "evidence_passed", "verifier_passed", "failure_category",
        "verifier_execution_ref", "verifier_model_family", "trial_digest", "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ModelBenchmarkRunnerError("benchmark trial fields are invalid")
    if payload.get("schema_ref") != "schemas/model-benchmark-trial-result.schema.json" or payload.get("schema_version") != 1 or payload.get("invariants") != RESULT_INVARIANTS:
        raise ModelBenchmarkRunnerError("benchmark trial contract is invalid")
    for key in ("trial_id", "project_id", "workload_id", "model_ref", "verifier_execution_ref", "verifier_model_family"):
        _id(payload.get(key), key)
    for key in ("plan_digest", "execution_profile_digest", "suite_digest", "source_digest", "workload_digest", "case_digest", "inventory_digest", "trial_digest"):
        _sha(payload.get(key), key)
    _integer(payload.get("repetition"), "repetition", minimum=1)
    _timestamp(payload.get("observed_at"), "observed at")
    for key in ("quality_score_basis_points", "reliability_score_basis_points"):
        _integer(payload.get(key), key, maximum=10000)
    _integer(payload.get("latency_ms"), "latency", maximum=3600000)
    for key in ("input_tokens", "output_tokens", "retry_count", "human_corrections", "estimated_cost_microunits", "actual_cost_microunits"):
        _integer(payload.get(key), key)
    for key in ("timed_out", "parse_passed", "format_passed", "evidence_passed", "verifier_passed"):
        if not isinstance(payload.get(key), bool):
            raise ModelBenchmarkRunnerError("benchmark trial flags are invalid")
    if payload.get("failure_category") not in FAILURE_CATEGORIES | {None}:
        raise ModelBenchmarkRunnerError("benchmark trial failure is invalid")
    if (
        (payload["format_passed"] and not payload["parse_passed"])
        or (payload["evidence_passed"] and not payload["format_passed"])
        or (payload["verifier_passed"] and not payload["evidence_passed"])
        or (
            payload["timed_out"]
            and any(
                payload[key]
                for key in (
                    "parse_passed",
                    "format_passed",
                    "evidence_passed",
                    "verifier_passed",
                )
            )
        )
    ):
        raise ModelBenchmarkRunnerError("benchmark trial outcome ordering is invalid")
    expected_failure = None
    if payload["timed_out"]:
        expected_failure = "timeout"
    elif payload["failure_category"] == "adapter-error":
        expected_failure = "adapter-error"
    elif not payload["parse_passed"]:
        expected_failure = "parse-failed"
    elif not payload["format_passed"]:
        expected_failure = "format-failed"
    elif not payload["evidence_passed"]:
        expected_failure = "evidence-failed"
    elif not payload["verifier_passed"]:
        expected_failure = "verifier-failed"
    if payload["failure_category"] != expected_failure:
        raise ModelBenchmarkRunnerError("benchmark trial failure is inconsistent")
    successful = bool(payload["parse_passed"] and payload["format_passed"] and payload["evidence_passed"] and payload["verifier_passed"] and not payload["timed_out"])
    if successful != (payload["failure_category"] is None):
        raise ModelBenchmarkRunnerError("benchmark trial outcome is inconsistent")
    semantic = {key: payload[key] for key in fields - {"schema_ref", "schema_version", "trial_digest", "invariants"}}
    if payload["trial_digest"] != _digest(semantic):
        raise ModelBenchmarkRunnerError("benchmark trial digest is invalid")
    _safe(payload, "benchmark trial")
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _round(value: float) -> int:
    return int(math.floor(value + 0.5))


def _metric(values: Sequence[int]) -> dict[str, int]:
    ordered = sorted(values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "mean": _round(statistics.fmean(ordered)),
        "median": _round(statistics.median(ordered)),
        "p95": ordered[p95_index],
        "variance": _round(statistics.pvariance(ordered)),
    }


def aggregate_model_benchmark_trials(
    repo_root: Path,
    plan: Mapping[str, object],
    trials: Sequence[Mapping[str, object]],
    *,
    observed_at: str,
) -> dict[str, object]:
    policy = load_model_benchmark_runner_policy(repo_root)
    plan = parse_model_benchmark_run_plan(plan, policy=policy)
    parsed = [parse_model_benchmark_trial_result(item) for item in trials]
    if len(parsed) != plan["repetitions"] or len(parsed) < policy.minimum_confidence_samples:
        raise ModelBenchmarkRunnerError("benchmark aggregate sample count is not confidence-safe")
    expected_ids = list(plan["trial_ids"])
    if [item["trial_id"] for item in parsed] != expected_ids or [item["repetition"] for item in parsed] != list(range(1, len(parsed) + 1)):
        raise ModelBenchmarkRunnerError("benchmark aggregate trial sequence is invalid")
    bound_fields = {
        "plan_digest": plan["plan_digest"],
        "execution_profile_digest": plan["execution_profile_digest"],
        "project_id": plan["project_id"],
        "suite_digest": plan["suite_digest"],
        "source_digest": plan["source_digest"],
        "workload_id": plan["workload_id"],
        "workload_digest": plan["workload_digest"],
        "case_digest": plan["case_digest"],
        "model_ref": plan["model_ref"],
        "inventory_digest": plan["inventory_digest"],
    }
    for trial in parsed:
        if any(trial[key] != value for key, value in bound_fields.items()):
            raise ModelBenchmarkRunnerError("incomparable benchmark profiles cannot be pooled")
    approved = sum(bool(item["verifier_passed"]) for item in parsed)
    totals = {
        "input_tokens": sum(int(item["input_tokens"]) for item in parsed),
        "output_tokens": sum(int(item["output_tokens"]) for item in parsed),
        "retries": sum(int(item["retry_count"]) for item in parsed),
        "human_corrections": sum(int(item["human_corrections"]) for item in parsed),
        "estimated_cost_microunits": sum(int(item["estimated_cost_microunits"]) for item in parsed),
        "actual_cost_microunits": sum(int(item["actual_cost_microunits"]) for item in parsed),
    }
    passed = bool(
        approved == len(parsed)
        and all(item["quality_score_basis_points"] >= policy.minimum_quality_basis_points for item in parsed)
        and all(item["reliability_score_basis_points"] >= policy.minimum_reliability_basis_points for item in parsed)
    )
    semantic = {
        **bound_fields,
        "aggregate_id": "benchmark-aggregate-" + _digest({"plan_digest": plan["plan_digest"], "trial_digests": [item["trial_digest"] for item in parsed]})[:24],
        "observed_at": _timestamp(observed_at, "observed at"),
        "sample_count": len(parsed),
        "confidence_safe": True,
        "verifier_approved_count": approved,
        "passed": passed,
        "statistics": {
            "quality_score_basis_points": _metric([int(item["quality_score_basis_points"]) for item in parsed]),
            "reliability_score_basis_points": _metric([int(item["reliability_score_basis_points"]) for item in parsed]),
            "latency_ms": _metric([int(item["latency_ms"]) for item in parsed]),
            "total_tokens": _metric([int(item["input_tokens"]) + int(item["output_tokens"]) for item in parsed]),
            "estimated_cost_microunits": _metric([int(item["estimated_cost_microunits"]) for item in parsed]),
        },
        "totals": totals,
        "cost_per_verifier_approved_result_microunits": None if approved == 0 else _round(totals["estimated_cost_microunits"] / approved),
        "trial_digests": [item["trial_digest"] for item in parsed],
    }
    return parse_model_benchmark_aggregate_result({
        "schema_ref": "schemas/model-benchmark-aggregate-result.schema.json",
        "schema_version": 1,
        **semantic,
        "aggregate_digest": _digest(semantic),
        "invariants": dict(RESULT_INVARIANTS),
    }, minimum_samples=policy.minimum_confidence_samples)


def parse_model_benchmark_aggregate_result(payload: object, *, minimum_samples: int = 5) -> dict[str, object]:
    fields = {
        "schema_ref", "schema_version", "plan_digest", "execution_profile_digest",
        "project_id", "suite_digest", "source_digest", "workload_id", "workload_digest",
        "case_digest", "model_ref", "inventory_digest", "aggregate_id", "observed_at",
        "sample_count", "confidence_safe", "verifier_approved_count", "passed", "statistics",
        "totals", "cost_per_verifier_approved_result_microunits", "trial_digests",
        "aggregate_digest", "invariants",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ModelBenchmarkRunnerError("benchmark aggregate fields are invalid")
    if payload.get("schema_ref") != "schemas/model-benchmark-aggregate-result.schema.json" or payload.get("schema_version") != 1 or payload.get("invariants") != RESULT_INVARIANTS:
        raise ModelBenchmarkRunnerError("benchmark aggregate contract is invalid")
    for key in ("project_id", "workload_id", "model_ref", "aggregate_id"):
        _id(payload.get(key), key)
    for key in ("plan_digest", "execution_profile_digest", "suite_digest", "source_digest", "workload_digest", "case_digest", "inventory_digest", "aggregate_digest"):
        _sha(payload.get(key), key)
    _timestamp(payload.get("observed_at"), "observed at")
    count = _integer(payload.get("sample_count"), "sample count", minimum=minimum_samples)
    approved = _integer(payload.get("verifier_approved_count"), "approved count", maximum=count)
    if payload.get("confidence_safe") is not True or not isinstance(payload.get("passed"), bool):
        raise ModelBenchmarkRunnerError("benchmark aggregate confidence is invalid")
    if payload["passed"] and approved != count:
        raise ModelBenchmarkRunnerError("passed aggregate requires every verifier approval")
    stats_payload = payload.get("statistics")
    expected_metrics = {"quality_score_basis_points", "reliability_score_basis_points", "latency_ms", "total_tokens", "estimated_cost_microunits"}
    if not isinstance(stats_payload, Mapping) or set(stats_payload) != expected_metrics:
        raise ModelBenchmarkRunnerError("benchmark aggregate statistics are invalid")
    for metric in stats_payload.values():
        if not isinstance(metric, Mapping) or set(metric) != {"mean", "median", "p95", "variance"}:
            raise ModelBenchmarkRunnerError("benchmark aggregate metric is invalid")
        for value in metric.values():
            _integer(value, "aggregate metric")
    totals = payload.get("totals")
    if not isinstance(totals, Mapping) or set(totals) != {"input_tokens", "output_tokens", "retries", "human_corrections", "estimated_cost_microunits", "actual_cost_microunits"}:
        raise ModelBenchmarkRunnerError("benchmark aggregate totals are invalid")
    for value in totals.values():
        _integer(value, "aggregate total")
    cost_per = payload.get("cost_per_verifier_approved_result_microunits")
    if (approved == 0) != (cost_per is None):
        raise ModelBenchmarkRunnerError("benchmark cost per approved result is inconsistent")
    if cost_per is not None:
        _integer(cost_per, "cost per approved result")
        if cost_per != _round(int(totals["estimated_cost_microunits"]) / approved):
            raise ModelBenchmarkRunnerError("benchmark cost per approved result is invalid")
    digests = payload.get("trial_digests")
    if not isinstance(digests, list) or len(digests) != count or len(set(digests)) != count:
        raise ModelBenchmarkRunnerError("benchmark aggregate trial digests are invalid")
    for digest in digests:
        _sha(digest, "trial digest")
    expected_aggregate_id = "benchmark-aggregate-" + _digest(
        {"plan_digest": payload["plan_digest"], "trial_digests": digests}
    )[:24]
    if payload["aggregate_id"] != expected_aggregate_id:
        raise ModelBenchmarkRunnerError("benchmark aggregate identity is invalid")
    semantic = {key: payload[key] for key in fields - {"schema_ref", "schema_version", "aggregate_digest", "invariants"}}
    if payload["aggregate_digest"] != _digest(semantic):
        raise ModelBenchmarkRunnerError("benchmark aggregate digest is invalid")
    _safe(payload, "benchmark aggregate")
    return json.loads(json.dumps(payload, ensure_ascii=False))


def execute_model_benchmark_run(
    repo_root: Path,
    plan: Mapping[str, object],
    *,
    expected_plan_id: str,
    suite: Mapping[str, object],
    model: Mapping[str, object],
    health_record: Mapping[str, object],
    execution_profile: Mapping[str, object],
    current_source_digest: str,
    adapter: BenchmarkAdapter,
    observed_at: datetime,
    provider_authorization: ProviderAuthorization | None = None,
    provider_authorization_ref: str | None = None,
) -> BenchmarkRunOutput:
    """Execute every planned repetition through the explicitly injected adapter."""

    if not callable(adapter):
        raise ModelBenchmarkRunnerError("an injected benchmark adapter is required")
    policy = load_model_benchmark_runner_policy(repo_root)
    plan = parse_model_benchmark_run_plan(plan, policy=policy)
    if expected_plan_id != plan["plan_id"]:
        raise ModelBenchmarkRunnerError("benchmark exact plan does not match")
    suite = parse_model_benchmark_suite(suite)
    model = parse_model_inventory_record(dict(model))
    health = parse_model_health_record(dict(health_record))
    profile = parse_benchmark_execution_profile(execution_profile)
    current_source_digest = _sha(current_source_digest, "current source digest")
    case = _case(suite, str(plan["workload_id"]))
    if (
        plan["suite_digest"] != suite["suite_digest"]
        or plan["source_digest"] != suite["source_digest"]
        or plan["source_digest"] != current_source_digest
        or plan["workload_digest"] != case["workload_digest"]
        or plan["case_digest"] != case["case_digest"]
        or plan["inventory_digest"] != model["inventory_digest"]
        or plan["health_result_digest"] != health["result_digest"]
        or plan["execution_profile_digest"] != profile["profile_digest"]
        or health_effective_state(health, _utc(observed_at)) != "health-passed"
    ):
        raise ModelBenchmarkRunnerError("benchmark inputs changed after plan preparation")
    request_id, auth_ref = _authorization_binding(model, profile, provider_authorization, provider_authorization_ref)
    if request_id != plan["provider_request_id"] or auth_ref != plan["provider_authorization_ref"]:
        raise ModelBenchmarkRunnerError("provider authorization changed after preparation")
    trials = []
    timestamp = _utc(observed_at).isoformat().replace("+00:00", "Z")
    for repetition in range(1, int(plan["repetitions"]) + 1):
        request = {
            "schema_version": 1,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["plan_digest"],
            "trial_id": plan["trial_ids"][repetition - 1],
            "repetition": repetition,
            "repetition_count": plan["repetitions"],
            "project_id": plan["project_id"],
            "suite_digest": plan["suite_digest"],
            "source_digest": plan["source_digest"],
            "workload_id": plan["workload_id"],
            "workload_kind": plan["workload_kind"],
            "workload_digest": plan["workload_digest"],
            "case_digest": plan["case_digest"],
            "fixture_policy": plan["fixture_policy"],
            "required_output_sections": list(case["required_output_sections"]),
            "execution_profile": profile,
            "timeout_ms": plan["timeout_ms"],
            "provider_request_id": plan["provider_request_id"],
            "raw_content_included": False,
            "grants_authority": False,
        }
        _safe(request, "adapter request")
        try:
            raw_outcome = adapter(request)
        except TimeoutError:
            outcome = {
                "quality_score_basis_points": 0,
                "reliability_score_basis_points": 0,
                "latency_ms": plan["timeout_ms"],
                "input_tokens": 0,
                "output_tokens": 0,
                "retry_count": 0,
                "human_corrections": 0,
                "estimated_cost_microunits": 0,
                "actual_cost_microunits": 0,
                "parse_passed": False,
                "format_passed": False,
                "evidence_passed": False,
                "verifier_passed": False,
                "timed_out": True,
                "failure_category": "timeout",
                "verifier_execution_ref": profile["verifier_execution_ref"],
                "verifier_model_family": profile["verifier_model_family"],
            }
        except Exception:
            outcome = {
                "quality_score_basis_points": 0,
                "reliability_score_basis_points": 0,
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "retry_count": 0,
                "human_corrections": 0,
                "estimated_cost_microunits": 0,
                "actual_cost_microunits": 0,
                "parse_passed": False,
                "format_passed": False,
                "evidence_passed": False,
                "verifier_passed": False,
                "timed_out": False,
                "failure_category": "adapter-error",
                "verifier_execution_ref": profile["verifier_execution_ref"],
                "verifier_model_family": profile["verifier_model_family"],
            }
        else:
            outcome = _adapter_outcome(raw_outcome)
        trials.append(_trial_result(plan, profile, repetition=repetition, observed_at=timestamp, outcome=outcome))
    aggregate = aggregate_model_benchmark_trials(repo_root, plan, trials, observed_at=timestamp)
    benchmark_record = build_model_benchmark_result(
        suite,
        model,
        workload_id=str(plan["workload_id"]),
        observed_at=timestamp,
        quality_score_basis_points=int(aggregate["statistics"]["quality_score_basis_points"]["mean"]),
        reliability_score_basis_points=int(aggregate["statistics"]["reliability_score_basis_points"]["mean"]),
        latency_ms=int(aggregate["statistics"]["latency_ms"]["p95"]),
        passed=bool(aggregate["passed"]),
    )
    runtime = tuple(
        build_model_runtime_observation(
            model,
            project_id=str(plan["project_id"]),
            workload=str(plan["workload_kind"]),
            model_assignment_id=str(plan["model_assignment_id"]),
            trace_digest=str(trial["trial_digest"]),
            observed_at=str(trial["observed_at"]),
            successful=bool(trial["failure_category"] is None),
            verifier_passed=bool(trial["verifier_passed"]),
            latency_ms=int(trial["latency_ms"]),
            input_tokens=int(trial["input_tokens"]),
            output_tokens=int(trial["output_tokens"]),
            actual_cost_microunits=int(trial["actual_cost_microunits"]),
        )
        for trial in trials
    )
    parse_model_benchmark_result(benchmark_record)
    for item in runtime:
        parse_model_runtime_observation(item)
    return BenchmarkRunOutput(plan, tuple(trials), aggregate, (benchmark_record,), runtime)
