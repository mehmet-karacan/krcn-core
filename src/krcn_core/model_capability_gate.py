"""Local A/B gate that preserves model capability under KRCN constraints."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .foundation import load_json
from .information_records import canonical_json


HARD_CONSTRAINTS = {
    "authority-boundary",
    "evidence-integrity",
    "output-contract-validity",
    "secret-protection",
    "side-effect-boundary",
}
SOFT_GUIDANCE = {
    "alternative-generation",
    "assumption-challenge",
    "counter-evidence",
    "lazy-retrieval",
    "research-order",
    "solution-method",
}
THRESHOLD_KEYS = {
    "maximum_general_success_regression_basis_points",
    "maximum_general_score_regression_basis_points",
    "maximum_critical_regressions",
    "maximum_hard_constraint_violations",
    "advisory_token_overhead_basis_points",
    "advisory_latency_overhead_basis_points",
    "advisory_agent_call_overhead_basis_points",
    "advisory_human_intervention_overhead_basis_points",
}
MEASUREMENT_KEYS = {
    "execution_digest",
    "task_success",
    "verifier_pass",
    "score_basis_points",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "agent_call_count",
    "human_intervention_count",
    "hard_constraint_violations",
}


class ModelCapabilityGateError(ValueError):
    """Raised when capability evidence is incomplete, unsafe, or inconsistent."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ModelCapabilityGateError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str, maximum: int | None = None) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or (maximum is not None and value > maximum)
    ):
        raise ModelCapabilityGateError(f"{label} is invalid")
    return value


def _sorted_identifiers(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(
            not isinstance(item, str)
            or not item
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in item)
            or not item[0].isalpha()
            for item in value
        )
        or len(set(value)) != len(value)
        or value != sorted(value)
    ):
        raise ModelCapabilityGateError(f"{label} must be a sorted identifier list")
    return tuple(value)


@dataclass(frozen=True)
class ModelCapabilityPolicy:
    revision: int
    thresholds: Mapping[str, int]
    hard_constraints: tuple[str, ...]
    soft_guidance: tuple[str, ...]
    policy_digest: str


@dataclass(frozen=True)
class GoldenCapabilityCase:
    case_id: str
    critical: bool
    hard_constraint_refs: tuple[str, ...]
    soft_guidance_refs: tuple[str, ...]
    evaluation_traits: tuple[str, ...]


@dataclass(frozen=True)
class ModelCapabilityGoldenSet:
    revision: int
    cases: tuple[GoldenCapabilityCase, ...]
    golden_set_digest: str


@dataclass(frozen=True)
class CapabilityMeasurement:
    execution_digest: str
    task_success: bool
    verifier_pass: bool
    score_basis_points: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    agent_call_count: int
    human_intervention_count: int
    hard_constraint_violations: tuple[str, ...]

    @property
    def successful(self) -> bool:
        return (
            self.task_success
            and self.verifier_pass
            and not self.hard_constraint_violations
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_digest": self.execution_digest,
            "task_success": self.task_success,
            "verifier_pass": self.verifier_pass,
            "score_basis_points": self.score_basis_points,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "agent_call_count": self.agent_call_count,
            "human_intervention_count": self.human_intervention_count,
            "hard_constraint_violations": list(self.hard_constraint_violations),
        }


@dataclass(frozen=True)
class ModelCapabilityEvaluation:
    evaluation_id: str
    policy_digest: str
    golden_set_digest: str
    status: str
    case_results: tuple[Mapping[str, object], ...]
    aggregate: Mapping[str, object]
    blocking_reasons: tuple[str, ...]
    advisories: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/model-capability-evaluation.schema.json",
            "schema_version": 1,
            "evaluation_id": self.evaluation_id,
            "policy_digest": self.policy_digest,
            "golden_set_digest": self.golden_set_digest,
            "status": self.status,
            "case_results": [dict(item) for item in self.case_results],
            "aggregate": dict(self.aggregate),
            "blocking_reasons": list(self.blocking_reasons),
            "advisories": list(self.advisories),
            "invariants": {
                "raw_prompt_included": False,
                "raw_output_included": False,
                "private_chain_of_thought_included": False,
                "provider_call_performed": False,
                "grants_authority": False,
            },
        }


