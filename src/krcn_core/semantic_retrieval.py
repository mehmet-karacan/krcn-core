"""Provider-gated semantic retrieval with an offline deterministic fallback."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Mapping

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
from .provider_gate import (
    ProviderApproval,
    ProviderGateError,
    ProviderRequest,
    authorize_provider_request,
    create_provider_request,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TOKEN = re.compile(r"\w+", re.UNICODE)
MAX_QUERY_LENGTH = 4096
MAX_RESULT_LIMIT = 100
DISCLOSED_DATA_CATEGORIES = ("catalog-text", "query-text")
SEMANTIC_OPERATION_SCOPE = "semantic-search"


class SemanticRetrievalError(ValueError):
    """Raised when semantic retrieval violates disclosure or provider rules."""


@dataclass(frozen=True)
class SemanticQuery:
    query_id: str
    text: str
    provider: str
    remote: bool
    session_id: str
    limit: int
    minimum_score: float
    include_unavailable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/semantic-query.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "text": self.text,
            "provider": self.provider,
            "remote": self.remote,
            "session_id": self.session_id,
            "limit": self.limit,
            "minimum_score": self.minimum_score,
            "include_unavailable": self.include_unavailable,
        }

    @property
    def query_digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class SemanticDocument:
    record_id: str
    title: str
    text: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]
    content_digest: str

    def provider_payload(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "title": self.title,
            "text": self.text,
            "aliases": list(self.aliases),
            "keywords": list(self.keywords),
            "content_digest": self.content_digest,
        }


RemoteSemanticScorer = Callable[
    [str, tuple[SemanticDocument, ...]],
    Mapping[str, float],
]


@dataclass(frozen=True)
class SemanticHit:
    entry: CatalogEntry
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            **self.entry.as_dict(),
            "score": self.score,
            "evidence_count": len(self.entry.record.provenance.evidence),
        }


@dataclass(frozen=True)
class SemanticResult:
    query_id: str
    query_digest: str
    catalog_digest: str
    candidate_digest: str
    provider_request_id: str
    provider: str
    remote: bool
    mode: str
    approval_verified: bool
    hits: tuple[SemanticHit, ...]
    truncated: bool

    @property
    def result_digest(self) -> str:
        identity = {
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "candidate_digest": self.candidate_digest,
            "provider_request_id": self.provider_request_id,
            "provider": self.provider,
            "remote": self.remote,
            "mode": self.mode,
            "approval_verified": self.approval_verified,
            "hits": [hit.as_dict() for hit in self.hits],
            "truncated": self.truncated,
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/semantic-result.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "candidate_digest": self.candidate_digest,
            "provider_request_id": self.provider_request_id,
            "provider": self.provider,
            "remote": self.remote,
            "mode": self.mode,
            "approval_verified": self.approval_verified,
            "result_digest": self.result_digest,
            "hit_count": len(self.hits),
            "truncated": self.truncated,
            "hits": [hit.as_dict() for hit in self.hits],
        }


def parse_semantic_query(payload: object) -> SemanticQuery:
    expected = {
        "schema_ref",
        "schema_version",
        "query_id",
        "text",
        "provider",
        "remote",
        "session_id",
        "limit",
        "minimum_score",
        "include_unavailable",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise SemanticRetrievalError("semantic query fields are invalid")
    if payload.get("schema_ref") != "schemas/semantic-query.schema.json":
        raise SemanticRetrievalError("semantic query schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise SemanticRetrievalError("semantic query schema_version must be 1")
    query_id = payload.get("query_id")
    provider = payload.get("provider")
    if not isinstance(query_id, str) or not IDENTIFIER.fullmatch(query_id):
        raise SemanticRetrievalError("semantic query_id is invalid")
    if not isinstance(provider, str) or not IDENTIFIER.fullmatch(provider):
        raise SemanticRetrievalError("semantic provider is invalid")
    text = payload.get("text")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > MAX_QUERY_LENGTH
    ):
        raise SemanticRetrievalError("semantic query text is invalid")
    remote = payload.get("remote")
    include_unavailable = payload.get("include_unavailable")
    if not isinstance(remote, bool):
        raise SemanticRetrievalError("semantic remote flag must be boolean")
    if not isinstance(include_unavailable, bool):
        raise SemanticRetrievalError("include_unavailable must be boolean")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise SemanticRetrievalError("semantic session_id is invalid")
    limit = payload.get("limit")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RESULT_LIMIT
    ):
        raise SemanticRetrievalError("semantic result limit is invalid")
    minimum_score = payload.get("minimum_score")
    if (
        not isinstance(minimum_score, (int, float))
        or isinstance(minimum_score, bool)
        or not math.isfinite(float(minimum_score))
        or not 0 <= float(minimum_score) <= 1
    ):
        raise SemanticRetrievalError("semantic minimum_score is invalid")
    return SemanticQuery(
        query_id=query_id,
        text=unicodedata.normalize("NFC", text),
        provider=provider,
        remote=remote,
        session_id=session_id,
        limit=limit,
        minimum_score=float(minimum_score),
        include_unavailable=include_unavailable,
    )


def create_semantic_provider_request(
    query: SemanticQuery,
    *,
    endpoint: str,
    retention_assumptions: str,
) -> ProviderRequest:
    query = parse_semantic_query(query.as_dict())
    try:
        return create_provider_request(
            provider=query.provider,
            endpoint=endpoint,
            data_categories=DISCLOSED_DATA_CATEGORIES,
            operation_scope=SEMANTIC_OPERATION_SCOPE,
            retention_assumptions=retention_assumptions,
            session_id=query.session_id,
            remote=query.remote,
        )
    except ProviderGateError as exc:
        raise SemanticRetrievalError(str(exc)) from exc


def _validate_provider_request(
    query: SemanticQuery,
    request: ProviderRequest,
) -> ProviderRequest:
    try:
        rebuilt = create_provider_request(
            provider=request.provider,
            endpoint=request.endpoint,
            data_categories=request.data_categories,
            operation_scope=request.operation_scope,
            retention_assumptions=request.retention_assumptions,
            session_id=request.session_id,
            remote=request.remote,
        )
    except (AttributeError, ProviderGateError) as exc:
        raise SemanticRetrievalError("semantic provider request is invalid") from exc
    if rebuilt != request:
        raise SemanticRetrievalError("semantic provider request identity is invalid")
    if (
        request.provider != query.provider
        or request.remote != query.remote
        or request.session_id != query.session_id
        or request.data_categories != DISCLOSED_DATA_CATEGORIES
        or request.operation_scope != SEMANTIC_OPERATION_SCOPE
    ):
        raise SemanticRetrievalError(
            "semantic provider request does not match the query disclosure"
        )
    return request


def _semantic_documents(
    catalog: InformationCatalog,
    *,
    include_unavailable: bool,
) -> tuple[tuple[CatalogEntry, SemanticDocument], ...]:
    documents: list[tuple[CatalogEntry, SemanticDocument]] = []
    seen: set[str] = set()
    for catalog_entry in catalog.entries:
        try:
            record = parse_information_record(catalog_entry.record.as_payload())
        except InformationRecordError as exc:
            raise SemanticRetrievalError("catalog entry record is invalid") from exc
        if record.record_id in seen:
            raise SemanticRetrievalError("catalog record ids must be unique")
        seen.add(record.record_id)
        if catalog_entry.availability not in AVAILABILITY_RANK:
            raise SemanticRetrievalError("catalog entry availability is invalid")
        if not include_unavailable and catalog_entry.availability != "current":
            continue
        entry = CatalogEntry(
            record,
            catalog_entry.availability,
            catalog_entry.binding_ref,
        )
        title = str(record.payload["title"])
        aliases = tuple(str(item) for item in record.payload["aliases"])
        if record.information_class == "knowledge":
            text = str(record.payload["text"])
            keywords = tuple(str(item) for item in record.payload["keywords"])
        else:
            text = ""
            keywords = ()
        documents.append(
            (
                entry,
                SemanticDocument(
                    record_id=record.record_id,
                    title=title,
                    text=text,
                    aliases=aliases,
                    keywords=keywords,
                    content_digest=record.content_digest,
                ),
            )
        )
    return tuple(documents)


def _tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return frozenset(TOKEN.findall(normalized))


def _local_score(query_text: str, document: SemanticDocument) -> float:
    query_tokens = _tokens(query_text)
    document_tokens = _tokens(
        " ".join(
            (
                document.title,
                document.text,
                *document.aliases,
                *document.keywords,
            )
        )
    )
    if not query_tokens or not document_tokens:
        return 0.0
    return len(query_tokens & document_tokens) / len(query_tokens | document_tokens)


def _validated_scores(
    documents: tuple[tuple[CatalogEntry, SemanticDocument], ...],
    scores: Mapping[str, float],
) -> dict[str, float]:
    if not isinstance(scores, Mapping):
        raise SemanticRetrievalError("semantic provider scores must be a mapping")
    candidate_ids = {document.record_id for _, document in documents}
    if any(not isinstance(key, str) or key not in candidate_ids for key in scores):
        raise SemanticRetrievalError("semantic provider returned an unknown record")
    validated: dict[str, float] = {}
    for record_id, score in scores.items():
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 1
        ):
            raise SemanticRetrievalError("semantic provider score is invalid")
        validated[record_id] = float(f"{float(score):.12f}")
    return validated


def _hit_sort_key(hit: SemanticHit) -> tuple[object, ...]:
    entry = hit.entry
    return (
        -hit.score,
        AVAILABILITY_RANK[entry.availability],
        entry.authority_rank,
        -entry.record.revision,
        -len(entry.record.provenance.evidence),
        entry.record.subject_ref,
        entry.record.record_id,
    )


def retrieve_semantic(
    catalog: InformationCatalog,
    query: SemanticQuery,
    policy: dict,
    provider_request: ProviderRequest,
    *,
    approval: ProviderApproval | None = None,
    remote_scorer: RemoteSemanticScorer | None = None,
) -> SemanticResult:
    """Retrieve through the existing provider gate without implicit networking."""

    query = parse_semantic_query(query.as_dict())
    provider_request = _validate_provider_request(query, provider_request)
    try:
        authorization = authorize_provider_request(
            policy,
            provider_request,
            approval=approval,
        )
    except ProviderGateError as exc:
        raise SemanticRetrievalError(str(exc)) from exc
    documents = _semantic_documents(
        catalog,
        include_unavailable=query.include_unavailable,
    )
    if query.remote:
        if remote_scorer is None:
            raise SemanticRetrievalError(
                "remote semantic scorer must be supplied after authorization"
            )
        raw_scores = remote_scorer(
            query.text,
            tuple(document for _, document in documents),
        )
        mode = "remote-provider"
    else:
        raw_scores = {
            document.record_id: _local_score(query.text, document)
            for _, document in documents
        }
        mode = "offline-deterministic-fallback"
    scores = _validated_scores(documents, raw_scores)
    hits = tuple(
        sorted(
            (
                SemanticHit(entry, scores.get(document.record_id, 0.0))
                for entry, document in documents
                if scores.get(document.record_id, 0.0) >= query.minimum_score
                and scores.get(document.record_id, 0.0) > 0
            ),
            key=_hit_sort_key,
        )
    )
    candidate_identity = [
        {
            "record_id": document.record_id,
            "content_digest": document.content_digest,
            "availability": entry.availability,
        }
        for entry, document in documents
    ]
    candidate_digest = hashlib.sha256(canonical_json(candidate_identity)).hexdigest()
    return SemanticResult(
        query_id=query.query_id,
        query_digest=query.query_digest,
        catalog_digest=catalog.catalog_digest,
        candidate_digest=candidate_digest,
        provider_request_id=provider_request.request_id,
        provider=provider_request.provider,
        remote=provider_request.remote,
        mode=mode,
        approval_verified=authorization.approval_verified,
        hits=hits[: query.limit],
        truncated=len(hits) > query.limit,
    )
