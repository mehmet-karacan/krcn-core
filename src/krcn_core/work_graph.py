"""Authoritative project work graph and rebuildable local projection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, TYPE_CHECKING

from .home_layout import project_derived_path
from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, plan_mutation

if TYPE_CHECKING:
    from .local_store import LocalWorkspaceStore, RecordWritePlan
    from .mutation_gate import OwnershipResolver


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
WORK_TYPES = {"request", "defect", "task", "subtask", "decision"}
STATUSES = {"proposed", "active", "blocked", "completed", "cancelled", "archived"}
ACTIVE_STATUSES = {"proposed", "active", "blocked"}
RELATION_TYPES = {
    "depends-on", "blocks", "parent-of", "implements", "caused-by",
    "relates-to", "supersedes",
}
EVIDENCE_TYPES = {"commit", "branch", "file", "test", "release", "document"}
TRANSITIONS = {
    "proposed": {"proposed", "active", "cancelled", "archived"},
    "active": {"active", "blocked", "completed", "cancelled", "archived"},
    "blocked": {"blocked", "active", "completed", "cancelled", "archived"},
    "completed": {"completed", "archived", "active"},
    "cancelled": {"cancelled", "archived", "active"},
    "archived": {"archived", "active"},
}


class WorkGraphError(ValueError):
    """Raised when authoritative work history is invalid or stale."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise WorkGraphError(f"{label} must contain non-empty strings")
    return tuple(value)


@dataclass(frozen=True)
class WorkRelation:
    relation_type: str
    target_ref: str

    def as_dict(self) -> dict[str, str]:
        return {"relation_type": self.relation_type, "target_ref": self.target_ref}


@dataclass(frozen=True)
class WorkEvidence:
    evidence_type: str
    reference: str
    digest: str | None
    label: str

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type,
            "reference": self.reference,
            "digest": self.digest,
            "label": self.label,
        }


@dataclass(frozen=True)
class WorkItem:
    work_item_id: str
    project_id: str
    work_type: str
    title: str
    description: str
    status: str
    acceptance_criteria: tuple[str, ...]
    relations: tuple[WorkRelation, ...]
    evidence: tuple[WorkEvidence, ...]
    provenance: Mapping[str, object]
    revision: int
    work_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-item.schema.json",
            "schema_version": 1,
            "work_item_id": self.work_item_id,
            "project_id": self.project_id,
            "work_type": self.work_type,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "acceptance_criteria": list(self.acceptance_criteria),
            "relations": [item.as_dict() for item in self.relations],
            "evidence": [item.as_dict() for item in self.evidence],
            "provenance": dict(self.provenance),
            "revision": self.revision,
            "work_digest": self.work_digest,
        }


@dataclass(frozen=True)
class WorkEvent:
    work_event_id: str
    project_id: str
    work_item_id: str
    from_status: str | None
    to_status: str
    item_revision: int
    item_digest: str
    provenance: Mapping[str, object]
    revision: int
    event_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-event.schema.json",
            "schema_version": 1,
            "work_event_id": self.work_event_id,
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "item_revision": self.item_revision,
            "item_digest": self.item_digest,
            "provenance": dict(self.provenance),
            "revision": self.revision,
            "event_digest": self.event_digest,
        }


