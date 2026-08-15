"""Versioned golden evaluation and synthetic scale fixtures for retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Iterator, Mapping, Sequence

from .foundation import detect_content_findings, load_json
from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SAFE_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._:/-]*$")
BLOCKING_DETECTORS = {
    "windows-absolute-path",
    "posix-user-path",
    "private-key",
    "github-token",
    "aws-access-key",
    "generic-secret-assignment",
    "credential-uri",
    "unicode-long-dash",
}
RANKING_OUTCOMES = {"ranked"}
SAFETY_OUTCOMES = {"empty", "stale-rejected"}


class RetrievalQualityError(ValueError):
    """Raised when retrieval quality evidence is incomplete or unsafe."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise RetrievalQualityError(f"{label} must be a portable identifier")
    return value


def _text(value: object, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RetrievalQualityError(f"{label} must be bounded non-empty text")
    normalized = value.strip()
    if detect_content_findings(normalized, label, BLOCKING_DETECTORS):
        raise RetrievalQualityError(f"{label} contains sensitive or non-portable content")
    return normalized


def _reference(value: object, label: str) -> str:
    if not isinstance(value, str) or not SAFE_REF.fullmatch(value):
        raise RetrievalQualityError(f"{label} must be a portable logical reference")
    path_part = value.split(":", 1)[1]
    if (
        PurePosixPath(path_part).is_absolute()
        or PureWindowsPath(path_part).drive
        or ".." in PurePosixPath(path_part).parts
        or "\\" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise RetrievalQualityError(f"{label} must not disclose a physical path")
    return value


def _unique_identifiers(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise RetrievalQualityError(f"{label} must be a non-empty list")
    items = tuple(_identifier(item, label) for item in value)
    if len(set(items)) != len(items):
        raise RetrievalQualityError(f"{label} must be unique")
    return items


def _unique_references(
    value: object,
    label: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise RetrievalQualityError(f"{label} must be a list")
    items = tuple(_reference(item, label) for item in value)
    if len(set(items)) != len(items):
        raise RetrievalQualityError(f"{label} must be unique")
    return items


def _basis_points(value: float) -> int:
    return int(round(max(0.0, min(1.0, value)) * 10000))


def _percentile(values: Sequence[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return int(ordered[index])


@dataclass(frozen=True)
class RetrievalGoldenCase:
    case_id: str
    category: str
    language: str
    query_text: str
    scope_project_ids: tuple[str, ...]
    expected_relevant_refs: tuple[str, ...]
    forbidden_refs: tuple[str, ...]
    expected_outcome: str
    critical: bool

    def identity(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "language": self.language,
            "query_text": self.query_text,
            "scope_project_ids": list(self.scope_project_ids),
            "expected_relevant_refs": list(self.expected_relevant_refs),
            "forbidden_refs": list(self.forbidden_refs),
            "expected_outcome": self.expected_outcome,
            "critical": self.critical,
        }


@dataclass(frozen=True)
class RetrievalGoldenSet:
    suite_id: str
    revision: int
    top_k: int
    minimum_recall_at_k_basis_points: int
    minimum_mrr_basis_points: int
    minimum_ndcg_at_k_basis_points: int
    minimum_exact_top_one_basis_points: int
    maximum_p95_latency_ms: int
    cases: tuple[RetrievalGoldenCase, ...]
    suite_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/retrieval-golden-set.schema.json",
            "schema_version": 1,
            "suite_id": self.suite_id,
            "revision": self.revision,
            "top_k": self.top_k,
            "thresholds": {
                "minimum_recall_at_k_basis_points": self.minimum_recall_at_k_basis_points,
                "minimum_mrr_basis_points": self.minimum_mrr_basis_points,
                "minimum_ndcg_at_k_basis_points": self.minimum_ndcg_at_k_basis_points,
                "minimum_exact_top_one_basis_points": self.minimum_exact_top_one_basis_points,
                "maximum_p95_latency_ms": self.maximum_p95_latency_ms,
            },
            "cases": [item.identity() for item in self.cases],
            "suite_digest": self.suite_digest,
            "invariants": {
                "source_content_included": False,
                "secret_values_included": False,
                "physical_paths_included": False,
                "provider_call_performed": False,
                "grants_authority": False,
            },
        }


@dataclass(frozen=True)
class RetrievalHitObservation:
    logical_ref: str
    project_id: str
    revision_digest: str

    def as_dict(self) -> dict[str, str]:
        return {
            "logical_ref": self.logical_ref,
            "project_id": self.project_id,
            "revision_digest": self.revision_digest,
        }


@dataclass(frozen=True)
class RetrievalCaseObservation:
    case_id: str
    status: str
    hits: tuple[RetrievalHitObservation, ...]
    latency_ms: int

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "hits": [item.as_dict() for item in self.hits],
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class RetrievalScaleProfile:
    profile_id: str
    document_count: int
    query_count: int
    project_count: int
    payload_tokens_per_document: int
    maximum_expected_p95_ms: int


@dataclass(frozen=True)
class RetrievalScalePolicy:
    policy_id: str
    revision: int
    profiles: tuple[RetrievalScaleProfile, ...]
    policy_digest: str


@dataclass(frozen=True)
class RetrievalScaleDocument:
    document_id: str
    project_id: str
    logical_ref: str
    revision_digest: str
    text: str


@dataclass(frozen=True)
class RetrievalScaleQuery:
    query_id: str
    query_text: str
    scope_project_id: str
    expected_ref: str


def parse_retrieval_golden_set(payload: Mapping[str, object]) -> RetrievalGoldenSet:
    expected = {
        "schema_ref",
        "schema_version",
        "suite_id",
        "revision",
        "top_k",
        "thresholds",
        "cases",
        "suite_digest",
        "invariants",
    }
    if set(payload) != expected:
        raise RetrievalQualityError("retrieval golden set fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/retrieval-golden-set.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise RetrievalQualityError("retrieval golden set schema is invalid")
    suite_id = _identifier(payload.get("suite_id"), "suite id")
    revision = payload.get("revision")
    top_k = payload.get("top_k")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise RetrievalQualityError("retrieval golden revision is invalid")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
        raise RetrievalQualityError("retrieval golden top_k is invalid")
    thresholds = payload.get("thresholds")
    threshold_fields = {
        "minimum_recall_at_k_basis_points",
        "minimum_mrr_basis_points",
        "minimum_ndcg_at_k_basis_points",
        "minimum_exact_top_one_basis_points",
        "maximum_p95_latency_ms",
    }
    if not isinstance(thresholds, dict) or set(thresholds) != threshold_fields:
        raise RetrievalQualityError("retrieval golden thresholds are invalid")
    for name in threshold_fields - {"maximum_p95_latency_ms"}:
        value = thresholds.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10000:
            raise RetrievalQualityError("retrieval golden quality threshold is invalid")
    maximum_p95 = thresholds.get("maximum_p95_latency_ms")
    if not isinstance(maximum_p95, int) or isinstance(maximum_p95, bool) or maximum_p95 < 1:
        raise RetrievalQualityError("retrieval golden latency threshold is invalid")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) < 9:
        raise RetrievalQualityError("retrieval golden set must cover every required category")
    cases: list[RetrievalGoldenCase] = []
    required_categories = {
        "exact-id",
        "typo-lexical",
        "business-concept",
        "symbol-lookup",
        "dependency-impact",
        "continuity-resume",
        "plsql-symbol",
        "cross-project-isolation",
        "stale-revision",
    }
    for raw in raw_cases:
        case_fields = {
            "case_id",
            "category",
            "language",
            "query_text",
            "scope_project_ids",
            "expected_relevant_refs",
            "forbidden_refs",
            "expected_outcome",
            "critical",
        }
        if not isinstance(raw, dict) or set(raw) != case_fields:
            raise RetrievalQualityError("retrieval golden case fields are invalid")
        category = raw.get("category")
        language = raw.get("language")
        outcome = raw.get("expected_outcome")
        if category not in required_categories or language not in {"tr", "en", "polyglot"}:
            raise RetrievalQualityError("retrieval golden case taxonomy is invalid")
        if outcome not in RANKING_OUTCOMES | SAFETY_OUTCOMES:
            raise RetrievalQualityError("retrieval golden expected outcome is invalid")
        relevant = _unique_references(
            raw.get("expected_relevant_refs"),
            "expected relevant refs",
            allow_empty=outcome in SAFETY_OUTCOMES,
        )
        forbidden = _unique_references(
            raw.get("forbidden_refs"),
            "forbidden refs",
            allow_empty=outcome in RANKING_OUTCOMES,
        )
        if outcome in SAFETY_OUTCOMES and relevant:
            raise RetrievalQualityError("safety cases must not declare relevant hits")
        if outcome in RANKING_OUTCOMES and not relevant:
            raise RetrievalQualityError("ranking cases require relevant hits")
        if set(relevant) & set(forbidden):
            raise RetrievalQualityError("relevant and forbidden refs must be disjoint")
        scope_projects = _unique_identifiers(
            raw.get("scope_project_ids"),
            "scope project ids",
        )
        relevant_projects = {
            ref.split(":", 1)[1].split("/", 1)[0] for ref in relevant
        }
        if not relevant_projects.issubset(set(scope_projects)):
            raise RetrievalQualityError("relevant refs must remain inside case scope")
        if category == "cross-project-isolation" and not any(
            ref.split(":", 1)[1].split("/", 1)[0] not in set(scope_projects)
            for ref in forbidden
        ):
            raise RetrievalQualityError("isolation cases require an out-of-scope ref")
        critical = raw.get("critical")
        if not isinstance(critical, bool):
            raise RetrievalQualityError("retrieval golden critical flag is invalid")
        cases.append(
            RetrievalGoldenCase(
                _identifier(raw.get("case_id"), "case id"),
                str(category),
                str(language),
                _text(raw.get("query_text"), "retrieval query"),
                scope_projects,
                relevant,
                forbidden,
                str(outcome),
                critical,
            )
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise RetrievalQualityError("retrieval golden case ids must be unique")
    if {case.category for case in cases} != required_categories:
        raise RetrievalQualityError("retrieval golden category coverage is incomplete")
    identity = {
        "suite_id": suite_id,
        "revision": revision,
        "top_k": top_k,
        "thresholds": thresholds,
        "cases": [case.identity() for case in cases],
    }
    suite_digest = payload.get("suite_digest")
    if not isinstance(suite_digest, str) or suite_digest != _digest(identity):
        raise RetrievalQualityError("retrieval golden set digest is invalid")
    invariants = payload.get("invariants")
    if invariants != {
        "source_content_included": False,
        "secret_values_included": False,
        "physical_paths_included": False,
        "provider_call_performed": False,
        "grants_authority": False,
    }:
        raise RetrievalQualityError("retrieval golden invariants are invalid")
    return RetrievalGoldenSet(
        suite_id,
        revision,
        top_k,
        int(thresholds["minimum_recall_at_k_basis_points"]),
        int(thresholds["minimum_mrr_basis_points"]),
        int(thresholds["minimum_ndcg_at_k_basis_points"]),
        int(thresholds["minimum_exact_top_one_basis_points"]),
        int(maximum_p95),
        tuple(cases),
        suite_digest,
    )


def load_retrieval_golden_set(repo_root: Path) -> RetrievalGoldenSet:
    return parse_retrieval_golden_set(
        load_json(repo_root / "config" / "retrieval-golden-set.json")
    )


def parse_retrieval_observations(
    payload: object,
    golden_set: RetrievalGoldenSet,
) -> tuple[RetrievalCaseObservation, ...]:
    if not isinstance(payload, list):
        raise RetrievalQualityError("retrieval observations must be a list")
    observations: list[RetrievalCaseObservation] = []
    for raw in payload:
        if not isinstance(raw, dict) or set(raw) != {
            "case_id",
            "status",
            "hits",
            "latency_ms",
        }:
            raise RetrievalQualityError("retrieval observation fields are invalid")
        status = raw.get("status")
        latency = raw.get("latency_ms")
        if status not in {"completed", "stale-rejected"}:
            raise RetrievalQualityError("retrieval observation status is invalid")
        if not isinstance(latency, int) or isinstance(latency, bool) or latency < 0:
            raise RetrievalQualityError("retrieval observation latency is invalid")
        raw_hits = raw.get("hits")
        if not isinstance(raw_hits, list) or len(raw_hits) > golden_set.top_k:
            raise RetrievalQualityError("retrieval observation hit count is invalid")
        hits: list[RetrievalHitObservation] = []
        for raw_hit in raw_hits:
            if not isinstance(raw_hit, dict) or set(raw_hit) != {
                "logical_ref",
                "project_id",
                "revision_digest",
            }:
                raise RetrievalQualityError("retrieval hit observation fields are invalid")
            revision_digest = raw_hit.get("revision_digest")
            if not isinstance(revision_digest, str) or not SHA256.fullmatch(revision_digest):
                raise RetrievalQualityError("retrieval hit revision digest is invalid")
            hits.append(
                RetrievalHitObservation(
                    _reference(raw_hit.get("logical_ref"), "retrieval hit ref"),
                    _identifier(raw_hit.get("project_id"), "retrieval hit project"),
                    revision_digest,
                )
            )
            ref_project = hits[-1].logical_ref.split(":", 1)[1].split("/", 1)[0]
            if ref_project != hits[-1].project_id:
                raise RetrievalQualityError(
                    "retrieval hit project must match its logical reference"
                )
        if len({hit.logical_ref for hit in hits}) != len(hits):
            raise RetrievalQualityError("retrieval hit refs must be unique")
        observations.append(
            RetrievalCaseObservation(
                _identifier(raw.get("case_id"), "observation case id"),
                str(status),
                tuple(hits),
                latency,
            )
        )
    expected_ids = [case.case_id for case in golden_set.cases]
    actual_ids = [item.case_id for item in observations]
    if len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != set(expected_ids):
        raise RetrievalQualityError("observations must cover the exact golden set")
    by_id = {item.case_id: item for item in observations}
    return tuple(by_id[case_id] for case_id in expected_ids)


def _ranking_case_metrics(
    case: RetrievalGoldenCase,
    observation: RetrievalCaseObservation,
    top_k: int,
) -> tuple[int, int, int, int | None]:
    ranked = [hit.logical_ref for hit in observation.hits[:top_k]]
    relevant = set(case.expected_relevant_refs)
    found = [rank for rank, ref in enumerate(ranked, 1) if ref in relevant]
    recall = len(found) / len(relevant)
    first_rank = min(found) if found else None
    reciprocal = 0.0 if first_rank is None else 1.0 / first_rank
    dcg = sum(1.0 / math.log2(rank + 1) for rank in found)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), top_k) + 1))
    ndcg = 0.0 if ideal == 0 else dcg / ideal
    return (
        _basis_points(recall),
        _basis_points(reciprocal),
        _basis_points(ndcg),
        first_rank,
    )


def evaluate_retrieval_golden_set(
    golden_set: RetrievalGoldenSet,
    observations: Iterable[RetrievalCaseObservation],
    *,
    engine_profile_id: str,
) -> dict[str, object]:
    engine_profile_id = _identifier(engine_profile_id, "engine profile id")
    observed = tuple(observations)
    if [item.case_id for item in observed] != [case.case_id for case in golden_set.cases]:
        raise RetrievalQualityError("observations must preserve golden set order")
    ranking_results: list[dict[str, object]] = []
    safety_results: list[dict[str, object]] = []
    exact_top_one: list[bool] = []
    cross_project_leakage_count = 0
    stale_acceptance_count = 0
    critical_failures: list[str] = []
    latencies: list[int] = []
    for case, observation in zip(golden_set.cases, observed):
        latencies.append(observation.latency_ms)
        refs = [hit.logical_ref for hit in observation.hits]
        scoped = set(case.scope_project_ids)
        cross_project = sum(hit.project_id not in scoped for hit in observation.hits)
        forbidden = sorted(set(refs) & set(case.forbidden_refs))
        cross_project_leakage_count += cross_project
        if case.expected_outcome == "stale-rejected":
            stale_accepted = observation.status != "stale-rejected" or bool(observation.hits)
            stale_acceptance_count += int(stale_accepted)
            passed = not stale_accepted and not forbidden and cross_project == 0
            safety_results.append(
                {
                    "case_id": case.case_id,
                    "passed": passed,
                    "status": observation.status,
                    "forbidden_hit_count": len(forbidden),
                    "cross_project_hit_count": cross_project,
                }
            )
        elif case.expected_outcome == "empty":
            passed = (
                observation.status == "completed"
                and not observation.hits
                and not forbidden
                and cross_project == 0
            )
            safety_results.append(
                {
                    "case_id": case.case_id,
                    "passed": passed,
                    "status": observation.status,
                    "forbidden_hit_count": len(forbidden),
                    "cross_project_hit_count": cross_project,
                }
            )
        else:
            recall, reciprocal, ndcg, first_rank = _ranking_case_metrics(
                case,
                observation,
                golden_set.top_k,
            )
            top_one = first_rank == 1
            if case.category == "exact-id":
                exact_top_one.append(top_one)
            passed = (
                observation.status == "completed"
                and recall > 0
                and not forbidden
                and cross_project == 0
            )
            ranking_results.append(
                {
                    "case_id": case.case_id,
                    "recall_at_k_basis_points": recall,
                    "reciprocal_rank_basis_points": reciprocal,
                    "ndcg_at_k_basis_points": ndcg,
                    "first_relevant_rank": first_rank,
                    "forbidden_hit_count": len(forbidden),
                    "cross_project_hit_count": cross_project,
                    "passed": passed,
                }
            )
        if case.critical and not passed:
            critical_failures.append(case.case_id)
    if not ranking_results or not safety_results or not exact_top_one:
        raise RetrievalQualityError("golden set lacks ranking, safety, or exact evidence")
    recall = round(sum(int(item["recall_at_k_basis_points"]) for item in ranking_results) / len(ranking_results))
    mrr = round(sum(int(item["reciprocal_rank_basis_points"]) for item in ranking_results) / len(ranking_results))
    ndcg = round(sum(int(item["ndcg_at_k_basis_points"]) for item in ranking_results) / len(ranking_results))
    exact = round(sum(exact_top_one) / len(exact_top_one) * 10000)
    safety = round(sum(bool(item["passed"]) for item in safety_results) / len(safety_results) * 10000)
    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    passed = (
        recall >= golden_set.minimum_recall_at_k_basis_points
        and mrr >= golden_set.minimum_mrr_basis_points
        and ndcg >= golden_set.minimum_ndcg_at_k_basis_points
        and exact >= golden_set.minimum_exact_top_one_basis_points
        and safety == 10000
        and cross_project_leakage_count == 0
        and stale_acceptance_count == 0
        and p95 <= golden_set.maximum_p95_latency_ms
        and not critical_failures
    )
    identity = {
        "suite_digest": golden_set.suite_digest,
        "engine_profile_id": engine_profile_id,
        "ranking_results": ranking_results,
        "safety_results": safety_results,
        "metrics": {
            "recall_at_k_basis_points": recall,
            "mean_reciprocal_rank_basis_points": mrr,
            "ndcg_at_k_basis_points": ndcg,
            "exact_top_one_basis_points": exact,
            "safety_pass_basis_points": safety,
            "cross_project_leakage_count": cross_project_leakage_count,
            "stale_acceptance_count": stale_acceptance_count,
        },
        "critical_failure_case_ids": sorted(critical_failures),
        "passed": passed,
    }
    return {
        "schema_ref": "schemas/retrieval-golden-result.schema.json",
        "schema_version": 1,
        **identity,
        "result_digest": _digest(identity),
        "latency_ms": {"p50": p50, "p95": p95},
        "case_count": len(golden_set.cases),
        "provider_call_performed": False,
        "source_content_copied": False,
        "grants_authority": False,
    }


def parse_retrieval_scale_policy(payload: Mapping[str, object]) -> RetrievalScalePolicy:
    if set(payload) != {
        "schema_ref",
        "schema_version",
        "policy_id",
        "revision",
        "profiles",
        "policy_digest",
        "invariants",
    }:
        raise RetrievalQualityError("retrieval scale policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/retrieval-scale-policy.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise RetrievalQualityError("retrieval scale policy schema is invalid")
    policy_id = _identifier(payload.get("policy_id"), "scale policy id")
    revision = payload.get("revision")
    raw_profiles = payload.get("profiles")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise RetrievalQualityError("retrieval scale policy revision is invalid")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise RetrievalQualityError("retrieval scale profiles are invalid")
    profiles: list[RetrievalScaleProfile] = []
    for raw in raw_profiles:
        fields = {
            "profile_id",
            "document_count",
            "query_count",
            "project_count",
            "payload_tokens_per_document",
            "maximum_expected_p95_ms",
        }
        if not isinstance(raw, dict) or set(raw) != fields:
            raise RetrievalQualityError("retrieval scale profile fields are invalid")
        counts = [
            raw.get("document_count"),
            raw.get("query_count"),
            raw.get("project_count"),
            raw.get("payload_tokens_per_document"),
            raw.get("maximum_expected_p95_ms"),
        ]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in counts):
            raise RetrievalQualityError("retrieval scale profile values are invalid")
        if int(raw["query_count"]) > int(raw["document_count"]):
            raise RetrievalQualityError("retrieval scale queries exceed documents")
        profiles.append(
            RetrievalScaleProfile(
                _identifier(raw.get("profile_id"), "scale profile id"),
                int(raw["document_count"]),
                int(raw["query_count"]),
                int(raw["project_count"]),
                int(raw["payload_tokens_per_document"]),
                int(raw["maximum_expected_p95_ms"]),
            )
        )
    if len({profile.profile_id for profile in profiles}) != len(profiles):
        raise RetrievalQualityError("retrieval scale profile ids must be unique")
    identity = {
        "policy_id": policy_id,
        "revision": revision,
        "profiles": [
            {
                "profile_id": item.profile_id,
                "document_count": item.document_count,
                "query_count": item.query_count,
                "project_count": item.project_count,
                "payload_tokens_per_document": item.payload_tokens_per_document,
                "maximum_expected_p95_ms": item.maximum_expected_p95_ms,
            }
            for item in profiles
        ],
    }
    policy_digest = payload.get("policy_digest")
    if not isinstance(policy_digest, str) or policy_digest != _digest(identity):
        raise RetrievalQualityError("retrieval scale policy digest is invalid")
    if payload.get("invariants") != {
        "synthetic_only": True,
        "source_content_included": False,
        "physical_paths_included": False,
        "provider_call_performed": False,
        "grants_authority": False,
    }:
        raise RetrievalQualityError("retrieval scale invariants are invalid")
    return RetrievalScalePolicy(policy_id, revision, tuple(profiles), policy_digest)


def load_retrieval_scale_policy(repo_root: Path) -> RetrievalScalePolicy:
    return parse_retrieval_scale_policy(
        load_json(repo_root / "config" / "retrieval-scale-fixtures.json")
    )


def iter_retrieval_scale_documents(
    policy: RetrievalScalePolicy,
    profile_id: str,
) -> Iterator[RetrievalScaleDocument]:
    profile_id = _identifier(profile_id, "scale profile id")
    profile = next((item for item in policy.profiles if item.profile_id == profile_id), None)
    if profile is None:
        raise RetrievalQualityError("retrieval scale profile is unknown")
    categories = (
        "java symbol dependency",
        "python service workflow",
        "sql migration relation",
        "plsql package procedure",
        "turkish business concept",
        "continuity resume checkpoint",
    )
    for index in range(profile.document_count):
        project_number = index % profile.project_count + 1
        anchor_number = index % profile.query_count + 1
        document_id = f"scale-doc-{index + 1:06d}"
        project_id = f"scale-project-{project_number:03d}"
        anchor = f"anchor-{anchor_number:06d}"
        base_tokens = (categories[index % len(categories)] + " " + anchor).split()
        tokens = [base_tokens[position % len(base_tokens)] for position in range(profile.payload_tokens_per_document)]
        text = " ".join(tokens)
        logical_ref = f"fixture:{project_id}/{document_id}"
        revision_digest = _digest(
            {
                "document_id": document_id,
                "project_id": project_id,
                "logical_ref": logical_ref,
                "text": text,
            }
        )
        yield RetrievalScaleDocument(
            document_id,
            project_id,
            logical_ref,
            revision_digest,
            text,
        )


def build_retrieval_scale_manifest(
    policy: RetrievalScalePolicy,
    profile_id: str,
) -> dict[str, object]:
    profile = next((item for item in policy.profiles if item.profile_id == profile_id), None)
    if profile is None:
        raise RetrievalQualityError("retrieval scale profile is unknown")
    accumulator = hashlib.sha256()
    first_refs: list[str] = []
    last_refs: list[str] = []
    count = 0
    for document in iter_retrieval_scale_documents(policy, profile_id):
        accumulator.update(
            canonical_json(
                {
                    "document_id": document.document_id,
                    "project_id": document.project_id,
                    "logical_ref": document.logical_ref,
                    "revision_digest": document.revision_digest,
                    "text_digest": _digest(document.text),
                }
            )
            + b"\n"
        )
        if len(first_refs) < 3:
            first_refs.append(document.logical_ref)
        last_refs = (last_refs + [document.logical_ref])[-3:]
        count += 1
    query_accumulator = hashlib.sha256()
    sample_query_ids: list[str] = []
    for query in iter_retrieval_scale_queries(policy, profile_id):
        query_accumulator.update(canonical_json(query.__dict__) + b"\n")
        if len(sample_query_ids) < 3:
            sample_query_ids.append(query.query_id)
    identity = {
        "policy_digest": policy.policy_digest,
        "profile_id": profile.profile_id,
        "document_count": count,
        "query_count": profile.query_count,
        "project_count": profile.project_count,
        "payload_tokens_per_document": profile.payload_tokens_per_document,
        "maximum_expected_p95_ms": profile.maximum_expected_p95_ms,
        "corpus_digest": accumulator.hexdigest(),
        "query_digest": query_accumulator.hexdigest(),
        "sample_refs": first_refs + [ref for ref in last_refs if ref not in first_refs],
        "sample_query_ids": sample_query_ids,
    }
    return {
        "schema_ref": "schemas/retrieval-scale-manifest.schema.json",
        "schema_version": 1,
        **identity,
        "manifest_digest": _digest(identity),
        "synthetic_only": True,
        "source_content_included": False,
        "physical_paths_included": False,
        "provider_call_performed": False,
        "grants_authority": False,
    }


def iter_retrieval_scale_queries(
    policy: RetrievalScalePolicy,
    profile_id: str,
) -> Iterator[RetrievalScaleQuery]:
    profile_id = _identifier(profile_id, "scale profile id")
    profile = next((item for item in policy.profiles if item.profile_id == profile_id), None)
    if profile is None:
        raise RetrievalQualityError("retrieval scale profile is unknown")
    for index in range(profile.query_count):
        document_number = index + 1
        project_number = index % profile.project_count + 1
        query_id = f"scale-query-{document_number:06d}"
        project_id = f"scale-project-{project_number:03d}"
        document_id = f"scale-doc-{document_number:06d}"
        yield RetrievalScaleQuery(
            query_id,
            f"{document_id} anchor-{document_number:06d}",
            project_id,
            f"fixture:{project_id}/{document_id}",
        )
