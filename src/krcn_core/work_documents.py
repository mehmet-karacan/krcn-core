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
from dataclasses import dataclass, replace
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
    source_provenance: tuple[tuple[str, str], ...]
    work_type: str
    external_id: str
    document_year: str | None
    original_name: str

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
            "source_provenance": [
                {"source_id": source_id, "source_ref": source_ref}
                for source_id, source_ref in self.source_provenance
            ],
            "work_type": self.work_type,
            "external_id": self.external_id,
            "document_year": self.document_year,
            "original_name": self.original_name,
            "document_revision": 1,
            "previous_sha256": None,
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
        raise WorkDocumentError("combined request folder requires reviewed split mapping")
    key = numbers[0] if numbers else _slug(folder)
    base = root / category / key
    tail = parts[3:] if len(parts) > 3 else (parts[2],)
    target = base / PurePosixPath(*tail).name
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
        raise WorkDocumentError("combined request folder requires reviewed split mapping")
    key = numbers[0] if numbers else _slug(folder)
    base = root / category / key
    target = base / PurePosixPath(*parts[3:]).name
    return target, work_type, "/".join(parts)


def _digest_suffixed_name(path: Path, sha256: str) -> str:
    return f"{path.stem}__sha256-{sha256[:12]}{path.suffix}"


def _resolve_entry_targets(
    entries: Sequence[DocumentCopyEntry],
    target_root: Path,
) -> tuple[DocumentCopyEntry, ...]:
    """Deduplicate equal content and deterministically name basename conflicts."""

    groups: dict[tuple[str, str], list[DocumentCopyEntry]] = {}
    for entry in entries:
        parent = entry.target_path.parent.relative_to(target_root).as_posix().casefold()
        groups.setdefault((parent, entry.target_path.name.casefold()), []).append(entry)
    resolved: list[DocumentCopyEntry] = []
    occupied: dict[str, str] = {}
    for _, values in sorted(groups.items()):
        by_digest: dict[str, list[DocumentCopyEntry]] = {}
        for entry in values:
            by_digest.setdefault(entry.sha256, []).append(entry)
        distinct: list[DocumentCopyEntry] = []
        for sha256, matches in sorted(by_digest.items()):
            chosen = min(matches, key=lambda value: (value.source_id, value.source_ref))
            linked = tuple(sorted({item for value in matches for item in value.work_item_ids}))
            provenance = tuple(sorted({
                item
                for value in matches
                for item in value.source_provenance
            }))
            distinct.append(replace(
                chosen,
                work_item_ids=linked,
                source_provenance=provenance,
            ))
        conflict = len(distinct) > 1
        for entry in sorted(distinct, key=lambda value: (value.sha256, value.source_ref)):
            target = (
                entry.target_path.with_name(_digest_suffixed_name(entry.target_path, entry.sha256))
                if conflict else entry.target_path
            )
            key = target.relative_to(target_root).as_posix().casefold()
            prior = occupied.get(key)
            if prior is not None and prior != entry.sha256:
                raise WorkDocumentError("deterministic document target still conflicts")
            occupied[key] = entry.sha256
            resolved.append(replace(
                entry,
                target_path=target,
                target_ref=_logical_ref(target_root, target),
            ))
    return tuple(sorted(resolved, key=lambda value: value.target_ref))


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
    identity_review_required: tuple[str, ...]

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
            "layout_version": 2,
            "identity_review_required": list(self.identity_review_required),
            "review_required": bool(self.identity_review_required),
            "source_files_modified": False,
            "source_files_deleted": False,
            "absolute_paths_persisted": False,
            "paths_disclosed": False,
        }


@dataclass(frozen=True)
class ManifestDocumentEntry:
    path: Path
    reference: str
    sha256: str
    previous_sha256: str | None
    document_revision: int
    change_kind: str