def parse_work_event(payload: object) -> WorkEvent:
    expected = {
        "schema_ref", "schema_version", "work_event_id", "project_id",
        "work_item_id", "from_status", "to_status", "item_revision",
        "item_digest", "provenance", "revision", "event_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkGraphError("work event fields are invalid")
    if payload.get("schema_ref") != "schemas/work-event.schema.json" or payload.get("schema_version") != 1:
        raise WorkGraphError("work event header is invalid")
    for field in ("work_event_id", "project_id", "work_item_id"):
        if not IDENTIFIER.fullmatch(str(payload.get(field, ""))):
            raise WorkGraphError("work event identity is invalid")
    if payload.get("from_status") is not None and payload.get("from_status") not in STATUSES:
        raise WorkGraphError("work event prior status is invalid")
    if payload.get("to_status") not in STATUSES:
        raise WorkGraphError("work event target status is invalid")
    for field in ("item_revision", "revision"):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise WorkGraphError("work event revision is invalid")
    if payload["revision"] != 1 or not SHA256.fullmatch(str(payload.get("item_digest", ""))):
        raise WorkGraphError("work event digest reference is invalid")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {"source_kind", "source_ref"}:
        raise WorkGraphError("work event provenance is invalid")
    identity = dict(payload)
    digest = identity.pop("event_digest", None)
    if not isinstance(digest, str) or digest != _digest(identity):
        raise WorkGraphError("work event digest does not match")
    return WorkEvent(
        str(payload["work_event_id"]), str(payload["project_id"]),
        str(payload["work_item_id"]), payload["from_status"],
        str(payload["to_status"]), int(payload["item_revision"]),
        str(payload["item_digest"]), dict(provenance), 1, digest,
    )


def build_work_event(item: WorkItem, from_status: str | None) -> WorkEvent:
    payload = {
        "schema_ref": "schemas/work-event.schema.json",
        "schema_version": 1,
        "work_event_id": f"{item.work_item_id}-r{item.revision}",
        "project_id": item.project_id,
        "work_item_id": item.work_item_id,
        "from_status": from_status,
        "to_status": item.status,
        "item_revision": item.revision,
        "item_digest": item.work_digest,
        "provenance": dict(item.provenance),
        "revision": 1,
    }
    payload["event_digest"] = _digest(payload)
    return parse_work_event(payload)


def parse_work_item(payload: object) -> WorkItem:
    expected = {
        "schema_ref", "schema_version", "work_item_id", "project_id",
        "work_type", "title", "description", "status", "acceptance_criteria",
        "relations", "evidence", "provenance", "revision", "work_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkGraphError("work item fields are invalid")
    if payload.get("schema_ref") != "schemas/work-item.schema.json" or payload.get("schema_version") != 1:
        raise WorkGraphError("work item header is invalid")
    for field in ("work_item_id", "project_id"):
        if not IDENTIFIER.fullmatch(str(payload.get(field, ""))):
            raise WorkGraphError("work item identity is invalid")
    if payload.get("work_type") not in WORK_TYPES or payload.get("status") not in STATUSES:
        raise WorkGraphError("work item type or status is invalid")
    if not isinstance(payload.get("title"), str) or not str(payload["title"]).strip():
        raise WorkGraphError("work item title is required")
    if not isinstance(payload.get("description"), str):
        raise WorkGraphError("work item description is invalid")
    acceptance = _strings(payload.get("acceptance_criteria"), "acceptance criteria")
    relations_value = payload.get("relations")
    if not isinstance(relations_value, list):
        raise WorkGraphError("work relations are invalid")
    relations = []
    relation_keys = set()
    for value in relations_value:
        if not isinstance(value, dict) or set(value) != {"relation_type", "target_ref"}:
            raise WorkGraphError("work relation fields are invalid")
        kind, target = value.get("relation_type"), value.get("target_ref")
        if kind not in RELATION_TYPES or not isinstance(target, str) or not IDENTIFIER.fullmatch(target):
            raise WorkGraphError("work relation is invalid")
        key = (kind, target)
        if key in relation_keys or target == payload["work_item_id"]:
            raise WorkGraphError("work relation is duplicate or self-referential")
        relation_keys.add(key)
        relations.append(WorkRelation(kind, target))
    evidence_value = payload.get("evidence")
    if not isinstance(evidence_value, list):
        raise WorkGraphError("work evidence is invalid")
    evidence = []
    evidence_keys = set()
    for value in evidence_value:
        if not isinstance(value, dict) or set(value) != {"evidence_type", "reference", "digest", "label"}:
            raise WorkGraphError("work evidence fields are invalid")
        kind, reference, digest, label = (
            value.get("evidence_type"), value.get("reference"),
            value.get("digest"), value.get("label"),
        )
        if kind not in EVIDENCE_TYPES or not isinstance(reference, str) or not reference.strip():
            raise WorkGraphError("work evidence identity is invalid")
        if digest is not None and (not isinstance(digest, str) or not SHA256.fullmatch(digest)):
            raise WorkGraphError("work evidence digest is invalid")
        if not isinstance(label, str) or not label.strip():
            raise WorkGraphError("work evidence label is invalid")
        key = (kind, reference)
        if key in evidence_keys:
            raise WorkGraphError("work evidence is duplicated")
        evidence_keys.add(key)
        evidence.append(WorkEvidence(kind, reference, digest, label))
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {"source_kind", "source_ref"}:
        raise WorkGraphError("work provenance fields are invalid")
    if provenance.get("source_kind") not in {"user", "import", "orchestrator", "repository"}:
        raise WorkGraphError("work provenance source kind is invalid")
    if not isinstance(provenance.get("source_ref"), str) or not provenance["source_ref"].strip():
        raise WorkGraphError("work provenance source ref is required")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkGraphError("work item revision is invalid")
    digest = payload.get("work_digest")
    identity = dict(payload)
    identity.pop("work_digest")
    if not isinstance(digest, str) or digest != _digest(identity):
        raise WorkGraphError("work item digest does not match")
    return WorkItem(
        str(payload["work_item_id"]), str(payload["project_id"]),
        str(payload["work_type"]), str(payload["title"]),
        str(payload["description"]), str(payload["status"]), acceptance,
        tuple(relations), tuple(evidence), dict(provenance), revision, digest,
    )


def build_work_item(arguments: Mapping[str, object], revision: int) -> WorkItem:
    payload = {
        "schema_ref": "schemas/work-item.schema.json",
        "schema_version": 1,
        "work_item_id": arguments.get("work_item_id"),
        "project_id": arguments.get("project_id"),
        "work_type": arguments.get("work_type"),
        "title": arguments.get("title"),
        "description": arguments.get("description", ""),
        "status": arguments.get("status", "proposed"),
        "acceptance_criteria": arguments.get("acceptance_criteria", []),
        "relations": arguments.get("relations", []),
        "evidence": arguments.get("evidence", []),
        "provenance": arguments.get("provenance", {"source_kind": "user", "source_ref": "direct-request"}),
        "revision": revision,
    }
    payload["work_digest"] = _digest(payload)
    return parse_work_item(payload)


def work_graph_index_path(data_root: Path, project_id: str) -> Path:
    return project_derived_path(data_root, project_id, "retrieval/work-graph-v1.sqlite")


def _project_items(store: "LocalWorkspaceStore", project_id: str) -> tuple[WorkItem, ...]:
    return tuple(
        item for item in (
            parse_work_item(record.payload) for record in store.list_records("work-items")
        ) if item.project_id == project_id
    )


def _validate_graph(items: Sequence[WorkItem]) -> None:
    by_id = {item.work_item_id: item for item in items}
    edges = {
        item.work_item_id: {
            relation.target_ref for relation in item.relations
            if relation.relation_type in {"depends-on", "parent-of"}
            and relation.target_ref in by_id
        }
        for item in items
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            raise WorkGraphError("work graph contains a dependency cycle")
        if node in visited:
            return
        visiting.add(node)
        for target in edges[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)
    for node in edges:
        visit(node)


@dataclass(frozen=True)
class WorkGraphWritePlan:
    project_id: str
    item: WorkItem
    record_plan: "RecordWritePlan"
    event_plan: "RecordWritePlan"
    projection_mutation: MutationPlan
    graph_digest: str
    plan_id: str

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return (
            self.record_plan.mutation,
            self.event_plan.mutation,
            self.projection_mutation,
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-graph-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "work_item_id": self.item.work_item_id,
            "status": self.item.status,
            "next_revision": self.item.revision,
            "graph_digest": self.graph_digest,
            "authoritative_status": True,
            "effect_plans": [item.as_dict() for item in self.effect_plans],
        }


def prepare_work_item(
    store: "LocalWorkspaceStore",
    ownership: "OwnershipResolver",
    arguments: Mapping[str, object],
) -> WorkGraphWritePlan:
    project_id = str(arguments.get("project_id", ""))
    if store.read("projects", project_id) is None:
        raise WorkGraphError("work item project is not registered")
    work_id = str(arguments.get("work_item_id", ""))
    current = store.read("work-items", work_id) if IDENTIFIER.fullmatch(work_id) else None
    item = build_work_item(arguments, (current.revision + 1) if current else 1)
    if current:
        previous = parse_work_item(current.payload)
        if previous.project_id != item.project_id or item.status not in TRANSITIONS[previous.status]:
            raise WorkGraphError("work item project or status transition is invalid")
    else:
        previous = None
    if item.status == "completed" and not item.evidence:
        raise WorkGraphError("completed work item requires evidence")
    items = [value for value in _project_items(store, project_id) if value.work_item_id != work_id]
    items.append(item)
    known_ids = {value.work_item_id for value in items}
    if any(
        relation.target_ref not in known_ids
        for value in items
        for relation in value.relations
    ):
        raise WorkGraphError("work relation target was not found in the project")
    _validate_graph(items)
    graph_digest = _digest([value.as_dict() for value in sorted(items, key=lambda value: value.work_item_id)])
    record_plan = store.prepare_put(
        "work-items", work_id, item.as_dict(),
        expected_revision=current.revision if current else 0,
        project_id=project_id,
    )
    event = build_work_event(item, previous.status if previous else None)
    event_plan = store.prepare_put(
        "work-events", event.work_event_id, event.as_dict(),
        expected_revision=0, project_id=project_id,
    )
    target = work_graph_index_path(store.data_root, project_id)
    target_ref = ".krcn/" + target.relative_to(store.data_root).as_posix()
    projection = plan_mutation(
        ownership, operation="update" if target.exists() else "create",
        target_ref=target_ref, expected_ownership="derived",
        change_digest=graph_digest, reversible=True,
    )
    plan_id = _digest({
        "project_id": project_id, "work_item": item.as_dict(),
        "graph_digest": graph_digest,
        "effects": [
            record_plan.mutation.as_dict(), event_plan.mutation.as_dict(),
            projection.as_dict(),
        ],
    })
    return WorkGraphWritePlan(
        project_id, item, record_plan, event_plan, projection, graph_digest, plan_id
    )


def _write_projection(path: Path, items: Sequence[WorkItem], graph_digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".work-graph-", suffix=".sqlite", dir=path.parent)
        os.close(descriptor)
        descriptor = None
        temporary = Path(name)
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(
                "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                "CREATE TABLE items(work_item_id TEXT PRIMARY KEY, work_type TEXT NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, revision INTEGER NOT NULL, digest TEXT NOT NULL);"
                "CREATE TABLE relations(source_id TEXT NOT NULL, relation_type TEXT NOT NULL, target_ref TEXT NOT NULL, PRIMARY KEY(source_id, relation_type, target_ref));"
                "CREATE TABLE evidence(work_item_id TEXT NOT NULL, evidence_type TEXT NOT NULL, reference TEXT NOT NULL, digest TEXT, label TEXT NOT NULL, PRIMARY KEY(work_item_id, evidence_type, reference));"
                "CREATE VIRTUAL TABLE search USING fts5(work_item_id UNINDEXED, title, description);"
            )
            connection.execute("INSERT INTO metadata VALUES('graph_digest', ?)", (graph_digest,))
            for item in items:
                connection.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)", (
                    item.work_item_id, item.work_type, item.status, item.title,
                    item.description, item.revision, item.work_digest,
                ))
                connection.execute("INSERT INTO search VALUES(?,?,?)", (item.work_item_id, item.title, item.description))
                connection.executemany("INSERT INTO relations VALUES(?,?,?)", [
                    (item.work_item_id, relation.relation_type, relation.target_ref)
                    for relation in item.relations
                ])
                connection.executemany("INSERT INTO evidence VALUES(?,?,?,?,?)", [
                    (item.work_item_id, evidence.evidence_type, evidence.reference, evidence.digest, evidence.label)
                    for evidence in item.evidence
                ])
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise WorkGraphError("work graph projection integrity check failed")
        finally:
            connection.close()
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)


