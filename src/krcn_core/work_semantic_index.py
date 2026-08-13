"""Contentless semantic vectors over authoritative project WorkItem v1 records."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TYPE_CHECKING

from .foundation import detect_content_findings, load_json
from .home_layout import project_derived_path
from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, plan_mutation
from .work_graph import (
    WorkItem,
    parse_work_item,
    work_graph_digest,
    work_graph_projection_is_current,
)

if TYPE_CHECKING:
    from .local_store import LocalWorkspaceStore
    from .mutation_gate import OwnershipResolver


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
TOKEN = re.compile(r"\w+", re.UNICODE)
SHA256 = re.compile(r"^[a-f0-9]{64}$")
POLICY_SCHEMA = "schemas/work-retrieval-policy.schema.json"
INDEX_SCHEMA = "work-semantic-v1"
SENSITIVE_DETECTORS = {
    "windows-absolute-path",
    "posix-user-path",
    "private-key",
    "github-token",
    "generic-secret-assignment",
    "credential-uri",
}

WINDOWS_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/][^\s\"'<>|,;)]*"
)
POSIX_PATH = re.compile(
    r"(?<![A-Za-z0-9_:])/(?:Users|home)/[^\s\"'<>|,;)]*"
)
PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
GITHUB_TOKEN = re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|"
    r"client[_-]?secret|access[_-]?token)\s*[:=]\s*"
    r"(?:[\"'][^\"'\r\n]+[\"']|[^\s,;]+)"
)
CREDENTIAL_URI = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]{1,20}://)[^\s/:@]+:[^\s/@]+@"
)


class WorkSemanticIndexError(ValueError):
    """Raised when a work semantic index is unsafe, corrupt, or stale."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class WorkRetrievalPolicy:
    index_revision: int
    embedding_profile_id: str
    vector_dimensions: int
    maximum_document_characters: int
    maximum_results: int
    graph_max_depth: int
    semantic_minimum_score: float
    policy_digest: str


@dataclass(frozen=True)
class WorkSemanticDocument:
    work_item_id: str
    work_digest: str
    document_digest: str
    canonical_text: str


@dataclass(frozen=True)
class WorkSemanticEntry:
    work_item_id: str
    work_digest: str
    document_digest: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class WorkSemanticIndexPlan:
    project_id: str
    graph_digest: str
    policy_digest: str
    embedding_profile_id: str
    vector_dimensions: int
    entries: tuple[WorkSemanticEntry, ...]
    processed_item_count: int
    reused_item_count: int
    removed_item_count: int
    index_digest: str
    mutation: MutationPlan

    @property
    def plan_id(self) -> str:
        return self.mutation.plan_id

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-semantic-index-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "graph_digest": self.graph_digest,
            "policy_digest": self.policy_digest,
            "index_digest": self.index_digest,
            "embedding_profile_id": self.embedding_profile_id,
            "vector_dimensions": self.vector_dimensions,
            "item_count": len(self.entries),
            "processed_item_count": self.processed_item_count,
            "reused_item_count": self.reused_item_count,
            "removed_item_count": self.removed_item_count,
            "mutation": self.mutation.as_dict(),
            "incremental": True,
            "authoritative_source": "work-item-v1",
            "canonical_document_persisted": False,
            "source_content_persisted": False,
            "remote_provider_used": False,
        }


