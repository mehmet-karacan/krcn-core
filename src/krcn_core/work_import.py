"""Atomic, idempotent batch import into the authoritative Work Graph."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping, Sequence

from .home_layout import project_capsule_root
from .json_documents import canonical_json_bytes, parse_json_bytes, pretty_json_bytes
from .local_store import LocalWorkspaceStore, RecordWritePlan
from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)
from .work_graph import (
    IDENTIFIER,
    TRANSITIONS,
    WorkItem,
    _project_items,
    _validate_graph,
    _write_projection,
    build_work_event,
    build_work_item,
    parse_work_item,
    work_graph_digest,
    work_graph_index_path,
)
from .work_index import (
    WorkIndexPlan,
    apply_work_index,
    assert_work_index_preflight,
    prepare_work_index_from_items,
    work_index_path,
)


SHA256 = re.compile(r"^[a-f0-9]{64}$")
WINDOWS_ABSOLUTE = re.compile(r"(?i)(?:^|[\s(\"'])[a-z]:[\\/]")
POSIX_ABSOLUTE = re.compile(
    r"(?:^|[\s(\"'])/(?:Users|home|tmp|var|etc|private|mnt|opt|srv|root)(?:/|$)"
)
SECRET_VALUE = re.compile(
    r"(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|github_pat_[A-Za-z0-9_]+|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|"
    r"(?:password|passwd|token|api[-_ ]?key|client[-_ ]?secret)\s*[:=]\s*[^\s,;]+|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
)
SENSITIVE_PATH_PARTS = {
    ".env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "secrets",
}


class WorkImportError(ValueError):
    """Raised when a legacy Work Graph import is unsafe, stale, or invalid."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _file_digest(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise WorkImportError("source file changed while inventory was being built")
    return digest.hexdigest()


def _portable_ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        raise WorkImportError(f"{label} must be a non-empty portable reference")
    candidate = value.strip()
    posix = PurePosixPath(candidate)
    if (
        posix.is_absolute()
        or PureWindowsPath(candidate).is_absolute()
        or ".." in posix.parts
        or WINDOWS_ABSOLUTE.search(candidate)
        or POSIX_ABSOLUTE.search(candidate)
        or candidate.lower().startswith("file:")
    ):
        raise WorkImportError(f"{label} may not contain an absolute path")
    if SECRET_VALUE.search(candidate):
        raise WorkImportError(f"{label} may not contain a secret value")
    return posix.as_posix()


def _safe_text(value: object, label: str, *, non_empty: bool = False) -> str:
    if not isinstance(value, str) or (non_empty and not value.strip()):
        raise WorkImportError(f"{label} is invalid")
    if WINDOWS_ABSOLUTE.search(value) or POSIX_ABSOLUTE.search(value):
        raise WorkImportError(f"{label} may not contain an absolute path")
    if SECRET_VALUE.search(value):
        raise WorkImportError(f"{label} may not contain a secret value")
    return value


@dataclass(frozen=True)
class WorkSourceEntry:
    source_ref: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class WorkSourceInventory:
    source_id: str
    logical_root: str
    entries: tuple[WorkSourceEntry, ...]
    inventory_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "logical_root": self.logical_root,
            "entries": [entry.as_dict() for entry in self.entries],
            "inventory_digest": self.inventory_digest,
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "logical_root": self.logical_root,
            "entry_count": len(self.entries),
            "inventory_digest": self.inventory_digest,
            "paths_disclosed": False,
        }


def _inventory_identity(
    source_id: str,
    logical_root: str,
    entries: Sequence[WorkSourceEntry],
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "logical_root": logical_root,
        "entries": [entry.as_dict() for entry in entries],
    }


