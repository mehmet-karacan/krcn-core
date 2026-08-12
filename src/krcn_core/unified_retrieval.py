"""Deterministic, evidence-first retrieval across KRCN project domains.

The module composes results that were already produced by trusted domain
services.  It never reads a remote endpoint, builds an index, or treats a
semantic score as authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .exact_retrieval import ExactRetrievalResult
from .hybrid_retrieval import HybridResult
from .information_records import canonical_json
from .provider_gate import ProviderAuthorization
from .semantic_retrieval import SemanticResult


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
TOKEN_SPAN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
DOMAINS = {"work", "code", "oracle", "knowledge"}
INTENTS = {"status", "code", "oracle", "knowledge", "broad"}
SCOPES = {"project", "multi-project"}
RETRIEVAL_MODES = {"exact", "graph", "dependency", "fts", "hybrid", "semantic"}
CURRENT_STATUSES = {"authoritative", "current"}
EVIDENCE_TIER = {
    "exact": 0,
    "graph": 1,
    "dependency": 2,
    "fts": 3,
    "hybrid": 3,
    "semantic": 4,
}
INTENT_DOMAINS = {
    "status": ("work", "knowledge"),
    "code": ("code", "work", "knowledge"),
    "oracle": ("oracle", "work", "knowledge"),
    "knowledge": ("knowledge", "work"),
    "broad": ("work", "code", "oracle", "knowledge"),
}
MAX_RESULTS = 500
MAX_TOKEN_BUDGET = 1_000_000


class UnifiedRetrievalError(ValueError):
    """Raised when unified retrieval would weaken scope or evidence rules."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return folded.translate(str.maketrans({"ı": "i"}))


def _token_count(value: str) -> int:
    return max(1, len(TOKEN_SPAN.findall(value)))


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise UnifiedRetrievalError(f"{label} must be a portable identifier")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise UnifiedRetrievalError(f"{label} must be a SHA-256 digest")
    return value


