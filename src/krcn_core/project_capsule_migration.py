"""Backup-backed migration from flat KRCN homes to project capsules."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .home_layout import (
    HOME_LAYOUT_FILE,
    collection_target,
    home_layout_version,
    project_capsule_payload,
    project_derived_path,
    user_home_layout_bytes,
)
from .json_documents import canonical_json_bytes, pretty_json_bytes
from .local_store import COLLECTIONS, LocalWorkspaceStore
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .portable_backup import SECRET_PATTERNS, _is_secret_path


class ProjectCapsuleMigrationError(ValueError):
    """Raised when layout v2 migration cannot remain exact and reversible."""


def _canonical_json(payload: object) -> bytes:
    return canonical_json_bytes(payload, trailing_newline=True)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _record_envelope(record_type: str, record_id: str, payload: dict[str, object]) -> bytes:
    digest = _sha256(_canonical_json(payload))
    return pretty_json_bytes(
        {
            "schema_version": 1,
            "record_type": record_type,
            "record_id": record_id,
            "revision": 1,
            "payload": payload,
            "payload_sha256": digest,
        }
    )


@dataclass(frozen=True)
class CapsuleMigrationEntry:
    source: Path
    target: Path
    source_ref: str
    target_ref: str
    ownership: str
    content: bytes
    sha256: str
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "size": len(self.content),
            "sha256": self.sha256,
            "ownership": self.ownership,
            "mutation": self.mutation.as_dict(),
        }


@dataclass(frozen=True)
class CapsuleGeneratedEntry:
    target: Path
    target_ref: str
    content: bytes
    sha256: str
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "target_ref": self.target_ref,
            "size": len(self.content),
            "sha256": self.sha256,
            "mutation": self.mutation.as_dict(),
        }


@dataclass(frozen=True)
class CapsuleMigrationBackup:
    archive_path: Path
    backup_id: str
    mutation: MutationPlan


@dataclass(frozen=True)
class ProjectCapsuleMigrationPlan:
    plan_id: str
    data_root: Path
    backup: CapsuleMigrationBackup
    project_ids: tuple[str, ...]
    moves: tuple[CapsuleMigrationEntry, ...]
    generated: tuple[CapsuleGeneratedEntry, ...]
    source_snapshot_digest: str

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return (
            self.backup.mutation,
            *(item.mutation for item in self.moves),
            *(item.mutation for item in self.generated),
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-capsule-migration-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "from_layout_version": 1,
            "to_layout_version": 2,
            "project_ids": list(self.project_ids),
            "project_count": len(self.project_ids),
            "move_count": len(self.moves),
            "generated_entry_count": len(self.generated),
            "backup_id": self.backup.backup_id,
            "backup_required_before_move": True,
            "source_content_copied": False,
            "secret_values_included": False,
            "paths_disclosed": False,
            "moves": [item.public_summary() for item in self.moves],
            "generated": [item.public_summary() for item in self.generated],
            "effect_plans": [item.as_dict() for item in self.effect_plans],
            "rollback": {
                "kind": "restore-exact-flat-layout-from-verified-backup",
                "automatic_on_failure": True,
                "backup_retained": True,
            },
        }


@dataclass(frozen=True)
class ProjectCapsuleMigrationResult:
    plan_id: str
    backup_id: str
    project_count: int
    moved_entry_count: int
    generated_entry_count: int
    verification_digest: str

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "backup_id": self.backup_id,
            "layout_version": 2,
            "project_count": self.project_count,
            "moved_entry_count": self.moved_entry_count,
            "generated_entry_count": self.generated_entry_count,
            "verification_digest": self.verification_digest,
            "rollback_ready": True,
            "source_content_copied": False,
        }


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ProjectCapsuleMigrationError("migration path escaped the KRCN home") from exc


def _assert_safe_content(relative: str, content: bytes) -> None:
    if _is_secret_path(relative):
        raise ProjectCapsuleMigrationError("secret path cannot enter capsule migration")
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        raise ProjectCapsuleMigrationError(
            f"secret-like content blocks capsule migration: {relative}"
        )


def _move_entry(
    root: Path,
    source: Path,
    target: Path,
    ownership: str,
    resolver: OwnershipResolver,
) -> CapsuleMigrationEntry:
    if source.is_symlink() or not source.is_file():
        raise ProjectCapsuleMigrationError("migration source must be a regular file")
    if target.exists():
        raise ProjectCapsuleMigrationError("capsule migration target already exists")
    content = source.read_bytes()
    source_ref = f".krcn/{_relative(root, source)}"
    target_ref = f".krcn/{_relative(root, target)}"
    _assert_safe_content(source_ref, content)
    digest = _sha256(content)
    mutation = plan_mutation(
        resolver,
        operation="move",
        target_ref=target_ref,
        expected_ownership=ownership,
        change_digest=_sha256(f"{source_ref}:{target_ref}:{digest}".encode("utf-8")),
        reversible=True,
    )
    return CapsuleMigrationEntry(
        source,
        target,
        source_ref,
        target_ref,
        ownership,
        content,
        digest,
        mutation,
    )


def _generated_entry(
    root: Path,
    target: Path,
    content: bytes,
    ownership: str,
    resolver: OwnershipResolver,
) -> CapsuleGeneratedEntry:
    if target.exists():
        raise ProjectCapsuleMigrationError("generated capsule target already exists")
    target_ref = f".krcn/{_relative(root, target)}"
    digest = _sha256(content)
    mutation = plan_mutation(
        resolver,
        operation="create",
        target_ref=target_ref,
        expected_ownership=ownership,
        change_digest=digest,
        reversible=True,
    )
    return CapsuleGeneratedEntry(target, target_ref, content, digest, mutation)


def _snapshot_digest(moves: tuple[CapsuleMigrationEntry, ...]) -> str:
    return _sha256(
        _canonical_json(
            [
                {
                    "source_ref": item.source_ref,
                    "target_ref": item.target_ref,
                    "sha256": item.sha256,
                }
                for item in moves
            ]
        )
    )


def _backup_bytes(plan: ProjectCapsuleMigrationPlan) -> bytes:
    manifest = {
        "schema_version": 1,
        "backup_kind": "project-capsule-layout-v1",
        "backup_id": plan.backup.backup_id,
        "entries": [
            {
                "path": item.source_ref[len(".krcn/") :],
                "size": len(item.content),
                "sha256": item.sha256,
            }
            for item in plan.moves
        ],
        "secret_values_included": False,
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        items = [("manifest.json", pretty_json_bytes(manifest))]
        items.extend(
            (
                f"payload/{item.source_ref[len('.krcn/'):]}",
                item.content,
            )
            for item in plan.moves
        )
        for name, content in items:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def _verify_backup(plan: ProjectCapsuleMigrationPlan) -> None:
    try:
        with zipfile.ZipFile(plan.backup.archive_path) as archive:
            if archive.testzip() is not None:
                raise ProjectCapsuleMigrationError("capsule migration backup is corrupt")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("backup_id") != plan.backup.backup_id:
                raise ProjectCapsuleMigrationError("capsule backup identity is invalid")
            for item in plan.moves:
                path = f"payload/{item.source_ref[len('.krcn/') :]}"
                if _sha256(archive.read(path)) != item.sha256:
                    raise ProjectCapsuleMigrationError("capsule backup payload is invalid")
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ProjectCapsuleMigrationError("capsule migration backup is invalid") from exc


def prepare_project_capsule_migration(
    data_root: Path,
    backup_path: Path,
    ownership: OwnershipResolver,
) -> ProjectCapsuleMigrationPlan:
    """Plan a complete flat-to-capsule migration without changing user data."""

    if not data_root.is_absolute() or not backup_path.is_absolute():
        raise ProjectCapsuleMigrationError("migration paths must be absolute")
    root = data_root.resolve()
    backup = backup_path.resolve(strict=False)
    if not root.is_dir() or root.is_symlink():
        raise ProjectCapsuleMigrationError("KRCN home must be a regular directory")
    if home_layout_version(root) != 1:
        raise ProjectCapsuleMigrationError("KRCN home already uses layout v2")
    try:
        backup.relative_to(root)
    except ValueError:
        pass
    else:
        raise ProjectCapsuleMigrationError("migration backup must be outside KRCN home")
    if backup.exists():
        raise ProjectCapsuleMigrationError("migration backup already exists")

    store = LocalWorkspaceStore(root, ownership)
    project_ids = tuple(record.record_id for record in store.list_records("projects"))
    if not project_ids:
        raise ProjectCapsuleMigrationError("no registered project is available to migrate")

    moves: list[CapsuleMigrationEntry] = []
    for record_type, collection in COLLECTIONS.items():
        if record_type == "project-capsules":
            continue
        for record in store.list_records(record_type):
            project_id = store.record_project_id(
                record_type,
                record.record_id,
                record.payload,
            )
            if project_id not in project_ids:
                project_id = None
            source = root.joinpath(*collection[1].split("/")) / f"{record.record_id}.json"
            target = collection_target(root, record_type, record.record_id, project_id)
            moves.append(
                _move_entry(root, source, target, collection[2], ownership)
            )

    legacy_hybrid = root / "derived" / "retrieval" / "hybrid-v1.sqlite"
    if legacy_hybrid.exists():
        moves.append(
            _move_entry(
                root,
                legacy_hybrid,
                root / "global" / "derived" / "retrieval" / "hybrid-v1.sqlite",
                "derived",
                ownership,
            )
        )
    for project_id in project_ids:
        legacy_index = (
            root
            / "derived"
            / "retrieval"
            / "source-code-v1"
            / f"{project_id}.sqlite"
        )
        if legacy_index.exists():
            moves.append(
                _move_entry(
                    root,
                    legacy_index,
                    project_derived_path(
                        root,
                        project_id,
                        "retrieval/source-code-v1.sqlite",
                    ),
                    "derived",
                    ownership,
                )
            )

    moves_tuple = tuple(sorted(moves, key=lambda item: item.source_ref))
    snapshot = _snapshot_digest(moves_tuple)
    backup_identity = {
        "source_snapshot_digest": snapshot,
        "archive_name": backup.name,
    }
    backup_id = _sha256(_canonical_json(backup_identity))
    backup_mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=f"project-capsule-migration-backups/{backup.name}",
        expected_ownership="unmanaged",
        change_digest=backup_id,
        reversible=True,
    )

    generated: list[CapsuleGeneratedEntry] = []
    for project_id in project_ids:
        content = _record_envelope(
            "project-capsules",
            project_id,
            project_capsule_payload(project_id),
        )
        generated.append(
            _generated_entry(
                root,
                collection_target(root, "project-capsules", project_id, project_id),
                content,
                "user-data",
                ownership,
            )
        )
    generated.append(
        _generated_entry(
            root,
            root / HOME_LAYOUT_FILE,
            user_home_layout_bytes(),
            "user-data",
            ownership,
        )
    )
    generated_tuple = tuple(sorted(generated, key=lambda item: item.target_ref))
    identity = {
        "backup_id": backup_id,
        "source_snapshot_digest": snapshot,
        "project_ids": list(project_ids),
        "moves": [item.mutation.plan_id for item in moves_tuple],
        "generated": [item.mutation.plan_id for item in generated_tuple],
    }
    plan_id = _sha256(_canonical_json(identity))
    return ProjectCapsuleMigrationPlan(
        plan_id,
        root,
        CapsuleMigrationBackup(backup, backup_id, backup_mutation),
        project_ids,
        moves_tuple,
        generated_tuple,
        snapshot,
    )


def _require_authorizations(
    plan: ProjectCapsuleMigrationPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> None:
    for mutation in plan.effect_plans:
        authorization = authorizations.get(mutation.plan_id)
        if (
            authorization is None
            or authorization.plan.plan_id != mutation.plan_id
            or not authorization.dry_run_verified
            or (mutation.approval_required and not authorization.approval_verified)
        ):
            raise ProjectCapsuleMigrationError(
                "every capsule migration effect requires exact authorization"
            )


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _clean_empty_parents(path: Path, root: Path) -> None:
    parent = path.parent
    while parent != root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def _rollback_partial(plan: ProjectCapsuleMigrationPlan) -> None:
    layout = plan.data_root / HOME_LAYOUT_FILE
    layout.unlink(missing_ok=True)
    for item in plan.moves:
        if not item.source.exists():
            _write_atomic(item.source, item.content)
        if item.target.exists() and item.target.is_file() and not item.target.is_symlink():
            item.target.unlink()
            _clean_empty_parents(item.target, plan.data_root)
    for item in plan.generated:
        if item.target.exists() and item.target.is_file() and not item.target.is_symlink():
            item.target.unlink()
            _clean_empty_parents(item.target, plan.data_root)


def apply_project_capsule_migration(
    plan: ProjectCapsuleMigrationPlan,
    authorizations: Mapping[str, MutationAuthorization],
    ownership: OwnershipResolver,
) -> ProjectCapsuleMigrationResult:
    """Back up, migrate, verify, and automatically roll back on failure."""

    _require_authorizations(plan, authorizations)
    try:
        current = prepare_project_capsule_migration(
            plan.data_root,
            plan.backup.archive_path,
            ownership,
        )
    except ProjectCapsuleMigrationError:
        raise
    except (OSError, ValueError) as exc:
        raise ProjectCapsuleMigrationError(
            "capsule migration source changed before apply"
        ) from exc
    if current.plan_id != plan.plan_id:
        raise ProjectCapsuleMigrationError("capsule migration plan changed before apply")

    plan.backup.archive_path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(plan.backup.archive_path, _backup_bytes(plan))
    _verify_backup(plan)

    try:
        layout_entry = next(
            item for item in plan.generated if item.target.name == HOME_LAYOUT_FILE
        )
        other_generated = tuple(
            item for item in plan.generated if item.target != layout_entry.target
        )
        for item in (*plan.moves, *other_generated):
            _write_atomic(item.target, item.content)
        for item in (*plan.moves, *other_generated):
            if _sha256(item.target.read_bytes()) != item.sha256:
                raise ProjectCapsuleMigrationError("capsule target verification failed")
        for item in plan.moves:
            if _sha256(item.source.read_bytes()) != item.sha256:
                raise ProjectCapsuleMigrationError("flat source changed during migration")
            item.source.unlink()
        _write_atomic(layout_entry.target, layout_entry.content)

        if home_layout_version(plan.data_root) != 2:
            raise ProjectCapsuleMigrationError("layout v2 marker verification failed")
        store = LocalWorkspaceStore(plan.data_root, ownership)
        if tuple(record.record_id for record in store.list_records("projects")) != plan.project_ids:
            raise ProjectCapsuleMigrationError("migrated project catalog is invalid")
        for project_id in plan.project_ids:
            if store.read("project-capsules", project_id) is None:
                raise ProjectCapsuleMigrationError("project capsule manifest is missing")
        for item in plan.moves:
            if item.source.exists() or _sha256(item.target.read_bytes()) != item.sha256:
                raise ProjectCapsuleMigrationError("capsule migration verification failed")
    except Exception:
        _rollback_partial(plan)
        raise

    verification_digest = _sha256(
        _canonical_json(
            [
                {"target_ref": item.target_ref, "sha256": item.sha256}
                for item in (*plan.moves, *plan.generated)
            ]
        )
    )
    return ProjectCapsuleMigrationResult(
        plan.plan_id,
        plan.backup.backup_id,
        len(plan.project_ids),
        len(plan.moves),
        len(plan.generated),
        verification_digest,
    )
