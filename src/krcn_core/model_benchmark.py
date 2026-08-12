"""Deterministic project-specific micro benchmark suite manifests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .information_records import canonical_json, parse_information_record
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .mutation_gate import MutationAuthorization
from .project_capability_profile import (
    load_project_capability_profiler_policy,
    parse_project_capability_profile,
)
from .project_integration_state import parse_project_integration_state
from .source_bindings import parse_source_binding
from .source_state import parse_source_state


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EVIDENCE_ID = re.compile(r"^evidence-[a-f0-9]{64}$")
WORKLOAD_KINDS = {
    "analysis",
    "architecture",
    "implementation",
    "verification",
    "code-review",
    "database-analysis",
    "security-review",
    "performance-analysis",
    "embedding",
    "reranking",
}
FIXTURE_POLICIES = {"synthetic-only", "sanitized-derived", "local-only"}
INVARIANTS = {
    "source_content_included": False,
    "prompt_content_included": False,
    "secret_values_included": False,
    "absolute_paths_included": False,
    "remote_call_performed": False,
    "grants_authority": False,
}


class ModelBenchmarkError(ValueError):
    """Raised when a benchmark suite is stale, unsafe, or inconsistent."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ModelBenchmarkError(f"{label} is invalid")
    return value


def _identifier_list(
    value: object,
    label: str,
    *,
    evidence: bool = False,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    pattern = EVIDENCE_ID if evidence else IDENTIFIER
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not pattern.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
        or tuple(value) != tuple(sorted(value))
    ):
        raise ModelBenchmarkError(f"{label} must be a sorted unique identifier list")
    return tuple(value)


@dataclass(frozen=True)
class BenchmarkTemplate:
    workload_kind: str
    template_id: str
    required_output_sections: tuple[str, ...]


@dataclass(frozen=True)
class ModelBenchmarkPolicy:
    policy_revision: int
    builder_id: str
    builder_revision: int
    maximum_cases: int
    maximum_context_refs_per_case: int
    quality_weight: int
    reliability_weight: int
    latency_weight: int
    templates: Mapping[str, BenchmarkTemplate]
    policy_digest: str


def load_model_benchmark_policy(repo_root: Path) -> ModelBenchmarkPolicy:
    """Load the versioned benchmark builder policy without network access."""

    path = repo_root / "config" / "model-benchmark-policy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelBenchmarkError("model benchmark policy is unreadable") from exc
    expected = {
        "schema_ref",
        "schema_version",
        "policy_revision",
        "suite_builder_id",
        "suite_builder_revision",
        "maximum_cases",
        "maximum_context_refs_per_case",
        "score_weights",
        "templates",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelBenchmarkError("model benchmark policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-benchmark-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants") != INVARIANTS
    ):
        raise ModelBenchmarkError("model benchmark policy contract is invalid")
    policy_revision = payload.get("policy_revision")
    builder_revision = payload.get("suite_builder_revision")
    maximum_cases = payload.get("maximum_cases")
    maximum_refs = payload.get("maximum_context_refs_per_case")
    if (
        any(
            not isinstance(item, int) or isinstance(item, bool) or item < 1
            for item in (
                policy_revision,
                builder_revision,
                maximum_cases,
                maximum_refs,
            )
        )
        or maximum_cases > 100
        or maximum_refs > 500
    ):
        raise ModelBenchmarkError("model benchmark policy limits are invalid")
    builder_id = _identifier(payload.get("suite_builder_id"), "suite_builder_id")
    weights = payload.get("score_weights")
    if not isinstance(weights, dict) or set(weights) != {
        "quality",
        "reliability",
        "latency",
    }:
        raise ModelBenchmarkError("model benchmark weights are invalid")
    weight_values = tuple(weights[key] for key in ("quality", "reliability", "latency"))
    if (
        any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or not 0 <= item <= 100
            for item in weight_values
        )
        or sum(weight_values) != 100
    ):
        raise ModelBenchmarkError("model benchmark weights must total 100")
    templates_payload = payload.get("templates")
    if not isinstance(templates_payload, list):
        raise ModelBenchmarkError("model benchmark templates must be a list")
    templates: dict[str, BenchmarkTemplate] = {}
    for item in templates_payload:
        if not isinstance(item, dict) or set(item) != {
            "workload_kind",
            "template_id",
            "required_output_sections",
        }:
            raise ModelBenchmarkError("model benchmark template fields are invalid")
        kind = item.get("workload_kind")
        if kind not in WORKLOAD_KINDS or kind in templates:
            raise ModelBenchmarkError("model benchmark workload template is invalid")
        templates[str(kind)] = BenchmarkTemplate(
            str(kind),
            _identifier(item.get("template_id"), "template_id"),
            _identifier_list(
                sorted(item.get("required_output_sections", [])),
                "required_output_sections",
                allow_empty=False,
            ),
        )
    if set(templates) != WORKLOAD_KINDS:
        raise ModelBenchmarkError("every workload kind requires one template")
    return ModelBenchmarkPolicy(
        int(policy_revision),
        builder_id,
        int(builder_revision),
        int(maximum_cases),
        int(maximum_refs),
        int(weights["quality"]),
        int(weights["reliability"]),
        int(weights["latency"]),
        templates,
        _digest(payload),
    )


