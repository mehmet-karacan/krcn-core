"""Read-only memory hygiene, research dedupe, and context effectiveness.

The hygiene layer consumes reviewed metadata only.  It never reads memory
content and never deletes, merges, supersedes, or revokes a memory.  Reviewed
suggestions must pass through the existing Memory Gate as separate exact plans.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .information_records import canonical_json
from .local_store import LocalWorkspaceStore
from .memory_gate import (
    MemoryAction,
    MemoryLifecyclePlan,
    parse_memory_action,
    prepare_memory_lifecycle,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/@-]*$")
LIFECYCLES = {"current", "superseded", "archived"}
PUBLIC_INVARIANTS = {
    "memory_content_included": False,
    "source_content_included": False,
    "physical_paths_included": False,
    "secret_values_included": False,
    "automatic_delete_performed": False,
    "automatic_merge_performed": False,
    "automatic_lifecycle_mutation_performed": False,
    "memory_gate_required": True,
    "grants_authority": False,
}


class MemoryHygieneError(ValueError):
    """Raised when metadata, measurements, or a hygiene digest is unsafe."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _strict(payload: object, expected: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise MemoryHygieneError(f"{label} fields are invalid")
    return payload


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise MemoryHygieneError(f"{label} is invalid")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise MemoryHygieneError(f"{label} must be a SHA-256 digest")
    return value


def _logical_ref(value: object, label: str) -> str:
    if isinstance(value, str):
        lowered = value.lower()
        if any(token in lowered for token in ("password=", "token=", "api-key=", "secret=")):
            raise MemoryHygieneError(f"{label} must not contain a secret")
        if "\\" in value or "://" in value:
            raise MemoryHygieneError(f"{label} must not contain a physical path")
    if not isinstance(value, str) or not LOGICAL_REF.fullmatch(value):
        raise MemoryHygieneError(f"{label} must be a logical reference")
    suffix = value.split(":", 1)[1]
    if ".." in suffix.split("/"):
        raise MemoryHygieneError(f"{label} must not contain a physical path")
    return value


