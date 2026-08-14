"""Exact-plan migration from legacy Work Documents paths to layout V2."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from .json_documents import pretty_json_bytes
from .local_store import LocalWorkspaceStore
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .work_documents import (
    MANIFEST_SCHEMA,
    NUMBER,
    WorkDocumentError,
    _atomic_copy,
    _digest,
    _existing_work_maps,
    _file_digest,
    _logical_ref,
    _portable_target_ref,
    _read_manifest,
    work_documents_root,
)


MIGRATION_SCHEMA = "schemas/work-document-layout-migration-plan.schema.json"


@dataclass(frozen=True)
class LayoutMigrationEntry:
    source_path: Path
    target_path: Path
    source_ref: str
    target_ref: str
    sha256: str
    size_bytes: int
    manifest_entry: Mapping[str, object]
    legacy_source_refs: tuple[str, ...]


@dataclass(frozen=True)
class WorkDocumentLayoutMigrationPlan:
    project_id: str
    entries: tuple[LayoutMigrationEntry, ...]
    source_files: tuple[tuple[Path, str], ...]
    manifest_path: Path
    previous_manifest_digest: str
    desired_manifest: Mapping[str, object]
    source_inventory_digest: str
    effect_plans: tuple[MutationPlan, ...]
    identity_review_required: tuple[str, ...]
    reviewed_identity_decisions: Mapping[str, str]
    excluded_review_refs: tuple[str, ...]
    document_count: int
    source_mapping_count: int
    physical_target_count: int
    collision_group_count: int
    content_conflict_count: int
    deduplicated_group_count: int
    mapping_digest: str
    plan_id: str
    no_op: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": MIGRATION_SCHEMA,
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "from_layout_versions": [1, 2],
            "target_layout_version": 2,
            "document_count": self.document_count,
            "source_mapping_count": self.source_mapping_count,
            "physical_target_count": self.physical_target_count,
            "collision_group_count": self.collision_group_count,
            "content_conflict_count": self.content_conflict_count,
            "deduplicated_group_count": self.deduplicated_group_count,
            "copy_count": sum(value.source_path != value.target_path for value in self.entries),
            "legacy_source_count": len(self.source_files),
            "source_inventory_digest": self.source_inventory_digest,
            "previous_manifest_digest": self.previous_manifest_digest,
            "desired_manifest_digest": self.desired_manifest["manifest_digest"],
            "identity_review_required": list(self.identity_review_required),
            "reviewed_identity_decisions": dict(self.reviewed_identity_decisions),
            "excluded_review_refs": list(self.excluded_review_refs),
            "unresolved_review_count": len(self.identity_review_required),
            "excluded_count": len(self.excluded_review_refs),
            "review_required": bool(self.identity_review_required),
            "mapping_digest": self.mapping_digest,
            "approval_required": bool(self.effect_plans),
            "no_op": self.no_op,
            "reversible": True,
            "work_document_processing_required": not self.no_op,
            "derived_rebuild_required": not self.no_op,
            "cleanup_required": not self.no_op,
            "transaction_rollback_supported": True,
            "post_apply_rollback_available": False,
            "paths_disclosed": False,
        }


def _manifest_entry_by_ref(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    values = manifest.get("entries")
    if not isinstance(values, list):
        raise WorkDocumentError("work document manifest entries are invalid")
    result: dict[str, Mapping[str, object]] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("target_ref"), str):
            raise WorkDocumentError("work document manifest entry is invalid")
        result[str(value["target_ref"])] = value
    preserved = manifest.get("legacy_preserved_entries", [])
    if isinstance(preserved, list):
        for value in preserved:
            if not isinstance(value, dict) or not isinstance(value.get("entry"), dict):
                raise WorkDocumentError("work document preserved manifest entry is invalid")
            entry = value["entry"]
            if not isinstance(entry.get("target_ref"), str):
                raise WorkDocumentError("work document preserved reference is invalid")
            result[str(entry["target_ref"])] = entry
    aliases = manifest.get("legacy_reference_aliases", {})
    if isinstance(aliases, dict):
        for legacy_ref, target_refs in aliases.items():
            if not isinstance(legacy_ref, str) or not isinstance(target_refs, list):
                raise WorkDocumentError("work document legacy reference alias is invalid")
            matches = [result.get(value) for value in target_refs if isinstance(value, str)]
            matches = [value for value in matches if value is not None]
            if matches:
                result[legacy_ref] = matches[0]
    return result


def _external_ids(parts: tuple[str, ...], raw: Mapping[str, object] | None) -> tuple[str, ...]:
    if parts[:2] == ("shared", "requests"):
        work_ids = () if raw is None else tuple(
            value for value in raw.get("work_item_ids", []) if isinstance(value, str)
        )
        identifiers = tuple(dict.fromkeys(
            value.rsplit("-", 1)[-1] for value in work_ids
            if value.rsplit("-", 1)[-1].isdigit()
        ))
        if identifiers:
            return identifiers
        location = "/".join(parts[:4])
        return tuple(dict.fromkeys(NUMBER.findall(location)))
    if not parts or parts[0] not in {"requests", "defects"}:
        return ()
    if len(parts) >= 4 and parts[1].isdigit() and len(parts[1]) == 4:
        return (parts[2],)
    if len(parts) >= 3:
        return (parts[1],)
    return ()


def _category(parts: tuple[str, ...]) -> str | None:
    if parts[:2] == ("shared", "requests"):
        return "requests"
    if parts and parts[0] in {"requests", "defects"}:
        return parts[0]
    return None


def _suffix(path: Path, sha256: str) -> Path:
    return path.with_name(f"{path.stem}__sha256-{sha256[:12]}{path.suffix}")


def _merge_exact_duplicates(values: Sequence[LayoutMigrationEntry]) -> LayoutMigrationEntry:
    chosen = min(values, key=lambda item: item.source_ref)
    raw = dict(chosen.manifest_entry)
    work_ids = sorted({
        work_id
        for value in values
        for work_id in value.manifest_entry.get("work_item_ids", [])
        if isinstance(work_id, str)
    })
    provenance: dict[tuple[str, str], dict[str, str]] = {}
    for value in values:
        raw_provenance = value.manifest_entry.get("source_provenance")
        if isinstance(raw_provenance, list) and raw_provenance:
            for item in raw_provenance:
                if isinstance(item, dict) and isinstance(item.get("source_id"), str) and isinstance(item.get("source_ref"), str):
                    provenance[(item["source_id"], item["source_ref"])] = {
                        "source_id": item["source_id"],
                        "source_ref": item["source_ref"],
                    }
        else:
            source_id = str(value.manifest_entry.get("source_id", "user"))
            source_ref = str(value.manifest_entry.get("source_ref", value.source_ref))
            provenance[(source_id, source_ref)] = {
                "source_id": source_id,
                "source_ref": source_ref,
            }
    raw["work_item_ids"] = work_ids
    raw["source_provenance"] = [provenance[key] for key in sorted(provenance)]
    return LayoutMigrationEntry(
        chosen.source_path,
        chosen.target_path,
        chosen.source_ref,
        chosen.target_ref,
        chosen.sha256,
        chosen.size_bytes,
        raw,
        tuple(sorted({ref for value in values for ref in value.legacy_source_refs})),
    )


def _resolve_targets(
    candidates: Sequence[LayoutMigrationEntry],
    root: Path,
) -> tuple[tuple[LayoutMigrationEntry, ...], int, int, int]:
    groups: dict[str, list[LayoutMigrationEntry]] = {}
    for value in candidates:
        key = value.target_path.relative_to(root).as_posix().casefold()
        groups.setdefault(key, []).append(value)
    result: dict[str, LayoutMigrationEntry] = {}
    collision_group_count = 0
    content_conflict_count = 0
    deduplicated_group_count = 0
    for values in groups.values():
        by_digest: dict[str, list[LayoutMigrationEntry]] = {}
        for value in values:
            by_digest.setdefault(value.sha256, []).append(value)
        distinct = [
            _merge_exact_duplicates(items)
            for _, items in sorted(by_digest.items())
        ]
        if len(values) > 1:
            collision_group_count += 1
        if len(distinct) > 1:
            content_conflict_count += 1
        if len(values) > len(distinct):
            deduplicated_group_count += 1
        for value in distinct:
            target = _suffix(value.target_path, value.sha256) if len(distinct) > 1 else value.target_path
            key = target.relative_to(root).as_posix().casefold()
            prior = result.get(key)
            if prior is not None and prior.sha256 != value.sha256:
                raise WorkDocumentError("document migration target conflicts after suffixing")
            current = LayoutMigrationEntry(
                value.source_path,
                target,
                value.source_ref,
                _logical_ref(root, target),
                value.sha256,
                value.size_bytes,
                value.manifest_entry,
                value.legacy_source_refs,
            )
            if prior is not None:
                result[key] = _merge_exact_duplicates((prior, current))
                continue
            result[key] = current
    return (
        tuple(sorted(result.values(), key=lambda value: value.target_ref)),
        collision_group_count,
        content_conflict_count,
        deduplicated_group_count,
    )


def prepare_work_document_layout_migration(
    store: LocalWorkspaceStore,
    ownership: OwnershipResolver,
    project_id: str,
    reviewed_identity_decisions: Mapping[str, str] | None = None,
) -> WorkDocumentLayoutMigrationPlan:
    if store.read("projects", project_id) is None:
        raise WorkDocumentError("document project is not registered")
    root = work_documents_root(store.data_root, project_id)
    manifest_path = root / "_krcn" / "import-manifest.json"
    manifest = _read_manifest(manifest_path)
    by_ref = _manifest_entry_by_ref(manifest)
    current_items, _ = _existing_work_maps(store, project_id)
    layout_version = manifest.get("layout_version", 1)
    legacy_fallback_refs: set[str] = set()
    if layout_version == 2:
        aliases = manifest.get("legacy_reference_aliases", {})
        if isinstance(aliases, dict):
            legacy_fallback_refs.update(
                value for value in aliases if isinstance(value, str)
            )
        preserved = manifest.get("legacy_preserved_entries", [])
        if isinstance(preserved, list):
            legacy_fallback_refs.update(
                str(value["entry"]["target_ref"])
                for value in preserved
                if isinstance(value, dict)
                and isinstance(value.get("entry"), dict)
                and isinstance(value["entry"].get("target_ref"), str)
            )
    decisions = dict(reviewed_identity_decisions or {})
    for source_identity, target_identity in decisions.items():
        if (
            not isinstance(source_identity, str)
            or not source_identity
            or target_identity not in {"request", "defect", "exclude"}
        ):
            raise WorkDocumentError("reviewed work document identity decision is invalid")
    candidates: list[LayoutMigrationEntry] = []
    review: set[str] = set()
    unresolved_review_refs: set[str] = set()
    excluded_review_refs: set[str] = set()
    consumed_manifest_refs: set[str] = set()
    source_identity: list[dict[str, object]] = []
    source_files: list[tuple[Path, str]] = []
    document_count = 0
    source_mapping_count = 0
    for path in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink():
            raise WorkDocumentError("work documents may not contain symbolic links")
        if not path.is_file() or "_krcn" in {part.casefold() for part in path.relative_to(root).parts}:
            continue
        logical = _logical_ref(root, path)
        if logical in legacy_fallback_refs:
            # Copy-first V1 sources remain physically available until a
            # separately approved cleanup. A V2 rerun must not remigrate or
            # count these alias-backed fallback copies as incoming documents.
            continue
        document_count += 1
        parts = PurePosixPath(logical.removeprefix("work-documents/")).parts
        category = _category(parts)
        if category is None or parts[:2] == ("shared", "requests"):
            continue
        source_mapping_count += 1
        raw = by_ref.get(logical)
        identifiers = _external_ids(parts, raw)
        if not identifiers:
            raise WorkDocumentError("work document identity cannot be inferred for migration")
        sha256 = _file_digest(path)
        source_files.append((path, sha256))
        source_identity.append({"source_ref": logical, "sha256": sha256, "size_bytes": path.stat().st_size})
        for external_id in identifiers:
            if not external_id.isdigit():
                reviewed = decisions.get(external_id)
                expected_decision = "request" if category == "requests" else "defect"
                reviewed_work_item = (
                    layout_version == 2
                    and raw is not None
                    and any(
                        isinstance(work_id, str)
                        and work_id in current_items
                        and current_items[work_id].work_type == expected_decision
                        for work_id in raw.get("work_item_ids", [])
                    )
                )
                if reviewed is None and reviewed_work_item:
                    reviewed = expected_decision
                if reviewed is None:
                    review.add(external_id)
                    unresolved_review_refs.add(logical)
                    continue
                if reviewed == "exclude":
                    excluded_review_refs.add(logical)
                    continue
                if reviewed != expected_decision:
                    raise WorkDocumentError(
                        "reviewed work document identity decision conflicts with its category"
                    )
            target = root / category / external_id / path.name
            manifest_entry = dict(raw or {
                "source_id": "user",
                "source_ref": logical,
                "work_item_ids": [],
                "semantic_policy": "metadata-only",
                "sensitivity_classes": [],
            })
            if raw is not None and isinstance(raw.get("target_ref"), str):
                consumed_manifest_refs.add(str(raw["target_ref"]))
            candidates.append(LayoutMigrationEntry(
                path, target, logical, _logical_ref(root, target), sha256,
                path.stat().st_size, manifest_entry, (logical,),
            ))
    (
        entries,
        collision_group_count,
        content_conflict_count,
        deduplicated_group_count,
    ) = _resolve_targets(candidates, root)
    physical_target_count = (
        len(entries)
        + len(excluded_review_refs)
        + sum(
            1
            for source, _ in source_files
            if _logical_ref(root, source) not in {
                ref for value in entries for ref in value.legacy_source_refs
            }
            and _logical_ref(root, source) not in excluded_review_refs
        )
    )
    desired_entries = []
    for value in entries:
        raw = dict(value.manifest_entry)
        target_parts = PurePosixPath(
            value.target_ref.removeprefix("work-documents/")
        ).parts
        source_parts = PurePosixPath(
            value.source_ref.removeprefix("work-documents/")
        ).parts
        document_year = next(
            (
                part for part in source_parts
                if part.isdigit() and len(part) == 4 and part.startswith("20")
            ),
            raw.get("document_year"),
        )
        provenance = raw.get("source_provenance")
        if not isinstance(provenance, list) or not provenance:
            provenance = [{
                "source_id": str(raw.get("source_id", "user")),
                "source_ref": str(raw.get("source_ref", value.source_ref)),
            }]
        raw.update({
            "target_ref": value.target_ref,
            "sha256": value.sha256,
            "size_bytes": value.size_bytes,
            "work_type": "request" if target_parts[0] == "requests" else "defect",
            "external_id": target_parts[1],
            "document_year": document_year,
            "original_name": str(raw.get("original_name", value.source_path.name)),
            "source_provenance": provenance,
            "document_revision": raw.get("document_revision", 1),
            "previous_sha256": raw.get("previous_sha256"),
        })
        desired_entries.append(raw)
    raw_manifest_entries = manifest.get("entries", [])
    legacy_preserved_entries: list[Mapping[str, object]] = []
    for raw in raw_manifest_entries:
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("target_ref"), str)
            and raw["target_ref"] not in consumed_manifest_refs
        ):
            parts = PurePosixPath(
                str(raw["target_ref"]).removeprefix("work-documents/")
            ).parts
            if (
                len(parts) >= 4
                and parts[0] in {"requests", "defects"}
                and parts[1].isdigit()
                and len(parts[1]) == 4
            ):
                reason = (
                    "excluded-review"
                    if str(raw["target_ref"]) in excluded_review_refs
                    else "unresolved-review"
                )
                legacy_preserved_entries.append({
                    "entry": dict(raw),
                    "preservation_reason": reason,
                })
            else:
                desired_entries.append(dict(raw))
    previous_preserved = manifest.get("legacy_preserved_entries", [])
    if isinstance(previous_preserved, list):
        for preserved in previous_preserved:
            if not isinstance(preserved, dict) or not isinstance(preserved.get("entry"), dict):
                raise WorkDocumentError("work document preserved manifest entry is invalid")
            target_ref = preserved["entry"].get("target_ref")
            if isinstance(target_ref, str) and target_ref not in consumed_manifest_refs:
                legacy_preserved_entries.append({
                    "entry": dict(preserved["entry"]),
                    "preservation_reason": preserved.get("preservation_reason"),
                })
    desired_entries.sort(key=lambda value: str(value["target_ref"]))
    legacy_preserved_entries.sort(
        key=lambda value: str(value["entry"]["target_ref"])
    )
    aliases: dict[str, list[str]] = {}
    for value in entries:
        for legacy_ref in value.legacy_source_refs:
            if legacy_ref != value.target_ref:
                aliases.setdefault(legacy_ref, []).append(value.target_ref)
    previous_aliases = manifest.get("legacy_reference_aliases", {})
    if isinstance(previous_aliases, dict):
        for legacy_ref, targets in previous_aliases.items():
            if isinstance(legacy_ref, str) and isinstance(targets, list):
                aliases.setdefault(legacy_ref, []).extend(
                    target for target in targets if isinstance(target, str)
                )
    aliases = {
        key: sorted(set(values))
        for key, values in sorted(aliases.items())
    }
    desired: dict[str, object] = {
        "schema_ref": MANIFEST_SCHEMA,
        "schema_version": 2,
        "layout_version": 2,
        "legacy_reference_aliases": aliases,
        "legacy_preserved_entries": legacy_preserved_entries,
        "project_id": project_id,
        "source_inventory_digests": dict(manifest.get("source_inventory_digests", {})),
        "entries": desired_entries,
        "source_files_copied": True,
        "source_files_modified": False,
        "source_files_deleted": False,
        "generated_content_separated": True,
        "absolute_paths_included": False,
    }
    desired["manifest_digest"] = _digest(desired)
    source_inventory_digest = _digest(source_identity)
    mapping_digest = _digest({
        "mappings": [
            {
                "source_refs": list(value.legacy_source_refs),
                "target_ref": value.target_ref,
                "sha256": value.sha256,
            }
            for value in entries
        ],
        "reviewed_identity_decisions": dict(sorted(decisions.items())),
        "excluded_review_refs": sorted(excluded_review_refs),
    })
    effects: list[MutationPlan] = []
    for value in entries:
        if value.target_path != value.source_path and not value.target_path.exists():
            effects.append(plan_mutation(
                ownership,
                operation="create",
                target_ref=_portable_target_ref(store.data_root, value.target_path),
                expected_ownership="user-data",
                change_digest=value.sha256,
                reversible=True,
            ))
    desired_bytes = pretty_json_bytes(desired)
    if manifest_path.read_bytes() != desired_bytes:
        effects.append(plan_mutation(
            ownership,
            operation="update",
            target_ref=_portable_target_ref(store.data_root, manifest_path),
            expected_ownership="user-data",
            change_digest=str(desired["manifest_digest"]),
            reversible=True,
        ))
    identity = {
        "project_id": project_id,
        "source_inventory_digest": source_inventory_digest,
        "previous_manifest_digest": manifest["manifest_digest"],
        "desired_manifest_digest": desired["manifest_digest"],
        "effects": [value.as_dict() for value in effects],
        "identity_review_required": sorted(review),
        "reviewed_identity_decisions": dict(sorted(decisions.items())),
        "excluded_review_refs": sorted(excluded_review_refs),
        "mapping_digest": mapping_digest,
    }
    return WorkDocumentLayoutMigrationPlan(
        project_id,
        entries,
        tuple(source_files),
        manifest_path,
        str(manifest["manifest_digest"]),
        desired,
        source_inventory_digest,
        tuple(effects),
        tuple(sorted(review)),
        dict(sorted(decisions.items())),
        tuple(sorted(excluded_review_refs)),
        document_count,
        source_mapping_count,
        physical_target_count,
        collision_group_count,
        content_conflict_count,
        deduplicated_group_count,
        mapping_digest,
        _digest(identity),
        not effects,
    )


def _validate_authorizations(
    effects: Sequence[MutationPlan],
    authorizations: Mapping[str, MutationAuthorization],
) -> None:
    if set(authorizations) != {value.plan_id for value in effects}:
        raise WorkDocumentError("document migration authorization set is incomplete")
    for effect in effects:
        authorization = authorizations[effect.plan_id]
        if authorization.plan != effect or not authorization.dry_run_verified:
            raise WorkDocumentError("document migration authorization does not match its effect")
        if effect.approval_required and not authorization.approval_verified:
            raise WorkDocumentError("document migration requires matching user approval")


def _prune_empty_directories(start: Path, stop: Path) -> None:
    current = start
    stop = stop.resolve(strict=False)
    while current.resolve(strict=False) != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def apply_work_document_layout_migration(
    plan: WorkDocumentLayoutMigrationPlan,
    authorizations: Mapping[str, MutationAuthorization],
    *,
    expected_plan_id: str,
) -> dict[str, object]:
    if not hmac.compare_digest(plan.plan_id, expected_plan_id):
        raise WorkDocumentError("document migration approval does not match the exact plan")
    if plan.identity_review_required:
        raise WorkDocumentError("document migration has unresolved identity reviews")
    _validate_authorizations(plan.effect_plans, authorizations)
    if plan.no_op:
        return {"status": "already-applied", "document_count": len(plan.entries)}
    current = _read_manifest(plan.manifest_path)
    if current["manifest_digest"] != plan.previous_manifest_digest:
        raise WorkDocumentError("document manifest changed after migration planning")
    for source, sha256 in plan.source_files:
        if not source.is_file() or _file_digest(source) != sha256:
            raise WorkDocumentError("document source changed after migration planning")
    for value in plan.entries:
        if value.target_path.exists() and _file_digest(value.target_path) != value.sha256:
            raise WorkDocumentError("document target changed after migration planning")
    created: list[Path] = []
    previous_manifest = plan.manifest_path.read_bytes()
    try:
        for value in plan.entries:
            if value.target_path.exists():
                continue
            _atomic_copy(value.source_path, value.target_path)
            if _file_digest(value.target_path) != value.sha256:
                raise WorkDocumentError("migrated document digest verification failed")
            created.append(value.target_path)
        temporary = plan.manifest_path.with_suffix(".json.tmp")
        temporary.write_bytes(pretty_json_bytes(plan.desired_manifest))
        os.replace(temporary, plan.manifest_path)
        verified_manifest = _read_manifest(plan.manifest_path)
        if verified_manifest["manifest_digest"] != plan.desired_manifest["manifest_digest"]:
            raise WorkDocumentError("document migration manifest verification failed")
    except Exception:
        plan.manifest_path.write_bytes(previous_manifest)
        for target in reversed(created):
            target.unlink(missing_ok=True)
            _prune_empty_directories(target.parent, plan.manifest_path.parent.parent)
        raise
    return {
        "status": "applied",
        "document_count": len(plan.entries),
        "copied_count": len(created),
        "manifest_digest": plan.desired_manifest["manifest_digest"],
        "layout_version": 2,
        "work_document_processing_required": True,
        "derived_rebuild_required": True,
        "cleanup_required": True,
        "transaction_rollback_supported": True,
        "post_apply_rollback_available": False,
    }