def _current_profile(
    repo_root: Path,
    store: LocalWorkspaceStore,
    project_id: str,
) -> dict[str, object]:
    integration_record = store.read("project-integrations", project_id)
    capability_record = store.read("knowledge", f"{project_id}-capabilities")
    if integration_record is None or capability_record is None:
        raise ModelBenchmarkError("complete project integration is required")
    try:
        integration = parse_project_integration_state(integration_record.payload)
        information = parse_information_record(capability_record.payload)
        profile_payload = information.payload.get("profile")
        profile_policy = load_project_capability_profiler_policy(repo_root)
        profile = parse_project_capability_profile(
            profile_payload,
            policy=profile_policy,
        )
    except (OSError, ValueError) as exc:
        raise ModelBenchmarkError(
            "current structured project capability profile is required"
        ) from exc
    if (
        integration.project_id != project_id
        or profile["project_id"] != project_id
        or information.record_id != f"{project_id}-capabilities"
        or information.subject_ref != f"project:{project_id}/capabilities"
        or integration.source_digest != profile["source_digest"]
        or profile["coverage_state"] != "complete"
        or profile["authoritative_for_model_assignment"] is not True
    ):
        raise ModelBenchmarkError("project capability profile is incomplete or stale")
    binding_id = str(profile["binding_id"])
    binding_record = store.read("source-bindings", binding_id)
    state_record = store.read("source-states", binding_id)
    if binding_record is None or state_record is None:
        raise ModelBenchmarkError("project source identity is incomplete")
    binding = parse_source_binding(binding_record.payload)
    state = parse_source_state(state_record.payload)
    if (
        binding.source_id != project_id
        or binding.binding_id != binding_id
        or binding.revision != profile["binding_revision"]
        or state.binding_id != binding_id
        or state.binding_revision != binding.revision
        or state.root_digest != profile["source_digest"]
    ):
        raise ModelBenchmarkError("project source identity changed after profiling")
    current_files = {
        item.relative_path: item.sha256
        for item in state.files
    }
    for evidence in profile["evidence_catalog"]:
        if current_files.get(str(evidence["relative_path"])) != evidence["file_digest"]:
            raise ModelBenchmarkError("project profile evidence is stale")
    return profile


def _dimension_refs(profile: Mapping[str, object], category: str) -> list[str]:
    dimensions = profile["dimensions"]
    return sorted(str(item["capability_id"]) for item in dimensions[category])