def _datetime(value: object, label: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise MemoryHygieneError(f"{label} must be a UTC timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise MemoryHygieneError(f"{label} is invalid") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise MemoryHygieneError(f"{label} must be UTC")
    return parsed


def _timestamp(value: object, label: str, *, optional: bool = False) -> str | None:
    parsed = _datetime(value, label, optional=optional)
    return None if parsed is None else str(value)


def _sorted_unique_ids(value: object, label: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MemoryHygieneError(f"{label} must be a list")
    items = tuple(_identifier(item, label) for item in value)
    if (not allow_empty and not items) or items != tuple(sorted(set(items))):
        raise MemoryHygieneError(f"{label} must be a sorted unique identifier list")
    return items


def _basis(numerator: int, denominator: int, *, empty: int = 10000) -> int:
    if denominator == 0:
        return empty
    return min(10000, (numerator * 10000) // denominator)


@dataclass(frozen=True)
class MemoryHygienePolicy:
    policy_revision: int
    stale_after_days: int
    unused_after_days: int
    retention_review_after_days: int
    minimum_required_evidence_recall_basis_points: int
    minimum_context_use_basis_points: int
    maximum_stale_rate_basis_points: int
    maximum_duplicate_rate_basis_points: int
    maximum_omitted_rate_basis_points: int
    minimum_downstream_success_basis_points: int
    require_compaction_rehydration: bool
    policy_digest: str


def load_memory_hygiene_policy(repo_root: Path) -> MemoryHygienePolicy:
    path = repo_root / "config" / "memory-hygiene-policy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemoryHygieneError("memory hygiene policy is unreadable") from exc
    expected = {
        "schema_ref", "schema_version", "policy_revision", "stale_after_days",
        "unused_after_days", "retention_review_after_days", "context_thresholds",
        "invariants",
    }
    _strict(payload, expected, "memory hygiene policy")
    if (
        payload.get("schema_ref") != "schemas/memory-hygiene-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("invariants") != PUBLIC_INVARIANTS
    ):
        raise MemoryHygieneError("memory hygiene policy contract is invalid")
    limits = [payload.get(name) for name in (
        "policy_revision", "stale_after_days", "unused_after_days", "retention_review_after_days",
    )]
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in limits):
        raise MemoryHygieneError("memory hygiene policy limits are invalid")
    thresholds = _strict(
        payload.get("context_thresholds"),
        {
            "minimum_required_evidence_recall_basis_points",
            "minimum_context_use_basis_points",
            "maximum_stale_rate_basis_points",
            "maximum_duplicate_rate_basis_points",
            "maximum_omitted_rate_basis_points",
            "minimum_downstream_success_basis_points",
            "require_compaction_rehydration",
        },
        "memory hygiene context thresholds",
    )
    basis_names = tuple(name for name in thresholds if name != "require_compaction_rehydration")
    if any(
        not isinstance(thresholds[name], int)
        or isinstance(thresholds[name], bool)
        or not 0 <= thresholds[name] <= 10000
        for name in basis_names
    ) or not isinstance(thresholds["require_compaction_rehydration"], bool):
        raise MemoryHygieneError("memory hygiene context thresholds are invalid")
    return MemoryHygienePolicy(
        limits[0], limits[1], limits[2], limits[3],
        int(thresholds["minimum_required_evidence_recall_basis_points"]),
        int(thresholds["minimum_context_use_basis_points"]),
        int(thresholds["maximum_stale_rate_basis_points"]),
        int(thresholds["maximum_duplicate_rate_basis_points"]),
        int(thresholds["maximum_omitted_rate_basis_points"]),
        int(thresholds["minimum_downstream_success_basis_points"]),
        bool(thresholds["require_compaction_rehydration"]),
        _digest(payload),
    )


@dataclass(frozen=True)
class MemoryMetadataOverlay:
    memory_id: str
    revision: int
    content_digest: str
    semantic_digest: str
    created_at: str
    valid_from: str | None
    valid_until: str | None
    last_used_at: str | None
    usage_count: int
    retention_review_at: str | None
    conflict_refs: tuple[str, ...]
    lifecycle: str
    reviewed_by_ref: str
    review_digest: str
    metadata_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/memory-metadata-overlay.schema.json",
            "schema_version": 1,
            "memory_id": self.memory_id,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "semantic_digest": self.semantic_digest,
            "created_at": self.created_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "last_used_at": self.last_used_at,
            "usage_count": self.usage_count,
            "retention_review_at": self.retention_review_at,
            "conflict_refs": list(self.conflict_refs),
            "lifecycle": self.lifecycle,
            "reviewed_by_ref": self.reviewed_by_ref,
            "review_digest": self.review_digest,
            "metadata_digest": self.metadata_digest,
            "invariants": PUBLIC_INVARIANTS,
        }


def _metadata_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in payload if key not in {"schema_ref", "schema_version", "metadata_digest"}}


def build_memory_metadata_overlay(**values: object) -> MemoryMetadataOverlay:
    payload: dict[str, object] = {
        "schema_ref": "schemas/memory-metadata-overlay.schema.json",
        "schema_version": 1,
        **values,
        "invariants": PUBLIC_INVARIANTS,
    }
    payload["metadata_digest"] = _digest(_metadata_identity(payload))
    return parse_memory_metadata_overlay(payload)


def parse_memory_metadata_overlay(payload: object) -> MemoryMetadataOverlay:
    expected = {
        "schema_ref", "schema_version", "memory_id", "revision", "content_digest",
        "semantic_digest", "created_at", "valid_from", "valid_until", "last_used_at",
        "usage_count", "retention_review_at", "conflict_refs", "lifecycle",
        "reviewed_by_ref", "review_digest", "metadata_digest", "invariants",
    }
    data = _strict(payload, expected, "memory metadata overlay")
    if (
        data.get("schema_ref") != "schemas/memory-metadata-overlay.schema.json"
        or data.get("schema_version") != 1
        or data.get("invariants") != PUBLIC_INVARIANTS
        or data.get("lifecycle") not in LIFECYCLES
    ):
        raise MemoryHygieneError("memory metadata overlay contract is invalid")
    memory_id = _identifier(data.get("memory_id"), "memory_id")
    revision, usage_count = data.get("revision"), data.get("usage_count")
    if (
        not isinstance(revision, int) or isinstance(revision, bool) or revision < 1
        or not isinstance(usage_count, int) or isinstance(usage_count, bool) or usage_count < 0
    ):
        raise MemoryHygieneError("memory metadata counters are invalid")
    content_digest = _sha256(data.get("content_digest"), "content_digest")
    semantic_digest = _sha256(data.get("semantic_digest"), "semantic_digest")
    created_at = _timestamp(data.get("created_at"), "created_at")
    valid_from = _timestamp(data.get("valid_from"), "valid_from", optional=True)
    valid_until = _timestamp(data.get("valid_until"), "valid_until", optional=True)
    last_used = _timestamp(data.get("last_used_at"), "last_used_at", optional=True)
    retention = _timestamp(data.get("retention_review_at"), "retention_review_at", optional=True)
    created_dt = _datetime(created_at, "created_at")
    from_dt = _datetime(valid_from, "valid_from", optional=True)
    until_dt = _datetime(valid_until, "valid_until", optional=True)
    used_dt = _datetime(last_used, "last_used_at", optional=True)
    if from_dt is not None and until_dt is not None and until_dt <= from_dt:
        raise MemoryHygieneError("memory temporal validity interval is invalid")
    if used_dt is not None and used_dt < created_dt:
        raise MemoryHygieneError("last_used_at predates memory creation")
    conflict_refs = _sorted_unique_ids(data.get("conflict_refs"), "conflict_refs")
    reviewed_by_ref = _logical_ref(data.get("reviewed_by_ref"), "reviewed_by_ref")
    review_digest = _sha256(data.get("review_digest"), "review_digest")
    metadata_digest = _sha256(data.get("metadata_digest"), "metadata_digest")
    if metadata_digest != _digest(_metadata_identity(data)):
        raise MemoryHygieneError("memory metadata digest does not match")
    return MemoryMetadataOverlay(
        memory_id, revision, content_digest, semantic_digest, str(created_at),
        valid_from, valid_until, last_used, usage_count, retention, conflict_refs,
        str(data["lifecycle"]), reviewed_by_ref, review_digest, metadata_digest,
    )


@dataclass(frozen=True)
class ResearchEvidenceMetadata:
    evidence_id: str
    canonical_source_ref: str
    content_digest: str
    observed_at: str
    evidence_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/research-evidence-metadata.schema.json",
            "schema_version": 1,
            "evidence_id": self.evidence_id,
            "canonical_source_ref": self.canonical_source_ref,
            "content_digest": self.content_digest,
            "observed_at": self.observed_at,
            "evidence_digest": self.evidence_digest,
            "invariants": PUBLIC_INVARIANTS,
        }