def classify_intent(text: str) -> str:
    """Classify a query without a provider or learned model."""

    if not isinstance(text, str) or not text.strip():
        raise UnifiedRetrievalError("query text is required")
    query = _fold(text)
    groups = {
        "status": (
            "nerede kaldik", "durum", "aktif gorev", "tamamlanan gorev",
            "status", "resume", "where did we stop", "task history",
        ),
        "code": (
            "kaynak kod", "source code", "kodda", "fonksiyon", "class ",
            "method", "implementation", "implementasyon",
        ),
        "oracle": (
            "oracle", "plsql", "paket", "package", "tablo", "table",
            "kolon", "column", "index", "ddl", "schema", "trigger",
            "procedure", "dependency",
        ),
        "knowledge": (
            "dokuman", "document", "karar", "decision",
            "knowledge", "acikla", "explain", "policy",
        ),
    }
    matches = [intent for intent, terms in groups.items() if any(term in query for term in terms)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "broad"
    return "knowledge"


@dataclass(frozen=True)
class UnifiedRetrievalRequest:
    query_id: str
    text: str
    intent: str
    scope: str
    project_ids: tuple[str, ...]
    result_limit: int
    token_budget: int

    def as_dict(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "text": self.text,
            "intent": self.intent,
            "scope": self.scope,
            "project_ids": list(self.project_ids),
            "result_limit": self.result_limit,
            "token_budget": self.token_budget,
        }

    @property
    def query_digest(self) -> str:
        return _digest(self.as_dict())


def create_unified_request(
    *,
    query_id: str,
    text: str,
    current_project_id: str,
    project_ids: Sequence[str] | None = None,
    scope: str = "project",
    intent: str = "auto",
    result_limit: int = 20,
    token_budget: int = 4000,
) -> UnifiedRetrievalRequest:
    """Create a project-scoped request; multi-project scope must be explicit."""

    query = _identifier(query_id, "query id")
    current = _identifier(current_project_id, "current project id")
    if not isinstance(text, str) or not text.strip() or len(text) > 16_384:
        raise UnifiedRetrievalError("query text is invalid")
    if scope not in SCOPES:
        raise UnifiedRetrievalError("retrieval scope is invalid")
    selected = tuple(project_ids) if project_ids is not None else (current,)
    if not selected or len(set(selected)) != len(selected):
        raise UnifiedRetrievalError("project scope must contain unique projects")
    selected = tuple(_identifier(item, "project id") for item in selected)
    if scope == "project" and len(selected) != 1:
        raise UnifiedRetrievalError("multiple projects require explicit multi-project scope")
    if scope == "multi-project" and len(selected) < 2:
        raise UnifiedRetrievalError("multi-project scope requires at least two projects")
    resolved_intent = classify_intent(text) if intent == "auto" else intent
    if resolved_intent not in INTENTS:
        raise UnifiedRetrievalError("retrieval intent is invalid")
    if (
        not isinstance(result_limit, int)
        or isinstance(result_limit, bool)
        or not 1 <= result_limit <= MAX_RESULTS
    ):
        raise UnifiedRetrievalError("result limit is invalid")
    if (
        not isinstance(token_budget, int)
        or isinstance(token_budget, bool)
        or not 1 <= token_budget <= MAX_TOKEN_BUDGET
    ):
        raise UnifiedRetrievalError("token budget is invalid")
    return UnifiedRetrievalRequest(
        query,
        unicodedata.normalize("NFC", text),
        resolved_intent,
        scope,
        selected,
        result_limit,
        token_budget,
    )


@dataclass(frozen=True)
class UnifiedCandidate:
    project_id: str
    domain: str
    hit_id: str
    logical_ref: str
    title: str
    content: str
    authority: str
    authority_rank: int
    revision: str
    digest: str
    evidence_refs: tuple[str, ...]
    retrieval_mode: str
    score: float
    score_breakdown: Mapping[str, float]


@dataclass(frozen=True)
class RetrievalBatch:
    project_id: str
    domain: str
    freshness: str
    candidates: tuple[UnifiedCandidate, ...]
    source_revision_digest: str | None = None
    indexed_revision_digest: str | None = None
    index_digest: str | None = None
    provider_request_id: str | None = None
    provider_remote: bool = False


@dataclass(frozen=True)
class UnifiedContextCandidate:
    candidate_id: str
    project_id: str
    domain: str
    source_ref: str
    revision: str
    digest: str
    authority: str
    evidence_refs: tuple[str, ...]
    content: str
    token_count: int
    priority: int
    selection_reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "project_id": self.project_id,
            "domain": self.domain,
            "source_ref": self.source_ref,
            "revision": self.revision,
            "digest": self.digest,
            "authority": self.authority,
            "evidence_refs": list(self.evidence_refs),
            "content": self.content,
            "token_count": self.token_count,
            "priority": self.priority,
            "selection_reason": self.selection_reason,
        }


@dataclass(frozen=True)
class UnifiedHit:
    candidate: UnifiedCandidate
    unified_score: float
    unified_score_breakdown: Mapping[str, float]
    evidence_tier: int
    token_count: int
    index_digest: str | None

    def as_dict(self) -> dict[str, object]:
        item = self.candidate
        return {
            "project_id": item.project_id,
            "domain": item.domain,
            "hit_id": item.hit_id,
            "logical_ref": item.logical_ref,
            "title": item.title,
            "content": item.content,
            "authority": item.authority,
            "authority_rank": item.authority_rank,
            "revision": item.revision,
            "digest": item.digest,
            "evidence_refs": list(item.evidence_refs),
            "retrieval_mode": item.retrieval_mode,
            "source_score": item.score,
            "source_score_breakdown": dict(item.score_breakdown),
            "unified_score": self.unified_score,
            "unified_score_breakdown": dict(self.unified_score_breakdown),
            "evidence_tier": self.evidence_tier,
            "token_count": self.token_count,
            "index_digest": self.index_digest,
        }

    def context_candidate(self, priority: int) -> UnifiedContextCandidate:
        item = self.candidate
        return UnifiedContextCandidate(
            candidate_id=_digest(
                [item.project_id, item.domain, item.logical_ref, item.revision, item.digest]
            ),
            project_id=item.project_id,
            domain=item.domain,
            source_ref=item.logical_ref,
            revision=item.revision,
            digest=item.digest,
            authority=item.authority,
            evidence_refs=item.evidence_refs,
            content=item.content,
            token_count=self.token_count,
            priority=priority,
            selection_reason=(
                f"{item.retrieval_mode}:tier-{self.evidence_tier}:"
                f"score-{self.unified_score:.12f}"
            ),
        )