def parse_model_capability_policy(payload: object) -> ModelCapabilityPolicy:
    expected = {
        "schema_ref",
        "schema_version",
        "revision",
        "thresholds",
        "hard_constraints",
        "soft_guidance",
        "context_policy",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelCapabilityGateError("model capability policy fields are invalid")
    if (
        payload.get("schema_ref")
        != "schemas/model-capability-preservation-policy.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise ModelCapabilityGateError("model capability policy contract is invalid")
    revision = _positive_int(payload.get("revision"), "policy revision")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != THRESHOLD_KEYS:
        raise ModelCapabilityGateError("model capability thresholds are invalid")
    normalized_thresholds = {
        key: _nonnegative_int(value, key)
        for key, value in sorted(thresholds.items())
    }
    if (
        normalized_thresholds["maximum_general_success_regression_basis_points"]
        > 200
        or normalized_thresholds[
            "maximum_general_score_regression_basis_points"
        ]
        > 200
        or normalized_thresholds["maximum_critical_regressions"] != 0
        or normalized_thresholds["maximum_hard_constraint_violations"] != 0
    ):
        raise ModelCapabilityGateError("blocking thresholds weaken the V1 boundary")
    hard = _sorted_identifiers(payload.get("hard_constraints"), "hard constraints")
    soft = _sorted_identifiers(payload.get("soft_guidance"), "soft guidance")
    if set(hard) != HARD_CONSTRAINTS or set(soft) != SOFT_GUIDANCE:
        raise ModelCapabilityGateError("hard and soft policy coverage is incomplete")
    if payload.get("context_policy") != {
        "minimum_required_context": True,
        "lazy_retrieval": True,
        "full_history_by_default": False,
        "private_chain_of_thought_persisted": False,
        "alternative_and_counter_evidence_allowed": True,
        "assumption_challenge_allowed": True,
    }:
        raise ModelCapabilityGateError("model context preservation policy is invalid")
    if payload.get("invariants") != {
        "provider_call_during_evaluation": False,
        "raw_prompt_persisted": False,
        "raw_output_persisted": False,
        "model_decision_grants_authority": False,
    }:
        raise ModelCapabilityGateError("model capability invariants are invalid")
    return ModelCapabilityPolicy(revision, normalized_thresholds, hard, soft, _digest(payload))


def load_model_capability_policy(repo_root: Path) -> ModelCapabilityPolicy:
    return parse_model_capability_policy(
        load_json(repo_root / "config" / "model-capability-preservation.json")
    )


def parse_model_capability_golden_set(
    payload: object,
    policy: ModelCapabilityPolicy,
) -> ModelCapabilityGoldenSet:
    expected = {"schema_ref", "schema_version", "revision", "cases", "invariants"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelCapabilityGateError("model capability golden set fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-capability-golden-set.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants")
        != {
            "prompt_content_included": False,
            "source_content_included": False,
            "secret_values_included": False,
            "absolute_paths_included": False,
            "grants_authority": False,
        }
    ):
        raise ModelCapabilityGateError("model capability golden set contract is invalid")
    revision = _positive_int(payload.get("revision"), "golden set revision")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases or len(raw_cases) > 100:
        raise ModelCapabilityGateError("model capability golden cases are invalid")
    cases: list[GoldenCapabilityCase] = []
    for raw in raw_cases:
        if not isinstance(raw, dict) or set(raw) != {
            "case_id",
            "critical",
            "hard_constraint_refs",
            "soft_guidance_refs",
            "evaluation_traits",
        }:
            raise ModelCapabilityGateError("golden case fields are invalid")
        case_ids = _sorted_identifiers([raw.get("case_id")], "case id")
        critical = raw.get("critical")
        if not isinstance(critical, bool):
            raise ModelCapabilityGateError("golden case critical flag is invalid")
        hard = _sorted_identifiers(raw.get("hard_constraint_refs"), "case hard constraints")
        soft = _sorted_identifiers(raw.get("soft_guidance_refs"), "case soft guidance")
        traits = _sorted_identifiers(raw.get("evaluation_traits"), "evaluation traits")
        if not set(hard).issubset(policy.hard_constraints) or not set(soft).issubset(
            policy.soft_guidance
        ):
            raise ModelCapabilityGateError("golden case references unknown policy rules")
        cases.append(GoldenCapabilityCase(case_ids[0], critical, hard, soft, traits))
    if (
        [item.case_id for item in cases] != sorted(item.case_id for item in cases)
        or len({item.case_id for item in cases}) != len(cases)
        or not any(item.critical for item in cases)
        or set().union(*(set(item.hard_constraint_refs) for item in cases))
        != set(policy.hard_constraints)
        or set().union(*(set(item.soft_guidance_refs) for item in cases))
        != set(policy.soft_guidance)
    ):
        raise ModelCapabilityGateError("golden set coverage or ordering is invalid")
    return ModelCapabilityGoldenSet(revision, tuple(cases), _digest(payload))


def load_model_capability_golden_set(
    repo_root: Path,
    policy: ModelCapabilityPolicy,
) -> ModelCapabilityGoldenSet:
    return parse_model_capability_golden_set(
        load_json(repo_root / "config" / "model-capability-golden-set.json"),
        policy,
    )


def _measurement(
    payload: object,
    case: GoldenCapabilityCase,
    label: str,
) -> CapabilityMeasurement:
    if not isinstance(payload, dict) or set(payload) != MEASUREMENT_KEYS:
        raise ModelCapabilityGateError(f"{label} measurement fields are invalid")
    digest = payload.get("execution_digest")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ModelCapabilityGateError(f"{label} execution digest is invalid")
    task_success = payload.get("task_success")
    verifier_pass = payload.get("verifier_pass")
    if not isinstance(task_success, bool) or not isinstance(verifier_pass, bool):
        raise ModelCapabilityGateError(f"{label} outcome booleans are invalid")
    violations = _sorted_identifiers(
        payload.get("hard_constraint_violations"),
        f"{label} hard constraint violations",
        allow_empty=True,
    )
    if not set(violations).issubset(case.hard_constraint_refs):
        raise ModelCapabilityGateError(f"{label} violation is outside the golden case")
    return CapabilityMeasurement(
        digest,
        task_success,
        verifier_pass,
        _nonnegative_int(payload.get("score_basis_points"), f"{label} score", 10000),
        _nonnegative_int(payload.get("input_tokens"), f"{label} input tokens"),
        _nonnegative_int(payload.get("output_tokens"), f"{label} output tokens"),
        _nonnegative_int(payload.get("latency_ms"), f"{label} latency"),
        _nonnegative_int(payload.get("agent_call_count"), f"{label} agent calls"),
        _nonnegative_int(
            payload.get("human_intervention_count"),
            f"{label} human interventions",
        ),
        violations,
    )


def _rate(count: int, total: int) -> int:
    return round(count * 10000 / total)


def _relative_delta(enabled: int, baseline: int) -> int | None:
    if baseline == 0:
        return None
    return round((enabled - baseline) * 10000 / baseline)


def _overhead_exceeds(enabled: int, baseline: int, threshold: int) -> bool:
    if baseline == 0:
        return enabled > 0
    return bool(_relative_delta(enabled, baseline) > threshold)


def evaluate_model_capability(
    policy: ModelCapabilityPolicy,
    golden_set: ModelCapabilityGoldenSet,
    baseline_results: Mapping[str, object],
    krcn_enabled_results: Mapping[str, object],
) -> ModelCapabilityEvaluation:
    expected_ids = tuple(item.case_id for item in golden_set.cases)
    if set(baseline_results) != set(expected_ids) or set(krcn_enabled_results) != set(
        expected_ids
    ):
        raise ModelCapabilityGateError("A/B results must cover the exact golden set")
    case_results: list[Mapping[str, object]] = []
    baseline_measurements: list[CapabilityMeasurement] = []
    enabled_measurements: list[CapabilityMeasurement] = []
    critical_regressions = 0
    for case in golden_set.cases:
        baseline = _measurement(baseline_results[case.case_id], case, "baseline")
        enabled = _measurement(
            krcn_enabled_results[case.case_id], case, "KRCN-enabled"
        )
        critical_regression = bool(
            case.critical
            and baseline.successful
            and (
                not enabled.successful
                or enabled.score_basis_points < baseline.score_basis_points
            )
        )
        if critical_regression:
            critical_regressions += 1
        baseline_measurements.append(baseline)
        enabled_measurements.append(enabled)
        case_results.append(
            {
                "case_id": case.case_id,
                "critical": case.critical,
                "baseline": baseline.as_dict(),
                "krcn_enabled": enabled.as_dict(),
                "baseline_success": baseline.successful,
                "krcn_enabled_success": enabled.successful,
                "critical_regression": critical_regression,
            }
        )
    all_execution_digests = [
        item.execution_digest
        for pair in zip(baseline_measurements, enabled_measurements)
        for item in pair
    ]
    if (
        len(set(all_execution_digests)) != len(all_execution_digests)
        or any(
            baseline.execution_digest == enabled.execution_digest
            for baseline, enabled in zip(
                baseline_measurements, enabled_measurements
            )
        )
    ):
        raise ModelCapabilityGateError(
            "every A/B golden case requires distinct execution evidence"
        )
    case_count = len(golden_set.cases)
    baseline_success = sum(item.successful for item in baseline_measurements)
    enabled_success = sum(item.successful for item in enabled_measurements)
    baseline_rate = _rate(baseline_success, case_count)
    enabled_rate = _rate(enabled_success, case_count)
    baseline_score = round(
        sum(item.score_basis_points for item in baseline_measurements) / case_count
    )
    enabled_score = round(
        sum(item.score_basis_points for item in enabled_measurements) / case_count
    )
    baseline_tokens = sum(
        item.input_tokens + item.output_tokens for item in baseline_measurements
    )
    enabled_tokens = sum(
        item.input_tokens + item.output_tokens for item in enabled_measurements
    )
    baseline_latency = sum(item.latency_ms for item in baseline_measurements)
    enabled_latency = sum(item.latency_ms for item in enabled_measurements)
    baseline_calls = sum(item.agent_call_count for item in baseline_measurements)
    enabled_calls = sum(item.agent_call_count for item in enabled_measurements)
    baseline_human = sum(
        item.human_intervention_count for item in baseline_measurements
    )
    enabled_human = sum(
        item.human_intervention_count for item in enabled_measurements
    )
    hard_violations = sum(
        len(item.hard_constraint_violations) for item in enabled_measurements
    )
    aggregate = {
        "case_count": case_count,
        "critical_case_count": sum(item.critical for item in golden_set.cases),
        "baseline_success_count": baseline_success,
        "enabled_success_count": enabled_success,
        "baseline_success_rate_basis_points": baseline_rate,
        "enabled_success_rate_basis_points": enabled_rate,
        "success_delta_basis_points": enabled_rate - baseline_rate,
        "baseline_average_score_basis_points": baseline_score,
        "enabled_average_score_basis_points": enabled_score,
        "score_delta_basis_points": enabled_score - baseline_score,
        "critical_regression_count": critical_regressions,
        "hard_constraint_violation_count": hard_violations,
        "token_delta_basis_points": _relative_delta(enabled_tokens, baseline_tokens),
        "latency_delta_basis_points": _relative_delta(
            enabled_latency, baseline_latency
        ),
        "agent_call_delta_basis_points": _relative_delta(
            enabled_calls, baseline_calls
        ),
        "human_intervention_delta_basis_points": _relative_delta(
            enabled_human, baseline_human
        ),
    }
    blocking: list[str] = []
    if baseline_rate - enabled_rate > policy.thresholds[
        "maximum_general_success_regression_basis_points"
    ]:
        blocking.append("general-success-regression")
    if baseline_score - enabled_score > policy.thresholds[
        "maximum_general_score_regression_basis_points"
    ]:
        blocking.append("general-score-regression")
    if critical_regressions > policy.thresholds["maximum_critical_regressions"]:
        blocking.append("critical-regression")
    if hard_violations > policy.thresholds["maximum_hard_constraint_violations"]:
        blocking.append("hard-constraint-violation")
    advisories: list[str] = []
    if _overhead_exceeds(
        enabled_tokens,
        baseline_tokens,
        policy.thresholds["advisory_token_overhead_basis_points"],
    ):
        advisories.append("token-overhead")
    if _overhead_exceeds(
        enabled_latency,
        baseline_latency,
        policy.thresholds["advisory_latency_overhead_basis_points"],
    ):
        advisories.append("latency-overhead")
    if _overhead_exceeds(
        enabled_calls,
        baseline_calls,
        policy.thresholds["advisory_agent_call_overhead_basis_points"],
    ):
        advisories.append("agent-call-overhead")
    if _overhead_exceeds(
        enabled_human,
        baseline_human,
        policy.thresholds["advisory_human_intervention_overhead_basis_points"],
    ):
        advisories.append("human-intervention-overhead")
    identity = {
        "policy_digest": policy.policy_digest,
        "golden_set_digest": golden_set.golden_set_digest,
        "case_results": case_results,
        "aggregate": aggregate,
        "blocking_reasons": sorted(blocking),
        "advisories": sorted(advisories),
    }
    return ModelCapabilityEvaluation(
        f"evaluation-{_digest(identity)}",
        policy.policy_digest,
        golden_set.golden_set_digest,
        "blocked" if blocking else "passed",
        tuple(case_results),
        aggregate,
        tuple(sorted(blocking)),
        tuple(sorted(advisories)),
    )


def parse_model_capability_evaluation(
    payload: object,
    policy: ModelCapabilityPolicy,
    golden_set: ModelCapabilityGoldenSet,
) -> ModelCapabilityEvaluation:
    expected = {
        "schema_ref",
        "schema_version",
        "evaluation_id",
        "policy_digest",
        "golden_set_digest",
        "status",
        "case_results",
        "aggregate",
        "blocking_reasons",
        "advisories",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelCapabilityGateError("model capability evaluation fields are invalid")
    cases = payload.get("case_results")
    if not isinstance(cases, list):
        raise ModelCapabilityGateError("model capability case results are invalid")
    baseline: dict[str, object] = {}
    enabled: dict[str, object] = {}
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise ModelCapabilityGateError("model capability case result is invalid")
        baseline[item["case_id"]] = item.get("baseline")
        enabled[item["case_id"]] = item.get("krcn_enabled")
    rebuilt = evaluate_model_capability(policy, golden_set, baseline, enabled)
    if canonical_json(payload) != canonical_json(rebuilt.as_dict()):
        raise ModelCapabilityGateError("model capability evaluation digest is invalid")
    return rebuilt