def _evidence_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in payload if key not in {"schema_ref", "schema_version", "evidence_digest"}}


def build_research_evidence_metadata(
    *, evidence_id: str, canonical_source_ref: str, content_digest: str, observed_at: str,
) -> ResearchEvidenceMetadata:
    payload: dict[str, object] = {
        "schema_ref": "schemas/research-evidence-metadata.schema.json",
        "schema_version": 1,
        "evidence_id": evidence_id,
        "canonical_source_ref": canonical_source_ref,
        "content_digest": content_digest,
        "observed_at": observed_at,
        "invariants": PUBLIC_INVARIANTS,
    }
    payload["evidence_digest"] = _digest(_evidence_identity(payload))
    return parse_research_evidence_metadata(payload)


def parse_research_evidence_metadata(payload: object) -> ResearchEvidenceMetadata:
    expected = {
        "schema_ref", "schema_version", "evidence_id", "canonical_source_ref",
        "content_digest", "observed_at", "evidence_digest", "invariants",
    }
    data = _strict(payload, expected, "research evidence metadata")
    if (
        data.get("schema_ref") != "schemas/research-evidence-metadata.schema.json"
        or data.get("schema_version") != 1
        or data.get("invariants") != PUBLIC_INVARIANTS
    ):
        raise MemoryHygieneError("research evidence metadata contract is invalid")
    evidence_id = _identifier(data.get("evidence_id"), "evidence_id")
    source_ref = _logical_ref(data.get("canonical_source_ref"), "canonical_source_ref")
    content_digest = _sha256(data.get("content_digest"), "content_digest")
    observed_at = _timestamp(data.get("observed_at"), "observed_at")
    evidence_digest = _sha256(data.get("evidence_digest"), "evidence_digest")
    if evidence_digest != _digest(_evidence_identity(data)):
        raise MemoryHygieneError("research evidence digest does not match")
    return ResearchEvidenceMetadata(evidence_id, source_ref, content_digest, str(observed_at), evidence_digest)


def group_research_evidence_duplicates(evidence: Iterable[ResearchEvidenceMetadata]) -> tuple[dict[str, object], ...]:
    """Return deterministic duplicate-of suggestions with a single group weight."""

    checked = [parse_research_evidence_metadata(item.as_payload()) for item in evidence]
    if len({item.evidence_id for item in checked}) != len(checked):
        raise MemoryHygieneError("research evidence contains duplicate identities")
    parent = {item.evidence_id: item.evidence_id for item in checked}

    def root(item_id: str) -> str:
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    def union(left: str, right: str) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for index, left in enumerate(checked):
        for right in checked[index + 1:]:
            if left.canonical_source_ref == right.canonical_source_ref or left.content_digest == right.content_digest:
                union(left.evidence_id, right.evidence_id)
    groups: dict[str, list[str]] = {}
    for item in checked:
        groups.setdefault(root(item.evidence_id), []).append(item.evidence_id)
    return tuple(
        {
            "canonical_evidence_id": sorted(ids)[0],
            "duplicate_of_suggestions": [
                {"evidence_id": item_id, "duplicate_of": sorted(ids)[0], "evidence_weight": 0}
                for item_id in sorted(ids)[1:]
            ],
            "canonical_evidence_weight": 1,
        }
        for ids in sorted(groups.values(), key=lambda group: sorted(group)[0])
        if len(ids) > 1
    )


