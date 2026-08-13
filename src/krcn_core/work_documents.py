"""Project-local request, defect, and task document ingestion.

Original documents are preserved below project ``local-data``.  Work Graph
records only retain portable references and digests.  Derived semantic indexes
remain separate and rebuildable.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from .foundation import detect_content_findings
from .home_layout import project_capsule_root
from .json_documents import canonical_json_bytes, parse_json_bytes, pretty_json_bytes
from .local_store import LocalWorkspaceStore
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .work_graph import WorkItem, parse_work_item
from .work_import import WorkImportPlan, WorkSourceEntry, prepare_work_import


SHA256 = re.compile(r"^[a-f0-9]{64}$")
YEAR = re.compile(r"^20[0-9]{2}$")
NUMBER = re.compile(r"(?<![0-9])([0-9]{4,})(?![0-9])")
TASK_ID = re.compile(r"(?i)(?:G|SC)-[0-9]{8}-[0-9]{3}")
TEXT_EXTENSIONS = {
    ".csv", ".html", ".json", ".jrxml", ".md", ".sql", ".txt", ".xml",
    ".yaml", ".yml",
}
SENSITIVE_DETECTORS = {
    "windows-absolute-path", "posix-user-path", "private-key", "github-token",
    "aws-access-key", "generic-secret-assignment", "credential-uri", "email-address",
    "ip-address",
}
BLOCKED_PARTS = {".git", ".idea", ".krcn", "node_modules", "__pycache__"}
MANIFEST_SCHEMA = "schemas/work-document-manifest.schema.json"


class WorkDocumentError(ValueError):
    """Raised when a document migration or processing plan is unsafe."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _file_digest(path: Path) -> str:
    before = path.stat()
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise WorkDocumentError("document source changed while it was being read")
    return value.hexdigest()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    result = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return result or "document"


def work_documents_root(data_root: Path, project_id: str) -> Path:
    return project_capsule_root(data_root, project_id) / "local-data" / "work-documents"


def _portable_target_ref(data_root: Path, target: Path) -> str:
    return ".krcn/" + target.relative_to(data_root.resolve(strict=False)).as_posix()


def _logical_ref(target_root: Path, target: Path) -> str:
    return "work-documents/" + target.relative_to(target_root).as_posix()


def _document_policy(path: Path, relative: str) -> tuple[str, tuple[str, ...]]:
    if path.suffix.casefold() not in TEXT_EXTENSIONS or path.stat().st_size > 1024 * 1024:
        return "metadata-only", ()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return "metadata-only", ("non-utf8",)
    findings = detect_content_findings(text, relative, SENSITIVE_DETECTORS)
    detector_ids = tuple(sorted({finding.code for finding in findings}))
    return ("excluded-sensitive" if detector_ids else "safe-text"), detector_ids


def _existing_work_maps(
    store: LocalWorkspaceStore,
    project_id: str,
) -> tuple[dict[str, WorkItem], dict[str, set[str]]]:
    items: dict[str, WorkItem] = {}
    digest_map: dict[str, set[str]] = {}
    for record in store.list_records("work-items"):
        item = parse_work_item(record.payload)
        if item.project_id != project_id:
            continue
        items[item.work_item_id] = item
        for evidence in item.evidence:
            if evidence.digest:
                digest_map.setdefault(evidence.digest, set()).add(item.work_item_id)
    return items, digest_map


def _inferred_work_ids(
    project_id: str,
    work_type: str,
    source_hint: str,
    known_ids: set[str],
) -> set[str]:
    result: set[str] = set()
    if work_type == "task":
        match = TASK_ID.search(source_hint)
        if match:
            prefix = f"{project_id}-task-{_slug(match.group(0))}"
            result.update(value for value in known_ids if value == prefix or value.startswith(prefix + "-variant-"))
        return result
    for external_id in NUMBER.findall(source_hint):
        candidate = f"{project_id}-{work_type}-item-{external_id}"
        if candidate in known_ids:
            result.add(candidate)
    if result:
        return result
    special = _slug(PurePosixPath(source_hint).parts[-1])
    candidate = f"{project_id}-{work_type}-{special}"
    if candidate in known_ids:
        result.add(candidate)
    return result


