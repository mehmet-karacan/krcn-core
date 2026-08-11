"""Revision-aware dependency graph records and deterministic traversal."""

from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .information_records import (
    EVIDENCE_RELATIONS,
    PROVENANCE_KINDS,
    EvidenceRef,
    InformationRecordError,
    Provenance,
    canonical_json,
    parse_information_record,
)
from .knowledge_catalog import (
    AVAILABILITY_RANK,
    CatalogEntry,
    InformationCatalog,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")
REVISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
RELATION_TYPES = {
    "contains",
    "depends-on",
    "references",
    "implements",
    "documents",
    "decides",
    "tracks",
    "derived-from",
    "related-to",
}
DIRECTIONS = {"outbound", "inbound", "both"}
MAX_DEPTH = 10
MAX_NODE_BUDGET = 500
MAX_EDGE_BUDGET = 1000


class DependencyRetrievalError(ValueError):
    """Raised when a graph record or traversal request is unsafe or ambiguous."""


@dataclass(frozen=True)
class InformationRelation:
    relation_id: str
    from_record_id: str
    to_record_id: str
    relation_type: str
    revision: int
    relation_digest: str
    provenance: Provenance
    lifecycle: str

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/information-relation.schema.json",
            "schema_version": 1,
            "relation_id": self.relation_id,
            "from_record_id": self.from_record_id,
            "to_record_id": self.to_record_id,
            "relation_type": self.relation_type,
            "revision": self.revision,
            "relation_digest": self.relation_digest,
            "provenance": self.provenance.as_dict(),
            "lifecycle": self.lifecycle,
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "relation_id": self.relation_id,
            "from_record_id": self.from_record_id,
            "to_record_id": self.to_record_id,
            "relation_type": self.relation_type,
            "revision": self.revision,
            "relation_digest": self.relation_digest,
            "lifecycle": self.lifecycle,
            "evidence": [item.as_dict() for item in self.provenance.evidence],
        }


@dataclass(frozen=True)
class DependencyQuery:
    query_id: str
    seed_record_ids: tuple[str, ...]
    direction: str
    relation_types: tuple[str, ...]
    max_depth: int
    node_budget: int
    edge_budget: int
    include_stale_edges: bool
    include_unavailable_nodes: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/dependency-query.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "seed_record_ids": list(self.seed_record_ids),
            "direction": self.direction,
            "relation_types": list(self.relation_types),
            "max_depth": self.max_depth,
            "node_budget": self.node_budget,
            "edge_budget": self.edge_budget,
            "include_stale_edges": self.include_stale_edges,
            "include_unavailable_nodes": self.include_unavailable_nodes,
        }

    @property
    def query_digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True)
class DependencyNode:
    entry: CatalogEntry
    depth: int
    seed: bool
    via_relation_id: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            **self.entry.as_dict(),
            "depth": self.depth,
            "seed": self.seed,
            "via_relation_id": self.via_relation_id,
        }


@dataclass(frozen=True)
class DependencyEdge:
    relation: InformationRelation
    availability: str
    traversal_direction: str
    depth: int

    def as_dict(self) -> dict[str, object]:
        return {
            **self.relation.public_summary(),
            "availability": self.availability,
            "traversal_direction": self.traversal_direction,
            "depth": self.depth,
        }


@dataclass(frozen=True)
class DependencyResult:
    query_id: str
    query_digest: str
    catalog_digest: str
    graph_digest: str
    nodes: tuple[DependencyNode, ...]
    edges: tuple[DependencyEdge, ...]
    cycle_relation_ids: tuple[str, ...]
    truncated: bool
    depth_limited: bool

    @property
    def result_digest(self) -> str:
        identity = {
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "graph_digest": self.graph_digest,
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
            "cycle_relation_ids": list(self.cycle_relation_ids),
            "truncated": self.truncated,
            "depth_limited": self.depth_limited,
        }
        return hashlib.sha256(canonical_json(identity)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/dependency-result.schema.json",
            "schema_version": 1,
            "query_id": self.query_id,
            "query_digest": self.query_digest,
            "catalog_digest": self.catalog_digest,
            "graph_digest": self.graph_digest,
            "result_digest": self.result_digest,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "cycle_relation_ids": list(self.cycle_relation_ids),
            "truncated": self.truncated,
            "depth_limited": self.depth_limited,
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
        }


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise DependencyRetrievalError(f"{label} must be a portable identifier")
    return value