@dataclass(frozen=True)
class ContextEffectiveness:
    evaluation_id: str
    policy_digest: str
    required_evidence_refs: tuple[str, ...]
    recalled_evidence_refs: tuple[str, ...]
    selected_bytes: int
    used_bytes: int
    selected_tokens: int
    used_tokens: int
    selected_count: int
    stale_selected_count: int
    duplicate_selected_count: int
    omitted_required_count: int
    downstream_success_basis_points: int
    compaction_rehydration_passed: bool
    metrics: Mapping[str, int]
    passed: bool
    evaluation_digest: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/context-effectiveness.schema.json",
            "schema_version": 1,
            "evaluation_id": self.evaluation_id,
            "policy_digest": self.policy_digest,
            "required_evidence_refs": list(self.required_evidence_refs),
            "recalled_evidence_refs": list(self.recalled_evidence_refs),
            "selected_bytes": self.selected_bytes,
            "used_bytes": self.used_bytes,
            "selected_tokens": self.selected_tokens,
            "used_tokens": self.used_tokens,
            "selected_count": self.selected_count,
            "stale_selected_count": self.stale_selected_count,
            "duplicate_selected_count": self.duplicate_selected_count,
            "omitted_required_count": self.omitted_required_count,
            "downstream_success_basis_points": self.downstream_success_basis_points,
            "compaction_rehydration_passed": self.compaction_rehydration_passed,
            "metrics": dict(self.metrics),
            "passed": self.passed,
            "evaluation_digest": self.evaluation_digest,
            "invariants": PUBLIC_INVARIANTS,
        }


def _context_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: payload[key] for key in payload if key not in {"schema_ref", "schema_version", "evaluation_digest"}}


def build_context_effectiveness(
    policy: MemoryHygienePolicy,
    *,
    evaluation_id: str,
    required_evidence_refs: Iterable[str],
    recalled_evidence_refs: Iterable[str],
    selected_bytes: int,
    used_bytes: int,
    selected_tokens: int,
    used_tokens: int,
    selected_count: int,
    stale_selected_count: int,
    duplicate_selected_count: int,
    omitted_required_count: int,
    downstream_success_basis_points: int,
    compaction_rehydration_passed: bool,
) -> ContextEffectiveness:
    required = tuple(sorted(set(required_evidence_refs)))
    recalled = tuple(sorted(set(recalled_evidence_refs)))
    for ref in required + recalled:
        _logical_ref(ref, "evidence reference")
    if not required:
        raise MemoryHygieneError("required evidence references cannot be empty")
    counters = (
        selected_bytes, used_bytes, selected_tokens, used_tokens, selected_count,
        stale_selected_count, duplicate_selected_count, omitted_required_count,
        downstream_success_basis_points,
    )
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in counters):
        raise MemoryHygieneError("context effectiveness counters are invalid")
    if (
        used_bytes > selected_bytes or used_tokens > selected_tokens
        or stale_selected_count > selected_count
        or duplicate_selected_count > selected_count
        or omitted_required_count > len(required)
        or downstream_success_basis_points > 10000
        or not isinstance(compaction_rehydration_passed, bool)
    ):
        raise MemoryHygieneError("context effectiveness measurements are inconsistent")
    recalled_required = len(set(required) & set(recalled))
    metrics = {
        "required_evidence_recall_basis_points": _basis(recalled_required, len(required)),
        "used_bytes_basis_points": _basis(used_bytes, selected_bytes, empty=0),
        "used_tokens_basis_points": _basis(used_tokens, selected_tokens, empty=0),
        "stale_rate_basis_points": _basis(stale_selected_count, selected_count, empty=0),
        "duplicate_rate_basis_points": _basis(duplicate_selected_count, selected_count, empty=0),
        "omitted_rate_basis_points": _basis(omitted_required_count, len(required), empty=0),
        "downstream_success_basis_points": downstream_success_basis_points,
    }
    passed = (
        metrics["required_evidence_recall_basis_points"] >= policy.minimum_required_evidence_recall_basis_points
        and min(metrics["used_bytes_basis_points"], metrics["used_tokens_basis_points"]) >= policy.minimum_context_use_basis_points
        and metrics["stale_rate_basis_points"] <= policy.maximum_stale_rate_basis_points
        and metrics["duplicate_rate_basis_points"] <= policy.maximum_duplicate_rate_basis_points
        and metrics["omitted_rate_basis_points"] <= policy.maximum_omitted_rate_basis_points
        and downstream_success_basis_points >= policy.minimum_downstream_success_basis_points
        and (compaction_rehydration_passed or not policy.require_compaction_rehydration)
    )
    payload: dict[str, object] = {
        "schema_ref": "schemas/context-effectiveness.schema.json",
        "schema_version": 1,
        "evaluation_id": evaluation_id,
        "policy_digest": policy.policy_digest,
        "required_evidence_refs": list(required),
        "recalled_evidence_refs": list(recalled),
        "selected_bytes": selected_bytes,
        "used_bytes": used_bytes,
        "selected_tokens": selected_tokens,
        "used_tokens": used_tokens,
        "selected_count": selected_count,
        "stale_selected_count": stale_selected_count,
        "duplicate_selected_count": duplicate_selected_count,
        "omitted_required_count": omitted_required_count,
        "downstream_success_basis_points": downstream_success_basis_points,
        "compaction_rehydration_passed": compaction_rehydration_passed,
        "metrics": metrics,
        "passed": passed,
        "invariants": PUBLIC_INVARIANTS,
    }
    payload["evaluation_digest"] = _digest(_context_identity(payload))
    return parse_context_effectiveness(payload)


