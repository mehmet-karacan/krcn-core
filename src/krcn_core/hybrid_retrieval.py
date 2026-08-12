"""Rebuildable SQLite FTS and deterministic vector retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .dependency_retrieval import InformationRelation
from .information_records import canonical_json, parse_information_record
from .knowledge_catalog import AVAILABILITY_RANK, CatalogEntry, InformationCatalog
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
TOKEN = re.compile(r"\w+", re.UNICODE)
MAX_QUERY_LENGTH = 4096
MAX_RESULT_LIMIT = 100
VECTOR_DIMENSIONS = 192
INDEX_REVISION = 1
INDEX_TARGET_REF = ".krcn/derived/retrieval/hybrid-v1.sqlite"
WEIGHTS = {
    "exact": 0.30,
    "fts": 0.25,
    "vector": 0.25,
    "dependency": 0.10,
    "authority": 0.05,
    "availability": 0.05,
}


class HybridRetrievalError(ValueError):
    """Raised when a hybrid index or retrieval request is unsafe or stale."""


@dataclass(frozen=True)
class HybridIndexPlan:
    catalog_digest: str
    entry_count: int
    document_digest: str
    vector_dimensions: int
    mutation: MutationPlan

    @property
    def plan_id(self) -> str:
        return self.mutation.plan_id

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/hybrid-index-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "index_revision": INDEX_REVISION,
            "catalog_digest": self.catalog_digest,
            "entry_count": self.entry_count,
            "document_digest": self.document_digest,
            "vector_dimensions": self.vector_dimensions,
            "mutation": self.mutation.as_dict(),
            "external_source_content_copied": False,
            "derived_index_rebuildable": True,
        }


@dataclass(frozen=True)
class HybridQuery:
    query_id: str
    text: str
    seed_record_ids: tuple[str, ...]
    include_unavailable: bool
    limit: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/hybrid-retrieval-query.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "text": self.text,
            "seed_record_ids": list(self.seed_record_ids),
            "include_unavailable": self.include_unavailable,
            "limit": self.limit,
        }

    @property
    def query_digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class HybridHit:
    entry: CatalogEntry
    score: float
    score_breakdown: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            **self.entry.as_dict(),
            "score": self.score,
            "score_breakdown": dict(self.score_breakdown),
            "evidence_count": len(self.entry.record.provenance.evidence),
        }


@dataclass(frozen=True)
class HybridResult:
    query_id: str
    query_digest: str
    catalog_digest: str
    index_digest: str
    hits: tuple[HybridHit, ...]
    candidate_count: int
    truncated: bool

    @property
    def result_digest(self) -> str:
        identity = {
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "index_digest": self.index_digest,
            "hits": [item.as_dict() for item in self.hits],
            "candidate_count": self.candidate_count,
            "truncated": self.truncated,
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/hybrid-retrieval-result.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "index_digest": self.index_digest,
            "result_digest": self.result_digest,
            "mode": "sqlite-fts-deterministic-vector",
            "weights": dict(WEIGHTS),
            "candidate_count": self.candidate_count,
            "hit_count": len(self.hits),
            "truncated": self.truncated,
            "hits": [item.as_dict() for item in self.hits],
            "remote": False,
            "external_source_content_copied": False,
        }


def parse_hybrid_query(payload: object) -> HybridQuery:
    expected = {
        "schema_ref",
        "schema_version",
        "query_id",
        "text",
        "seed_record_ids",
        "include_unavailable",
        "limit",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise HybridRetrievalError("hybrid retrieval query fields are invalid")
    if payload.get("schema_ref") != "schemas/hybrid-retrieval-query.schema.json":
        raise HybridRetrievalError("hybrid retrieval schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise HybridRetrievalError("hybrid retrieval schema_version must be 1")
    query_id = payload.get("query_id")
    text = payload.get("text")
    seed_ids = payload.get("seed_record_ids")
    include_unavailable = payload.get("include_unavailable")
    limit = payload.get("limit")
    if not isinstance(query_id, str) or not IDENTIFIER.fullmatch(query_id):
        raise HybridRetrievalError("hybrid query_id is invalid")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_QUERY_LENGTH:
        raise HybridRetrievalError("hybrid query text is invalid")
    if (
        not isinstance(seed_ids, list)
        or any(not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in seed_ids)
        or len(set(seed_ids)) != len(seed_ids)
    ):
        raise HybridRetrievalError("hybrid seed record ids are invalid")
    if not isinstance(include_unavailable, bool):
        raise HybridRetrievalError("hybrid include_unavailable must be boolean")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RESULT_LIMIT:
        raise HybridRetrievalError("hybrid result limit is invalid")
    return HybridQuery(
        query_id,
        unicodedata.normalize("NFC", text),
        tuple(seed_ids),
        include_unavailable,
        limit,
    )


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(TOKEN.findall(normalized))


def _features(value: str) -> tuple[str, ...]:
    tokens = _tokens(value)
    features = list(tokens)
    for token in tokens:
        padded = f"^{token}$"
        features.extend(f"g:{padded[index:index + 3]}" for index in range(max(0, len(padded) - 2)))
    return tuple(features)


def _vector(value: str) -> tuple[float, ...]:
    values = [0.0] * VECTOR_DIMENSIONS
    for feature in _features(value):
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSIONS
        values[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in values))
    if norm:
        values = [item / norm for item in values]
    return tuple(float(f"{item:.12f}") for item in values)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != VECTOR_DIMENSIONS or len(right) != VECTOR_DIMENSIONS:
        raise HybridRetrievalError("hybrid vector dimensions are invalid")
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def _document(entry: CatalogEntry) -> tuple[str, str, str, str, str]:
    record = parse_information_record(entry.record.as_payload())
    title = str(record.payload["title"])
    aliases = " ".join(str(item) for item in record.payload["aliases"])
    if record.information_class == "knowledge":
        keywords = " ".join(str(item) for item in record.payload["keywords"])
        text = str(record.payload["text"])
    else:
        keywords = ""
        text = ""
    combined = " ".join((record.record_id, record.subject_ref, title, aliases, keywords, text))
    return title, aliases, keywords, text, combined


def _document_identity(catalog: InformationCatalog) -> list[dict[str, object]]:
    return [
        {
            "record_id": entry.record.record_id,
            "content_digest": entry.record.content_digest,
            "availability": entry.availability,
            "document_digest": hashlib.sha256(_document(entry)[4].encode("utf-8")).hexdigest(),
        }
        for entry in catalog.entries
    ]


def hybrid_index_path(data_root: Path) -> Path:
    return data_root.resolve() / "derived" / "retrieval" / "hybrid-v1.sqlite"


def prepare_hybrid_index(
    data_root: Path,
    catalog: InformationCatalog,
    ownership: OwnershipResolver,
) -> HybridIndexPlan:
    identity = _document_identity(catalog)
    document_digest = hashlib.sha256(canonical_json(identity)).hexdigest()
    target = hybrid_index_path(data_root)
    mutation = plan_mutation(
        ownership,
        operation="update" if target.exists() else "create",
        target_ref=INDEX_TARGET_REF,
        expected_ownership="derived",
        change_digest=document_digest,
        reversible=True,
    )
    return HybridIndexPlan(
        catalog.catalog_digest,
        len(catalog.entries),
        document_digest,
        VECTOR_DIMENSIONS,
        mutation,
    )


def _create_index(path: Path, plan: HybridIndexPlan, catalog: InformationCatalog) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE documents (record_id TEXT PRIMARY KEY, content_digest TEXT NOT NULL, availability TEXT NOT NULL, authority_rank INTEGER NOT NULL, vector_json TEXT NOT NULL)"
        )
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE documents_fts USING fts5(record_id UNINDEXED, content, tokenize='unicode61 remove_diacritics 2')"
            )
        except sqlite3.Error as exc:
            raise HybridRetrievalError("SQLite FTS5 support is required") from exc
        metadata = {
            "index_revision": str(INDEX_REVISION),
            "catalog_digest": plan.catalog_digest,
            "document_digest": plan.document_digest,
            "entry_count": str(plan.entry_count),
            "vector_dimensions": str(plan.vector_dimensions),
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            tuple(sorted(metadata.items())),
        )
        for entry in catalog.entries:
            _, _, _, _, combined = _document(entry)
            vector_json = json.dumps(_vector(combined), separators=(",", ":"))
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
                (
                    entry.record.record_id,
                    entry.record.content_digest,
                    entry.availability,
                    entry.authority_rank,
                    vector_json,
                ),
            )
            connection.execute(
                "INSERT INTO documents_fts(record_id, content) VALUES (?, ?)",
                (entry.record.record_id, combined),
            )
        connection.commit()
    finally:
        connection.close()


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return dict(connection.execute("SELECT key, value FROM metadata").fetchall())
    except sqlite3.Error as exc:
        raise HybridRetrievalError("hybrid index metadata is invalid") from exc


def apply_hybrid_index(
    data_root: Path,
    catalog: InformationCatalog,
    plan: HybridIndexPlan,
    authorization: MutationAuthorization,
) -> dict[str, object]:
    if authorization.plan.plan_id != plan.plan_id or not authorization.dry_run_verified:
        raise HybridRetrievalError("hybrid index authorization does not match the plan")
    if plan.catalog_digest != catalog.catalog_digest:
        raise HybridRetrievalError("hybrid catalog changed after planning")
    target = hybrid_index_path(data_root)
    document_identity = _document_identity(catalog)
    expected_document_digest = hashlib.sha256(
        canonical_json(document_identity)
    ).hexdigest()
    expected_operation = "update" if target.exists() else "create"
    if (
        plan.entry_count != len(catalog.entries)
        or plan.document_digest != expected_document_digest
        or plan.vector_dimensions != VECTOR_DIMENSIONS
        or plan.mutation.operation != expected_operation
        or plan.mutation.change_digest != plan.document_digest
        or plan.mutation.ownership != "derived"
    ):
        raise HybridRetrievalError("hybrid index plan is no longer current")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise HybridRetrievalError("hybrid index path may not use symbolic links")
    handle, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=".hybrid-v1.",
        suffix=".sqlite",
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        _create_index(temporary, plan, catalog)
        verification = sqlite3.connect(temporary)
        try:
            metadata = _metadata(verification)
            count = verification.execute("SELECT count(*) FROM documents").fetchone()[0]
            integrity = verification.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            verification.close()
        if (
            metadata.get("catalog_digest") != plan.catalog_digest
            or metadata.get("document_digest") != plan.document_digest
            or count != plan.entry_count
            or integrity != "ok"
        ):
            raise HybridRetrievalError("hybrid index verification failed")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "index_revision": INDEX_REVISION,
        "catalog_digest": plan.catalog_digest,
        "document_digest": plan.document_digest,
        "entry_count": plan.entry_count,
        "vector_dimensions": plan.vector_dimensions,
        "integrity_verified": True,
        "external_source_content_copied": False,
    }


def _dependency_scores(
    record_ids: set[str],
    relations: Iterable[InformationRelation],
    seeds: tuple[str, ...],
) -> dict[str, float]:
    if not seeds:
        return {}
    if any(seed not in record_ids for seed in seeds):
        raise HybridRetrievalError("hybrid dependency seed is not in the catalog")
    adjacency: dict[str, set[str]] = {record_id: set() for record_id in record_ids}
    for relation in relations:
        if relation.lifecycle != "current":
            continue
        if relation.from_record_id in adjacency and relation.to_record_id in adjacency:
            adjacency[relation.from_record_id].add(relation.to_record_id)
            adjacency[relation.to_record_id].add(relation.from_record_id)
    distances = {seed: 0 for seed in seeds}
    queue = deque(seeds)
    while queue:
        current = queue.popleft()
        if distances[current] >= 3:
            continue
        for candidate in sorted(adjacency[current]):
            if candidate not in distances:
                distances[candidate] = distances[current] + 1
                queue.append(candidate)
    return {record_id: 1.0 / (distance + 1) for record_id, distance in distances.items()}


def _exact_score(query: str, entry: CatalogEntry) -> float:
    needle = unicodedata.normalize("NFKC", query).casefold().strip()
    title, aliases, keywords, text, _ = _document(entry)
    fields = (
        entry.record.record_id,
        entry.record.subject_ref,
        title,
        *aliases.split(),
        *keywords.split(),
    )
    normalized_fields = tuple(unicodedata.normalize("NFKC", item).casefold() for item in fields)
    if needle in normalized_fields:
        return 1.0
    haystack = " ".join((*normalized_fields, text.casefold()))
    if needle in haystack:
        return 0.7
    return 0.0


def _fts_scores(connection: sqlite3.Connection, query: str) -> dict[str, float]:
    tokens = tuple(dict.fromkeys(_tokens(query)))[:32]
    if not tokens:
        return {}
    expression = " OR ".join('"' + item.replace('"', '""') + '"' for item in tokens)
    try:
        rows = connection.execute(
            "SELECT record_id, bm25(documents_fts) FROM documents_fts WHERE documents_fts MATCH ?",
            (expression,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise HybridRetrievalError("hybrid FTS query failed") from exc
    raw = {str(record_id): max(0.0, -float(rank)) for record_id, rank in rows}
    maximum = max(raw.values(), default=0.0)
    if maximum == 0:
        return {record_id: 1.0 for record_id in raw}
    return {record_id: value / maximum for record_id, value in raw.items()}


def retrieve_hybrid(
    data_root: Path,
    catalog: InformationCatalog,
    relations: Iterable[InformationRelation],
    query: HybridQuery,
) -> HybridResult:
    query = parse_hybrid_query(query.as_dict())
    target = hybrid_index_path(data_root)
    if not target.is_file() or target.is_symlink():
        raise HybridRetrievalError("hybrid index is unavailable; build it before search")
    uri = target.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    try:
        connection.execute("PRAGMA query_only = ON")
        metadata = _metadata(connection)
        if (
            metadata.get("index_revision") != str(INDEX_REVISION)
            or metadata.get("catalog_digest") != catalog.catalog_digest
            or metadata.get("vector_dimensions") != str(VECTOR_DIMENSIONS)
        ):
            raise HybridRetrievalError("hybrid index is stale; rebuild it before search")
        fts_scores = _fts_scores(connection, query.text)
        stored_rows = connection.execute(
            "SELECT record_id, content_digest, availability, authority_rank, vector_json FROM documents"
        ).fetchall()
    finally:
        connection.close()
    entries = {entry.record.record_id: entry for entry in catalog.entries}
    if len(stored_rows) != len(entries):
        raise HybridRetrievalError("hybrid index catalog membership is invalid")
    dependency_scores = _dependency_scores(set(entries), relations, query.seed_record_ids)
    query_vector = _vector(query.text)
    hits: list[HybridHit] = []
    for record_id, content_digest, availability, authority_rank, vector_json in stored_rows:
        entry = entries.get(str(record_id))
        if (
            entry is None
            or entry.record.content_digest != content_digest
            or entry.availability != availability
            or entry.authority_rank != authority_rank
        ):
            raise HybridRetrievalError("hybrid index document evidence is invalid")
        if not query.include_unavailable and entry.availability != "current":
            continue
        try:
            document_vector = tuple(float(item) for item in json.loads(vector_json))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HybridRetrievalError("hybrid index vector is invalid") from exc
        signals = {
            "exact": _exact_score(query.text, entry),
            "fts": fts_scores.get(entry.record.record_id, 0.0),
            "vector": _cosine(query_vector, document_vector),
            "dependency": dependency_scores.get(entry.record.record_id, 0.0),
            "authority": 1.0 if entry.authority_rank == 0 else 0.8,
            "availability": 1.0 / (AVAILABILITY_RANK[entry.availability] + 1),
        }
        score = sum(signals[name] * WEIGHTS[name] for name in WEIGHTS)
        if score > WEIGHTS["authority"] + WEIGHTS["availability"]:
            hits.append(
                HybridHit(
                    entry,
                    float(f"{score:.12f}"),
                    {name: float(f"{value:.12f}") for name, value in signals.items()},
                )
            )
    hits.sort(
        key=lambda item: (
            -item.score,
            item.entry.authority_rank,
            AVAILABILITY_RANK[item.entry.availability],
            item.entry.record.record_id,
        )
    )
    selected = tuple(hits[: query.limit])
    return HybridResult(
        query.query_id,
        query.query_digest,
        catalog.catalog_digest,
        metadata["document_digest"],
        selected,
        len(hits),
        len(hits) > query.limit,
    )