def _parse_evidence(payload: object) -> tuple[EvidenceRef, ...]:
    if not isinstance(payload, list) or not payload:
        raise DependencyRetrievalError("relation evidence must be a non-empty list")
    evidence: list[EvidenceRef] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in payload:
        if not isinstance(item, dict) or set(item) != {
            "source_ref",
            "revision_id",
            "digest",
            "relation",
        }:
            raise DependencyRetrievalError("relation evidence fields are invalid")
        source_ref = item.get("source_ref")
        revision_id = item.get("revision_id")
        digest = item.get("digest")
        evidence_relation = item.get("relation")
        if not isinstance(source_ref, str) or not LOGICAL_REF.fullmatch(source_ref):
            raise DependencyRetrievalError("relation evidence source_ref is invalid")
        if ".." in source_ref.split(":", 1)[1].split("/") or "://" in source_ref:
            raise DependencyRetrievalError("relation evidence source_ref is not portable")
        if not isinstance(revision_id, str) or not REVISION_ID.fullmatch(revision_id):
            raise DependencyRetrievalError("relation evidence revision_id is invalid")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise DependencyRetrievalError("relation evidence digest is invalid")
        if (
            not isinstance(evidence_relation, str)
            or evidence_relation not in EVIDENCE_RELATIONS
            or evidence_relation not in {"supports", "derived-from", "observed-at"}
        ):
            raise DependencyRetrievalError("relation evidence type is invalid")
        identity = (source_ref, revision_id, digest, evidence_relation)
        if identity in seen:
            raise DependencyRetrievalError("relation evidence must be unique")
        seen.add(identity)
        evidence.append(EvidenceRef(*identity))
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.source_ref,
                item.revision_id,
                item.digest,
                item.relation,
            ),
        )
    )