def parse_context_effectiveness(payload: object) -> ContextEffectiveness:
    expected = {
        "schema_ref", "schema_version", "evaluation_id", "policy_digest", "required_evidence_refs",
        "recalled_evidence_refs", "selected_bytes", "used_bytes", "selected_tokens",
        "used_tokens", "selected_count", "stale_selected_count",
        "duplicate_selected_count", "omitted_required_count",
        "downstream_success_basis_points", "compaction_rehydration_passed",
        "metrics", "passed", "evaluation_digest", "invariants",
    }
    data = _strict(payload, expected, "context effectiveness")
    if (
        data.get("schema_ref") != "schemas/context-effectiveness.schema.json"
        or data.get("schema_version") != 1
        or data.get("invariants") != PUBLIC_INVARIANTS
        or not isinstance(data.get("passed"), bool)
        or not isinstance(data.get("compaction_rehydration_passed"), bool)
    ):
        raise MemoryHygieneError("context effectiveness contract is invalid")
    evaluation_id = _identifier(data.get("evaluation_id"), "evaluation_id")
    policy_digest = _sha256(data.get("policy_digest"), "policy_digest")
    required = data.get("required_evidence_refs")
    recalled = data.get("recalled_evidence_refs")
    if not isinstance(required, list) or not isinstance(recalled, list) or not required:
        raise MemoryHygieneError("context evidence references are invalid")
    required_refs = tuple(_logical_ref(item, "required evidence reference") for item in required)
    recalled_refs = tuple(_logical_ref(item, "recalled evidence reference") for item in recalled)
    if required_refs != tuple(sorted(set(required_refs))) or recalled_refs != tuple(sorted(set(recalled_refs))):
        raise MemoryHygieneError("context evidence references must be sorted and unique")
    counter_names = (
        "selected_bytes", "used_bytes", "selected_tokens", "used_tokens", "selected_count",
        "stale_selected_count", "duplicate_selected_count", "omitted_required_count",
        "downstream_success_basis_points",
    )
    counters = tuple(data.get(name) for name in counter_names)
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in counters):
        raise MemoryHygieneError("context effectiveness counters are invalid")
    metrics = _strict(
        data.get("metrics"),
        {
            "required_evidence_recall_basis_points", "used_bytes_basis_points",
            "used_tokens_basis_points", "stale_rate_basis_points",
            "duplicate_rate_basis_points", "omitted_rate_basis_points",
            "downstream_success_basis_points",
        },
        "context effectiveness metrics",
    )
    if any(not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10000 for value in metrics.values()):
        raise MemoryHygieneError("context effectiveness metrics are invalid")
    expected_metrics = {
        "required_evidence_recall_basis_points": _basis(len(set(required_refs) & set(recalled_refs)), len(required_refs)),
        "used_bytes_basis_points": _basis(counters[1], counters[0], empty=0),
        "used_tokens_basis_points": _basis(counters[3], counters[2], empty=0),
        "stale_rate_basis_points": _basis(counters[5], counters[4], empty=0),
        "duplicate_rate_basis_points": _basis(counters[6], counters[4], empty=0),
        "omitted_rate_basis_points": _basis(counters[7], len(required_refs), empty=0),
        "downstream_success_basis_points": counters[8],
    }
    if dict(metrics) != expected_metrics:
        raise MemoryHygieneError("context effectiveness metrics do not match measurements")
    evaluation_digest = _sha256(data.get("evaluation_digest"), "evaluation_digest")
    if evaluation_digest != _digest(_context_identity(data)):
        raise MemoryHygieneError("context effectiveness digest does not match")
    return ContextEffectiveness(
        evaluation_id, policy_digest, required_refs, recalled_refs,
        counters[0], counters[1], counters[2], counters[3], counters[4],
        counters[5], counters[6], counters[7], counters[8],
        bool(data["compaction_rehydration_passed"]), dict(metrics),
        bool(data["passed"]), evaluation_digest,
    )


