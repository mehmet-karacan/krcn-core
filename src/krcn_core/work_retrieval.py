"""Project-scoped work retrieval with strict evidence-tier precedence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import deque
from pathlib import Path
from typing import Mapping, TYPE_CHECKING

from .json_documents import canonical_json_bytes
from .work_graph import (
    STATUSES,
    WORK_TYPES,
    WorkItem,
    parse_work_item,
    work_graph_digest,
    work_graph_index_path,
    work_graph_projection_is_current,
)
from .work_semantic_index import (
    WorkSemanticIndexError,
    canonical_work_document,
    load_work_retrieval_policy,
    semantic_work_scores,
    work_semantic_index_summary,
)

if TYPE_CHECKING:
    from .local_store import LocalWorkspaceStore


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
TOKEN = re.compile(r"\w+", re.UNICODE)
RANKING_ORDER = ("exact", "lexical", "graph", "semantic")


class WorkRetrievalError(ValueError):
    """Raised when work retrieval scope, evidence, or indexes are invalid."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(TOKEN.findall(normalized))


def _project_items(
    store: "LocalWorkspaceStore",
    project_id: str,
) -> dict[str, WorkItem]:
    items = {}
    for record in store.list_records("work-items"):
        item = parse_work_item(record.payload)
        if item.project_id == project_id:
            items[item.work_item_id] = item
    return items


def _exact_score(query: str, item: WorkItem) -> float:
    needle = unicodedata.normalize("NFKC", query).casefold().strip()
    work_item_id = item.work_item_id.casefold()
    if needle == work_item_id:
        return 1.0
    if needle.isdigit() and needle in work_item_id.split("-"):
        return 0.98
    return 0.0