def apply_work_item(
    store: "LocalWorkspaceStore",
    plan: WorkGraphWritePlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> dict[str, object]:
    store.assert_plan_current(plan.record_plan)
    store.assert_plan_current(plan.event_plan)
    for effect in plan.effect_plans:
        authorization = authorizations.get(effect.plan_id)
        if authorization is None or authorization.plan.plan_id != effect.plan_id:
            raise WorkGraphError("work graph authorization is incomplete")
    stored = store.apply_put(plan.record_plan, authorizations[plan.record_plan.mutation.plan_id])
    store.apply_put(plan.event_plan, authorizations[plan.event_plan.mutation.plan_id])
    items = _project_items(store, plan.project_id)
    graph_digest = _digest([value.as_dict() for value in sorted(items, key=lambda value: value.work_item_id)])
    if graph_digest != plan.graph_digest:
        raise WorkGraphError("work graph changed before projection")
    _write_projection(work_graph_index_path(store.data_root, plan.project_id), items, graph_digest)
    return {
        "project_id": plan.project_id,
        "work_item_id": plan.item.work_item_id,
        "record_revision": stored.revision,
        "status": plan.item.status,
        "graph_digest": graph_digest,
        "projection_updated": True,
    }


def query_work_graph(store: "LocalWorkspaceStore", arguments: Mapping[str, object]) -> dict[str, object]:
    allowed = {"project_id", "statuses", "work_types", "text", "limit", "work_item_id"}
    if set(arguments) - allowed:
        raise WorkGraphError("work query contains unsupported fields")
    project_id = str(arguments.get("project_id", ""))
    if not IDENTIFIER.fullmatch(project_id):
        raise WorkGraphError("work query project id is invalid")
    statuses = set(arguments.get("statuses", []))
    work_types = set(arguments.get("work_types", []))
    if not statuses.issubset(STATUSES) or not work_types.issubset(WORK_TYPES):
        raise WorkGraphError("work query filters are invalid")
    text = str(arguments.get("text", "")).casefold().strip()
    item_id = arguments.get("work_item_id")
    if item_id is not None and (not isinstance(item_id, str) or not IDENTIFIER.fullmatch(item_id)):
        raise WorkGraphError("work query item id is invalid")
    limit = arguments.get("limit", 50)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 500:
        raise WorkGraphError("work query limit is invalid")
    items = []
    for item in _project_items(store, project_id):
        if statuses and item.status not in statuses:
            continue
        if work_types and item.work_type not in work_types:
            continue
        if item_id is not None and item.work_item_id != item_id:
            continue
        haystack = f"{item.work_item_id} {item.title} {item.description}".casefold()
        if text and text not in haystack:
            continue
        items.append(item)
    items.sort(key=lambda value: (value.status not in ACTIVE_STATUSES, value.work_item_id))
    selected = items[:limit]
    return {
        "schema_ref": "schemas/work-graph-result.schema.json",
        "schema_version": 1,
        "project_id": project_id,
        "active_count": sum(item.status in ACTIVE_STATUSES for item in items),
        "matched_count": len(items),
        "items": [item.as_dict() for item in selected],
        "authoritative_status": True,
        "paths_disclosed": False,
        "result_digest": _digest([item.as_dict() for item in selected]),
    }


def query_work_history(
    store: "LocalWorkspaceStore",
    arguments: Mapping[str, object],
) -> dict[str, object]:
    if set(arguments) != {"project_id", "work_item_id"}:
        raise WorkGraphError("work history requires project_id and work_item_id")
    project_id = str(arguments.get("project_id", ""))
    work_item_id = str(arguments.get("work_item_id", ""))
    if not IDENTIFIER.fullmatch(project_id) or not IDENTIFIER.fullmatch(work_item_id):
        raise WorkGraphError("work history identity is invalid")
    events = tuple(sorted(
        (
            event for event in (
                parse_work_event(record.payload)
                for record in store.list_records("work-events")
            )
            if event.project_id == project_id and event.work_item_id == work_item_id
        ),
        key=lambda event: event.item_revision,
    ))
    return {
        "project_id": project_id,
        "work_item_id": work_item_id,
        "event_count": len(events),
        "events": [event.as_dict() for event in events],
        "authoritative_history": True,
        "history_digest": _digest([event.as_dict() for event in events]),
    }