@dataclass(frozen=True)
class HygieneActionSuggestion:
    suggestion_id: str
    action: str
    memory_id: str
    expected_revision: int
    expected_content_digest: str
    replacement_ref: str | None
    reason_codes: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "suggestion_id": self.suggestion_id,
            "action": self.action,
            "memory_id": self.memory_id,
            "expected_revision": self.expected_revision,
            "expected_content_digest": self.expected_content_digest,
            "replacement_ref": self.replacement_ref,
            "reason_codes": list(self.reason_codes),
            "requires_memory_gate": True,
            "grants_authority": False,
        }


def build_memory_hygiene_report(
    policy: MemoryHygienePolicy,
    memories: Iterable[MemoryMetadataOverlay],
    research_evidence: Iterable[ResearchEvidenceMetadata],
    context_evaluations: Iterable[ContextEffectiveness],
    *,
    report_id: str,
    as_of: str,
) -> dict[str, object]:
    """Build a deterministic read-only report over reviewed metadata."""

    report_id = _identifier(report_id, "report_id")
    as_of_dt = _datetime(as_of, "as_of")
    checked = [parse_memory_metadata_overlay(item.as_payload()) for item in memories]
    if len({item.memory_id for item in checked}) != len(checked):
        raise MemoryHygieneError("memory metadata contains duplicate identities")
    checked.sort(key=lambda item: item.memory_id)
    evidence = [parse_research_evidence_metadata(item.as_payload()) for item in research_evidence]
    contexts = [parse_context_effectiveness(item.as_payload()) for item in context_evaluations]
    if len({item.evaluation_id for item in contexts}) != len(contexts):
        raise MemoryHygieneError("context evaluations contain duplicate identities")

    stale: list[str] = []
    conflicts: list[str] = []
    unused: list[str] = []
    retention: list[str] = []
    not_yet_valid: list[str] = []
    semantic_groups: dict[str, list[MemoryMetadataOverlay]] = {}
    for item in checked:
        semantic_groups.setdefault(item.semantic_digest, []).append(item)
        valid_from = _datetime(item.valid_from, "valid_from", optional=True)
        valid_until = _datetime(item.valid_until, "valid_until", optional=True)
        last_used = _datetime(item.last_used_at, "last_used_at", optional=True)
        created = _datetime(item.created_at, "created_at")
        review_at = _datetime(item.retention_review_at, "retention_review_at", optional=True)
        if valid_from is not None and valid_from > as_of_dt:
            not_yet_valid.append(item.memory_id)
        if valid_until is not None and valid_until <= as_of_dt:
            stale.append(item.memory_id)
        elif item.lifecycle == "current" and as_of_dt - (last_used or created) >= timedelta(days=policy.stale_after_days):
            stale.append(item.memory_id)
        if item.conflict_refs:
            conflicts.append(item.memory_id)
        if item.usage_count == 0 and as_of_dt - (last_used or created) >= timedelta(days=policy.unused_after_days):
            unused.append(item.memory_id)
        if (
            review_at is not None and review_at <= as_of_dt
        ) or (
            review_at is None and as_of_dt - created >= timedelta(days=policy.retention_review_after_days)
        ):
            retention.append(item.memory_id)

    duplicate_groups = []
    duplicate_ids: set[str] = set()
    canonical_by_duplicate: dict[str, str] = {}
    for group in sorted(semantic_groups.values(), key=lambda values: values[0].memory_id):
        current = sorted((item for item in group if item.lifecycle == "current"), key=lambda item: item.memory_id)
        if len(current) < 2:
            continue
        canonical = current[0]
        duplicates = [item.memory_id for item in current[1:]]
        duplicate_ids.update(duplicates)
        canonical_by_duplicate.update({item_id: canonical.memory_id for item_id in duplicates})
        duplicate_groups.append({
            "canonical_memory_id": canonical.memory_id,
            "duplicate_memory_ids": duplicates,
            "semantic_digest": canonical.semantic_digest,
        })

    suggestions: list[HygieneActionSuggestion] = []
    by_id = {item.memory_id: item for item in checked}
    candidate_ids = sorted(set(stale) | set(retention) | duplicate_ids)
    for memory_id in candidate_ids:
        item = by_id[memory_id]
        reasons = tuple(sorted(
            code for code, members in (
                ("duplicate", duplicate_ids), ("retention-review", set(retention)), ("stale", set(stale)),
            ) if memory_id in members
        ))
        if memory_id in duplicate_ids:
            action = "supersede"
            replacement = f"memory:{canonical_by_duplicate[memory_id]}"
        else:
            action = "revoke"
            replacement = None
        suggestions.append(HygieneActionSuggestion(
            f"hygiene-{action}-{memory_id}", action, memory_id, item.revision,
            item.content_digest, replacement, reasons,
        ))

    identity: dict[str, object] = {
        "report_id": report_id,
        "as_of": as_of,
        "policy_digest": policy.policy_digest,
        "reviewed_memory_digests": sorted(item.metadata_digest for item in checked),
        "reviewed_evidence_digests": sorted(item.evidence_digest for item in evidence),
        "context_evaluation_digests": sorted(item.evaluation_digest for item in contexts),
        "stale_memory_ids": sorted(stale),
        "conflict_memory_ids": sorted(conflicts),
        "duplicate_groups": duplicate_groups,
        "unused_memory_ids": sorted(unused),
        "retention_candidate_ids": sorted(retention),
        "not_yet_valid_memory_ids": sorted(not_yet_valid),
        "research_duplicate_groups": list(group_research_evidence_duplicates(evidence)),
        "context_effectiveness": [item.as_payload() for item in sorted(contexts, key=lambda item: item.evaluation_id)],
        "action_suggestions": [item.as_payload() for item in suggestions],
        "invariants": PUBLIC_INVARIANTS,
    }
    report = {
        "schema_ref": "schemas/memory-hygiene-report.schema.json",
        "schema_version": 1,
        **identity,
        "report_digest": _digest(identity),
    }
    return parse_memory_hygiene_report(report)