def load_work_retrieval_policy(repo_root: Path) -> WorkRetrievalPolicy:
    """Load the local-only work retrieval policy without provider discovery."""

    payload = load_json(repo_root / "config" / "work-retrieval.json")
    expected = {
        "schema_ref",
        "schema_version",
        "enabled",
        "index_revision",
        "offline_embedding_profile_id",
        "vector_dimensions",
        "maximum_document_characters",
        "maximum_results",
        "graph_max_depth",
        "semantic_minimum_score",
        "source_content_persisted",
        "remote_provider_implicit",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkSemanticIndexError("work retrieval policy fields are invalid")
    if (
        payload.get("schema_ref") != POLICY_SCHEMA
        or payload.get("schema_version") != 1
        or payload.get("enabled") is not True
        or payload.get("index_revision") != 1
        or payload.get("offline_embedding_profile_id")
        != "deterministic-hashing"
        or payload.get("source_content_persisted") is not False
        or payload.get("remote_provider_implicit") is not False
    ):
        raise WorkSemanticIndexError("work retrieval policy safety fields are invalid")
    dimensions = payload.get("vector_dimensions")
    maximum_characters = payload.get("maximum_document_characters")
    maximum_results = payload.get("maximum_results")
    graph_depth = payload.get("graph_max_depth")
    minimum_score = payload.get("semantic_minimum_score")
    if (
        not isinstance(dimensions, int)
        or isinstance(dimensions, bool)
        or not 32 <= dimensions <= 4096
        or not isinstance(maximum_characters, int)
        or isinstance(maximum_characters, bool)
        or not 256 <= maximum_characters <= 100000
        or not isinstance(maximum_results, int)
        or isinstance(maximum_results, bool)
        or not 1 <= maximum_results <= 500
        or not isinstance(graph_depth, int)
        or isinstance(graph_depth, bool)
        or not 1 <= graph_depth <= 3
        or not isinstance(minimum_score, (int, float))
        or isinstance(minimum_score, bool)
        or not math.isfinite(float(minimum_score))
        or not 0 <= float(minimum_score) <= 1
    ):
        raise WorkSemanticIndexError("work retrieval policy limits are invalid")
    return WorkRetrievalPolicy(
        index_revision=1,
        embedding_profile_id="deterministic-hashing",
        vector_dimensions=dimensions,
        maximum_document_characters=maximum_characters,
        maximum_results=maximum_results,
        graph_max_depth=graph_depth,
        semantic_minimum_score=float(minimum_score),
        policy_digest=_digest(payload),
    )


def _sanitize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = PRIVATE_KEY.sub("[redacted-secret]", normalized)
    normalized = GITHUB_TOKEN.sub("[redacted-secret]", normalized)
    normalized = SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[redacted-secret]",
        normalized,
    )
    normalized = CREDENTIAL_URI.sub(
        lambda match: f"{match.group(1)}[redacted-credentials]@",
        normalized,
    )
    normalized = WINDOWS_PATH.sub("[redacted-path]", normalized)
    normalized = POSIX_PATH.sub("[redacted-path]", normalized)
    normalized = " ".join(normalized.split())
    if detect_content_findings(normalized, "work-item", SENSITIVE_DETECTORS):
        raise WorkSemanticIndexError(
            "work item contains content that cannot enter the semantic index"
        )
    return normalized


def canonical_work_document(
    item: WorkItem,
    policy: WorkRetrievalPolicy,
) -> WorkSemanticDocument:
    """Build a safe document from WorkItem fields, never source material."""

    payload = {
        "work_item_id": item.work_item_id,
        "project_id": item.project_id,
        "work_type": item.work_type,
        "status": item.status,
        "title": _sanitize_text(item.title),
        "description": _sanitize_text(item.description),
        "acceptance_criteria": [
            _sanitize_text(value) for value in item.acceptance_criteria
        ],
        "relations": [
            {
                "relation_type": relation.relation_type,
                "target_ref": relation.target_ref,
            }
            for relation in item.relations
        ],
        "evidence_labels": [
            _sanitize_text(evidence.label) for evidence in item.evidence
        ],
    }
    document = canonical_json_bytes(payload).decode("utf-8")
    if len(document) > policy.maximum_document_characters:
        raise WorkSemanticIndexError("work semantic document exceeds the safe limit")
    return WorkSemanticDocument(
        work_item_id=item.work_item_id,
        work_digest=item.work_digest,
        document_digest=hashlib.sha256(document.encode("utf-8")).hexdigest(),
        canonical_text=document,
    )


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(TOKEN.findall(normalized))