def inventory_work_source(
    source_root: Path,
    *,
    source_id: str,
    logical_root: str,
) -> WorkSourceInventory:
    """Hash a legacy tree without retaining its physical location or contents."""

    if not IDENTIFIER.fullmatch(source_id):
        raise WorkImportError("source id must be portable")
    logical = _portable_ref(logical_root, "logical root")
    root = source_root.resolve(strict=False)
    if source_root.is_symlink() or not root.is_dir():
        raise WorkImportError("source root must be a regular directory")
    entries: list[WorkSourceEntry] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            raise WorkImportError("source inventory may not follow symbolic links")
        if path.is_dir():
            continue
        if not path.is_file():
            raise WorkImportError("source inventory contains a non-regular file")
        relative = path.relative_to(root).as_posix()
        lowered = {part.casefold() for part in PurePosixPath(relative).parts}
        if lowered & SENSITIVE_PATH_PARTS or any(
            part.startswith(".env.")
            or part.endswith((".pem", ".p12", ".pfx"))
            or "credential" in part
            for part in lowered
        ):
            raise WorkImportError("source inventory contains a sensitive path")
        reference = _portable_ref(f"{logical}/{relative}", "source reference")
        entries.append(WorkSourceEntry(reference, _file_digest(path), path.stat().st_size))
    identity = _inventory_identity(source_id, logical, entries)
    return WorkSourceInventory(source_id, logical, tuple(entries), _digest(identity))