def parse_memory_hygiene_report(payload: object) -> dict[str, object]:
    expected = {
        "schema_ref", "schema_version", "report_id", "as_of", "policy_digest",
        "reviewed_memory_digests", "reviewed_evidence_digests",
        "context_evaluation_digests", "stale_memory_ids", "conflict_memory_ids",
        "duplicate_groups", "unused_memory_ids", "retention_candidate_ids",
        "not_yet_valid_memory_ids", "research_duplicate_groups",
        "context_effectiveness", "action_suggestions", "invariants", "report_digest",
    }
    data = _strict(payload, expected, "memory hygiene report")
    if (
        data.get("schema_ref") != "schemas/memory-hygiene-report.schema.json"
        or data.get("schema_version") != 1
        or data.get("invariants") != PUBLIC_INVARIANTS
    ):
        raise MemoryHygieneError("memory hygiene report contract is invalid")
    _identifier(data.get("report_id"), "report_id")
    _timestamp(data.get("as_of"), "as_of")
    _sha256(data.get("policy_digest"), "policy_digest")
    for field in ("reviewed_memory_digests", "reviewed_evidence_digests", "context_evaluation_digests"):
        values = data.get(field)
        if not isinstance(values, list) or tuple(values) != tuple(sorted(set(values))):
            raise MemoryHygieneError(f"{field} must be sorted and unique")
        for value in values:
            _sha256(value, field)
    for field in (
        "stale_memory_ids", "conflict_memory_ids", "unused_memory_ids",
        "retention_candidate_ids", "not_yet_valid_memory_ids",
    ):
        _sorted_unique_ids(data.get(field), field)
    duplicate_groups = data.get("duplicate_groups")
    research_groups = data.get("research_duplicate_groups")
    if not isinstance(duplicate_groups, list) or not isinstance(research_groups, list):
        raise MemoryHygieneError("memory hygiene duplicate groups are invalid")
    previous_canonical = None
    seen_memory_ids: set[str] = set()
    for group in duplicate_groups:
        checked_group = _strict(
            group,
            {"canonical_memory_id", "duplicate_memory_ids", "semantic_digest"},
            "memory duplicate group",
        )
        canonical = _identifier(checked_group.get("canonical_memory_id"), "canonical_memory_id")
        duplicates = _sorted_unique_ids(
            checked_group.get("duplicate_memory_ids"),
            "duplicate_memory_ids",
            allow_empty=False,
        )
        _sha256(checked_group.get("semantic_digest"), "semantic_digest")
        if canonical in duplicates or canonical in seen_memory_ids or any(item in seen_memory_ids for item in duplicates):
            raise MemoryHygieneError("memory duplicate groups overlap")
        if previous_canonical is not None and canonical <= previous_canonical:
            raise MemoryHygieneError("memory duplicate groups must be sorted")
        previous_canonical = canonical
        seen_memory_ids.update((canonical, *duplicates))
    previous_evidence = None
    seen_evidence_ids: set[str] = set()
    for group in research_groups:
        checked_group = _strict(
            group,
            {"canonical_evidence_id", "duplicate_of_suggestions", "canonical_evidence_weight"},
            "research duplicate group",
        )
        canonical = _identifier(checked_group.get("canonical_evidence_id"), "canonical_evidence_id")
        if checked_group.get("canonical_evidence_weight") != 1:
            raise MemoryHygieneError("canonical research evidence weight must be one")
        suggestions_payload = checked_group.get("duplicate_of_suggestions")
        if not isinstance(suggestions_payload, list) or not suggestions_payload:
            raise MemoryHygieneError("research duplicate suggestions are invalid")
        suggestion_ids: list[str] = []
        for suggestion in suggestions_payload:
            checked_suggestion = _strict(
                suggestion,
                {"evidence_id", "duplicate_of", "evidence_weight"},
                "research duplicate suggestion",
            )
            evidence_id = _identifier(checked_suggestion.get("evidence_id"), "evidence_id")
            if checked_suggestion.get("duplicate_of") != canonical or checked_suggestion.get("evidence_weight") != 0:
                raise MemoryHygieneError("research duplicate suggestion is inconsistent")
            suggestion_ids.append(evidence_id)
        if suggestion_ids != sorted(set(suggestion_ids)) or canonical in suggestion_ids:
            raise MemoryHygieneError("research duplicate suggestion identities are invalid")
        if canonical in seen_evidence_ids or any(item in seen_evidence_ids for item in suggestion_ids):
            raise MemoryHygieneError("research duplicate groups overlap")
        if previous_evidence is not None and canonical <= previous_evidence:
            raise MemoryHygieneError("research duplicate groups must be sorted")
        previous_evidence = canonical
        seen_evidence_ids.update((canonical, *suggestion_ids))
    context_payloads = data.get("context_effectiveness")
    if not isinstance(context_payloads, list):
        raise MemoryHygieneError("context effectiveness list is invalid")
    parsed_contexts = [parse_context_effectiveness(item) for item in context_payloads]
    if [item.evaluation_id for item in parsed_contexts] != sorted(
        {item.evaluation_id for item in parsed_contexts}
    ):
        raise MemoryHygieneError("context effectiveness list must be sorted and unique")
    if sorted(item.evaluation_digest for item in parsed_contexts) != data.get("context_evaluation_digests"):
        raise MemoryHygieneError("context evaluation digests do not match payloads")
    suggestions = data.get("action_suggestions")
    if not isinstance(suggestions, list):
        raise MemoryHygieneError("memory hygiene suggestions are invalid")
    for item in suggestions:
        parse_hygiene_action_suggestion(item)
    report_digest = _sha256(data.get("report_digest"), "report_digest")
    identity = {key: data[key] for key in data if key not in {"schema_ref", "schema_version", "report_digest"}}
    if report_digest != _digest(identity):
        raise MemoryHygieneError("memory hygiene report digest does not match")
    return dict(data)