@dataclass(frozen=True)
class WorkDocumentManifestUpdatePlan:
    project_id: str
    manifest_path: Path
    previous_manifest_digest: str
    desired_manifest: Mapping[str, object]
    new_entries: tuple[ManifestDocumentEntry, ...]
    mutation: MutationPlan | None
    plan_id: str
    no_op: bool

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return () if self.mutation is None else (self.mutation,)

    def public_summary(self) -> dict[str, object]:
        revisions = [value for value in self.new_entries if value.change_kind == "revision"]
        return {
            "schema_ref": "schemas/work-document-manifest-update-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "previous_manifest_digest": self.previous_manifest_digest,
            "desired_manifest_digest": self.desired_manifest["manifest_digest"],
            "new_document_count": sum(
                value.change_kind == "new" for value in self.new_entries
            ),
            "revised_document_count": len(revisions),
            "revision_digest": _digest([
                {
                    "reference": value.reference,
                    "previous_sha256": value.previous_sha256,
                    "sha256": value.sha256,
                    "document_revision": value.document_revision,
                }
                for value in revisions
            ]),
            "no_op": self.no_op,
            "approval_required": self.mutation is not None,
            "work_document_processing_required": bool(self.new_entries),
            "reversible": True,
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
    selected: list[DocumentCopyEntry] = []

    def add(
        source_id: str,
        value: tuple[Path, str, str, int],
        mapped: tuple[Path, str, str] | None,
    ) -> None:
        if mapped is None:
            return
        source_path, relative, sha256, size = value
        target, work_type, hint = mapped
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
            source_provenance=((source_id, f"{source_id}/{relative}"),),
            work_type=work_type,
            external_id=(
                target.parent.name
                if work_type in {"request", "defect"}
                else _slug(target.parent.parent.name)
            ),
            document_year=(
                next((part for part in PurePosixPath(relative).parts if YEAR.fullmatch(part)), None)
            ),
            original_name=source_path.name,
        ))

    for value in db_values:
        add("db-scripts", value, _target_for_db(target_root, PurePosixPath(value[1])))
    for value in legacy_values:
        add("mk-hub", value, _target_for_legacy(target_root, PurePosixPath(value[1])))
    selected = list(_resolve_entry_targets(selected, target_root))
    identity_review_required = tuple(sorted({
        entry.target_path.parent.name
        for entry in selected
        if entry.target_path.parent.parent.name in {"requests", "defects"}
        and not entry.target_path.parent.name.isdigit()
    }))
    source_digests = {
        "db-scripts": _inventory_digest(db_values, "db-scripts"),
        "mk-hub": _inventory_digest(legacy_values, "mk-hub"),
    }
    manifest: dict[str, object] = {
        "schema_ref": MANIFEST_SCHEMA,
        "schema_version": 2,
        "layout_version": 2,
        "legacy_reference_aliases": {},
        "legacy_preserved_entries": [],
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
        manifest_path, plan_id, not effects, identity_review_required,
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
    version = payload.get("schema_version")
    if version not in {1, 2}:
        raise WorkDocumentError("work document manifest version is unsupported")
    if version == 2 and payload.get("layout_version") != 2:
        raise WorkDocumentError("work document manifest layout version is invalid")
    if version == 2:
        preserved = payload.get("legacy_preserved_entries")
        if not isinstance(preserved, list):
            raise WorkDocumentError("V2 legacy preserved entries are invalid")
        for value in preserved:
            if (
                not isinstance(value, dict)
                or set(value) != {"entry", "preservation_reason"}
                or value.get("preservation_reason") not in {
                    "excluded-review", "unresolved-review"
                }
                or not isinstance(value.get("entry"), dict)
                or not isinstance(value["entry"].get("target_ref"), str)
            ):
                raise WorkDocumentError("V2 legacy preserved entry is invalid")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise WorkDocumentError("work document manifest entries are invalid")
        for raw in entries:
            if not isinstance(raw, dict):
                raise WorkDocumentError("work document manifest entry is invalid")
            reference = raw.get("target_ref")
            if not isinstance(reference, str):
                raise WorkDocumentError("work document manifest reference is invalid")
            parts = PurePosixPath(reference.removeprefix("work-documents/")).parts
            if parts and parts[0] in {"requests", "defects"}:
                if len(parts) != 3:
                    raise WorkDocumentError("V2 request and defect documents must be direct ID children")
                expected_type = "request" if parts[0] == "requests" else "defect"
                if raw.get("work_type") != expected_type or raw.get("external_id") != parts[1]:
                    raise WorkDocumentError("V2 work document identity metadata does not match its path")
                year = raw.get("document_year")
                if year is not None and (not isinstance(year, str) or not YEAR.fullmatch(year)):
                    raise WorkDocumentError("V2 work document year metadata is invalid")
                original_name = raw.get("original_name")
                if (
                    not isinstance(original_name, str)
                    or not original_name
                    or PurePosixPath(original_name).name != original_name
                    or "\\" in original_name
                ):
                    raise WorkDocumentError("V2 work document original name is invalid")
                provenance = raw.get("source_provenance")
                if not isinstance(provenance, list) or not provenance:
                    raise WorkDocumentError("V2 work document source provenance is required")
                for value in provenance:
                    if (
                        not isinstance(value, dict)
                        or set(value) != {"source_id", "source_ref"}
                        or value.get("source_id") not in {"db-scripts", "mk-hub", "user"}
                        or not isinstance(value.get("source_ref"), str)
                        or not str(value["source_ref"]).strip()
                    ):
                        raise WorkDocumentError("V2 work document source provenance is invalid")
                revision = raw.get("document_revision")
                if (
                    not isinstance(revision, int)
                    or isinstance(revision, bool)
                    or revision < 1
                ):
                    raise WorkDocumentError("V2 work document revision is invalid")
                previous_sha256 = raw.get("previous_sha256")
                if previous_sha256 is not None and (
                    not isinstance(previous_sha256, str)
                    or not SHA256.fullmatch(previous_sha256)
                    or previous_sha256 == raw.get("sha256")
                ):
                    raise WorkDocumentError("V2 previous document digest is invalid")
    digest = payload.get("manifest_digest")
    identity = dict(payload)
    identity.pop("manifest_digest", None)
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or digest != _digest(identity):
        raise WorkDocumentError("work document manifest digest does not match")
    return payload


def prepare_work_document_manifest_update(
    store: LocalWorkspaceStore,
    ownership: OwnershipResolver,
    project_id: str,
    *,
    requested_external_id: str | None = None,
    requested_work_type: str | None = None,
) -> WorkDocumentManifestUpdatePlan:
    if requested_work_type not in {None, "request", "defect"}:
        raise WorkDocumentError("manifest update supports request or defect documents")
    root = work_documents_root(store.data_root, project_id)
    manifest_path = root / "_krcn" / "import-manifest.json"
    manifest = _read_manifest(manifest_path)
    if manifest.get("layout_version") != 2:
        raise WorkDocumentError("work document layout V2 migration is required")
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        raise WorkDocumentError("work document manifest entries are invalid")
    known = {
        str(value["target_ref"]): dict(value)
        for value in raw_entries
        if isinstance(value, dict) and isinstance(value.get("target_ref"), str)
    }
    current_items, _ = _existing_work_maps(store, project_id)
    replacements: dict[str, Mapping[str, object]] = {}
    documents: list[ManifestDocumentEntry] = []
    matched_types: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            raise WorkDocumentError("work documents may not contain symbolic links")
        if not path.is_file() or "_krcn" in {part.casefold() for part in path.relative_to(root).parts}:
            continue
        reference = _logical_ref(root, path)
        parts = PurePosixPath(reference.removeprefix("work-documents/")).parts
        if len(parts) != 3 or parts[0] not in {"requests", "defects"}:
            continue
        work_type = "request" if parts[0] == "requests" else "defect"
        external_id = parts[1]
        if requested_external_id is not None and external_id != requested_external_id:
            continue
        if requested_work_type is not None and work_type != requested_work_type:
            continue
        matched_types.add(work_type)
        sha256 = _file_digest(path)
        previous = known.get(reference)
        if previous is not None and previous.get("sha256") == sha256:
            continue
        policy, findings = _document_policy(path, reference.removeprefix("work-documents/"))
        work_id = (
            f"{project_id}-{work_type}-item-{external_id}"
            if external_id.isdigit()
            else f"{project_id}-{work_type}-{_slug(external_id)}"
        )
        if not external_id.isdigit():
            reviewed = current_items.get(work_id)
            if reviewed is None or reviewed.work_type != work_type:
                raise WorkDocumentError(
                    "non-numeric work document identity requires reviewed Work Item evidence"
                )
        prior_revision = 0 if previous is None else previous.get("document_revision", 1)
        if previous is not None and (
            not isinstance(prior_revision, int)
            or isinstance(prior_revision, bool)
            or prior_revision < 1
        ):
            raise WorkDocumentError("work document revision metadata is invalid")
        desired_entry = {
            "target_ref": reference,
            "sha256": sha256,
            "size_bytes": path.stat().st_size,
            "source_id": "user" if previous is None else previous.get("source_id"),
            "source_ref": reference if previous is None else previous.get("source_ref"),
            "work_item_ids": (
                [work_id]
                if previous is None
                else list(previous.get("work_item_ids", []))
            ),
            "semantic_policy": policy,
            "sensitivity_classes": list(findings),
            "source_provenance": (
                [{"source_id": "user", "source_ref": reference}]
                if previous is None
                else list(previous.get("source_provenance", []))
            ),
            "work_type": work_type,
            "external_id": external_id,
            "document_year": None if previous is None else previous.get("document_year"),
            "original_name": path.name if previous is None else previous.get("original_name"),
            "document_revision": prior_revision + (1 if previous is not None else 1),
            "previous_sha256": None if previous is None else previous.get("sha256"),
        }
        replacements[reference] = desired_entry
        documents.append(ManifestDocumentEntry(
            path,
            reference,
            sha256,
            None if previous is None else str(previous["sha256"]),
            int(desired_entry["document_revision"]),
            "new" if previous is None else "revision",
        ))
    if requested_external_id is not None and requested_work_type is None and len(matched_types) > 1:
        raise WorkDocumentError("requested work document identity matches multiple work types")
    desired = dict(manifest)
    desired.pop("manifest_digest", None)
    desired_entries = [
        dict(replacements.get(str(value.get("target_ref")), value))
        for value in raw_entries
        if isinstance(value, dict)
    ]
    desired_entries.extend(
        dict(value) for reference, value in replacements.items() if reference not in known
    )
    desired_entries.sort(key=lambda value: str(value["target_ref"]))
    desired["entries"] = desired_entries
    desired["manifest_digest"] = _digest(desired)
    desired_bytes = pretty_json_bytes(desired)
    current_bytes = manifest_path.read_bytes()
    mutation = None
    if desired_bytes != current_bytes:
        mutation = plan_mutation(
            ownership,
            operation="update",
            target_ref=_portable_target_ref(store.data_root, manifest_path),
            expected_ownership="user-data",
            change_digest=str(desired["manifest_digest"]),
            reversible=True,
        )
    identity = {
        "project_id": project_id,
        "previous_manifest_digest": manifest["manifest_digest"],
        "desired_manifest_digest": desired["manifest_digest"],
        "document_changes": [
            {
                "reference": value.reference,
                "previous_sha256": value.previous_sha256,
                "sha256": value.sha256,
                "document_revision": value.document_revision,
                "change_kind": value.change_kind,
            }
            for value in documents
        ],
        "mutation": None if mutation is None else mutation.as_dict(),
    }
    return WorkDocumentManifestUpdatePlan(
        project_id,
        manifest_path,
        str(manifest["manifest_digest"]),
        desired,
        tuple(documents),
        mutation,
        _digest(identity),
        mutation is None,
    )


def apply_work_document_manifest_update(
    plan: WorkDocumentManifestUpdatePlan,
    authorization: MutationAuthorization | None,
    *,
    expected_plan_id: str,
) -> dict[str, object]:
    if not hmac.compare_digest(plan.plan_id, expected_plan_id):
        raise WorkDocumentError("manifest update approval does not match the exact plan")
    if plan.no_op:
        if authorization is not None:
            raise WorkDocumentError("no-op manifest update may not carry authorization")
        return {
            "status": "already-applied",
            "new_document_count": 0,
            "revised_document_count": 0,
        }
    if (
        plan.mutation is None
        or authorization is None
        or authorization.plan != plan.mutation
        or not authorization.dry_run_verified
        or (plan.mutation.approval_required and not authorization.approval_verified)
    ):
        raise WorkDocumentError("manifest update requires matching user approval")
    current = _read_manifest(plan.manifest_path)
    if current["manifest_digest"] != plan.previous_manifest_digest:
        raise WorkDocumentError("work document manifest changed after update planning")
    for value in plan.new_entries:
        if not value.path.is_file() or _file_digest(value.path) != value.sha256:
            raise WorkDocumentError("work document changed after manifest update planning")
    previous = plan.manifest_path.read_bytes()
    temporary = plan.manifest_path.with_suffix(".json.tmp")
    try:
        temporary.write_bytes(pretty_json_bytes(plan.desired_manifest))
        os.replace(temporary, plan.manifest_path)
        verified = _read_manifest(plan.manifest_path)
        if verified["manifest_digest"] != plan.desired_manifest["manifest_digest"]:
            raise WorkDocumentError("manifest update verification failed")
    except Exception:
        temporary.unlink(missing_ok=True)
        plan.manifest_path.write_bytes(previous)
        raise
    return {
        "status": "applied",
        "new_document_count": sum(
            value.change_kind == "new" for value in plan.new_entries
        ),
        "revised_document_count": sum(
            value.change_kind == "revision" for value in plan.new_entries
        ),
        "manifest_digest": plan.desired_manifest["manifest_digest"],
        "work_document_processing_required": True,
    }


def _local_work_identity(
    project_id: str,
    reference: str,
    known_ids: set[str],
) -> tuple[str, tuple[str, ...]]:
    parts = PurePosixPath(reference.removeprefix("work-documents/")).parts
    if len(parts) < 3:
        raise WorkDocumentError("incoming work document path is incomplete")
    if parts[0] in {"requests", "defects"}:
        work_type = "request" if parts[0] == "requests" else "defect"
        if YEAR.fullmatch(parts[1]) and len(parts) >= 4:
            external_id = parts[2]
        else:
            external_id = parts[1]
        if external_id.isdigit():
            work_id = f"{project_id}-{work_type}-item-{external_id}"
        else:
            work_id = f"{project_id}-{work_type}-{_slug(external_id)}"
            if work_id not in known_ids:
                raise WorkDocumentError(
                    "non-numeric work document identity requires a reviewed Work Item"
                )
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
    requested_external_id: str | None = None,
    requested_work_type: str | None = None,
) -> tuple[WorkImportPlan | None, Mapping[str, object]]:
    if requested_work_type not in {None, "request", "defect", "task"}:
        raise WorkDocumentError("requested work document type is invalid")
    root = work_documents_root(store.data_root, project_id)
    manifest = _read_manifest(root / "_krcn" / "import-manifest.json")
    layout_version = manifest.get("layout_version", 1)
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        raise WorkDocumentError("work document manifest entries are invalid")
    files: list[WorkSourceEntry] = []
    by_work: dict[str, list[Mapping[str, object]]] = {}
    work_types: dict[str, str] = {}
    known_references: set[str] = set()
    current_items, _ = _existing_work_maps(store, project_id)
    known_ids = set(current_items)

    def requested(work_id: str) -> bool:
        if requested_work_type is not None and f"-{requested_work_type}-" not in work_id:
            return False
        if requested_external_id is None:
            return True
        return (
            work_id.endswith(f"-item-{requested_external_id}")
            or work_id.endswith(f"-{requested_external_id}")
        )
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
        relative_parts = PurePosixPath(relative).parts
        if layout_version == 2 and relative_parts[:2] == ("shared", "requests"):
            # Shared V1 request bundles are carried forward for provenance and
            # cleanup review. They are not authoritative V2 processing inputs.
            continue
        path = root / Path(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink() or _file_digest(path) != digest:
            raise WorkDocumentError("work document differs from its manifest")
        files.append(WorkSourceEntry(reference, str(digest), int(size)))
        raw_work_ids = {
            value for value in raw.get("work_item_ids", [])
            if isinstance(value, str)
        }
        inferred_type = raw.get("work_type")
        if inferred_type not in {"request", "defect", "task"}:
            reviewed_types = {
                current_items[work_id].work_type
                for work_id in raw_work_ids
                if work_id in current_items
            }
            if len(reviewed_types) > 1:
                raise WorkDocumentError(
                    "manifest work document links use conflicting work types"
                )
            if reviewed_types:
                inferred_type = next(iter(reviewed_types))
            else:
                inferred_type, _ = _local_work_identity(
                    project_id,
                    reference,
                    known_ids | raw_work_ids,
                )
        for work_id in raw.get("work_item_ids", []):
            if isinstance(work_id, str) and requested(work_id):
                by_work.setdefault(work_id, []).append(raw)
                current = current_items.get(work_id)
                work_types[work_id] = (
                    current.work_type if current is not None else inferred_type
                )
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
        relative_parts = PurePosixPath(
            reference.removeprefix("work-documents/")
        ).parts
        if (
            layout_version == 2
            and relative_parts
            and relative_parts[0] in {"requests", "defects", "shared"}
            and (
                relative_parts[0] == "shared"
                or len(relative_parts) < 3
                or YEAR.fullmatch(relative_parts[1]) is not None
            )
        ):
            # V1 files remain as copy-first migration fallback until a separate
            # cleanup approval. The V2 manifest is authoritative for processing.
            continue
        work_type, work_ids = _local_work_identity(
            project_id, reference, known_ids,
        )
        selected_work_ids = tuple(work_id for work_id in work_ids if requested(work_id))
        if not selected_work_ids:
            continue
        if layout_version == 2:
            raise WorkDocumentError(
                "unmanifested V2 work document requires an exact manifest update plan"
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
            "work_item_ids": list(selected_work_ids),
            "semantic_policy": policy,
            "sensitivity_classes": list(findings),
            "source_provenance": [{
                "source_id": "user",
                "source_ref": reference,
            }],
            "work_type": work_type,
            "external_id": (
                selected_work_ids[0].rsplit("-item-", 1)[-1]
                if "-item-" in selected_work_ids[0]
                else selected_work_ids[0].rsplit("-", 1)[-1]
            ),
            "document_year": None,
            "original_name": path.name,
            "document_revision": 1,
            "previous_sha256": None,
        }
        known_references.add(reference)
        files.append(WorkSourceEntry(reference, digest, path.stat().st_size))
        incoming_count += 1
        for work_id in selected_work_ids:
            by_work.setdefault(work_id, []).append(raw)
            work_types[work_id] = work_type
    files.sort(key=lambda value: value.source_ref)
    if (
        requested_external_id is not None
        and requested_work_type is None
        and len({work_types[work_id] for work_id in by_work}) > 1
    ):
        raise WorkDocumentError(
            "requested work document identity matches multiple work types"
        )
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
        "requested_external_id": requested_external_id,
        "requested_work_type": requested_work_type,
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