def relation_digest(
    from_record_id: str,
    to_record_id: str,
    relation_type: str,
    provenance: Provenance,
) -> str:
    identity = {
        "from_record_id": from_record_id,
        "to_record_id": to_record_id,
        "relation_type": relation_type,
        "provenance": provenance.as_dict(),
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def parse_information_relation(payload: object) -> InformationRelation:
    expected = {
        "schema_ref",
        "schema_version",
        "relation_id",
        "from_record_id",
        "to_record_id",
        "relation_type",
        "revision",
        "relation_digest",
        "provenance",
        "lifecycle",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise DependencyRetrievalError("information relation fields are invalid")
    if payload.get("schema_ref") != "schemas/information-relation.schema.json":
        raise DependencyRetrievalError("information relation schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise DependencyRetrievalError("information relation schema_version must be 1")
    relation_id = _identifier(payload.get("relation_id"), "relation_id")
    from_record_id = _identifier(payload.get("from_record_id"), "from_record_id")
    to_record_id = _identifier(payload.get("to_record_id"), "to_record_id")
    if from_record_id == to_record_id:
        raise DependencyRetrievalError("information relation endpoints must differ")
    relation_type = payload.get("relation_type")
    if not isinstance(relation_type, str) or relation_type not in RELATION_TYPES:
        raise DependencyRetrievalError("information relation type is invalid")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise DependencyRetrievalError("information relation revision must be positive")
    provenance_payload = payload.get("provenance")
    if not isinstance(provenance_payload, dict) or set(provenance_payload) != {
        "kind",
        "evidence",
    }:
        raise DependencyRetrievalError("information relation provenance is invalid")
    provenance_kind = provenance_payload.get("kind")
    if not isinstance(provenance_kind, str) or provenance_kind not in PROVENANCE_KINDS:
        raise DependencyRetrievalError("information relation provenance kind is invalid")
    provenance = Provenance(
        provenance_kind,
        _parse_evidence(provenance_payload.get("evidence")),
    )
    digest = payload.get("relation_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise DependencyRetrievalError("information relation digest is invalid")
    if digest != relation_digest(
        from_record_id,
        to_record_id,
        relation_type,
        provenance,
    ):
        raise DependencyRetrievalError("information relation digest does not match")
    lifecycle = payload.get("lifecycle")
    if (
        not isinstance(lifecycle, str)
        or lifecycle not in {"current", "superseded", "stale", "archived"}
    ):
        raise DependencyRetrievalError("information relation lifecycle is invalid")
    return InformationRelation(
        relation_id=relation_id,
        from_record_id=from_record_id,
        to_record_id=to_record_id,
        relation_type=relation_type,
        revision=revision,
        relation_digest=digest,
        provenance=provenance,
        lifecycle=str(lifecycle),
    )


def parse_dependency_query(payload: object) -> DependencyQuery:
    expected = {
        "schema_ref",
        "schema_version",
        "query_id",
        "seed_record_ids",
        "direction",
        "relation_types",
        "max_depth",
        "node_budget",
        "edge_budget",
        "include_stale_edges",
        "include_unavailable_nodes",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise DependencyRetrievalError("dependency query fields are invalid")
    if payload.get("schema_ref") != "schemas/dependency-query.schema.json":
        raise DependencyRetrievalError("dependency query schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise DependencyRetrievalError("dependency query schema_version must be 1")
    query_id = _identifier(payload.get("query_id"), "query_id")
    seeds_payload = payload.get("seed_record_ids")
    if not isinstance(seeds_payload, list) or not seeds_payload:
        raise DependencyRetrievalError("seed_record_ids must be a non-empty list")
    seeds = tuple(_identifier(item, "seed_record_id") for item in seeds_payload)
    if len(set(seeds)) != len(seeds):
        raise DependencyRetrievalError("seed_record_ids must be unique")
    direction = payload.get("direction")
    if not isinstance(direction, str) or direction not in DIRECTIONS:
        raise DependencyRetrievalError("dependency direction is invalid")
    relation_types_payload = payload.get("relation_types")
    if (
        not isinstance(relation_types_payload, list)
        or not relation_types_payload
        or any(
            not isinstance(item, str) or item not in RELATION_TYPES
            for item in relation_types_payload
        )
        or len(set(relation_types_payload)) != len(relation_types_payload)
    ):
        raise DependencyRetrievalError("dependency relation_types are invalid")
    max_depth = payload.get("max_depth")
    node_budget = payload.get("node_budget")
    edge_budget = payload.get("edge_budget")
    for value, label, maximum in (
        (max_depth, "max_depth", MAX_DEPTH),
        (node_budget, "node_budget", MAX_NODE_BUDGET),
        (edge_budget, "edge_budget", MAX_EDGE_BUDGET),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= maximum
        ):
            raise DependencyRetrievalError(f"dependency {label} is invalid")
    include_stale_edges = payload.get("include_stale_edges")
    include_unavailable_nodes = payload.get("include_unavailable_nodes")
    if not isinstance(include_stale_edges, bool):
        raise DependencyRetrievalError("include_stale_edges must be boolean")
    if not isinstance(include_unavailable_nodes, bool):
        raise DependencyRetrievalError("include_unavailable_nodes must be boolean")
    if node_budget < len(seeds):
        raise DependencyRetrievalError("node budget cannot fit all seed records")
    return DependencyQuery(
        query_id=query_id,
        seed_record_ids=tuple(sorted(seeds)),
        direction=direction,
        relation_types=tuple(sorted(relation_types_payload)),
        max_depth=max_depth,
        node_budget=node_budget,
        edge_budget=edge_budget,
        include_stale_edges=include_stale_edges,
        include_unavailable_nodes=include_unavailable_nodes,
    )


def _validated_catalog_entries(
    catalog: InformationCatalog,
) -> dict[str, CatalogEntry]:
    entries: dict[str, CatalogEntry] = {}
    for entry in catalog.entries:
        try:
            record = parse_information_record(entry.record.as_payload())
        except InformationRecordError as exc:
            raise DependencyRetrievalError("catalog entry record is invalid") from exc
        if entry.availability not in AVAILABILITY_RANK:
            raise DependencyRetrievalError("catalog entry availability is invalid")
        if record.record_id in entries:
            raise DependencyRetrievalError("catalog record ids must be unique")
        entries[record.record_id] = CatalogEntry(
            record,
            entry.availability,
            entry.binding_ref,
        )
    return entries


def _current_revisions(
    entries: dict[str, CatalogEntry],
) -> dict[str, tuple[str, str]]:
    revisions: dict[str, tuple[str, str]] = {}
    for record_id, entry in entries.items():
        if entry.availability != "current":
            continue
        revisions[f"record:{record_id}"] = (
            str(entry.record.revision),
            entry.record.content_digest,
        )
        if entry.record.information_class == "authoritative-source":
            revisions[entry.record.subject_ref] = (
                str(entry.record.payload["source_revision_id"]),
                str(entry.record.payload["source_digest"]),
            )
    return revisions


def _relation_availability(
    relation: InformationRelation,
    entries: dict[str, CatalogEntry],
    revisions: dict[str, tuple[str, str]],
) -> str:
    if relation.lifecycle in {"superseded", "archived", "stale"}:
        return relation.lifecycle
    if any(
        entries[record_id].availability != "current"
        for record_id in (relation.from_record_id, relation.to_record_id)
    ):
        return "stale"
    if any(
        revisions.get(item.source_ref) != (item.revision_id, item.digest)
        for item in relation.provenance.evidence
    ):
        return "stale"
    return "current"


def _graph_digest(relations: Iterable[InformationRelation]) -> str:
    summaries = [item.public_summary() for item in relations]
    return hashlib.sha256(canonical_json(summaries)).hexdigest()


def _adjacent(
    record_id: str,
    relations: tuple[InformationRelation, ...],
    direction: str,
) -> tuple[tuple[InformationRelation, str, str], ...]:
    found: list[tuple[InformationRelation, str, str]] = []
    for relation in relations:
        if direction in {"outbound", "both"} and relation.from_record_id == record_id:
            found.append((relation, relation.to_record_id, "outbound"))
        if direction in {"inbound", "both"} and relation.to_record_id == record_id:
            found.append((relation, relation.from_record_id, "inbound"))
    return tuple(
        sorted(
            found,
            key=lambda item: (
                item[0].relation_type,
                item[0].from_record_id,
                item[0].to_record_id,
                -item[0].revision,
                item[0].relation_id,
                item[2],
            ),
        )
    )


def _node_sort_key(node: DependencyNode) -> tuple[object, ...]:
    return (
        node.depth,
        not node.seed,
        AVAILABILITY_RANK[node.entry.availability],
        node.entry.authority_rank,
        node.entry.record.subject_ref,
        node.entry.record.record_id,
    )


def _cycle_relation_ids(
    edges: Iterable[DependencyEdge],
) -> tuple[str, ...]:
    selected = tuple(edges)
    adjacency: dict[str, list[str]] = {}
    for edge in selected:
        adjacency.setdefault(edge.relation.from_record_id, []).append(
            edge.relation.to_record_id
        )

    def path_exists(start: str, target: str) -> bool:
        pending = [start]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(
                reversed(sorted(set(adjacency.get(current, [])) - visited))
            )
        return False

    return tuple(
        sorted(
            edge.relation.relation_id
            for edge in selected
            if path_exists(
                edge.relation.to_record_id,
                edge.relation.from_record_id,
            )
        )
    )


def retrieve_dependencies(
    catalog: InformationCatalog,
    relations: Iterable[InformationRelation],
    query: DependencyQuery,
) -> DependencyResult:
    """Traverse an evidence-bound graph within explicit deterministic limits."""

    query = parse_dependency_query(query.as_dict())
    entries = _validated_catalog_entries(catalog)
    for seed in query.seed_record_ids:
        if seed not in entries:
            raise DependencyRetrievalError("dependency seed record was not found")
        if (
            entries[seed].availability != "current"
            and not query.include_unavailable_nodes
        ):
            raise DependencyRetrievalError("dependency seed record is unavailable")

    parsed_relations: list[InformationRelation] = []
    relation_ids: set[str] = set()
    for candidate in relations:
        try:
            relation = parse_information_relation(candidate.as_payload())
        except (AttributeError, DependencyRetrievalError) as exc:
            raise DependencyRetrievalError("information relation is invalid") from exc
        if relation.relation_id in relation_ids:
            raise DependencyRetrievalError("information relation ids must be unique")
        if relation.from_record_id not in entries or relation.to_record_id not in entries:
            raise DependencyRetrievalError("information relation endpoint was not found")
        relation_ids.add(relation.relation_id)
        parsed_relations.append(relation)
    ordered_relations = tuple(
        sorted(
            parsed_relations,
            key=lambda item: (
                item.relation_type,
                item.from_record_id,
                item.to_record_id,
                -item.revision,
                item.relation_id,
            ),
        )
    )
    revisions = _current_revisions(entries)

    nodes: dict[str, DependencyNode] = {
        seed: DependencyNode(entries[seed], 0, True, None)
        for seed in query.seed_record_ids
    }
    queue = deque(
        (seed, 0, (seed,))
        for seed in query.seed_record_ids
    )
    edges: dict[str, DependencyEdge] = {}
    truncated = False
    depth_limited = False

    while queue:
        record_id, depth, path = queue.popleft()
        adjacent = _adjacent(record_id, ordered_relations, query.direction)
        eligible = tuple(
            item for item in adjacent if item[0].relation_type in query.relation_types
        )
        if depth >= query.max_depth:
            if any(item[0].relation_id not in edges for item in eligible):
                depth_limited = True
            continue
        for relation, neighbor_id, traversal_direction in eligible:
            if relation.relation_id in edges:
                continue
            availability = _relation_availability(relation, entries, revisions)
            if availability != "current" and not query.include_stale_edges:
                continue
            neighbor = entries[neighbor_id]
            if (
                neighbor.availability != "current"
                and not query.include_unavailable_nodes
            ):
                continue
            is_new_node = neighbor_id not in nodes
            if is_new_node and len(nodes) >= query.node_budget:
                truncated = True
                continue
            if len(edges) >= query.edge_budget:
                truncated = True
                continue
            edge_depth = depth + 1
            edges[relation.relation_id] = DependencyEdge(
                relation,
                availability,
                traversal_direction,
                edge_depth,
            )
            if neighbor_id in path:
                continue
            if is_new_node:
                nodes[neighbor_id] = DependencyNode(
                    neighbor,
                    edge_depth,
                    False,
                    relation.relation_id,
                )
                queue.append((neighbor_id, edge_depth, path + (neighbor_id,)))

    ordered_nodes = tuple(sorted(nodes.values(), key=_node_sort_key))
    ordered_edges = tuple(
        sorted(
            edges.values(),
            key=lambda item: (
                item.depth,
                item.relation.relation_type,
                item.relation.from_record_id,
                item.relation.to_record_id,
                item.relation.relation_id,
            ),
        )
    )
    return DependencyResult(
        query_id=query.query_id,
        query_digest=query.query_digest,
        catalog_digest=catalog.catalog_digest,
        graph_digest=_graph_digest(ordered_relations),
        nodes=ordered_nodes,
        edges=ordered_edges,
        cycle_relation_ids=_cycle_relation_ids(ordered_edges),
        truncated=truncated,
        depth_limited=depth_limited,
    )