def parse_hygiene_action_suggestion(payload: object) -> HygieneActionSuggestion:
    expected = {
        "suggestion_id", "action", "memory_id", "expected_revision",
        "expected_content_digest", "replacement_ref", "reason_codes",
        "requires_memory_gate", "grants_authority",
    }
    data = _strict(payload, expected, "memory hygiene action suggestion")
    if data.get("requires_memory_gate") is not True or data.get("grants_authority") is not False:
        raise MemoryHygieneError("memory hygiene suggestion cannot grant authority")
    suggestion_id = _identifier(data.get("suggestion_id"), "suggestion_id")
    memory_id = _identifier(data.get("memory_id"), "memory_id")
    action = data.get("action")
    if action not in {"supersede", "revoke"}:
        raise MemoryHygieneError("memory hygiene action is invalid")
    revision = data.get("expected_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise MemoryHygieneError("memory hygiene suggestion revision is invalid")
    content_digest = _sha256(data.get("expected_content_digest"), "expected_content_digest")
    replacement = data.get("replacement_ref")
    if replacement is not None:
        replacement = _logical_ref(replacement, "replacement_ref")
    if (action == "supersede") != (replacement is not None):
        raise MemoryHygieneError("memory hygiene replacement does not match action")
    reason_codes = _sorted_unique_ids(data.get("reason_codes"), "reason_codes", allow_empty=False)
    return HygieneActionSuggestion(
        suggestion_id, str(action), memory_id, revision, content_digest,
        replacement, reason_codes,
    )


def prepare_reviewed_memory_action(
    store: LocalWorkspaceStore,
    suggestion: HygieneActionSuggestion,
    approved_action: MemoryAction,
) -> MemoryLifecyclePlan:
    """Bind a reviewed suggestion to the existing approval-gated Memory Gate."""

    suggestion = parse_hygiene_action_suggestion(suggestion.as_payload())
    action = parse_memory_action(approved_action.as_payload())
    if (
        action.action != suggestion.action
        or action.memory_id != suggestion.memory_id
        or action.expected_revision != suggestion.expected_revision
        or action.expected_content_digest != suggestion.expected_content_digest
        or action.replacement_ref != suggestion.replacement_ref
    ):
        raise MemoryHygieneError("approved memory action does not match the hygiene suggestion")
    return prepare_memory_lifecycle(store, action)