def _build_case(
    profile: Mapping[str, object],
    workload: Mapping[str, object],
    policy: ModelBenchmarkPolicy,
) -> dict[str, object]:
    workload_kind = str(workload["workload_kind"])
    template = policy.templates[workload_kind]
    context = {
        "capability_refs": sorted(workload["required_capability_refs"]),
        "module_refs": sorted(workload["scope_refs"]),
        "evidence_refs": sorted(workload["context_evidence_refs"]),
    }
    if sum(len(items) for items in context.values()) > policy.maximum_context_refs_per_case:
        raise ModelBenchmarkError("benchmark case context exceeds the policy limit")
    fixture = {
        "technology_refs": _dimension_refs(profile, "technologies"),
        "framework_refs": _dimension_refs(profile, "frameworks"),
        "database_refs": _dimension_refs(profile, "databases"),
        "testing_refs": _dimension_refs(profile, "testing"),
        "quality_refs": _dimension_refs(profile, "quality"),
    }
    fixture_policy = str(workload["fixture_policy"])
    semantic = {
        "workload_id": workload["workload_id"],
        "workload_kind": workload_kind,
        "workload_digest": workload["workload_digest"],
        "template_id": template.template_id,
        "fixture_policy": fixture_policy,
        "remote_eligible": fixture_policy != "local-only",
        "trust_role": workload["trust_role"],
        "specialization_profile_id": workload["specialization_profile_id"],
        "context": context,
        "fixture_descriptor": fixture,
        "required_output_sections": list(template.required_output_sections),
        "rubric": {
            "quality_weight": policy.quality_weight,
            "reliability_weight": policy.reliability_weight,
            "latency_weight": policy.latency_weight,
            "dimension_refs": sorted(workload["benchmark_dimensions"]),
            "evaluation_traits": sorted(workload["evaluation_traits"]),
        },
    }
    case_digest = _digest(semantic)
    return {
        "case_id": f"case-{case_digest}",
        **semantic,
        "case_digest": case_digest,
    }


def build_project_benchmark_suite(
    repo_root: Path,
    store: LocalWorkspaceStore,
    project_id: str,
    *,
    suite_revision: int,
) -> dict[str, object]:
    """Build a source-content-free suite from one current capability profile."""

    project_id = _identifier(project_id, "project_id")
    if not isinstance(suite_revision, int) or isinstance(suite_revision, bool) or suite_revision < 1:
        raise ModelBenchmarkError("suite_revision is invalid")
    policy = load_model_benchmark_policy(repo_root)
    profile = _current_profile(repo_root, store, project_id)
    workloads = profile["workload_profiles"]
    if not workloads or len(workloads) > policy.maximum_cases:
        raise ModelBenchmarkError("project workload count exceeds benchmark policy")
    cases = [
        _build_case(profile, workload, policy)
        for workload in workloads
    ]
    cases.sort(key=lambda item: str(item["workload_id"]))
    suite_id = f"{project_id}-micro-benchmark"
    semantic = {
        "suite_id": suite_id,
        "project_id": project_id,
        "profile_digest": profile["profile_digest"],
        "capability_digest": profile["capability_digest"],
        "source_digest": profile["source_digest"],
        "builder": {
            "builder_id": policy.builder_id,
            "builder_revision": policy.builder_revision,
            "policy_revision": policy.policy_revision,
            "policy_digest": policy.policy_digest,
        },
        "cases": cases,
        "case_count": len(cases),
        "remote_eligible_case_count": sum(
            bool(item["remote_eligible"]) for item in cases
        ),
        "local_only_case_count": sum(
            not bool(item["remote_eligible"]) for item in cases
        ),
        "invariants": dict(INVARIANTS),
    }
    return {
        "schema_ref": "schemas/model-benchmark-suite.schema.json",
        "schema_version": 1,
        **semantic,
        "suite_revision": suite_revision,
        "suite_digest": _digest(semantic),
    }