def _features(value: str) -> tuple[str, ...]:
    tokens = _tokens(value)
    features = list(tokens)
    for token in tokens:
        padded = f"^{token}$"
        features.extend(
            f"g:{padded[index:index + 3]}"
            for index in range(max(0, len(padded) - 2))
        )
    return tuple(features)


def deterministic_work_vector(
    value: str,
    dimensions: int,
) -> tuple[float, ...]:
    """Return the pinned offline deterministic-hashing embedding."""

    values = [0.0] * dimensions
    for feature in _features(value):
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in values))
    if norm:
        values = [item / norm for item in values]
    return tuple(float(f"{item:.12f}") for item in values)


def cosine_similarity(
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float:
    if len(left) != len(right) or not left:
        raise WorkSemanticIndexError("work semantic vector dimensions are invalid")
    if any(not math.isfinite(item) for item in (*left, *right)):
        raise WorkSemanticIndexError("work semantic vector values are invalid")
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def work_semantic_index_path(data_root: Path, project_id: str) -> Path:
    return project_derived_path(
        data_root,
        project_id,
        "retrieval/work-semantic-v1.sqlite",
    )


def work_semantic_index_target_ref(data_root: Path, project_id: str) -> str:
    target = work_semantic_index_path(data_root, project_id)
    return f".krcn/{target.relative_to(data_root.resolve()).as_posix()}"


def _project_items(
    store: "LocalWorkspaceStore",
    project_id: str,
) -> tuple[WorkItem, ...]:
    return tuple(sorted(
        (
            item
            for item in (
                parse_work_item(record.payload)
                for record in store.list_records("work-items")
            )
            if item.project_id == project_id
        ),
        key=lambda item: item.work_item_id,
    ))


def _index_identity(
    *,
    index_revision: int,
    project_id: str,
    graph_digest: str,
    policy_digest: str,
    embedding_profile_id: str,
    vector_dimensions: int,
    entries: tuple[WorkSemanticEntry, ...],
) -> dict[str, object]:
    return {
        "index_schema": INDEX_SCHEMA,
        "index_revision": index_revision,
        "project_id": project_id,
        "graph_digest": graph_digest,
        "policy_digest": policy_digest,
        "embedding_profile_id": embedding_profile_id,
        "vector_dimensions": vector_dimensions,
        "entries": [
            {
                "work_item_id": entry.work_item_id,
                "work_digest": entry.work_digest,
                "document_digest": entry.document_digest,
                "vector_sha256": _digest(list(entry.vector)),
            }
            for entry in entries
        ],
    }


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return dict(connection.execute("SELECT key, value FROM metadata"))
    except sqlite3.Error as exc:
        raise WorkSemanticIndexError(
            "work semantic index metadata is invalid"
        ) from exc


def _read_entries(
    connection: sqlite3.Connection,
    dimensions: int,
) -> tuple[WorkSemanticEntry, ...]:
    try:
        rows = connection.execute(
            "SELECT work_item_id, work_digest, document_digest, vector_json "
            "FROM vectors ORDER BY work_item_id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise WorkSemanticIndexError("work semantic vectors are invalid") from exc
    entries = []
    for work_item_id, work_digest, document_digest, vector_json in rows:
        try:
            payload = json.loads(vector_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise WorkSemanticIndexError("work semantic vector JSON is invalid") from exc
        if (
            not isinstance(work_item_id, str)
            or not IDENTIFIER.fullmatch(work_item_id)
            or not isinstance(work_digest, str)
            or not SHA256.fullmatch(work_digest)
            or not isinstance(document_digest, str)
            or not SHA256.fullmatch(document_digest)
            or not isinstance(payload, list)
            or len(payload) != dimensions
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in payload
            )
        ):
            raise WorkSemanticIndexError("work semantic vector row is invalid")
        entries.append(WorkSemanticEntry(
            work_item_id,
            work_digest,
            document_digest,
            tuple(float(value) for value in payload),
        ))
    return tuple(entries)


def _load_valid_index(
    target: Path,
) -> tuple[dict[str, str], tuple[WorkSemanticEntry, ...]] | None:
    if not target.is_file() or target.is_symlink():
        return None
    try:
        connection = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            metadata = _metadata(connection)
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return None
            dimensions = int(metadata.get("vector_dimensions", "0"))
            entries = _read_entries(connection, dimensions)
        finally:
            connection.close()
        if (
            metadata.get("index_schema") != INDEX_SCHEMA
            or metadata.get("index_revision") != "1"
            or not IDENTIFIER.fullmatch(metadata.get("project_id", ""))
            or not SHA256.fullmatch(metadata.get("graph_digest", ""))
            or not SHA256.fullmatch(metadata.get("policy_digest", ""))
            or metadata.get("embedding_profile_id") != "deterministic-hashing"
            or dimensions < 1
            or metadata.get("vector_count") != str(len(entries))
            or metadata.get("canonical_document_persisted") != "false"
            or metadata.get("source_content_persisted") != "false"
            or metadata.get("remote_provider_used") != "false"
        ):
            return None
        identity = _index_identity(
            index_revision=1,
            project_id=metadata["project_id"],
            graph_digest=metadata["graph_digest"],
            policy_digest=metadata["policy_digest"],
            embedding_profile_id=metadata["embedding_profile_id"],
            vector_dimensions=dimensions,
            entries=entries,
        )
        if metadata.get("index_digest") != _digest(identity):
            return None
        return metadata, entries
    except (OSError, sqlite3.Error, ValueError, WorkSemanticIndexError):
        return None


def prepare_work_semantic_index(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    ownership: "OwnershipResolver",
    project_id: str,
) -> WorkSemanticIndexPlan:
    """Prepare a local, contentless, incrementally reusable semantic index."""

    if not IDENTIFIER.fullmatch(project_id):
        raise WorkSemanticIndexError("work semantic project id is invalid")
    if store.read("projects", project_id) is None:
        raise WorkSemanticIndexError("work semantic project is not registered")
    if not work_graph_projection_is_current(store, project_id):
        raise WorkSemanticIndexError(
            "work graph projection is unavailable or stale; rebuild it first"
        )
    policy = load_work_retrieval_policy(repo_root)
    items = _project_items(store, project_id)
    graph_digest = work_graph_digest(store, project_id)
    target = work_semantic_index_path(store.data_root, project_id)
    loaded = _load_valid_index(target)
    reusable: dict[str, WorkSemanticEntry] = {}
    existing_ids: set[str] = set()
    if loaded is not None:
        metadata, prior_entries = loaded
        existing_ids = {entry.work_item_id for entry in prior_entries}
        if (
            metadata.get("project_id") == project_id
            and metadata.get("embedding_profile_id")
            == policy.embedding_profile_id
            and metadata.get("vector_dimensions")
            == str(policy.vector_dimensions)
        ):
            reusable = {entry.work_item_id: entry for entry in prior_entries}
    entries = []
    reused = 0
    processed = 0
    for item in items:
        document = canonical_work_document(item, policy)
        prior = reusable.get(item.work_item_id)
        if (
            prior is not None
            and prior.work_digest == item.work_digest
            and prior.document_digest == document.document_digest
        ):
            entries.append(prior)
            reused += 1
        else:
            entries.append(WorkSemanticEntry(
                item.work_item_id,
                item.work_digest,
                document.document_digest,
                deterministic_work_vector(
                    document.canonical_text,
                    policy.vector_dimensions,
                ),
            ))
            processed += 1
    entries_tuple = tuple(entries)
    identity = _index_identity(
        index_revision=policy.index_revision,
        project_id=project_id,
        graph_digest=graph_digest,
        policy_digest=policy.policy_digest,
        embedding_profile_id=policy.embedding_profile_id,
        vector_dimensions=policy.vector_dimensions,
        entries=entries_tuple,
    )
    index_digest = _digest(identity)
    mutation = plan_mutation(
        ownership,
        operation="update" if target.exists() else "create",
        target_ref=work_semantic_index_target_ref(store.data_root, project_id),
        expected_ownership="derived",
        change_digest=index_digest,
        reversible=True,
    )
    return WorkSemanticIndexPlan(
        project_id=project_id,
        graph_digest=graph_digest,
        policy_digest=policy.policy_digest,
        embedding_profile_id=policy.embedding_profile_id,
        vector_dimensions=policy.vector_dimensions,
        entries=entries_tuple,
        processed_item_count=processed,
        reused_item_count=reused,
        removed_item_count=len(existing_ids - {item.work_item_id for item in items}),
        index_digest=index_digest,
        mutation=mutation,
    )


def _create_index(path: Path, plan: WorkSemanticIndexPlan) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE vectors ("
            "work_item_id TEXT PRIMARY KEY, "
            "work_digest TEXT NOT NULL, "
            "document_digest TEXT NOT NULL, "
            "vector_json TEXT NOT NULL)"
        )
        metadata = {
            "index_schema": INDEX_SCHEMA,
            "index_revision": "1",
            "project_id": plan.project_id,
            "graph_digest": plan.graph_digest,
            "policy_digest": plan.policy_digest,
            "index_digest": plan.index_digest,
            "embedding_profile_id": plan.embedding_profile_id,
            "vector_dimensions": str(plan.vector_dimensions),
            "vector_count": str(len(plan.entries)),
            "canonical_document_persisted": "false",
            "source_content_persisted": "false",
            "remote_provider_used": "false",
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            tuple(sorted(metadata.items())),
        )
        connection.executemany(
            "INSERT INTO vectors VALUES (?, ?, ?, ?)",
            tuple(
                (
                    entry.work_item_id,
                    entry.work_digest,
                    entry.document_digest,
                    json.dumps(list(entry.vector), separators=(",", ":")),
                )
                for entry in plan.entries
            ),
        )
        connection.commit()
    finally:
        connection.close()


def apply_work_semantic_index(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    plan: WorkSemanticIndexPlan,
    authorization: MutationAuthorization,
) -> dict[str, object]:
    """Atomically install an exact semantic plan after a verified dry run."""

    if (
        authorization.plan.plan_id != plan.plan_id
        or not authorization.dry_run_verified
        or authorization.plan.ownership != "derived"
        or authorization.plan.change_digest != plan.index_digest
    ):
        raise WorkSemanticIndexError(
            "work semantic authorization does not match the plan"
        )
    if not work_graph_projection_is_current(store, plan.project_id):
        raise WorkSemanticIndexError("work graph changed after semantic planning")
    policy = load_work_retrieval_policy(repo_root)
    items = _project_items(store, plan.project_id)
    current_graph_digest = work_graph_digest(store, plan.project_id)
    rebuilt_entries = tuple(
        WorkSemanticEntry(
            item.work_item_id,
            item.work_digest,
            document.document_digest,
            deterministic_work_vector(
                document.canonical_text,
                policy.vector_dimensions,
            ),
        )
        for item in items
        for document in (canonical_work_document(item, policy),)
    )
    identity = _index_identity(
        index_revision=policy.index_revision,
        project_id=plan.project_id,
        graph_digest=current_graph_digest,
        policy_digest=policy.policy_digest,
        embedding_profile_id=policy.embedding_profile_id,
        vector_dimensions=policy.vector_dimensions,
        entries=rebuilt_entries,
    )
    if (
        current_graph_digest != plan.graph_digest
        or policy.policy_digest != plan.policy_digest
        or rebuilt_entries != plan.entries
        or _digest(identity) != plan.index_digest
    ):
        raise WorkSemanticIndexError(
            "work semantic plan is stale; prepare a new exact plan"
        )
    target = work_semantic_index_path(store.data_root, plan.project_id)
    expected_operation = "update" if target.exists() else "create"
    if plan.mutation.operation != expected_operation:
        raise WorkSemanticIndexError(
            "work semantic target changed after planning"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise WorkSemanticIndexError(
            "work semantic index path may not use symbolic links"
        )
    handle, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{plan.project_id}.work-semantic.",
        suffix=".sqlite",
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        _create_index(temporary, plan)
        loaded = _load_valid_index(temporary)
        if loaded is None:
            raise WorkSemanticIndexError("work semantic index verification failed")
        metadata, entries = loaded
        if (
            metadata.get("index_digest") != plan.index_digest
            or entries != plan.entries
        ):
            raise WorkSemanticIndexError("work semantic index verification failed")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "index_revision": policy.index_revision,
        "project_id": plan.project_id,
        "graph_digest": plan.graph_digest,
        "index_digest": plan.index_digest,
        "embedding_profile_id": plan.embedding_profile_id,
        "vector_dimensions": plan.vector_dimensions,
        "vector_count": len(plan.entries),
        "processed_item_count": plan.processed_item_count,
        "reused_item_count": plan.reused_item_count,
        "removed_item_count": plan.removed_item_count,
        "integrity_verified": True,
        "canonical_document_persisted": False,
        "source_content_persisted": False,
        "remote_provider_used": False,
    }


def work_semantic_index_summary(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    project_id: str,
) -> dict[str, object]:
    """Inspect index freshness without disclosing its physical location."""

    policy = load_work_retrieval_policy(repo_root)
    unavailable = {
        "status": "unavailable",
        "project_id": project_id,
        "graph_digest": None,
        "index_digest": None,
        "embedding_profile_id": policy.embedding_profile_id,
        "vector_dimensions": policy.vector_dimensions,
        "vector_count": 0,
        "canonical_document_persisted": False,
        "source_content_persisted": False,
        "remote_provider_used": False,
        "paths_disclosed": False,
    }
    target = work_semantic_index_path(store.data_root, project_id)
    if not target.is_file() or target.is_symlink():
        return unavailable
    loaded = _load_valid_index(target)
    if loaded is None:
        return {**unavailable, "status": "invalid"}
    metadata, entries = loaded
    try:
        current_graph_digest = work_graph_digest(store, project_id)
    except ValueError:
        return {**unavailable, "status": "invalid"}
    current = bool(
        work_graph_projection_is_current(store, project_id)
        and metadata.get("project_id") == project_id
        and metadata.get("graph_digest") == current_graph_digest
        and metadata.get("policy_digest") == policy.policy_digest
        and metadata.get("embedding_profile_id")
        == policy.embedding_profile_id
        and metadata.get("vector_dimensions") == str(policy.vector_dimensions)
        and len(entries) == len(_project_items(store, project_id))
    )
    return {
        "status": "current" if current else "stale",
        "project_id": project_id,
        "graph_digest": metadata.get("graph_digest"),
        "index_digest": metadata.get("index_digest"),
        "embedding_profile_id": metadata.get("embedding_profile_id"),
        "vector_dimensions": policy.vector_dimensions,
        "vector_count": len(entries),
        "database_bytes": target.stat().st_size,
        "integrity_verified": True,
        "canonical_document_persisted": False,
        "source_content_persisted": False,
        "remote_provider_used": False,
        "paths_disclosed": False,
    }


def semantic_work_scores(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    project_id: str,
    query: str,
) -> dict[str, float]:
    """Return current semantic scores, rejecting stale indexes fail-closed."""

    if not isinstance(query, str) or not query.strip():
        raise WorkSemanticIndexError("work semantic query is invalid")
    summary = work_semantic_index_summary(repo_root, store, project_id)
    if summary["status"] != "current":
        raise WorkSemanticIndexError(
            f"work semantic index is {summary['status']}; rebuild it before search"
        )
    policy = load_work_retrieval_policy(repo_root)
    target = work_semantic_index_path(store.data_root, project_id)
    loaded = _load_valid_index(target)
    if loaded is None:
        raise WorkSemanticIndexError("work semantic index became invalid")
    _, entries = loaded
    query_vector = deterministic_work_vector(query, policy.vector_dimensions)
    return {
        entry.work_item_id: float(f"{score:.6f}")
        for entry in entries
        for score in (cosine_similarity(query_vector, entry.vector),)
        if score >= policy.semantic_minimum_score
    }