def _fts_scores(connection: sqlite3.Connection, query: str) -> dict[str, float]:
    tokens = tuple(dict.fromkeys(_tokens(query)))[:32]
    if not tokens:
        return {}
    expression = " OR ".join(
        '"' + token.replace('"', '""') + '"' for token in tokens
    )
    try:
        rows = connection.execute(
            "SELECT work_item_id, bm25(search) FROM search "
            "WHERE search MATCH ?",
            (expression,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise WorkRetrievalError("work graph FTS query failed") from exc
    raw = {
        str(work_item_id): max(0.0, -float(rank))
        for work_item_id, rank in rows
    }
    maximum = max(raw.values(), default=0.0)
    if maximum == 0:
        return {work_item_id: 1.0 for work_item_id in raw}
    return {
        work_item_id: value / maximum for work_item_id, value in raw.items()
    }


def _lexical_score(query: str, item: WorkItem, fts_score: float) -> float:
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return 0.0
    document_tokens = set(_tokens(" ".join((
        item.work_item_id,
        item.title,
        item.description,
        *item.acceptance_criteria,
    ))))
    overlap = len(query_tokens & document_tokens) / len(query_tokens)
    return min(1.0, max(fts_score, overlap))


def _graph_scores(
    connection: sqlite3.Connection,
    item_ids: set[str],
    seed_ids: set[str],
    maximum_depth: int,
) -> dict[str, float]:
    if not seed_ids:
        return {}
    try:
        relations = connection.execute(
            "SELECT source_id, target_ref FROM relations"
        ).fetchall()
    except sqlite3.Error as exc:
        raise WorkRetrievalError("work graph relations are invalid") from exc
    adjacency = {work_item_id: set() for work_item_id in item_ids}
    for source_id, target_ref in relations:
        source = str(source_id)
        target = str(target_ref)
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)
    distances = {seed: 0 for seed in seed_ids if seed in adjacency}
    queue = deque(sorted(distances))
    while queue:
        current = queue.popleft()
        if distances[current] >= maximum_depth:
            continue
        for related in sorted(adjacency[current]):
            if related not in distances:
                distances[related] = distances[current] + 1
                queue.append(related)
    return {
        work_item_id: 1.0 / (distance + 1)
        for work_item_id, distance in distances.items()
        if distance > 0
    }


def _score_breakdown(scores: Mapping[str, float]) -> dict[str, object]:
    exact = float(scores.get("exact", 0.0))
    lexical = float(scores.get("lexical", 0.0))
    graph = float(scores.get("graph", 0.0))
    semantic = float(scores.get("semantic", 0.0))
    if exact > 0:
        tier = 0
        combined = exact
    elif lexical > 0:
        tier = 1
        combined = 0.75 * lexical + 0.15 * graph + 0.10 * semantic
    elif graph > 0:
        tier = 2
        combined = 0.70 * graph + 0.30 * semantic
    else:
        tier = 3
        combined = semantic
    return {
        "rank_tier": tier,
        "exact": float(f"{exact:.6f}"),
        "lexical": float(f"{lexical:.6f}"),
        "graph": float(f"{graph:.6f}"),
        "semantic": float(f"{semantic:.6f}"),
        "combined": float(f"{min(1.0, combined):.6f}"),
    }


def search_work(
    repo_root: Path,
    store: "LocalWorkspaceStore",
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Search one project using exact, lexical, graph, then semantic evidence."""

    allowed = {"project_id", "text", "limit", "statuses", "work_types"}
    if set(arguments) - allowed:
        raise WorkRetrievalError("work search contains unsupported fields")
    project_id = arguments.get("project_id")
    text = arguments.get("text")
    if not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id):
        raise WorkRetrievalError("work search project id is invalid")
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise WorkRetrievalError("work search text is invalid")
    policy = load_work_retrieval_policy(repo_root)
    limit = arguments.get("limit", 20)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= policy.maximum_results
    ):
        raise WorkRetrievalError("work search limit is invalid")
    statuses_value = arguments.get("statuses", [])
    work_types_value = arguments.get("work_types", [])
    if (
        not isinstance(statuses_value, list)
        or any(value not in STATUSES for value in statuses_value)
        or len(set(statuses_value)) != len(statuses_value)
        or not isinstance(work_types_value, list)
        or any(value not in WORK_TYPES for value in work_types_value)
        or len(set(work_types_value)) != len(work_types_value)
    ):
        raise WorkRetrievalError("work search filters are invalid")
    if not work_graph_projection_is_current(store, project_id):
        raise WorkRetrievalError(
            "work graph projection is unavailable or stale; rebuild it before search"
        )
    all_items = _project_items(store, project_id)
    statuses = set(statuses_value)
    work_types = set(work_types_value)
    items = {
        work_item_id: item
        for work_item_id, item in all_items.items()
        if (not statuses or item.status in statuses)
        and (not work_types or item.work_type in work_types)
    }
    semantic_summary = work_semantic_index_summary(
        repo_root,
        store,
        project_id,
    )
    semantic_status = str(semantic_summary["status"])
    if semantic_status in {"stale", "invalid"}:
        raise WorkRetrievalError(
            f"work semantic index is {semantic_status}; rebuild it before search"
        )
    target = work_graph_index_path(store.data_root, project_id)
    try:
        connection = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            fts_scores = _fts_scores(connection, text)
            exact_scores = {
                work_item_id: _exact_score(text, item)
                for work_item_id, item in items.items()
            }
            lexical_scores = {
                work_item_id: _lexical_score(
                    text,
                    item,
                    fts_scores.get(work_item_id, 0.0),
                )
                for work_item_id, item in items.items()
            }
            exact_seeds = {
                work_item_id
                for work_item_id, score in exact_scores.items()
                if score > 0
            }
            lexical_seeds = {
                work_item_id
                for work_item_id, score in lexical_scores.items()
                if score > 0
            }
            graph_scores = _graph_scores(
                connection,
                set(items),
                exact_seeds or lexical_seeds,
                policy.graph_max_depth,
            )
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        raise WorkRetrievalError("work graph projection is unreadable") from exc
    if semantic_status == "current":
        try:
            semantic_scores = semantic_work_scores(
                repo_root,
                store,
                project_id,
                text,
            )
        except WorkSemanticIndexError as exc:
            raise WorkRetrievalError(str(exc)) from exc
    else:
        semantic_scores = {}
    scored = []
    for work_item_id, item in items.items():
        scores = {
            "exact": exact_scores.get(work_item_id, 0.0),
            "lexical": lexical_scores.get(work_item_id, 0.0),
            "graph": graph_scores.get(work_item_id, 0.0),
            "semantic": semantic_scores.get(work_item_id, 0.0),
        }
        matched_by = [name for name in RANKING_ORDER if scores[name] > 0]
        if not matched_by:
            continue
        breakdown = _score_breakdown(scores)
        safe_payload = json.loads(
            canonical_work_document(item, policy).canonical_text
        )
        hit = {
            "work_item_id": work_item_id,
            "work_type": item.work_type,
            "status": item.status,
            "title": safe_payload["title"],
            "matched_by": matched_by,
            "score_breakdown": breakdown,
        }
        scored.append((
            int(breakdown["rank_tier"]),
            -float(breakdown["combined"]),
            work_item_id,
            hit,
        ))
    scored.sort(key=lambda value: value[:3])
    selected = [value[3] for value in scored[:limit]]
    result = {
        "schema_ref": "schemas/work-search-result.schema.json",
        "schema_version": 1,
        "project_id": project_id,
        "query": unicodedata.normalize("NFC", text),
        "graph_digest": work_graph_digest(store, project_id),
        "semantic_index_digest": (
            semantic_summary.get("index_digest")
            if semantic_status == "current"
            else None
        ),
        "semantic_status": semantic_status,
        "ranking_order": list(RANKING_ORDER),
        "matched_count": len(scored),
        "hits": selected,
        "paths_disclosed": False,
        "remote_provider_used": False,
    }
    result["result_digest"] = _digest(result)
    return result