@dataclass(frozen=True)
class UnifiedRetrievalResult:
    request: UnifiedRetrievalRequest
    hits: tuple[UnifiedHit, ...]
    context_candidates: tuple[UnifiedContextCandidate, ...]
    candidate_count: int
    excluded_by_budget: int
    token_budget_used: int
    source_batch_digest: str

    @property
    def result_digest(self) -> str:
        return _digest(
            {
                "query_digest": self.request.query_digest,
                "source_batch_digest": self.source_batch_digest,
                "hits": [item.as_dict() for item in self.hits],
                "context_candidates": [item.as_dict() for item in self.context_candidates],
                "candidate_count": self.candidate_count,
                "excluded_by_budget": self.excluded_by_budget,
                "token_budget_used": self.token_budget_used,
            }
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/unified-retrieval-result.schema.json",
            "schema_version": 1,
            "query_id": self.request.query_id,
            "query_digest": self.request.query_digest,
            "intent": self.request.intent,
            "scope": self.request.scope,
            "project_ids": list(self.request.project_ids),
            "candidate_count": self.candidate_count,
            "hit_count": len(self.hits),
            "excluded_by_budget": self.excluded_by_budget,
            "budget": {
                "unit": "tokens",
                "limit": self.request.token_budget,
                "used": self.token_budget_used,
                "remaining": self.request.token_budget - self.token_budget_used,
                "result_limit": self.request.result_limit,
            },
            "source_batch_digest": self.source_batch_digest,
            "result_digest": self.result_digest,
            "hits": [item.as_dict() for item in self.hits],
            "context_candidates": [item.as_dict() for item in self.context_candidates],
            "remote_call_performed": False,
            "semantic_can_override_exact": False,
            "paths_disclosed": False,
        }