def parse_source_inventory(payload: object) -> WorkSourceInventory:
    expected = {"source_id", "logical_root", "entries", "inventory_digest"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkImportError("source inventory fields are invalid")
    source_id = payload.get("source_id")
    if not isinstance(source_id, str) or not IDENTIFIER.fullmatch(source_id):
        raise WorkImportError("source inventory id is invalid")
    logical_root = _portable_ref(payload.get("logical_root"), "logical root")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise WorkImportError("source inventory entries are invalid")
    entries: list[WorkSourceEntry] = []
    seen: set[str] = set()
    prefix = logical_root.rstrip("/") + "/"
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != {"source_ref", "sha256", "size_bytes"}:
            raise WorkImportError("source inventory entry fields are invalid")
        source_ref = _portable_ref(raw.get("source_ref"), "source reference")
        sha256 = raw.get("sha256")
        size = raw.get("size_bytes")
        if not source_ref.startswith(prefix) or source_ref in seen:
            raise WorkImportError("source inventory reference is outside its logical root or duplicated")
        if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
            raise WorkImportError("source inventory digest is invalid")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise WorkImportError("source inventory size is invalid")
        seen.add(source_ref)
        entries.append(WorkSourceEntry(source_ref, sha256, size))
    if [entry.source_ref for entry in entries] != sorted(seen):
        raise WorkImportError("source inventory entries must be sorted")
    inventory = WorkSourceInventory(source_id, logical_root, tuple(entries), str(payload.get("inventory_digest", "")))
    expected_digest = _digest(_inventory_identity(source_id, logical_root, entries))
    if not hmac.compare_digest(inventory.inventory_digest, expected_digest):
        raise WorkImportError("source inventory digest does not match")
    return inventory


@dataclass(frozen=True)
class WorkImportCandidate:
    work_item_id: str
    work_type: str
    title: str
    description: str
    status: str
    acceptance_criteria: tuple[str, ...]
    relations: tuple[Mapping[str, str], ...]
    evidence: tuple[Mapping[str, object], ...]
    source_ref: str

    def intent_dict(self) -> dict[str, object]:
        return {
            "work_item_id": self.work_item_id,
            "work_type": self.work_type,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "acceptance_criteria": list(self.acceptance_criteria),
            "relations": [dict(value) for value in self.relations],
            "evidence": [dict(value) for value in self.evidence],
            "source_ref": self.source_ref,
        }


def _parse_candidate(
    payload: object,
    *,
    project_id: str,
    inventory_refs: set[str],
) -> WorkImportCandidate:
    expected = {
        "work_item_id", "work_type", "title", "description", "status",
        "acceptance_criteria", "relations", "evidence", "source_ref",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkImportError("work import candidate fields are invalid")
    work_item_id = payload.get("work_item_id")
    if (
        not isinstance(work_item_id, str)
        or not IDENTIFIER.fullmatch(work_item_id)
        or not work_item_id.startswith(project_id + "-")
    ):
        raise WorkImportError("work import candidate id must be project-scoped")
    title = _safe_text(payload.get("title"), "candidate title", non_empty=True)
    description = _safe_text(payload.get("description"), "candidate description")
    source_ref = _portable_ref(payload.get("source_ref"), "candidate source reference")
    if source_ref not in inventory_refs:
        raise WorkImportError("candidate source reference was not found in the inventory")
    acceptance = payload.get("acceptance_criteria")
    relations = payload.get("relations")
    evidence = payload.get("evidence")
    if not isinstance(acceptance, list) or any(
        not isinstance(value, str) or not value.strip() for value in acceptance
    ):
        raise WorkImportError("candidate acceptance criteria are invalid")
    safe_acceptance = tuple(
        _safe_text(value, "acceptance criterion", non_empty=True) for value in acceptance
    )
    if not isinstance(relations, list) or not isinstance(evidence, list):
        raise WorkImportError("candidate relations or evidence are invalid")
    safe_relations: list[Mapping[str, str]] = []
    for value in relations:
        if not isinstance(value, dict) or set(value) != {"relation_type", "target_ref"}:
            raise WorkImportError("candidate relation fields are invalid")
        target = value.get("target_ref")
        if not isinstance(target, str) or not IDENTIFIER.fullmatch(target):
            raise WorkImportError("candidate relation target is invalid")
        safe_relations.append({"relation_type": str(value.get("relation_type")), "target_ref": target})
    safe_evidence: list[Mapping[str, object]] = []
    for value in evidence:
        if not isinstance(value, dict) or set(value) != {"evidence_type", "reference", "digest", "label"}:
            raise WorkImportError("candidate evidence fields are invalid")
        reference = _portable_ref(value.get("reference"), "evidence reference")
        label = _safe_text(value.get("label"), "evidence label", non_empty=True)
        safe_evidence.append({
            "evidence_type": value.get("evidence_type"),
            "reference": reference,
            "digest": value.get("digest"),
            "label": label,
        })
    candidate = WorkImportCandidate(
        work_item_id=work_item_id,
        work_type=str(payload.get("work_type", "")),
        title=title,
        description=description,
        status=str(payload.get("status", "")),
        acceptance_criteria=safe_acceptance,
        relations=tuple(safe_relations),
        evidence=tuple(safe_evidence),
        source_ref=source_ref,
    )
    # Reuse WorkItem v1 as the authoritative validator before planning revisions.
    build_work_item({
        **candidate.intent_dict(),
        "project_id": project_id,
        "provenance": {"source_kind": "import", "source_ref": source_ref},
    }, 1)
    return candidate


def parse_work_import_request(
    payload: object,
) -> tuple[str, WorkSourceInventory, tuple[WorkImportCandidate, ...]]:
    expected = {"schema_ref", "schema_version", "project_id", "source_inventory", "candidates"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkImportError("work import request fields are invalid")
    if payload.get("schema_ref") != "schemas/work-import-request.schema.json" or payload.get("schema_version") != 1:
        raise WorkImportError("work import request header is invalid")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id):
        raise WorkImportError("work import project id is invalid")
    inventory = parse_source_inventory(payload.get("source_inventory"))
    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise WorkImportError("work import requires at least one candidate")
    inventory_refs = {entry.source_ref for entry in inventory.entries}
    candidates = tuple(
        sorted(
            (
                _parse_candidate(value, project_id=project_id, inventory_refs=inventory_refs)
                for value in raw_candidates
            ),
            key=lambda value: value.work_item_id,
        )
    )
    ids = [candidate.work_item_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise WorkImportError("work import candidate ids are duplicated")
    return project_id, inventory, candidates


def _manifest_path(data_root: Path, project_id: str, import_id: str) -> Path:
    return project_capsule_root(data_root, project_id) / "work" / "imports" / f"{import_id}.json"


def _target_ref(data_root: Path, target: Path) -> str:
    return ".krcn/" + target.relative_to(data_root.resolve(strict=False)).as_posix()


def _manifest_digest(payload: Mapping[str, object]) -> str:
    identity = dict(payload)
    identity.pop("manifest_digest", None)
    return _digest(identity)


def _parse_manifest(payload: object) -> Mapping[str, object]:
    expected = {
        "schema_ref", "schema_version", "import_id", "project_id",
        "import_digest", "source_id", "logical_root", "source_inventory_digest",
        "graph_digest_before", "graph_digest_after", "items", "status",
        "manifest_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise WorkImportError("work import manifest fields are invalid")
    if payload.get("schema_ref") != "schemas/work-import-manifest.schema.json" or payload.get("schema_version") != 1:
        raise WorkImportError("work import manifest header is invalid")
    for field in ("import_id", "project_id", "source_id"):
        if not isinstance(payload.get(field), str) or not IDENTIFIER.fullmatch(str(payload[field])):
            raise WorkImportError("work import manifest identity is invalid")
    for field in ("import_digest", "source_inventory_digest", "graph_digest_before", "graph_digest_after", "manifest_digest"):
        if not isinstance(payload.get(field), str) or not SHA256.fullmatch(str(payload[field])):
            raise WorkImportError("work import manifest digest is invalid")
    _portable_ref(payload.get("logical_root"), "manifest logical root")
    if payload.get("status") != "applied" or not isinstance(payload.get("items"), list):
        raise WorkImportError("work import manifest status or items are invalid")
    for item in payload["items"]:
        if not isinstance(item, dict) or set(item) != {"work_item_id", "revision", "work_digest", "source_ref"}:
            raise WorkImportError("work import manifest item fields are invalid")
        if not isinstance(item.get("work_item_id"), str) or not IDENTIFIER.fullmatch(item["work_item_id"]):
            raise WorkImportError("work import manifest item id is invalid")
        if not isinstance(item.get("revision"), int) or isinstance(item.get("revision"), bool) or item["revision"] < 1:
            raise WorkImportError("work import manifest item revision is invalid")
        if not isinstance(item.get("work_digest"), str) or not SHA256.fullmatch(item["work_digest"]):
            raise WorkImportError("work import manifest item digest is invalid")
        _portable_ref(item.get("source_ref"), "manifest source reference")
    if not hmac.compare_digest(str(payload["manifest_digest"]), _manifest_digest(payload)):
        raise WorkImportError("work import manifest digest does not match")
    return payload


def _read_manifest(path: Path) -> Mapping[str, object] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise WorkImportError("work import manifest must be a regular file")
    try:
        payload = parse_json_bytes(path.read_bytes(), label="work import manifest")
    except ValueError as exc:
        raise WorkImportError(str(exc)) from exc
    return _parse_manifest(payload)


def _manifest_effects_exist(store: LocalWorkspaceStore, manifest: Mapping[str, object]) -> bool:
    for item in manifest["items"]:
        current = store.read("work-items", str(item["work_item_id"]))
        if current is None or current.revision < item["revision"]:
            return False
        if current.revision == item["revision"] and current.payload.get("work_digest") != item["work_digest"]:
            return False
        event_id = f"{item['work_item_id']}-r{item['revision']}"
        event = store.read("work-events", event_id)
        if event is None or event.payload.get("item_digest") != item["work_digest"]:
            return False
    return True


def _projection_state(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, None
    if path.is_symlink() or not path.is_file():
        raise WorkImportError("work graph projection must be a regular file")
    return True, _file_digest(path)


@dataclass(frozen=True)
class WorkImportPlan:
    project_id: str
    import_id: str
    import_digest: str
    source_inventory: WorkSourceInventory
    items: tuple[WorkItem, ...]
    item_plans: tuple[RecordWritePlan, ...]
    event_plans: tuple[RecordWritePlan, ...]
    projection_mutation: MutationPlan | None
    projection_existed: bool
    projection_before_digest: str | None
    readable_index_plan: WorkIndexPlan | None
    manifest_payload: Mapping[str, object]
    manifest_mutation: MutationPlan | None
    graph_digest_before: str
    graph_digest_after: str
    no_op: bool
    plan_id: str
    repo_root: Path

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        if self.no_op:
            return ()
        assert self.projection_mutation is not None
        assert self.manifest_mutation is not None
        assert self.readable_index_plan is not None
        return tuple(
            [plan.mutation for plan in self.item_plans]
            + [plan.mutation for plan in self.event_plans]
            + [self.projection_mutation]
            + list(self.readable_index_plan.effect_plans)
            + [self.manifest_mutation]
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-import-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "import_id": self.import_id,
            "import_digest": self.import_digest,
            "source_inventory": self.source_inventory.public_summary(),
            "graph_digest_before": self.graph_digest_before,
            "graph_digest_after": self.graph_digest_after,
            "readable_index": (
                None
                if self.readable_index_plan is None
                else self.readable_index_plan.public_summary()
            ),
            "no_op": self.no_op,
            "item_count": len(self.manifest_payload["items"]),
            "work_item_ids": [item["work_item_id"] for item in self.manifest_payload["items"]],
            "effect_plans": [effect.as_dict() for effect in self.effect_plans],
            "paths_disclosed": False,
        }


def prepare_work_import(
    store: LocalWorkspaceStore,
    ownership: OwnershipResolver,
    request: Mapping[str, object],
    *,
    repo_root: Path | None = None,
) -> WorkImportPlan:
    resolved_repo_root = (
        Path(__file__).resolve().parents[2]
        if repo_root is None
        else repo_root.resolve()
    )
    project_id, inventory, candidates = parse_work_import_request(dict(request))
    if store.read("projects", project_id) is None:
        raise WorkImportError("work import project is not registered")
    intent = {
        "project_id": project_id,
        "source_id": inventory.source_id,
        "logical_root": inventory.logical_root,
        "source_inventory_digest": inventory.inventory_digest,
        "candidates": [candidate.intent_dict() for candidate in candidates],
    }
    import_digest = _digest(intent)
    import_id = f"work-import-{import_digest[:24]}"
    manifest_path = _manifest_path(store.data_root, project_id, import_id)
    existing_manifest = _read_manifest(manifest_path)
    current_graph_digest = work_graph_digest(store, project_id)
    if existing_manifest is not None:
        if existing_manifest.get("import_digest") != import_digest:
            raise WorkImportError("work import manifest identity collision")
        if not _manifest_effects_exist(store, existing_manifest):
            raise WorkImportError("work import manifest exists but its effects are incomplete")
        plan_id = _digest({
            "import_digest": import_digest,
            "status": "already-applied",
            "graph_digest": current_graph_digest,
        })
        return WorkImportPlan(
            project_id, import_id, import_digest, inventory, (), (), (), None,
            False, None, None, existing_manifest, None, current_graph_digest,
            current_graph_digest, True, plan_id, resolved_repo_root,
        )

    existing_items = {item.work_item_id: item for item in _project_items(store, project_id)}
    planned_items: list[WorkItem] = []
    previous_items: dict[str, WorkItem | None] = {}
    for candidate in candidates:
        current_record = store.read("work-items", candidate.work_item_id)
        previous = parse_work_item(current_record.payload) if current_record else None
        if previous is not None and previous.project_id != project_id:
            raise WorkImportError("work import candidate id belongs to another project")
        arguments = {
            **candidate.intent_dict(),
            "project_id": project_id,
            "provenance": {"source_kind": "import", "source_ref": candidate.source_ref},
        }
        item = build_work_item(arguments, (current_record.revision + 1) if current_record else 1)
        if previous is not None and item.status not in TRANSITIONS[previous.status]:
            raise WorkImportError("work import status transition is invalid")
        if item.status == "completed" and not item.evidence:
            raise WorkImportError("completed imported work item requires evidence")
        planned_items.append(item)
        previous_items[item.work_item_id] = previous

    merged = dict(existing_items)
    merged.update({item.work_item_id: item for item in planned_items})
    known_ids = set(merged)
    if any(
        relation.target_ref not in known_ids
        for item in merged.values()
        for relation in item.relations
    ):
        raise WorkImportError("work import relation target was not found in the project or batch")
    _validate_graph(tuple(merged.values()))
    graph_after = _digest([
        item.as_dict() for item in sorted(merged.values(), key=lambda value: value.work_item_id)
    ])

    item_plans: list[RecordWritePlan] = []
    event_plans: list[RecordWritePlan] = []
    for item in planned_items:
        previous = previous_items[item.work_item_id]
        item_plans.append(store.prepare_put(
            "work-items", item.work_item_id, item.as_dict(),
            expected_revision=previous.revision if previous else 0,
            project_id=project_id,
        ))
        event = build_work_event(item, previous.status if previous else None)
        event_plans.append(store.prepare_put(
            "work-events", event.work_event_id, event.as_dict(),
            expected_revision=0,
            project_id=project_id,
        ))

    projection_path = work_graph_index_path(store.data_root, project_id)
    projection_existed, projection_before_digest = _projection_state(projection_path)
    projection_mutation = plan_mutation(
        ownership,
        operation="update" if projection_existed else "create",
        target_ref=_target_ref(store.data_root, projection_path),
        expected_ownership="derived",
        change_digest=graph_after,
        reversible=True,
    )
    readable_index = prepare_work_index_from_items(
        resolved_repo_root,
        store,
        ownership,
        project_id,
        tuple(merged.values()),
        graph_after,
    )
    manifest_payload: dict[str, object] = {
        "schema_ref": "schemas/work-import-manifest.schema.json",
        "schema_version": 1,
        "import_id": import_id,
        "project_id": project_id,
        "import_digest": import_digest,
        "source_id": inventory.source_id,
        "logical_root": inventory.logical_root,
        "source_inventory_digest": inventory.inventory_digest,
        "graph_digest_before": current_graph_digest,
        "graph_digest_after": graph_after,
        "items": [
            {
                "work_item_id": item.work_item_id,
                "revision": item.revision,
                "work_digest": item.work_digest,
                "source_ref": item.provenance["source_ref"],
            }
            for item in planned_items
        ],
        "status": "applied",
    }
    manifest_payload["manifest_digest"] = _manifest_digest(manifest_payload)
    _parse_manifest(manifest_payload)
    manifest_mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=_target_ref(store.data_root, manifest_path),
        expected_ownership="user-data",
        change_digest=str(manifest_payload["manifest_digest"]),
        reversible=True,
    )
    effects = (
        [plan.mutation.as_dict() for plan in item_plans]
        + [plan.mutation.as_dict() for plan in event_plans]
        + [projection_mutation.as_dict()]
        + [effect.as_dict() for effect in readable_index.effect_plans]
        + [manifest_mutation.as_dict()]
    )
    plan_id = _digest({
        "import_digest": import_digest,
        "graph_digest_before": current_graph_digest,
        "graph_digest_after": graph_after,
        "effects": effects,
    })
    return WorkImportPlan(
        project_id, import_id, import_digest, inventory, tuple(planned_items),
        tuple(item_plans), tuple(event_plans), projection_mutation,
        projection_existed, projection_before_digest, readable_index,
        manifest_payload, manifest_mutation, current_graph_digest, graph_after,
        False, plan_id, resolved_repo_root,
    )


def _validate_authorizations(
    plan: WorkImportPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> None:
    if set(authorizations) != {effect.plan_id for effect in plan.effect_plans}:
        raise WorkImportError("work import authorization set is incomplete or contains extras")
    for effect in plan.effect_plans:
        authorization = authorizations[effect.plan_id]
        if authorization.plan != effect or not authorization.dry_run_verified:
            raise WorkImportError("work import authorization does not match its effect")
        if effect.approval_required and not authorization.approval_verified:
            raise WorkImportError("work import effect requires user approval")


def _atomic_write(path: Path, document: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise WorkImportError("work import target may not use symbolic links")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(document)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _snapshot_targets(paths: Sequence[Path]) -> dict[Path, bytes | None]:
    snapshots: dict[Path, bytes | None] = {}
    for path in paths:
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise WorkImportError("work import target must be a regular file")
            snapshots[path] = path.read_bytes()
        else:
            snapshots[path] = None
    return snapshots


def _restore_targets(snapshots: Mapping[Path, bytes | None]) -> None:
    failures: list[str] = []
    for path, document in reversed(tuple(snapshots.items())):
        try:
            if document is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, document)
        except OSError:
            failures.append(path.name)
    if failures:
        raise WorkImportError("work import rollback could not restore every target")


@dataclass(frozen=True)
class WorkImportResult:
    project_id: str
    import_id: str
    import_digest: str
    status: str
    item_count: int
    work_item_ids: tuple[str, ...]
    graph_digest: str
    projection_updated: bool
    readable_index_updated: bool
    manifest_recorded: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-import-result.schema.json",
            "schema_version": 1,
            "project_id": self.project_id,
            "import_id": self.import_id,
            "import_digest": self.import_digest,
            "status": self.status,
            "item_count": self.item_count,
            "work_item_ids": list(self.work_item_ids),
            "graph_digest": self.graph_digest,
            "projection_updated": self.projection_updated,
            "readable_index_updated": self.readable_index_updated,
            "manifest_recorded": self.manifest_recorded,
            "paths_disclosed": False,
        }


def apply_work_import(
    store: LocalWorkspaceStore,
    plan: WorkImportPlan,
    authorizations: Mapping[str, MutationAuthorization],
    *,
    expected_plan_id: str,
    current_source_inventory: Mapping[str, object],
) -> WorkImportResult:
    """Apply one exact batch, rolling back every touched target on failure."""

    if not hmac.compare_digest(plan.plan_id, expected_plan_id):
        raise WorkImportError("work import approval does not match the exact plan")
    current_inventory = parse_source_inventory(dict(current_source_inventory))
    if not hmac.compare_digest(current_inventory.inventory_digest, plan.source_inventory.inventory_digest):
        raise WorkImportError("work import source inventory changed after planning")
    if plan.no_op:
        return WorkImportResult(
            plan.project_id, plan.import_id, plan.import_digest, "already-applied",
            len(plan.manifest_payload["items"]),
            tuple(item["work_item_id"] for item in plan.manifest_payload["items"]),
            plan.graph_digest_after, False, False, True,
        )
    if work_graph_digest(store, plan.project_id) != plan.graph_digest_before:
        raise WorkImportError("work graph changed after import planning")
    for record_plan in (*plan.item_plans, *plan.event_plans):
        store.assert_plan_current(record_plan)
    projection_path = work_graph_index_path(store.data_root, plan.project_id)
    projection_existed, projection_digest = _projection_state(projection_path)
    if (
        projection_existed != plan.projection_existed
        or projection_digest != plan.projection_before_digest
    ):
        raise WorkImportError("work graph projection changed after import planning")
    manifest_path = _manifest_path(store.data_root, plan.project_id, plan.import_id)
    if manifest_path.exists():
        raise WorkImportError("work import manifest appeared after planning")
    assert plan.readable_index_plan is not None
    assert_work_index_preflight(
        plan.repo_root,
        store,
        plan.readable_index_plan,
    )
    _validate_authorizations(plan, authorizations)
    targets = [
        *(record_plan.target for record_plan in plan.item_plans),
        *(record_plan.target for record_plan in plan.event_plans),
        projection_path,
        work_index_path(store.data_root, plan.project_id),
        manifest_path,
    ]
    snapshots = _snapshot_targets(targets)
    try:
        for record_plan in plan.item_plans:
            store.apply_put(record_plan, authorizations[record_plan.mutation.plan_id])
        for record_plan in plan.event_plans:
            store.apply_put(record_plan, authorizations[record_plan.mutation.plan_id])
        items = _project_items(store, plan.project_id)
        actual_graph_digest = _digest([
            item.as_dict() for item in sorted(items, key=lambda value: value.work_item_id)
        ])
        if actual_graph_digest != plan.graph_digest_after:
            raise WorkImportError("work graph changed during batch apply")
        _write_projection(projection_path, items, actual_graph_digest)
        assert plan.readable_index_plan is not None
        index_authorization = (
            None
            if plan.readable_index_plan.mutation is None
            else authorizations[plan.readable_index_plan.mutation.plan_id]
        )
        index_result = apply_work_index(
            plan.repo_root,
            store,
            OwnershipResolver.from_repository(plan.repo_root),
            plan.readable_index_plan,
            index_authorization,
            expected_plan_id=plan.readable_index_plan.plan_id,
        )
        _atomic_write(manifest_path, pretty_json_bytes(plan.manifest_payload))
        stored_manifest = _read_manifest(manifest_path)
        if stored_manifest is None or stored_manifest.get("import_digest") != plan.import_digest:
            raise WorkImportError("work import manifest verification failed")
    except Exception as exc:
        try:
            _restore_targets(snapshots)
        except WorkImportError as rollback_exc:
            raise WorkImportError("work import failed and rollback was incomplete") from rollback_exc
        if isinstance(exc, WorkImportError):
            raise
        raise WorkImportError("work import failed and was rolled back") from exc
    return WorkImportResult(
        plan.project_id, plan.import_id, plan.import_digest, "applied",
        len(plan.items), tuple(item.work_item_id for item in plan.items),
        plan.graph_digest_after, True, index_result["status"] == "applied", True,
    )
