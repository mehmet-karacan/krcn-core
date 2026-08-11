"""Deterministic evidence-bounded context package construction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from .dependency_retrieval import DependencyResult
from .exact_retrieval import ExactRetrievalResult
from .information_records import (
    EvidenceRef,
    InformationRecord,
    InformationRecordError,
    canonical_json,
    parse_information_record,
)
from .knowledge_catalog import AVAILABILITY_RANK, CatalogEntry
from .semantic_retrieval import SemanticResult


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")
TOKEN_SPAN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
LAYERS = {"static": 0, "task": 1, "persistent": 2}
SELECTION_SOURCES = {
    "policy": 0,
    "static": 1,
    "exact": 2,
    "dependency": 3,
    "semantic": 4,
    "task-state": 5,
    "memory": 6,
}
AUTHORITY_RANK = {
    "authoritative-source": 0,
    "knowledge": 1,
    "memory": 2,
    "state": 3,
    "history": 4,
    "derived": 5,
}
BUDGET_UNITS = {"bytes", "characters", "tokens"}
MAX_BUDGET = 10_000_000
MAX_ITEMS = 10_000
SENSITIVE_REASON = re.compile(
    r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*=|"
    r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+|"
    r"(?:secret|keyring|env)://|"
    r"://[^/\s:@]+:[^/@\s]+@"
)


class ContextBuilderError(ValueError):
    """Raised when context cannot be built without weakening its contract."""


@dataclass(frozen=True)
class ContextBuildRequest:
    context_id: str
    task_ref: str
    project_ref: str | None
    budget_unit: str
    budget_limit: int
    item_limit: int
    allow_optional_truncation: bool
    minimum_fragment_units: int
    required_record_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/context-build-request.schema.json",
            "schema_version": 1,
            "context_id": self.context_id,
            "task_ref": self.task_ref,
            "project_ref": self.project_ref,
            "budget_unit": self.budget_unit,
            "budget_limit": self.budget_limit,
            "item_limit": self.item_limit,
            "allow_optional_truncation": self.allow_optional_truncation,
            "minimum_fragment_units": self.minimum_fragment_units,
            "required_record_ids": list(self.required_record_ids),
        }

    @property
    def request_digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class ContextCandidate:
    record: InformationRecord
    availability: str
    layer: str
    selection_sources: tuple[str, ...]
    selection_reasons: tuple[str, ...]
    required: bool
    priority: int
    allow_truncation: bool


@dataclass(frozen=True)
class ContextItem:
    record: InformationRecord
    layer: str
    selection_sources: tuple[str, ...]
    selection_reasons: tuple[str, ...]
    required: bool
    content: str
    original_units: int
    included_units: int
    truncated: bool
    truncation_reason: str | None
    projection_digest: str
    evidence: tuple[EvidenceRef, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record.record_id,
            "source_ref": self.record.subject_ref,
            "revision": self.record.revision,
            "digest": self.record.content_digest,
            "information_class": self.record.information_class,
            "ownership": self.record.ownership,
            "authority_rank": AUTHORITY_RANK[self.record.information_class],
            "layer": self.layer,
            "selection_sources": list(self.selection_sources),
            "selection_reasons": list(self.selection_reasons),
            "required": self.required,
            "content": self.content,
            "original_units": self.original_units,
            "included_units": self.included_units,
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "projection_digest": self.projection_digest,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class ContextExclusion:
    record_id: str
    content_digest: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "content_digest": self.content_digest,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ContextPackage:
    request: ContextBuildRequest
    candidate_digest: str
    items: tuple[ContextItem, ...]
    exclusions: tuple[ContextExclusion, ...]
    budget_used: int

    @property
    def required_record_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                item.record.record_id
                for item in self.items
                if item.required
            )
        )

    @property
    def context_digest(self) -> str:
        identity = {
            "request_digest": self.request.request_digest,
            "candidate_digest": self.candidate_digest,
            "items": [item.as_dict() for item in self.items],
            "exclusions": [item.as_dict() for item in self.exclusions],
            "budget": {
                "unit": self.request.budget_unit,
                "limit": self.request.budget_limit,
                "used": self.budget_used,
                "remaining": self.request.budget_limit - self.budget_used,
                "item_limit": self.request.item_limit,
                "item_used": len(self.items),
            },
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/context-package-v2.schema.json",
            "schema_version": 2,
            "context_id": self.request.context_id,
            "task_ref": self.request.task_ref,
            "project_ref": self.request.project_ref,
            "request_digest": self.request.request_digest,
            "candidate_digest": self.candidate_digest,
            "context_digest": self.context_digest,
            "required_record_ids": list(self.required_record_ids),
            "budget": {
                "unit": self.request.budget_unit,
                "limit": self.request.budget_limit,
                "used": self.budget_used,
                "remaining": self.request.budget_limit - self.budget_used,
                "item_limit": self.request.item_limit,
                "item_used": len(self.items),
            },
            "items": [item.as_dict() for item in self.items],
            "exclusions": [item.as_dict() for item in self.exclusions],
        }


def _logical_ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not LOGICAL_REF.fullmatch(value):
        raise ContextBuilderError(f"{label} must be a logical reference")
    if ".." in value.split(":", 1)[1].split("/") or "://" in value:
        raise ContextBuilderError(f"{label} must be portable")
    return value


def parse_context_build_request(payload: object) -> ContextBuildRequest:
    expected = {
        "schema_ref",
        "schema_version",
        "context_id",
        "task_ref",
        "project_ref",
        "budget_unit",
        "budget_limit",
        "item_limit",
        "allow_optional_truncation",
        "minimum_fragment_units",
        "required_record_ids",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ContextBuilderError("context build request fields are invalid")
    if payload.get("schema_ref") != "schemas/context-build-request.schema.json":
        raise ContextBuilderError("context build request schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ContextBuilderError("context build request schema_version must be 1")
    context_id = payload.get("context_id")
    if not isinstance(context_id, str) or not IDENTIFIER.fullmatch(context_id):
        raise ContextBuilderError("context_id must be a portable identifier")
    task_ref = _logical_ref(payload.get("task_ref"), "task_ref")
    project_ref_payload = payload.get("project_ref")
    project_ref = (
        None
        if project_ref_payload is None
        else _logical_ref(project_ref_payload, "project_ref")
    )
    budget_unit = payload.get("budget_unit")
    if not isinstance(budget_unit, str) or budget_unit not in BUDGET_UNITS:
        raise ContextBuilderError("context budget_unit is invalid")
    budget_limit = payload.get("budget_limit")
    item_limit = payload.get("item_limit")
    minimum_fragment_units = payload.get("minimum_fragment_units")
    for value, label, maximum in (
        (budget_limit, "budget_limit", MAX_BUDGET),
        (item_limit, "item_limit", MAX_ITEMS),
        (minimum_fragment_units, "minimum_fragment_units", MAX_BUDGET),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= maximum
        ):
            raise ContextBuilderError(f"context {label} is invalid")
    if minimum_fragment_units > budget_limit:
        raise ContextBuilderError("minimum fragment cannot exceed the budget")
    allow_optional_truncation = payload.get("allow_optional_truncation")
    if not isinstance(allow_optional_truncation, bool):
        raise ContextBuilderError("allow_optional_truncation must be boolean")
    required_payload = payload.get("required_record_ids")
    if not isinstance(required_payload, list) or any(
        not isinstance(item, str) or not IDENTIFIER.fullmatch(item)
        for item in required_payload
    ):
        raise ContextBuilderError("required_record_ids are invalid")
    if len(set(required_payload)) != len(required_payload):
        raise ContextBuilderError("required_record_ids must be unique")
    return ContextBuildRequest(
        context_id=context_id,
        task_ref=task_ref,
        project_ref=project_ref,
        budget_unit=budget_unit,
        budget_limit=budget_limit,
        item_limit=item_limit,
        allow_optional_truncation=allow_optional_truncation,
        minimum_fragment_units=minimum_fragment_units,
        required_record_ids=tuple(sorted(required_payload)),
    )


def _selection_metadata(
    layer: str,
    selection_source: str,
    selection_reason: str,
    priority: int,
) -> tuple[str, str, str, int]:
    if layer not in LAYERS:
        raise ContextBuilderError("context layer is invalid")
    if selection_source not in SELECTION_SOURCES:
        raise ContextBuilderError("context selection source is invalid")
    if (
        not isinstance(selection_reason, str)
        or not selection_reason.strip()
        or len(selection_reason) > 200
        or "\n" in selection_reason
        or "\r" in selection_reason
        or SENSITIVE_REASON.search(selection_reason)
    ):
        raise ContextBuilderError("context selection reason is invalid")
    if (
        not isinstance(priority, int)
        or isinstance(priority, bool)
        or not 0 <= priority <= 1000
    ):
        raise ContextBuilderError("context candidate priority is invalid")
    return layer, selection_source, selection_reason, priority


def context_candidate_from_entry(
    entry: CatalogEntry,
    *,
    layer: str,
    selection_source: str,
    selection_reason: str,
    required: bool = False,
    priority: int = 100,
    allow_truncation: bool = True,
) -> ContextCandidate:
    layer, selection_source, selection_reason, priority = _selection_metadata(
        layer,
        selection_source,
        selection_reason,
        priority,
    )
    if not isinstance(required, bool) or not isinstance(allow_truncation, bool):
        raise ContextBuilderError("context candidate flags must be boolean")
    return ContextCandidate(
        record=entry.record,
        availability=entry.availability,
        layer=layer,
        selection_sources=(selection_source,),
        selection_reasons=(selection_reason,),
        required=required,
        priority=priority,
        allow_truncation=allow_truncation,
    )


def candidates_from_exact_result(
    result: ExactRetrievalResult,
    *,
    layer: str = "task",
    priority: int = 100,
) -> tuple[ContextCandidate, ...]:
    return tuple(
        context_candidate_from_entry(
            hit.entry,
            layer=layer,
            selection_source="exact",
            selection_reason=f"exact:{hit.best_match}",
            priority=priority,
        )
        for hit in result.hits
    )


def candidates_from_dependency_result(
    result: DependencyResult,
    *,
    layer: str = "task",
    priority: int = 200,
) -> tuple[ContextCandidate, ...]:
    return tuple(
        context_candidate_from_entry(
            node.entry,
            layer=layer,
            selection_source="dependency",
            selection_reason=f"dependency:depth-{node.depth}",
            priority=priority + node.depth,
        )
        for node in result.nodes
    )


def candidates_from_semantic_result(
    result: SemanticResult,
    *,
    layer: str = "task",
    priority: int = 300,
) -> tuple[ContextCandidate, ...]:
    return tuple(
        context_candidate_from_entry(
            hit.entry,
            layer=layer,
            selection_source="semantic",
            selection_reason=f"semantic:score-{hit.score:.12f}",
            priority=priority,
        )
        for hit in result.hits
    )


def _content(record: InformationRecord) -> str:
    for key in ("text", "statement", "content"):
        value = record.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return canonical_json(dict(record.payload)).decode("utf-8")


def _unit_count(content: str, unit: str) -> int:
    if unit == "bytes":
        return len(content.encode("utf-8"))
    if unit == "characters":
        return len(content)
    return len(TOKEN_SPAN.findall(content))


def _truncate(content: str, unit: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if unit == "characters":
        return content[:limit]
    if unit == "tokens":
        matches = list(TOKEN_SPAN.finditer(content))
        if len(matches) <= limit:
            return content
        return content[: matches[limit - 1].end()]
    used = 0
    characters: list[str] = []
    for character in content:
        size = len(character.encode("utf-8"))
        if used + size > limit:
            break
        characters.append(character)
        used += size
    return "".join(characters)


def _candidate_sort_key(candidate: ContextCandidate) -> tuple[object, ...]:
    return (
        candidate.priority,
        LAYERS[candidate.layer],
        AUTHORITY_RANK[candidate.record.information_class],
        min(SELECTION_SOURCES[item] for item in candidate.selection_sources),
        -candidate.record.revision,
        candidate.record.subject_ref,
        candidate.record.record_id,
    )


def _evidence(record: InformationRecord) -> tuple[EvidenceRef, ...]:
    all_evidence = list(record.provenance.evidence)
    all_evidence.append(
        EvidenceRef(
            f"record:{record.record_id}",
            str(record.revision),
            record.content_digest,
            "observed-at",
        )
    )
    unique = {
        (item.source_ref, item.revision_id, item.digest, item.relation): item
        for item in all_evidence
    }
    return tuple(
        unique[key]
        for key in sorted(unique)
    )


def _merge_candidates(
    candidates: Iterable[ContextCandidate],
) -> tuple[ContextCandidate, ...]:
    merged: dict[str, ContextCandidate] = {}
    for candidate in candidates:
        try:
            record = parse_information_record(candidate.record.as_payload())
        except (AttributeError, InformationRecordError) as exc:
            raise ContextBuilderError("context candidate record is invalid") from exc
        if (
            not isinstance(candidate.selection_sources, tuple)
            or not candidate.selection_sources
            or len(set(candidate.selection_sources)) != len(candidate.selection_sources)
            or any(item not in SELECTION_SOURCES for item in candidate.selection_sources)
        ):
            raise ContextBuilderError("context candidate selection sources are invalid")
        if (
            not isinstance(candidate.selection_reasons, tuple)
            or not candidate.selection_reasons
            or len(set(candidate.selection_reasons)) != len(candidate.selection_reasons)
        ):
            raise ContextBuilderError("context candidate selection reasons are invalid")
        for reason in candidate.selection_reasons:
            _selection_metadata(
                candidate.layer,
                candidate.selection_sources[0],
                reason,
                candidate.priority,
            )
        if not isinstance(candidate.required, bool) or not isinstance(
            candidate.allow_truncation,
            bool,
        ):
            raise ContextBuilderError("context candidate flags must be boolean")
        if candidate.availability not in AVAILABILITY_RANK:
            raise ContextBuilderError("context candidate availability is invalid")
        current = ContextCandidate(
            record=record,
            availability=candidate.availability,
            layer=candidate.layer,
            selection_sources=tuple(candidate.selection_sources),
            selection_reasons=tuple(candidate.selection_reasons),
            required=candidate.required,
            priority=candidate.priority,
            allow_truncation=candidate.allow_truncation,
        )
        previous = merged.get(record.record_id)
        if previous is None:
            merged[record.record_id] = current
            continue
        if (
            previous.record.revision != record.revision
            or previous.record.content_digest != record.content_digest
            or previous.record.subject_ref != record.subject_ref
            or previous.availability != current.availability
        ):
            raise ContextBuilderError("context candidate versions conflict")
        merged[record.record_id] = ContextCandidate(
            record=record,
            availability=current.availability,
            layer=min((previous.layer, current.layer), key=LAYERS.__getitem__),
            selection_sources=tuple(
                sorted(
                    set(previous.selection_sources) | set(current.selection_sources),
                    key=SELECTION_SOURCES.__getitem__,
                )
            ),
            selection_reasons=tuple(
                sorted(set(previous.selection_reasons) | set(current.selection_reasons))
            ),
            required=previous.required or current.required,
            priority=min(previous.priority, current.priority),
            allow_truncation=(
                previous.allow_truncation and current.allow_truncation
            ),
        )
    return tuple(sorted(merged.values(), key=_candidate_sort_key))


def _candidate_digest(candidates: Iterable[ContextCandidate]) -> str:
    identity = [
        {
            "record_id": item.record.record_id,
            "revision": item.record.revision,
            "content_digest": item.record.content_digest,
            "availability": item.availability,
            "layer": item.layer,
            "selection_sources": list(item.selection_sources),
            "selection_reasons": list(item.selection_reasons),
            "required": item.required,
            "priority": item.priority,
            "allow_truncation": item.allow_truncation,
        }
        for item in candidates
    ]
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def _context_item(
    candidate: ContextCandidate,
    content: str,
    unit: str,
    *,
    original_units: int,
    truncated: bool,
) -> ContextItem:
    included_units = _unit_count(content, unit)
    return ContextItem(
        record=candidate.record,
        layer=candidate.layer,
        selection_sources=candidate.selection_sources,
        selection_reasons=candidate.selection_reasons,
        required=candidate.required,
        content=content,
        original_units=original_units,
        included_units=included_units,
        truncated=truncated,
        truncation_reason="budget" if truncated else None,
        projection_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        evidence=_evidence(candidate.record),
    )


def build_context_package(
    request: ContextBuildRequest,
    candidates: Iterable[ContextCandidate],
) -> ContextPackage:
    """Build context deterministically and fail closed for mandatory content."""

    request = parse_context_build_request(request.as_dict())
    merged = list(_merge_candidates(candidates))
    by_id = {item.record.record_id: item for item in merged}
    missing_required = set(request.required_record_ids) - set(by_id)
    if missing_required:
        raise ContextBuilderError("required context record was not supplied")
    required_ids = set(request.required_record_ids)
    merged = [
        ContextCandidate(
            record=item.record,
            availability=item.availability,
            layer=item.layer,
            selection_sources=item.selection_sources,
            selection_reasons=item.selection_reasons,
            required=item.required or item.record.record_id in required_ids,
            priority=item.priority,
            allow_truncation=item.allow_truncation,
        )
        for item in merged
    ]
    merged.sort(key=lambda item: (not item.required, *_candidate_sort_key(item)))
    candidate_digest = _candidate_digest(merged)

    required = [item for item in merged if item.required]
    if len(required) > request.item_limit:
        raise ContextBuilderError("mandatory context exceeds the item budget")
    for item in required:
        if item.availability != "current" or item.record.lifecycle != "current":
            raise ContextBuilderError("mandatory context is stale or unavailable")
    required_units = sum(
        _unit_count(_content(item.record), request.budget_unit)
        for item in required
    )
    if required_units > request.budget_limit:
        raise ContextBuilderError("mandatory context exceeds the content budget")

    items: list[ContextItem] = []
    exclusions: list[ContextExclusion] = []
    used = 0
    for candidate in merged:
        if candidate.availability != "current" or candidate.record.lifecycle != "current":
            exclusions.append(
                ContextExclusion(
                    candidate.record.record_id,
                    candidate.record.content_digest,
                    "stale-or-unavailable",
                )
            )
            continue
        if len(items) >= request.item_limit:
            exclusions.append(
                ContextExclusion(
                    candidate.record.record_id,
                    candidate.record.content_digest,
                    "item-budget",
                )
            )
            continue
        content = _content(candidate.record)
        original_units = _unit_count(content, request.budget_unit)
        remaining = request.budget_limit - used
        if original_units <= remaining:
            item = _context_item(
                candidate,
                content,
                request.budget_unit,
                original_units=original_units,
                truncated=False,
            )
            items.append(item)
            used += item.included_units
            continue
        if candidate.required:
            raise ContextBuilderError("mandatory context cannot be truncated")
        if (
            request.allow_optional_truncation
            and candidate.allow_truncation
            and remaining >= request.minimum_fragment_units
        ):
            fragment = _truncate(content, request.budget_unit, remaining)
            fragment_units = _unit_count(fragment, request.budget_unit)
            if fragment and fragment_units >= request.minimum_fragment_units:
                item = _context_item(
                    candidate,
                    fragment,
                    request.budget_unit,
                    original_units=original_units,
                    truncated=True,
                )
                items.append(item)
                used += item.included_units
                continue
        exclusions.append(
            ContextExclusion(
                candidate.record.record_id,
                candidate.record.content_digest,
                "content-budget",
            )
        )
    return ContextPackage(
        request=request,
        candidate_digest=candidate_digest,
        items=tuple(items),
        exclusions=tuple(exclusions),
        budget_used=used,
    )
