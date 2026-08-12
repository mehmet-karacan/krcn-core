"""Deterministic authoritative-source and curated-knowledge catalog."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .information_records import (
    InformationRecord,
    InformationRecordError,
    canonical_json,
    parse_information_record,
    record_is_stale,
)
from .source_bindings import SourceBinding, SourceBindingError, parse_source_binding


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
REVISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
AUTHORITY_RANK = {"authoritative-source": 0, "knowledge": 1}
AVAILABILITY_RANK = {
    "current": 0,
    "binding-missing": 1,
    "binding-stale": 2,
    "binding-conflict": 3,
    "stale": 4,
    "superseded": 5,
    "archived": 6,
}


class KnowledgeCatalogError(ValueError):
    """Raised when catalog inputs are ambiguous or structurally unsafe."""


@dataclass(frozen=True)
class AuthoritativeSourceMetadata:
    title: str
    source_id: str
    binding_id: str
    binding_revision: int
    source_revision_id: str
    source_digest: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeMetadata:
    title: str
    text: str
    keywords: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class CatalogEntry:
    record: InformationRecord
    availability: str
    binding_ref: str | None

    @property
    def authority_rank(self) -> int:
        return AUTHORITY_RANK[self.record.information_class]

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record.record_id,
            "information_class": self.record.information_class,
            "ownership": self.record.ownership,
            "subject_ref": self.record.subject_ref,
            "revision": self.record.revision,
            "content_digest": self.record.content_digest,
            "lifecycle": self.record.lifecycle,
            "availability": self.availability,
            "authority_rank": self.authority_rank,
            "binding_ref": self.binding_ref,
            "evidence": [
                evidence.as_dict() for evidence in self.record.provenance.evidence
            ],
        }


@dataclass(frozen=True)
class InformationCatalog:
    entries: tuple[CatalogEntry, ...]

    @property
    def catalog_digest(self) -> str:
        summaries = [entry.as_dict() for entry in self.entries]
        return hashlib.sha256(canonical_json(summaries)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/information-catalog.schema.json",
            "schema_version": 1,
            "catalog_digest": self.catalog_digest,
            "entry_count": len(self.entries),
            "entries": [entry.as_dict() for entry in self.entries],
        }

    def get(self, record_id: str) -> CatalogEntry | None:
        return next(
            (entry for entry in self.entries if entry.record.record_id == record_id),
            None,
        )

    def current_source_revisions(self) -> dict[str, tuple[str, str]]:
        """Return authoritative revision evidence accepted as current."""

        return {
            entry.record.subject_ref: (
                str(entry.record.payload["source_revision_id"]),
                str(entry.record.payload["source_digest"]),
            )
            for entry in self.entries
            if entry.record.information_class == "authoritative-source"
            and entry.availability == "current"
        }


def _non_empty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeCatalogError(f"{label} must be non-empty text")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise KnowledgeCatalogError(f"{label} must be a portable identifier")
    return value


def _unique_text_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise KnowledgeCatalogError(f"{label} must be a list")
    items = tuple(_non_empty_text(item, label) for item in value)
    if len(set(items)) != len(items):
        raise KnowledgeCatalogError(f"{label} must be unique")
    return tuple(sorted(items, key=lambda item: (item.casefold(), item)))


def _authoritative_metadata(record: InformationRecord) -> AuthoritativeSourceMetadata:
    expected = {
        "title",
        "source_id",
        "binding_id",
        "binding_revision",
        "source_revision_id",
        "source_digest",
        "aliases",
    }
    if set(record.payload) != expected:
        raise KnowledgeCatalogError("authoritative source payload fields are invalid")
    source_id = _identifier(record.payload.get("source_id"), "source_id")
    binding_id = _identifier(record.payload.get("binding_id"), "binding_id")
    binding_revision = record.payload.get("binding_revision")
    if (
        not isinstance(binding_revision, int)
        or isinstance(binding_revision, bool)
        or binding_revision < 1
    ):
        raise KnowledgeCatalogError("binding_revision must be positive")
    source_revision_id = record.payload.get("source_revision_id")
    if (
        not isinstance(source_revision_id, str)
        or not REVISION_ID.fullmatch(source_revision_id)
    ):
        raise KnowledgeCatalogError("source_revision_id is invalid")
    source_digest = record.payload.get("source_digest")
    if not isinstance(source_digest, str) or not SHA256.fullmatch(source_digest):
        raise KnowledgeCatalogError("source_digest is invalid")
    if record.subject_ref != f"source:{source_id}":
        raise KnowledgeCatalogError("source identity does not match subject_ref")
    exact_evidence = (
        record.subject_ref,
        source_revision_id,
        source_digest,
    )
    if not any(
        (item.source_ref, item.revision_id, item.digest) == exact_evidence
        and item.relation in {"supports", "observed-at"}
        for item in record.provenance.evidence
    ):
        raise KnowledgeCatalogError(
            "authoritative source requires evidence for its exact source revision"
        )
    return AuthoritativeSourceMetadata(
        title=_non_empty_text(record.payload.get("title"), "title"),
        source_id=source_id,
        binding_id=binding_id,
        binding_revision=binding_revision,
        source_revision_id=source_revision_id,
        source_digest=source_digest,
        aliases=_unique_text_list(record.payload.get("aliases"), "aliases"),
    )


def _knowledge_metadata(record: InformationRecord) -> KnowledgeMetadata:
    expected = {"title", "text", "keywords", "aliases"}
    if set(record.payload) != expected:
        raise KnowledgeCatalogError("knowledge payload fields are invalid")
    return KnowledgeMetadata(
        title=_non_empty_text(record.payload.get("title"), "title"),
        text=_non_empty_text(record.payload.get("text"), "text"),
        keywords=_unique_text_list(record.payload.get("keywords"), "keywords"),
        aliases=_unique_text_list(record.payload.get("aliases"), "aliases"),
    )


def _source_availability(
    record: InformationRecord,
    metadata: AuthoritativeSourceMetadata,
    bindings: Mapping[str, SourceBinding],
) -> str:
    if record.lifecycle in {"superseded", "archived"}:
        return record.lifecycle
    binding = bindings.get(metadata.binding_id)
    if binding is None:
        return "binding-missing"
    if binding.source_id != metadata.source_id or "read" not in binding.capabilities:
        return "binding-conflict"
    if binding.revision != metadata.binding_revision:
        return "binding-stale"
    return "current"


def _entry_sort_key(entry: CatalogEntry) -> tuple[object, ...]:
    return (
        entry.authority_rank,
        AVAILABILITY_RANK[entry.availability],
        entry.record.subject_ref,
        -entry.record.revision,
        entry.record.record_id,
    )


def build_information_catalog(
    source_bindings: Iterable[SourceBinding],
    records: Iterable[InformationRecord],
) -> InformationCatalog:
    """Build a portable catalog without reading source content or locators."""

    bindings: dict[str, SourceBinding] = {}
    for candidate in source_bindings:
        try:
            binding = parse_source_binding(
                {
                    "schema_version": candidate.schema_version,
                    "binding_id": candidate.binding_id,
                    "source_id": candidate.source_id,
                    "source_kind": candidate.source_kind,
                    "locator": {
                        "kind": candidate.locator.kind,
                        "value": candidate.locator.value,
                    },
                    "default_access": candidate.default_access,
                    "capabilities": list(candidate.capabilities),
                    "policy_refs": list(candidate.policy_refs),
                    "revision": candidate.revision,
                }
            )
        except (AttributeError, SourceBindingError) as exc:
            raise KnowledgeCatalogError("source binding is invalid") from exc
        if binding.binding_id in bindings:
            raise KnowledgeCatalogError("source binding ids must be unique")
        bindings[binding.binding_id] = binding

    seen_record_ids: set[str] = set()
    authoritative: list[
        tuple[InformationRecord, AuthoritativeSourceMetadata, str]
    ] = []
    knowledge: list[InformationRecord] = []
    current_subjects: set[str] = set()
    for candidate in records:
        try:
            record = parse_information_record(candidate.as_payload())
        except (AttributeError, InformationRecordError) as exc:
            raise KnowledgeCatalogError("information record is invalid") from exc
        if record.record_id in seen_record_ids:
            raise KnowledgeCatalogError("information record ids must be unique")
        seen_record_ids.add(record.record_id)
        if record.information_class == "authoritative-source":
            metadata = _authoritative_metadata(record)
            availability = _source_availability(record, metadata, bindings)
            if record.lifecycle == "current":
                if record.subject_ref in current_subjects:
                    raise KnowledgeCatalogError(
                        "only one current authoritative source may exist per subject"
                    )
                current_subjects.add(record.subject_ref)
            authoritative.append((record, metadata, availability))
        elif record.information_class == "knowledge":
            _knowledge_metadata(record)
            knowledge.append(record)
        else:
            raise KnowledgeCatalogError(
                "catalog accepts only authoritative-source and knowledge records"
            )

    entries: list[CatalogEntry] = []
    current_revisions: dict[str, tuple[str, str]] = {}
    for record, metadata, availability in authoritative:
        entries.append(
            CatalogEntry(record, availability, f"binding:{metadata.binding_id}")
        )
        if availability == "current":
            current_revisions[record.subject_ref] = (
                metadata.source_revision_id,
                metadata.source_digest,
            )

    for record in knowledge:
        if record.lifecycle in {"superseded", "archived"}:
            availability = record.lifecycle
        elif record.lifecycle == "stale" or record_is_stale(
            record,
            current_revisions,
        ):
            availability = "stale"
        else:
            availability = "current"
        entries.append(CatalogEntry(record, availability, None))

    return InformationCatalog(tuple(sorted(entries, key=_entry_sort_key)))