@dataclass(frozen=True)
class DocumentCopyEntry:
    source_path: Path
    source_id: str
    source_ref: str
    target_path: Path
    target_ref: str
    sha256: str
    size_bytes: int
    work_item_ids: tuple[str, ...]
    semantic_policy: str
    sensitivity_classes: tuple[str, ...]

    def manifest_dict(self) -> dict[str, object]:
        return {
            "target_ref": self.target_ref,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_id": self.source_id,
            "source_ref": self.source_ref,
            "work_item_ids": list(self.work_item_ids),
            "semantic_policy": self.semantic_policy,
            "sensitivity_classes": list(self.sensitivity_classes),
        }


def _target_for_db(root: Path, relative: PurePosixPath) -> tuple[Path, str, str]:
    parts = relative.parts
    if len(parts) < 3 or parts[0] not in {"Talep", "Defect"} or not YEAR.fullmatch(parts[1]):
        raise WorkDocumentError("DB_SCRIPTS document layout is not recognized")
    work_type = "request" if parts[0] == "Talep" else "defect"
    category = "requests" if work_type == "request" else "defects"
    folder = parts[2] if len(parts) > 3 else "unassigned"
    numbers = NUMBER.findall(folder)
    if work_type == "request" and len(numbers) > 1:
        base = root / "shared" / "requests" / parts[1] / "-".join(numbers)
    else:
        key = numbers[0] if numbers else _slug(folder)
        base = root / category / parts[1] / key
    tail = parts[3:] if len(parts) > 3 else (parts[2],)
    target = base / "source" / "db-scripts" / folder / Path(*tail)
    return target, work_type, "/".join(parts)


def _target_for_legacy(root: Path, relative: PurePosixPath) -> tuple[Path, str, str] | None:
    parts = relative.parts
    if not parts or parts[0] not in {"aktif", "arsiv"}:
        return None
    bucket = "active" if parts[0] == "aktif" else "archived"
    if len(parts) == 2 and relative.suffix.casefold() == ".md":
        task = TASK_ID.search(parts[1])
        key = _slug(task.group(0) if task else relative.stem)
        return root / "tasks" / bucket / key / "source" / "mk-hub" / parts[1], "task", "/".join(parts)
    if len(parts) < 4:
        return None
    match = re.fullmatch(r"(Talep|Defect)_(20[0-9]{2})", parts[1])
    if match is None:
        return None
    work_type = "request" if match.group(1) == "Talep" else "defect"
    category = "requests" if work_type == "request" else "defects"
    folder = parts[2]
    numbers = NUMBER.findall(folder + "/" + "/".join(parts[3:]))
    if work_type == "request" and len(set(numbers)) > 1 and "_" in folder:
        selected = list(dict.fromkeys(numbers))
        base = root / "shared" / "requests" / match.group(2) / "-".join(selected)
    else:
        key = numbers[0] if numbers else _slug(folder)
        base = root / category / match.group(2) / key
    target = base / "source" / "mk-hub" / folder / Path(*parts[3:])
    return target, work_type, "/".join(parts)