def _candidate_content(record: object) -> str:
    payload = getattr(record, "payload", {})
    if isinstance(payload, Mapping):
        for field in ("text", "description", "title"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ""


def _record_evidence(record: object) -> tuple[str, ...]:
    provenance = getattr(record, "provenance", None)
    evidence = getattr(provenance, "evidence", ())
    return tuple(
        sorted(
            f"{item.source_ref}@{item.revision_id}:{item.digest}:{item.relation}"
            for item in evidence
        )
    )


def batch_from_exact(result: ExactRetrievalResult, project_id: str) -> RetrievalBatch:
    """Adapt an exact information-catalog result."""

    project = _identifier(project_id, "project id")
    candidates = []
    for hit in result.hits:
        record = hit.entry.record
        candidates.append(
            UnifiedCandidate(
                project,
                "knowledge",
                record.record_id,
                record.subject_ref,
                str(record.payload.get("title", record.record_id)),
                _candidate_content(record),
                record.information_class,
                hit.entry.authority_rank,
                str(record.revision),
                record.content_digest,
                _record_evidence(record),
                "exact",
                1.0,
                {"exact": 1.0},
            )
        )
    return RetrievalBatch(project, "knowledge", "authoritative", tuple(candidates))


def batch_from_hybrid(result: HybridResult, project_id: str) -> RetrievalBatch:
    """Adapt a freshness-verified hybrid information result."""

    project = _identifier(project_id, "project id")
    candidates = []
    for hit in result.hits:
        record = hit.entry.record
        mode = "exact" if hit.score_breakdown.get("exact", 0.0) >= 1.0 else "hybrid"
        candidates.append(
            UnifiedCandidate(
                project,
                "knowledge",
                record.record_id,
                record.subject_ref,
                str(record.payload.get("title", record.record_id)),
                _candidate_content(record),
                record.information_class,
                hit.entry.authority_rank,
                str(record.revision),
                record.content_digest,
                _record_evidence(record),
                mode,
                hit.score,
                dict(hit.score_breakdown),
            )
        )
    return RetrievalBatch(
        project,
        "knowledge",
        "current",
        tuple(candidates),
        result.catalog_digest,
        result.catalog_digest,
        result.index_digest,
    )


def batch_from_semantic(
    result: SemanticResult,
    project_id: str,
    *,
    current_catalog_digest: str,
) -> RetrievalBatch:
    """Adapt an already authorized semantic result without invoking its provider."""

    project = _identifier(project_id, "project id")
    current = _sha256(current_catalog_digest, "current catalog digest")
    candidates = []
    for hit in result.hits:
        record = hit.entry.record
        candidates.append(
            UnifiedCandidate(
                project,
                "knowledge",
                record.record_id,
                record.subject_ref,
                str(record.payload.get("title", record.record_id)),
                _candidate_content(record),
                record.information_class,
                hit.entry.authority_rank,
                str(record.revision),
                record.content_digest,
                _record_evidence(record),
                "semantic",
                hit.score,
                {"semantic": hit.score},
            )
        )
    return RetrievalBatch(
        project,
        "knowledge",
        "current",
        tuple(candidates),
        current,
        result.catalog_digest,
        None,
        result.provider_request_id,
        result.remote,
    )


def batch_from_source_code(result: Mapping[str, object]) -> RetrievalBatch:
    """Adapt a source-code search result returned by its verified index service."""

    project = _identifier(result.get("project_id"), "source code project id")
    source_digest = _sha256(result.get("source_digest"), "source code source digest")
    index_digest = _sha256(result.get("index_digest"), "source code index digest")
    hits = result.get("hits")
    if not isinstance(hits, list):
        raise UnifiedRetrievalError("source code hits are invalid")
    candidates = []
    for item in hits:
        if not isinstance(item, Mapping):
            raise UnifiedRetrievalError("source code hit is invalid")
        chunk_id = str(item.get("chunk_id", ""))
        relative_path = str(item.get("relative_path", ""))
        start_line = int(item.get("start_line", 0))
        end_line = int(item.get("end_line", 0))
        digest = _sha256(item.get("content_sha256"), "source code chunk digest")
        breakdown = item.get("score_breakdown")
        if not isinstance(breakdown, Mapping):
            raise UnifiedRetrievalError("source code score breakdown is invalid")
        numeric_breakdown = {str(key): float(value) for key, value in breakdown.items()}
        mode = "exact" if numeric_breakdown.get("exact", 0.0) > 0 else "hybrid"
        symbols = item.get("symbols", [])
        title = relative_path
        if isinstance(symbols, list) and symbols:
            title = f"{relative_path}: {', '.join(str(value) for value in symbols)}"
        logical_ref = f"source-code:{project}/{relative_path}#L{start_line}-L{end_line}"
        candidates.append(
            UnifiedCandidate(
                project,
                "code",
                chunk_id,
                logical_ref,
                title,
                str(item.get("content") or title),
                "verified-source",
                1,
                source_digest,
                digest,
                (f"project:{project}/{relative_path}@{source_digest}:{digest}",),
                mode,
                float(item.get("score", 0.0)),
                numeric_breakdown,
            )
        )
    return RetrievalBatch(
        project,
        "code",
        "current",
        tuple(candidates),
        source_digest,
        source_digest,
        index_digest,
    )


def batch_from_work_graph(result: Mapping[str, object]) -> RetrievalBatch:
    """Adapt authoritative Work Graph items."""

    project = _identifier(result.get("project_id"), "work graph project id")
    if result.get("authoritative_status") is not True:
        raise UnifiedRetrievalError("work graph result is not authoritative")
    items = result.get("items")
    if not isinstance(items, list):
        raise UnifiedRetrievalError("work graph items are invalid")
    candidates = []
    for item in items:
        if not isinstance(item, Mapping):
            raise UnifiedRetrievalError("work graph item is invalid")
        work_id = _identifier(item.get("work_item_id"), "work item id")
        digest = _sha256(item.get("work_digest"), "work item digest")
        revision = str(item.get("revision", ""))
        evidence = item.get("evidence", [])
        evidence_refs = [f"work-item:{project}/{work_id}@r{revision}:{digest}"]
        if isinstance(evidence, list):
            for entry in evidence:
                if isinstance(entry, Mapping) and str(entry.get("reference", "")).strip():
                    evidence_refs.append(str(entry["reference"]))
        candidates.append(
            UnifiedCandidate(
                project,
                "work",
                work_id,
                f"work-item:{project}/{work_id}",
                str(item.get("title", work_id)),
                str(item.get("description") or item.get("title") or work_id),
                "authoritative-work",
                0,
                revision,
                digest,
                tuple(sorted(set(evidence_refs))),
                "exact",
                1.0,
                {"authoritative": 1.0, "exact": 1.0},
            )
        )
    return RetrievalBatch(project, "work", "authoritative", tuple(candidates))


def batch_from_oracle(
    result: Mapping[str, object],
    *,
    current_catalog_digest: str,
    indexed_catalog_digest: str,
) -> RetrievalBatch:
    """Adapt Oracle metadata search while binding it to the current catalog."""

    project = _identifier(result.get("project_id"), "Oracle project id")
    current = _sha256(current_catalog_digest, "Oracle current catalog digest")
    indexed = _sha256(indexed_catalog_digest, "Oracle indexed catalog digest")
    index_digest = _sha256(result.get("index_digest"), "Oracle index digest")
    hits = result.get("hits")
    if not isinstance(hits, list):
        raise UnifiedRetrievalError("Oracle hits are invalid")
    candidates = []
    for item in hits:
        if not isinstance(item, Mapping):
            raise UnifiedRetrievalError("Oracle hit is invalid")
        chunk_id = str(item.get("chunk_id", ""))
        object_id = str(item.get("object_id", ""))
        revision = str(item.get("revision_id", ""))
        digest = _sha256(item.get("content_digest"), "Oracle content digest")
        identity = item.get("identity", {})
        identity = identity if isinstance(identity, Mapping) else {}
        title = ".".join(
            value
            for value in (
                str(identity.get("owner", "")),
                str(identity.get("name", "")),
                str(item.get("symbol_path", "")),
            )
            if value
        )
        score = float(item.get("score", 0.0))
        logical_ref = f"oracle:{project}/{object_id}/{chunk_id}"
        candidates.append(
            UnifiedCandidate(
                project,
                "oracle",
                chunk_id,
                logical_ref,
                title or object_id,
                str(item.get("text") or title or object_id),
                "authoritative-metadata",
                0,
                revision,
                digest,
                (f"oracle-revision:{project}/{object_id}@{revision}:{digest}",),
                "hybrid",
                score,
                {"oracle-domain-score": score},
            )
        )
    return RetrievalBatch(
        project,
        "oracle",
        "current",
        tuple(candidates),
        current,
        indexed,
        index_digest,
    )


def _validate_candidate(candidate: UnifiedCandidate, batch: RetrievalBatch) -> None:
    if candidate.project_id != batch.project_id or candidate.domain != batch.domain:
        raise UnifiedRetrievalError("candidate scope does not match its batch")
    _identifier(candidate.project_id, "candidate project id")
    if candidate.domain not in DOMAINS or candidate.retrieval_mode not in RETRIEVAL_MODES:
        raise UnifiedRetrievalError("candidate domain or retrieval mode is invalid")
    if not candidate.hit_id or not candidate.logical_ref or not candidate.title:
        raise UnifiedRetrievalError("candidate identity and title are required")
    if not candidate.authority or not isinstance(candidate.authority_rank, int):
        raise UnifiedRetrievalError("candidate authority is invalid")
    if candidate.authority_rank < 0 or not candidate.revision:
        raise UnifiedRetrievalError("candidate revision or authority rank is invalid")
    _sha256(candidate.digest, "candidate digest")
    if not candidate.evidence_refs or any(not item.strip() for item in candidate.evidence_refs):
        raise UnifiedRetrievalError("every candidate requires evidence references")
    if len(set(candidate.evidence_refs)) != len(candidate.evidence_refs):
        raise UnifiedRetrievalError("candidate evidence references must be unique")
    if (
        not isinstance(candidate.score, (int, float))
        or isinstance(candidate.score, bool)
        or not math.isfinite(float(candidate.score))
        or not 0 <= float(candidate.score) <= 1
    ):
        raise UnifiedRetrievalError("candidate score is invalid")
    if not candidate.score_breakdown:
        raise UnifiedRetrievalError("candidate score must be explainable")
    for value in candidate.score_breakdown.values():
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise UnifiedRetrievalError("candidate score breakdown is invalid")


def _validate_batch(
    batch: RetrievalBatch,
    provider_authorizations: Mapping[str, ProviderAuthorization],
) -> None:
    _identifier(batch.project_id, "batch project id")
    if batch.domain not in DOMAINS or batch.freshness not in CURRENT_STATUSES:
        raise UnifiedRetrievalError("retrieval batch is stale or invalid")
    if batch.freshness == "authoritative":
        if any(
            value is not None
            for value in (
                batch.source_revision_digest,
                batch.indexed_revision_digest,
                batch.index_digest,
            )
        ):
            raise UnifiedRetrievalError("authoritative batch cannot claim index freshness")
    else:
        source = _sha256(batch.source_revision_digest, "source revision digest")
        indexed = _sha256(batch.indexed_revision_digest, "indexed revision digest")
        if source != indexed:
            raise UnifiedRetrievalError("retrieval index is stale")
        if batch.index_digest is not None:
            _sha256(batch.index_digest, "index digest")
    semantic = any(item.retrieval_mode == "semantic" for item in batch.candidates)
    if semantic:
        request_id = _sha256(batch.provider_request_id, "provider request id")
        authorization = provider_authorizations.get(request_id)
        if authorization is None or authorization.request.request_id != request_id:
            raise UnifiedRetrievalError("semantic result requires existing provider authorization")
        if authorization.request.remote != batch.provider_remote:
            raise UnifiedRetrievalError("semantic provider mode does not match authorization")
        if batch.provider_remote and not authorization.approval_verified:
            raise UnifiedRetrievalError("remote semantic result requires verified approval")
    elif batch.provider_request_id is not None:
        raise UnifiedRetrievalError("provider evidence is allowed only for semantic results")
    for candidate in batch.candidates:
        _validate_candidate(candidate, batch)


def _domain_priority(intent: str, domain: str) -> int:
    try:
        return INTENT_DOMAINS[intent].index(domain)
    except ValueError:
        return len(INTENT_DOMAINS[intent])


def _score(candidate: UnifiedCandidate, intent: str) -> tuple[float, dict[str, float]]:
    tier = EVIDENCE_TIER[candidate.retrieval_mode]
    domain_priority = _domain_priority(intent, candidate.domain)
    breakdown = {
        "evidence": float(f"{1.0 - tier / 4.0:.12f}"),
        "authority": float(f"{1.0 / (1.0 + candidate.authority_rank):.12f}"),
        "intent": float(f"{1.0 / (1.0 + domain_priority):.12f}"),
        "source": float(f"{candidate.score:.12f}"),
    }
    score = (
        0.40 * breakdown["evidence"]
        + 0.25 * breakdown["authority"]
        + 0.20 * breakdown["intent"]
        + 0.15 * breakdown["source"]
    )
    return float(f"{score:.12f}"), breakdown


def retrieve_unified(
    request: UnifiedRetrievalRequest,
    batches: Iterable[RetrievalBatch],
    *,
    provider_authorizations: Mapping[str, ProviderAuthorization] | None = None,
) -> UnifiedRetrievalResult:
    """Rank verified domain results without performing retrieval side effects."""

    validated = create_unified_request(
        query_id=request.query_id,
        text=request.text,
        current_project_id=request.project_ids[0],
        project_ids=request.project_ids,
        scope=request.scope,
        intent=request.intent,
        result_limit=request.result_limit,
        token_budget=request.token_budget,
    )
    authorizations = provider_authorizations or {}
    allowed_domains = set(INTENT_DOMAINS[validated.intent])
    scoped_batches = []
    for batch in batches:
        if batch.project_id not in validated.project_ids:
            raise UnifiedRetrievalError("retrieval batch escaped the requested project scope")
        if batch.domain not in allowed_domains:
            continue
        _validate_batch(batch, authorizations)
        scoped_batches.append(batch)
    source_identity = [
        {
            "project_id": batch.project_id,
            "domain": batch.domain,
            "freshness": batch.freshness,
            "source_revision_digest": batch.source_revision_digest,
            "indexed_revision_digest": batch.indexed_revision_digest,
            "index_digest": batch.index_digest,
            "provider_request_id": batch.provider_request_id,
            "candidates": [
                [item.hit_id, item.revision, item.digest, item.retrieval_mode]
                for item in batch.candidates
            ],
        }
        for batch in scoped_batches
    ]
    source_identity.sort(key=canonical_json)
    source_batch_digest = _digest(source_identity)
    ranked = []
    for batch in scoped_batches:
        for candidate in batch.candidates:
            score, breakdown = _score(candidate, validated.intent)
            ranked.append(
                UnifiedHit(
                    candidate,
                    score,
                    breakdown,
                    EVIDENCE_TIER[candidate.retrieval_mode],
                    _token_count(candidate.content),
                    batch.index_digest,
                )
            )
    ranked.sort(
        key=lambda item: (
            item.evidence_tier,
            _domain_priority(validated.intent, item.candidate.domain),
            item.candidate.authority_rank,
            -item.unified_score,
            item.candidate.project_id,
            item.candidate.domain,
            item.candidate.logical_ref,
            item.candidate.hit_id,
        )
    )
    unique = []
    identities = set()
    for item in ranked:
        identity = (
            item.candidate.project_id,
            item.candidate.logical_ref,
            item.candidate.digest,
        )
        if identity not in identities:
            identities.add(identity)
            unique.append(item)
    selected = []
    token_used = 0
    excluded_by_budget = 0
    for item in unique:
        if len(selected) >= validated.result_limit:
            break
        if token_used + item.token_count > validated.token_budget:
            excluded_by_budget += 1
            continue
        selected.append(item)
        token_used += item.token_count
    context_candidates = tuple(
        item.context_candidate(priority=index)
        for index, item in enumerate(selected)
    )
    return UnifiedRetrievalResult(
        validated,
        tuple(selected),
        context_candidates,
        len(unique),
        excluded_by_budget,
        token_used,
        source_batch_digest,
    )