def parse_model_benchmark_suite(
    payload: object,
    *,
    policy: ModelBenchmarkPolicy | None = None,
    profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Validate a persisted suite, case digests, and optional current inputs."""

    expected = {
        "schema_ref",
        "schema_version",
        "suite_id",
        "suite_revision",
        "project_id",
        "profile_digest",
        "capability_digest",
        "source_digest",
        "builder",
        "cases",
        "case_count",
        "remote_eligible_case_count",
        "local_only_case_count",
        "suite_digest",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ModelBenchmarkError("model benchmark suite fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/model-benchmark-suite.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants") != INVARIANTS
    ):
        raise ModelBenchmarkError("model benchmark suite contract is invalid")
    project_id = _identifier(payload.get("project_id"), "project_id")
    suite_id = _identifier(payload.get("suite_id"), "suite_id")
    if suite_id != f"{project_id}-micro-benchmark":
        raise ModelBenchmarkError("model benchmark suite identity is inconsistent")
    revision = payload.get("suite_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ModelBenchmarkError("suite_revision is invalid")
    for field in ("profile_digest", "capability_digest", "source_digest", "suite_digest"):
        if not isinstance(payload.get(field), str) or not SHA256.fullmatch(payload[field]):
            raise ModelBenchmarkError(f"{field} is invalid")
    builder = payload.get("builder")
    if not isinstance(builder, dict) or set(builder) != {
        "builder_id",
        "builder_revision",
        "policy_revision",
        "policy_digest",
    }:
        raise ModelBenchmarkError("model benchmark builder fields are invalid")
    _identifier(builder.get("builder_id"), "builder_id")
    if (
        any(
            not isinstance(builder.get(field), int)
            or isinstance(builder.get(field), bool)
            or builder[field] < 1
            for field in ("builder_revision", "policy_revision")
        )
        or not isinstance(builder.get("policy_digest"), str)
        or not SHA256.fullmatch(builder["policy_digest"])
    ):
        raise ModelBenchmarkError("model benchmark builder values are invalid")
    if policy is not None and builder != {
        "builder_id": policy.builder_id,
        "builder_revision": policy.builder_revision,
        "policy_revision": policy.policy_revision,
        "policy_digest": policy.policy_digest,
    }:
        raise ModelBenchmarkError("model benchmark suite policy is stale")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ModelBenchmarkError("model benchmark suite cases are invalid")
    parsed_cases = []
    seen_workloads = set()
    profile_workloads = {
        str(item["workload_id"]): item
        for item in (profile or {}).get("workload_profiles", [])
    }
    for item in cases:
        case_expected = {
            "case_id",
            "workload_id",
            "workload_kind",
            "workload_digest",
            "template_id",
            "fixture_policy",
            "remote_eligible",
            "trust_role",
            "specialization_profile_id",
            "context",
            "fixture_descriptor",
            "required_output_sections",
            "rubric",
            "case_digest",
        }
        if not isinstance(item, dict) or set(item) != case_expected:
            raise ModelBenchmarkError("model benchmark case fields are invalid")
        workload_id = _identifier(item.get("workload_id"), "workload_id")
        if workload_id in seen_workloads or item.get("workload_kind") not in WORKLOAD_KINDS:
            raise ModelBenchmarkError("model benchmark workload identity is invalid")
        seen_workloads.add(workload_id)
        if item.get("fixture_policy") not in FIXTURE_POLICIES:
            raise ModelBenchmarkError("model benchmark fixture policy is invalid")
        if item.get("remote_eligible") is not (
            item["fixture_policy"] != "local-only"
        ):
            raise ModelBenchmarkError("model benchmark remote eligibility is invalid")
        for field in ("template_id", "trust_role", "specialization_profile_id"):
            _identifier(item.get(field), field)
        if not isinstance(item.get("workload_digest"), str) or not SHA256.fullmatch(
            item["workload_digest"]
        ):
            raise ModelBenchmarkError("model benchmark workload digest is invalid")
        context = item.get("context")
        if not isinstance(context, dict) or set(context) != {
            "capability_refs",
            "module_refs",
            "evidence_refs",
        }:
            raise ModelBenchmarkError("model benchmark context fields are invalid")
        _identifier_list(context["capability_refs"], "capability_refs")
        _identifier_list(context["module_refs"], "module_refs")
        _identifier_list(context["evidence_refs"], "evidence_refs", evidence=True)
        fixture = item.get("fixture_descriptor")
        fixture_fields = {
            "technology_refs",
            "framework_refs",
            "database_refs",
            "testing_refs",
            "quality_refs",
        }
        if not isinstance(fixture, dict) or set(fixture) != fixture_fields:
            raise ModelBenchmarkError("model benchmark fixture descriptor is invalid")
        for field in fixture_fields:
            _identifier_list(fixture[field], field)
        _identifier_list(
            item.get("required_output_sections"),
            "required_output_sections",
            allow_empty=False,
        )
        rubric = item.get("rubric")
        if not isinstance(rubric, dict) or set(rubric) != {
            "quality_weight",
            "reliability_weight",
            "latency_weight",
            "dimension_refs",
            "evaluation_traits",
        }:
            raise ModelBenchmarkError("model benchmark rubric fields are invalid")
        weights = tuple(
            rubric[field]
            for field in ("quality_weight", "reliability_weight", "latency_weight")
        )
        if (
            any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 100
                for value in weights
            )
            or sum(weights) != 100
        ):
            raise ModelBenchmarkError("model benchmark case weights are invalid")
        _identifier_list(
            rubric["dimension_refs"],
            "dimension_refs",
            allow_empty=False,
        )
        _identifier_list(
            rubric["evaluation_traits"],
            "evaluation_traits",
            allow_empty=False,
        )
        semantic = {key: item[key] for key in case_expected - {"case_id", "case_digest"}}
        case_digest = _digest(semantic)
        if (
            item.get("case_digest") != case_digest
            or item.get("case_id") != f"case-{case_digest}"
        ):
            raise ModelBenchmarkError("model benchmark case digest is invalid")
        if policy is not None:
            template = policy.templates[str(item["workload_kind"])]
            if (
                item["template_id"] != template.template_id
                or tuple(item["required_output_sections"])
                != template.required_output_sections
                or weights
                != (
                    policy.quality_weight,
                    policy.reliability_weight,
                    policy.latency_weight,
                )
            ):
                raise ModelBenchmarkError("model benchmark case policy is stale")
        if profile is not None:
            workload = profile_workloads.get(workload_id)
            if (
                workload is None
                or item["workload_digest"] != workload["workload_digest"]
                or item["workload_kind"] != workload["workload_kind"]
            ):
                raise ModelBenchmarkError("model benchmark case profile is stale")
            if policy is not None and item != _build_case(profile, workload, policy):
                raise ModelBenchmarkError("model benchmark case no longer matches profile")
        parsed_cases.append(dict(item))
    if tuple(item["workload_id"] for item in cases) != tuple(sorted(seen_workloads)):
        raise ModelBenchmarkError("model benchmark cases are not deterministic")
    if (
        payload.get("case_count") != len(cases)
        or payload.get("remote_eligible_case_count")
        != sum(bool(item["remote_eligible"]) for item in cases)
        or payload.get("local_only_case_count")
        != sum(not bool(item["remote_eligible"]) for item in cases)
    ):
        raise ModelBenchmarkError("model benchmark case counts are invalid")
    semantic = {
        key: payload[key]
        for key in expected - {"schema_ref", "schema_version", "suite_revision", "suite_digest"}
    }
    if payload["suite_digest"] != _digest(semantic):
        raise ModelBenchmarkError("model benchmark suite digest is invalid")
    if profile is not None and (
        payload["profile_digest"] != profile["profile_digest"]
        or payload["capability_digest"] != profile["capability_digest"]
        or payload["source_digest"] != profile["source_digest"]
        or set(profile_workloads) != seen_workloads
    ):
        raise ModelBenchmarkError("model benchmark suite profile identity is stale")
    return json.loads(json.dumps(payload, ensure_ascii=False))


@dataclass(frozen=True)
class ProjectBenchmarkSuitePlan:
    plan_id: str
    suite: Mapping[str, object]
    effect_plan: RecordWritePlan | None

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "suite_id": self.suite["suite_id"],
            "project_id": self.suite["project_id"],
            "profile_digest": self.suite["profile_digest"],
            "suite_digest": self.suite["suite_digest"],
            "case_count": self.suite["case_count"],
            "remote_eligible_case_count": self.suite[
                "remote_eligible_case_count"
            ],
            "local_only_case_count": self.suite["local_only_case_count"],
            "workload_ids": [item["workload_id"] for item in self.suite["cases"]],
            "effect": self.effect_plan.public_summary() if self.effect_plan else None,
            "no_op": self.effect_plan is None,
            "source_content_included": False,
            "paths_disclosed": False,
            "remote_call_performed": False,
            "grants_authority": False,
        }


def prepare_project_benchmark_suite(
    repo_root: Path,
    store: LocalWorkspaceStore,
    project_id: str,
) -> ProjectBenchmarkSuitePlan:
    """Prepare an exact derived-data plan for one project benchmark suite."""

    project_id = _identifier(project_id, "project_id")
    suite_id = f"{project_id}-micro-benchmark"
    current = store.read("model-benchmark-suites", suite_id)
    next_revision = 1 if current is None else current.revision + 1
    suite = build_project_benchmark_suite(
        repo_root,
        store,
        project_id,
        suite_revision=next_revision,
    )
    effect = None
    if current is not None:
        parsed = parse_model_benchmark_suite(current.payload)
        if parsed["suite_digest"] == suite["suite_digest"]:
            suite = parsed
    if current is None or suite["suite_revision"] == next_revision:
        effect = store.prepare_put(
            "model-benchmark-suites",
            suite_id,
            suite,
            expected_revision=0 if current is None else current.revision,
            project_id=project_id,
        )
    identity = {
        "suite_id": suite_id,
        "suite_revision": suite["suite_revision"],
        "suite_digest": suite["suite_digest"],
        "effect_plan_id": effect.mutation.plan_id if effect else None,
    }
    return ProjectBenchmarkSuitePlan(_digest(identity), suite, effect)


def apply_project_benchmark_suite(
    store: LocalWorkspaceStore,
    plan: ProjectBenchmarkSuitePlan,
    authorization: MutationAuthorization | None,
) -> dict[str, object]:
    """Apply only the exact prepared benchmark suite record."""

    if plan.effect_plan is None:
        if authorization is not None:
            raise ModelBenchmarkError("no-op benchmark plan accepts no authorization")
        return parse_model_benchmark_suite(dict(plan.suite))
    if authorization is None:
        raise ModelBenchmarkError("benchmark suite authorization is required")
    stored = store.apply_put(plan.effect_plan, authorization)
    return parse_model_benchmark_suite(stored.payload)


def list_project_benchmark_suites(
    repo_root: Path,
    store: LocalWorkspaceStore,
    *,
    project_id: str | None = None,
) -> tuple[dict[str, object], ...]:
    """List safe suite summaries without fixture prompts or project paths."""

    if project_id is not None:
        project_id = _identifier(project_id, "project_id")
    results = []
    policy = load_model_benchmark_policy(repo_root)
    for stored in store.list_records("model-benchmark-suites"):
        suite = parse_model_benchmark_suite(stored.payload)
        if project_id is not None and suite["project_id"] != project_id:
            continue
        current = False
        try:
            profile = _current_profile(repo_root, store, str(suite["project_id"]))
            parse_model_benchmark_suite(
                stored.payload,
                policy=policy,
                profile=profile,
            )
            current = True
        except (ModelBenchmarkError, OSError, ValueError):
            current = False
        results.append(
            {
                "suite_id": suite["suite_id"],
                "project_id": suite["project_id"],
                "suite_revision": suite["suite_revision"],
                "profile_digest": suite["profile_digest"],
                "suite_digest": suite["suite_digest"],
                "case_count": suite["case_count"],
                "remote_eligible_case_count": suite[
                    "remote_eligible_case_count"
                ],
                "local_only_case_count": suite["local_only_case_count"],
                "workload_ids": [item["workload_id"] for item in suite["cases"]],
                "current": current,
                "effective_state": "current" if current else "stale",
                "source_content_included": False,
                "paths_disclosed": False,
                "remote_call_performed": False,
            }
        )
    return tuple(sorted(results, key=lambda item: str(item["suite_id"])))
