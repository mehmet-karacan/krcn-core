"""Offline and deterministic exact retrieval over an information catalog."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from .information_records import (
    InformationRecordError,
    canonical_json,
    parse_information_record,
)
from .knowledge_catalog import (
    AVAILABILITY_RANK,
    CatalogEntry,
    InformationCatalog,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
MATCH_RANK = {
    "record-id": 0,
    "subject-ref": 1,
    "path": 2,
    "title": 3,
    "alias": 4,
    "keyword": 5,
    "text": 6,
}
MAX_QUERY_LENGTH = 4096
MAX_RESULT_LIMIT = 100


class ExactRetrievalError(ValueError):
    """Raised when an exact retrieval request violates its contract."""


@dataclass(frozen=True)
class ExactRetrievalQuery:
    query_id: str
    text: str
    fields: tuple[str, ...]
    case_sensitive: bool
    include_unavailable: bool
    limit: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/exact-retrieval-query.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "text": self.text,
            "fields": list(self.fields),
            "case_sensitive": self.case_sensitive,
            "include_unavailable": self.include_unavailable,
            "limit": self.limit,
        }

    @property
    def query_digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class ExactRetrievalHit:
    entry: CatalogEntry
    matched_fields: tuple[str, ...]

    @property
    def best_match(self) -> str:
        return self.matched_fields[0]

    def as_dict(self) -> dict[str, object]:
        return {
            **self.entry.as_dict(),
            "matched_fields": list(self.matched_fields),
            "best_match": self.best_match,
            "evidence_count": len(self.entry.record.provenance.evidence),
        }


@dataclass(frozen=True)
class ExactRetrievalResult:
    query_id: str
    query_digest: str
    catalog_digest: str
    hits: tuple[ExactRetrievalHit, ...]
    truncated: bool

    @property
    def result_digest(self) -> str:
        identity = {
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "hits": [hit.as_dict() for hit in self.hits],
            "truncated": self.truncated,
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/exact-retrieval-result.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "result_digest": self.result_digest,
            "hit_count": len(self.hits),
            "truncated": self.truncated,
            "hits": [hit.as_dict() for hit in self.hits],
        }


def parse_exact_retrieval_query(payload: object) -> ExactRetrievalQuery:
    expected = {
        "schema_ref",
        "schema_version",
        "query_id",
        "text",
        "fields",
        "case_sensitive",
        "include_unavailable",
        "limit",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ExactRetrievalError("exact retrieval query fields are invalid")
    if payload.get("schema_ref") != "schemas/exact-retrieval-query.schema.json":
        raise ExactRetrievalError("exact retrieval query schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ExactRetrievalError("exact retrieval query schema_version must be 1")
    query_id = payload.get("query_id")
    if not isinstance(query_id, str) or not IDENTIFIER.fullmatch(query_id):
        raise ExactRetrievalError("query_id must be a portable identifier")
    text = payload.get("text")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > MAX_QUERY_LENGTH
    ):
        raise ExactRetrievalError("query text is invalid")
    fields_payload = payload.get("fields")
    if (
        not isinstance(fields_payload, list)
        or not fields_payload
        or any(
            not isinstance(field, str) or field not in MATCH_RANK
            for field in fields_payload
        )
        or len(set(fields_payload)) != len(fields_payload)
    ):
        raise ExactRetrievalError("query fields are invalid")
    case_sensitive = payload.get("case_sensitive")
    include_unavailable = payload.get("include_unavailable")
    if not isinstance(case_sensitive, bool):
        raise ExactRetrievalError("case_sensitive must be boolean")
    if not isinstance(include_unavailable, bool):
        raise ExactRetrievalError("include_unavailable must be boolean")
    limit = payload.get("limit")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RESULT_LIMIT
    ):
        raise ExactRetrievalError("query limit is invalid")
    return ExactRetrievalQuery(
        query_id=query_id,
        text=unicodedata.normalize("NFC", text),
        fields=tuple(sorted(fields_payload, key=MATCH_RANK.__getitem__)),
        case_sensitive=case_sensitive,
        include_unavailable=include_unavailable,
        limit=limit,
    )


def _normalized(value: str, *, case_sensitive: bool) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return normalized if case_sensitive else normalized.casefold()


def _field_values(entry: CatalogEntry, field: str) -> tuple[str, ...]:
    record = entry.record
    if field == "record-id":
        return (record.record_id,)
    if field == "subject-ref":
        return (record.subject_ref,)
    if field == "path":
        return (record.subject_ref.split(":", 1)[1],)
    if field == "title":
        return (str(record.payload["title"]),)
    if field == "alias":
        return tuple(str(item) for item in record.payload["aliases"])
    if field == "keyword" and record.information_class == "knowledge":
        return tuple(str(item) for item in record.payload["keywords"])
    if field == "text" and record.information_class == "knowledge":
        return (str(record.payload["text"]),)
    return ()


def _matches(query: str, candidate: str, field: str) -> bool:
    if field == "text":
        return query in candidate
    return query == candidate


def _hit_sort_key(hit: ExactRetrievalHit) -> tuple[object, ...]:
    entry = hit.entry
    return (
        MATCH_RANK[hit.best_match],
        AVAILABILITY_RANK[entry.availability],
        entry.authority_rank,
        -entry.record.revision,
        -len(entry.record.provenance.evidence),
        entry.record.subject_ref,
        entry.record.record_id,
    )


def retrieve_exact(
    catalog: InformationCatalog,
    query: ExactRetrievalQuery,
) -> ExactRetrievalResult:
    """Return exact catalog matches without source reads or provider access."""

    query = parse_exact_retrieval_query(query.as_dict())
    needle = _normalized(query.text, case_sensitive=query.case_sensitive)
    hits: list[ExactRetrievalHit] = []
    for entry in catalog.entries:
        try:
            validated_record = parse_information_record(entry.record.as_payload())
        except InformationRecordError as exc:
            raise ExactRetrievalError("catalog entry record is invalid") from exc
        if entry.availability not in AVAILABILITY_RANK:
            raise ExactRetrievalError("catalog entry availability is invalid")
        entry = CatalogEntry(
            validated_record,
            entry.availability,
            entry.binding_ref,
        )
        if not query.include_unavailable and entry.availability != "current":
            continue
        matched_fields: list[str] = []
        for field in query.fields:
            values = _field_values(entry, field)
            if any(
                _matches(
                    needle,
                    _normalized(value, case_sensitive=query.case_sensitive),
                    field,
                )
                for value in values
            ):
                matched_fields.append(field)
        if matched_fields:
            hits.append(
                ExactRetrievalHit(
                    entry,
                    tuple(sorted(matched_fields, key=MATCH_RANK.__getitem__)),
                )
            )
    ordered = tuple(sorted(hits, key=_hit_sort_key))
    return ExactRetrievalResult(
        query_id=query.query_id,
        query_digest=query.query_digest,
        catalog_digest=catalog.catalog_digest,
        hits=ordered[: query.limit],
        truncated=len(ordered) > query.limit,
    )