def _source_inventory(root: Path, source_id: str) -> tuple[tuple[Path, str, str, int], ...]:
    resolved = root.resolve(strict=False)
    if root.is_symlink() or not resolved.is_dir():
        raise WorkDocumentError("document source must be a regular directory")
    result = []
    for path in sorted(resolved.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            raise WorkDocumentError("document source may not contain symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(resolved).as_posix()
        if {part.casefold() for part in PurePosixPath(relative).parts} & BLOCKED_PARTS:
            continue
        result.append((path, relative, _file_digest(path), path.stat().st_size))
    return tuple(result)


@dataclass(frozen=True)
class WorkDocumentCopyPlan:
    project_id: str
    entries: tuple[DocumentCopyEntry, ...]
    source_inventory_digests: Mapping[str, str]
    manifest_payload: Mapping[str, object]
    effect_plans: tuple[MutationPlan, ...]
    manifest_path: Path
    plan_id: str
    no_op: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/work-document-copy-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "document_count": len(self.entries),
            "copy_count": len(self.effect_plans) - (0 if self.no_op else 1),
            "source_inventory_digests": dict(self.source_inventory_digests),
            "manifest_digest": self.manifest_payload["manifest_digest"],
            "work_item_link_count": sum(len(entry.work_item_ids) for entry in self.entries),
            "safe_text_count": sum(entry.semantic_policy == "safe-text" for entry in self.entries),
            "metadata_only_count": sum(entry.semantic_policy == "metadata-only" for entry in self.entries),
            "sensitive_excluded_count": sum(entry.semantic_policy == "excluded-sensitive" for entry in self.entries),
            "no_op": self.no_op,
            "source_files_modified": False,
            "source_files_deleted": False,
            "absolute_paths_persisted": False,
            "paths_disclosed": False,
        }


def _inventory_digest(values: Sequence[tuple[Path, str, str, int]], source_id: str) -> str:
    return _digest({
        "source_id": source_id,
        "entries": [
            {"source_ref": f"{source_id}/{relative}", "sha256": sha256, "size_bytes": size}
            for _, relative, sha256, size in values
        ],
    })


def prepare_initial_work_document_copy(
    store: LocalWorkspaceStore,
    ownership: OwnershipResolver,
    project_id: str,
    db_scripts_root: Path,
    legacy_root: Path,
) -> WorkDocumentCopyPlan:
    if store.read("projects", project_id) is None:
        raise WorkDocumentError("document project is not registered")
    target_root = work_documents_root(store.data_root, project_id)
    items, digest_map = _existing_work_maps(store, project_id)
    known_ids = set(items)
    db_values = _source_inventory(db_scripts_root, "db-scripts")
    legacy_values = _source_inventory(legacy_root, "mk-hub")
    db_digests = {value[2] for value in db_values}
    selected: list[DocumentCopyEntry] = []
    targets: dict[str, str] = {}

    def add(
        source_id: str,
        value: tuple[Path, str, str, int],
        mapped: tuple[Path, str, str] | None,
    ) -> None:
        if mapped is None:
            return
        source_path, relative, sha256, size = value
        target, work_type, hint = mapped
        target_key = target.relative_to(target_root).as_posix()
        prior = targets.get(target_key)
        if prior is not None:
            if prior != sha256:
                raise WorkDocumentError("two source documents resolve to the same target")
            return
        targets[target_key] = sha256
        work_ids = set(digest_map.get(sha256, set()))
        work_ids.update(_inferred_work_ids(project_id, work_type, hint, known_ids))
        policy, findings = _document_policy(source_path, relative)
        selected.append(DocumentCopyEntry(
            source_path=source_path,
            source_id=source_id,
            source_ref=f"{source_id}/{relative}",
            target_path=target,
            target_ref=_logical_ref(target_root, target),
            sha256=sha256,
            size_bytes=size,
            work_item_ids=tuple(sorted(work_ids)),
            semantic_policy=policy,
            sensitivity_classes=findings,
        ))

    for value in db_values:
        add("db-scripts", value, _target_for_db(target_root, PurePosixPath(value[1])))
    for value in legacy_values:
        if value[2] in db_digests:
            continue
        add("mk-hub", value, _target_for_legacy(target_root, PurePosixPath(value[1])))
    selected.sort(key=lambda value: value.target_ref)
    source_digests = {
        "db-scripts": _inventory_digest(db_values, "db-scripts"),
        "mk-hub": _inventory_digest(legacy_values, "mk-hub"),
    }
    manifest: dict[str, object] = {
        "schema_ref": MANIFEST_SCHEMA,
        "schema_version": 1,
        "project_id": project_id,
        "source_inventory_digests": source_digests,
        "entries": [entry.manifest_dict() for entry in selected],
        "source_files_copied": True,
        "source_files_modified": False,
        "source_files_deleted": False,
        "generated_content_separated": True,
        "absolute_paths_included": False,
    }
    manifest["manifest_digest"] = _digest(manifest)
    manifest_path = target_root / "_krcn" / "import-manifest.json"
    effects: list[MutationPlan] = []
    for entry in selected:
        if entry.target_path.exists():
            if entry.target_path.is_symlink() or _file_digest(entry.target_path) != entry.sha256:
                raise WorkDocumentError("existing document target differs from the approved source")
            continue
        effects.append(plan_mutation(
            ownership,
            operation="create",
            target_ref=_portable_target_ref(store.data_root, entry.target_path),
            expected_ownership="user-data",
            change_digest=entry.sha256,
            reversible=True,
        ))
    manifest_bytes = pretty_json_bytes(manifest)
    manifest_existing = manifest_path.read_bytes() if manifest_path.is_file() and not manifest_path.is_symlink() else None
    if manifest_path.exists() and manifest_existing is None:
        raise WorkDocumentError("document manifest target is not a regular file")
    if manifest_existing != manifest_bytes:
        effects.append(plan_mutation(
            ownership,
            operation="update" if manifest_existing is not None else "create",
            target_ref=_portable_target_ref(store.data_root, manifest_path),
            expected_ownership="user-data",
            change_digest=str(manifest["manifest_digest"]),
            reversible=True,
        ))
    plan_id = _digest({
        "project_id": project_id,
        "source_inventory_digests": source_digests,
        "manifest_digest": manifest["manifest_digest"],
        "effects": [effect.as_dict() for effect in effects],
    })
    return WorkDocumentCopyPlan(
        project_id, tuple(selected), source_digests, manifest, tuple(effects),
        manifest_path, plan_id, not effects,
    )


def _validate_authorizations(
    effects: Sequence[MutationPlan],
    authorizations: Mapping[str, MutationAuthorization],
) -> None:
    if set(authorizations) != {effect.plan_id for effect in effects}:
        raise WorkDocumentError("document copy authorization set is incomplete")
    for effect in effects:
        authorization = authorizations[effect.plan_id]
        if authorization.plan != effect or not authorization.dry_run_verified:
            raise WorkDocumentError("document copy authorization does not match its effect")
        if effect.approval_required and not authorization.approval_verified:
            raise WorkDocumentError("document copy requires matching user approval")


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise WorkDocumentError("document target may not use symbolic links")
    temporary_name: str | None = None
    try:
        with source.open("rb") as input_stream, tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as output_stream:
            temporary_name = output_stream.name
            while block := input_stream.read(1024 * 1024):
                output_stream.write(block)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def apply_initial_work_document_copy(
    plan: WorkDocumentCopyPlan,
    authorizations: Mapping[str, MutationAuthorization],
    *,
    expected_plan_id: str,
) -> dict[str, object]:
    if not hmac.compare_digest(plan.plan_id, expected_plan_id):
        raise WorkDocumentError("document copy approval does not match the exact plan")
    _validate_authorizations(plan.effect_plans, authorizations)
    if plan.no_op:
        return {"status": "already-applied", "document_count": len(plan.entries)}
    for entry in plan.entries:
        if _file_digest(entry.source_path) != entry.sha256:
            raise WorkDocumentError("document source changed after planning")
        if entry.target_path.exists() and _file_digest(entry.target_path) != entry.sha256:
            raise WorkDocumentError("document target changed after planning")
    created: list[Path] = []
    manifest_backup = plan.manifest_path.read_bytes() if plan.manifest_path.is_file() else None
    try:
        for entry in plan.entries:
            if entry.target_path.exists():
                continue
            _atomic_copy(entry.source_path, entry.target_path)
            if _file_digest(entry.target_path) != entry.sha256:
                raise WorkDocumentError("copied document digest verification failed")
            created.append(entry.target_path)
        plan.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        document = pretty_json_bytes(plan.manifest_payload)
        temporary = plan.manifest_path.with_suffix(".json.tmp")
        temporary.write_bytes(document)
        os.replace(temporary, plan.manifest_path)
    except Exception:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        if manifest_backup is None:
            plan.manifest_path.unlink(missing_ok=True)
        else:
            plan.manifest_path.write_bytes(manifest_backup)
        raise
    return {
        "status": "applied",
        "document_count": len(plan.entries),
        "copied_count": len(created),
        "manifest_digest": plan.manifest_payload["manifest_digest"],
        "source_files_modified": False,
        "source_files_deleted": False,
    }


def _read_manifest(path: Path) -> Mapping[str, object]:
    if not path.is_file() or path.is_symlink():
        raise WorkDocumentError("work document manifest is missing")
    payload = parse_json_bytes(path.read_bytes(), label="work document manifest")
    if not isinstance(payload, dict) or payload.get("schema_ref") != MANIFEST_SCHEMA:
        raise WorkDocumentError("work document manifest is invalid")
    digest = payload.get("manifest_digest")
    identity = dict(payload)
    identity.pop("manifest_digest", None)
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or digest != _digest(identity):
        raise WorkDocumentError("work document manifest digest does not match")
    return payload


def _local_work_identity(
    project_id: str,
    reference: str,
    known_ids: set[str],
) -> tuple[str, tuple[str, ...]]:
    parts = PurePosixPath(reference.removeprefix("work-documents/")).parts
    if len(parts) < 4:
        raise WorkDocumentError("incoming work document path is incomplete")
    if parts[0] in {"requests", "defects"}:
        work_type = "request" if parts[0] == "requests" else "defect"
        external_id = parts[2]
        if external_id.isdigit():
            work_id = f"{project_id}-{work_type}-item-{external_id}"
        else:
            work_id = f"{project_id}-{work_type}-{_slug(external_id)}"
        return work_type, (work_id,)
    if parts[:2] == ("shared", "requests") and len(parts) >= 5:
        identifiers = tuple(dict.fromkeys(NUMBER.findall(parts[3])))
        if not identifiers:
            raise WorkDocumentError("shared request path requires request identities")
        return "request", tuple(
            f"{project_id}-request-item-{external_id}"
            for external_id in identifiers
        )
    if parts[0] == "tasks":
        key = _slug(parts[2])
        prefix = f"{project_id}-task-{key}"
        matches = tuple(sorted(
            value for value in known_ids
            if value == prefix or value.startswith(prefix + "-variant-")
        ))
        if len(matches) > 1:
            raise WorkDocumentError(
                "incoming task document matches multiple preserved task variants"
            )
        return "task", matches or (prefix,)
    raise WorkDocumentError("incoming document is outside the supported work layout")


def prepare_work_document_processing(
    store: LocalWorkspaceStore,
    ownership: OwnershipResolver,
    project_id: str,
) -> tuple[WorkImportPlan | None, Mapping[str, object]]:
    root = work_documents_root(store.data_root, project_id)
    manifest = _read_manifest(root / "_krcn" / "import-manifest.json")
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        raise WorkDocumentError("work document manifest entries are invalid")
    files: list[WorkSourceEntry] = []
    by_work: dict[str, list[Mapping[str, object]]] = {}
    work_types: dict[str, str] = {}
    known_references: set[str] = set()
    current_items, _ = _existing_work_maps(store, project_id)
    known_ids = set(current_items)
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise WorkDocumentError("work document manifest entry is invalid")
        reference = raw.get("target_ref")
        digest = raw.get("sha256")
        size = raw.get("size_bytes")
        if not isinstance(reference, str) or not reference.startswith("work-documents/"):
            raise WorkDocumentError("work document reference is invalid")
        if reference in known_references:
            raise WorkDocumentError("work document manifest reference is duplicated")
        known_references.add(reference)
        relative = reference.removeprefix("work-documents/")
        path = root / Path(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink() or _file_digest(path) != digest:
            raise WorkDocumentError("work document differs from its manifest")
        files.append(WorkSourceEntry(reference, str(digest), int(size)))
        for work_id in raw.get("work_item_ids", []):
            if isinstance(work_id, str):
                by_work.setdefault(work_id, []).append(raw)
                current = current_items.get(work_id)
                if current is not None:
                    work_types[work_id] = current.work_type
    incoming_count = 0
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            raise WorkDocumentError("work documents may not contain symbolic links")
        if not path.is_file() or "_krcn" in {
            part.casefold() for part in path.relative_to(root).parts
        }:
            continue
        reference = _logical_ref(root, path)
        if reference in known_references:
            continue
        work_type, work_ids = _local_work_identity(
            project_id, reference, known_ids,
        )
        digest = _file_digest(path)
        policy, findings = _document_policy(
            path, reference.removeprefix("work-documents/"),
        )
        raw = {
            "target_ref": reference,
            "sha256": digest,
            "size_bytes": path.stat().st_size,
            "source_id": "user",
            "source_ref": reference,
            "work_item_ids": list(work_ids),
            "semantic_policy": policy,
            "sensitivity_classes": list(findings),
        }
        known_references.add(reference)
        files.append(WorkSourceEntry(reference, digest, path.stat().st_size))
        incoming_count += 1
        for work_id in work_ids:
            by_work.setdefault(work_id, []).append(raw)
            work_types[work_id] = work_type
    files.sort(key=lambda value: value.source_ref)
    inventory_identity = {
        "source_id": f"{project_id}-work-documents",
        "logical_root": "work-documents",
        "entries": [value.as_dict() for value in files],
    }
    inventory = {**inventory_identity, "inventory_digest": _digest(inventory_identity)}
    candidates = []
    for work_id, documents in sorted(by_work.items()):
        current = current_items.get(work_id)
        preserved = [] if current is None else [
            value.as_dict() for value in current.evidence
            if not value.reference.startswith("legacy-work/")
            and not value.reference.startswith("work-documents/")
        ]
        document_evidence = [
            {
                "evidence_type": "document",
                "reference": str(value["target_ref"]),
                "digest": str(value["sha256"]),
                "label": "Yerel iş belgesi",
            }
            for value in documents
        ]
        evidence = sorted(
            { (str(value["evidence_type"]), str(value["reference"])): value for value in preserved + document_evidence }.values(),
            key=lambda value: (str(value["evidence_type"]), str(value["reference"])),
        )
        source_ref = str(sorted(documents, key=lambda value: str(value["target_ref"]))[0]["target_ref"])
        work_type = current.work_type if current is not None else work_types[work_id]
        external_label = work_id.rsplit("-", 1)[-1]
        desired = {
            "work_item_id": work_id,
            "work_type": work_type,
            "title": (
                current.title if current is not None
                else f"{'Talep' if work_type == 'request' else 'Defect' if work_type == 'defect' else 'Görev'} {external_label}"
            ),
            "description": (
                current.description if current is not None
                else "Yerel iş belgelerinden oluşturuldu."
            ),
            "status": current.status if current is not None else "active",
            "acceptance_criteria": [] if current is None else list(current.acceptance_criteria),
            "relations": [] if current is None else [value.as_dict() for value in current.relations],
            "evidence": evidence,
            "source_ref": source_ref,
        }
        current_evidence = [] if current is None else [value.as_dict() for value in current.evidence]
        if (
            current is not None
            and current_evidence == evidence
            and current.provenance.get("source_ref") == source_ref
        ):
            continue
        candidates.append(desired)
    summary = {
        "project_id": project_id,
        "document_count": len(files),
        "linked_work_item_count": len(by_work),
        "changed_work_item_count": len(candidates),
        "incoming_document_count": incoming_count,
        "manifest_digest": manifest["manifest_digest"],
        "source_content_copied_to_work_graph": False,
        "semantic_index_automatic": True,
    }
    if not candidates:
        return None, summary
    request = {
        "schema_ref": "schemas/work-import-request.schema.json",
        "schema_version": 1,
        "project_id": project_id,
        "source_inventory": inventory,
        "candidates": candidates,
    }
    return prepare_work_import(store, ownership, request), summary
