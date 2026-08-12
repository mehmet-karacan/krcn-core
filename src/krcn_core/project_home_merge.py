"""Exact-plan merge of project-scoped KRCN records into a shared user home."""

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

from .json_documents import canonical_json_bytes, pretty_json_bytes
from .home_layout import home_layout_version
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .portable_backup import SECRET_NAMES, SECRET_PARTS, SECRET_PATTERNS, SECRET_SUFFIXES


MERGE_TOP_LEVEL = {
    "decisions",
    "documents",
    "integrations",
    "knowledge",
    "memory",
    "policies",
    "projects",
    "source-bindings",
    "work-items",
    "workspaces",
}
BACKUP_EXCLUDED_TOP_LEVEL = {"locks", "secrets", ".secrets"}


class ProjectHomeMergeError(ValueError):
    """Raised when a shared-home merge cannot remain exact and reversible."""


def _canonical_json(payload: object) -> bytes:
    return canonical_json_bytes(payload, trailing_newline=True)


def _is_secret_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    lower_parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    return bool(
        lower_parts & SECRET_PARTS
        or name in SECRET_NAMES
        or name.startswith(".env.")
        or path.suffix.casefold() in SECRET_SUFFIXES
    )


def _assert_separate(path: Path, root: Path, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError:
        return
    raise ProjectHomeMergeError(message)


@dataclass(frozen=True)
class LocalBackupEntry:
    path: str
    size: int
    sha256: str
    content: bytes

    def manifest_entry(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class LocalHomeBackupPlan:
    backup_id: str
    home: Path
    archive_path: Path
    entries: tuple[LocalBackupEntry, ...]
    excluded_secret_count: int
    mutation: MutationPlan

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "backup_id": self.backup_id,
            "backup_kind": "local-project-home-merge",
            "entries": [entry.manifest_entry() for entry in self.entries],
            "exclusions": {
                "secret_values": True,
                "lock_files": True,
                "excluded_secret_count": self.excluded_secret_count,
            },
        }


@dataclass(frozen=True)
class MergeEntry:
    path: str
    size: int
    sha256: str
    content: bytes
    record_revision: int | None
    payload_sha256: str | None
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "record_revision": self.record_revision,
            "payload_sha256": self.payload_sha256,
            "mutation": self.mutation.as_dict(),
        }


@dataclass(frozen=True)
class ProjectHomeMergePlan:
    plan_id: str
    source_home: Path
    target_home: Path
    source_backup: LocalHomeBackupPlan
    target_backup: LocalHomeBackupPlan
    merge_entries: tuple[MergeEntry, ...]
    identical_entry_count: int
    skipped_entry_count: int
    source_snapshot_digest: str
    target_snapshot_digest: str

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return (
            self.source_backup.mutation,
            self.target_backup.mutation,
            *(entry.mutation for entry in self.merge_entries),
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-home-merge-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "source_backup_id": self.source_backup.backup_id,
            "target_backup_id": self.target_backup.backup_id,
            "merge_entry_count": len(self.merge_entries),
            "identical_entry_count": self.identical_entry_count,
            "skipped_entry_count": self.skipped_entry_count,
            "source_excluded_secret_count": self.source_backup.excluded_secret_count,
            "target_excluded_secret_count": self.target_backup.excluded_secret_count,
            "source_preserved": True,
            "target_existing_content_preserved": True,
            "project_manifest_included": False,
            "runtime_included": False,
            "derived_included": False,
            "local_data_included": False,
            "secret_values_included": False,
            "paths_disclosed": False,
            "entries": [entry.public_summary() for entry in self.merge_entries],
            "effect_plans": [effect.as_dict() for effect in self.effect_plans],
            "rollback": {
                "kind": "remove-created-records-and-use-verified-backups",
                "source_preserved": True,
                "target_backup_required_before_write": True,
                "automatic_source_delete": False,
            },
        }


@dataclass(frozen=True)
class ProjectHomeMergeResult:
    plan_id: str
    source_backup_id: str
    target_backup_id: str
    merged_entry_count: int
    identical_entry_count: int
    verification_digest: str

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "source_backup_id": self.source_backup_id,
            "target_backup_id": self.target_backup_id,
            "merged_entry_count": self.merged_entry_count,
            "identical_entry_count": self.identical_entry_count,
            "verification_digest": self.verification_digest,
            "source_preserved": True,
            "source_deleted": False,
            "target_existing_content_preserved": True,
            "rollback_ready": True,
        }


def _collect_backup_entries(home: Path) -> tuple[tuple[LocalBackupEntry, ...], int]:
    entries: list[LocalBackupEntry] = []
    excluded_secret_count = 0
    for path in sorted(home.rglob("*")):
        relative = path.relative_to(home).as_posix()
        if path.is_symlink():
            raise ProjectHomeMergeError(f"symbolic link blocks local backup: {relative}")
        if not path.is_file():
            continue
        first = PurePosixPath(relative).parts[0].casefold()
        if first == "locks":
            continue
        if first in BACKUP_EXCLUDED_TOP_LEVEL or _is_secret_path(relative):
            excluded_secret_count += 1
            continue
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            raise ProjectHomeMergeError(
                f"secret-like content blocks local backup: {relative}"
            )
        entries.append(
            LocalBackupEntry(
                relative,
                len(content),
                hashlib.sha256(content).hexdigest(),
                content,
            )
        )
    return tuple(entries), excluded_secret_count


def _snapshot_digest(entries: tuple[LocalBackupEntry, ...], excluded: int) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "entries": [entry.manifest_entry() for entry in entries],
                "excluded_secret_count": excluded,
            }
        )
    ).hexdigest()


def _prepare_local_backup(
    home: Path,
    archive_path: Path,
    ownership: OwnershipResolver,
) -> LocalHomeBackupPlan:
    entries, excluded = _collect_backup_entries(home)
    backup_id = _snapshot_digest(entries, excluded)
    archive_identity = hashlib.sha256(str(archive_path).encode("utf-8")).hexdigest()
    change_digest = hashlib.sha256(
        f"{backup_id}:{archive_identity}".encode("utf-8")
    ).hexdigest()
    mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=f"local-merge-backups/{archive_path.name}",
        expected_ownership="unmanaged",
        change_digest=change_digest,
        reversible=True,
    )
    return LocalHomeBackupPlan(
        backup_id,
        home,
        archive_path,
        entries,
        excluded,
        mutation,
    )


def _backup_bytes(plan: LocalHomeBackupPlan) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        items = [("manifest.json", pretty_json_bytes(plan.manifest()))]
        items.extend((f"payload/{entry.path}", entry.content) for entry in plan.entries)
        for name, content in items:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def _apply_local_backup(
    plan: LocalHomeBackupPlan,
    authorization: MutationAuthorization,
) -> None:
    if authorization.plan.plan_id != plan.mutation.plan_id:
        raise ProjectHomeMergeError("local backup authorization does not match plan")
    if not authorization.dry_run_verified or not authorization.approval_verified:
        raise ProjectHomeMergeError("local backup requires dry-run and approval")
    if plan.archive_path.exists():
        raise ProjectHomeMergeError("local backup archive appeared after planning")
    current_entries, current_excluded = _collect_backup_entries(plan.home)
    if _snapshot_digest(current_entries, current_excluded) != plan.backup_id:
        raise ProjectHomeMergeError("KRCN home changed after backup planning")
    plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{plan.archive_path.name}.",
        suffix=".tmp",
        dir=plan.archive_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(_backup_bytes(plan))
        os.replace(temporary, plan.archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    try:
        with zipfile.ZipFile(plan.archive_path) as archive:
            if archive.testzip() is not None:
                raise ProjectHomeMergeError("local backup archive verification failed")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("backup_id") != plan.backup_id:
                raise ProjectHomeMergeError("local backup identity verification failed")
            for entry in plan.entries:
                content = archive.read(f"payload/{entry.path}")
                if hashlib.sha256(content).hexdigest() != entry.sha256:
                    raise ProjectHomeMergeError("local backup payload verification failed")
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ProjectHomeMergeError("local backup archive verification failed") from exc


def _record_metadata(content: bytes) -> tuple[int | None, str | None]:
    try:
        envelope = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(envelope, dict):
        return None, None
    revision = envelope.get("revision")
    payload_sha256 = envelope.get("payload_sha256")
    if not isinstance(revision, int) or isinstance(revision, bool):
        revision = None
    if not isinstance(payload_sha256, str) or len(payload_sha256) != 64:
        payload_sha256 = None
    return revision, payload_sha256


def _merge_source_entries(home: Path) -> tuple[LocalBackupEntry, ...]:
    entries: list[LocalBackupEntry] = []
    for path in sorted(home.rglob("*")):
        relative = path.relative_to(home).as_posix()
        if path.is_symlink():
            raise ProjectHomeMergeError(f"symbolic link blocks merge: {relative}")
        if not path.is_file():
            continue
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] not in MERGE_TOP_LEVEL or parts[0] == "local-data":
            continue
        if (
            len(parts) >= 3
            and parts[0] == "projects"
            and parts[2] in {"derived", "runtime", "local-data", "secrets"}
        ):
            continue
        if _is_secret_path(relative):
            continue
        content = path.read_bytes()
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            raise ProjectHomeMergeError(f"secret-like content blocks merge: {relative}")
        entries.append(
            LocalBackupEntry(
                relative,
                len(content),
                hashlib.sha256(content).hexdigest(),
                content,
            )
        )
    return tuple(entries)


def prepare_project_home_merge(
    source_home: Path,
    target_home: Path,
    backup_directory: Path,
    ownership: OwnershipResolver,
) -> ProjectHomeMergePlan:
    """Plan a conflict-free source-preserving merge into an existing user home."""

    if not all(path.is_absolute() for path in (source_home, target_home, backup_directory)):
        raise ProjectHomeMergeError("merge paths must be absolute")
    source = source_home.resolve()
    target = target_home.resolve()
    backup_root = backup_directory.resolve(strict=False)
    for home, label in ((source, "source"), (target, "target")):
        if not home.is_dir() or home.is_symlink():
            raise ProjectHomeMergeError(f"merge {label} must be a regular directory")
    if source == target:
        raise ProjectHomeMergeError("merge source and target must differ")
    if home_layout_version(source) >= 2 and home_layout_version(target) < 2:
        raise ProjectHomeMergeError(
            "layout v2 project capsules require a layout v2 merge target"
        )
    _assert_separate(target, source, "merge target must be outside source home")
    _assert_separate(source, target, "merge source must be outside target home")
    _assert_separate(backup_root, source, "merge backup must be outside source home")
    _assert_separate(backup_root, target, "merge backup must be outside target home")
    if backup_root.exists():
        raise ProjectHomeMergeError("merge backup directory must not already exist")

    source_backup = _prepare_local_backup(
        source,
        backup_root / "source-home-backup.zip",
        ownership,
    )
    target_backup = _prepare_local_backup(
        target,
        backup_root / "target-home-backup.zip",
        ownership,
    )
    source_snapshot = _snapshot_digest(
        source_backup.entries,
        source_backup.excluded_secret_count,
    )
    target_snapshot = _snapshot_digest(
        target_backup.entries,
        target_backup.excluded_secret_count,
    )

    merge_entries: list[MergeEntry] = []
    identical = 0
    selected = _merge_source_entries(source)
    for entry in selected:
        destination = target.joinpath(*PurePosixPath(entry.path).parts)
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise ProjectHomeMergeError(f"merge target is unsafe: {entry.path}")
            target_content = destination.read_bytes()
            if target_content == entry.content:
                identical += 1
                continue
            source_revision, source_payload = _record_metadata(entry.content)
            target_revision, target_payload = _record_metadata(target_content)
            raise ProjectHomeMergeError(
                "merge conflict for "
                f"{entry.path}: source revision/hash {source_revision}/{source_payload}, "
                f"target revision/hash {target_revision}/{target_payload}"
            )
        revision, payload_sha256 = _record_metadata(entry.content)
        mutation = plan_mutation(
            ownership,
            operation="create",
            target_ref=f".krcn/{entry.path}",
            change_digest=entry.sha256,
            reversible=True,
        )
        if mutation.ownership != "user-data":
            raise ProjectHomeMergeError("merge entry is outside user-data ownership")
        merge_entries.append(
            MergeEntry(
                entry.path,
                entry.size,
                entry.sha256,
                entry.content,
                revision,
                payload_sha256,
                mutation,
            )
        )

    skipped = len(source_backup.entries) - len(selected)
    identity = {
        "source_snapshot_digest": source_snapshot,
        "target_snapshot_digest": target_snapshot,
        "source_backup_id": source_backup.backup_id,
        "target_backup_id": target_backup.backup_id,
        "merge_entries": [
            {"path": entry.path, "sha256": entry.sha256, "plan_id": entry.mutation.plan_id}
            for entry in merge_entries
        ],
        "identical_entry_count": identical,
        "skipped_entry_count": skipped,
    }
    plan_id = hashlib.sha256(_canonical_json(identity)).hexdigest()
    return ProjectHomeMergePlan(
        plan_id,
        source,
        target,
        source_backup,
        target_backup,
        tuple(merge_entries),
        identical,
        skipped,
        source_snapshot,
        target_snapshot,
    )


def _require_authorizations(
    effects: tuple[MutationPlan, ...],
    authorizations: Mapping[str, MutationAuthorization],
) -> None:
    for mutation in effects:
        authorization = authorizations.get(mutation.plan_id)
        if (
            authorization is None
            or authorization.plan.plan_id != mutation.plan_id
            or not authorization.dry_run_verified
            or (mutation.approval_required and not authorization.approval_verified)
        ):
            raise ProjectHomeMergeError("every merge effect requires exact authorization")


def _remove_created_files(paths: list[Path], target_home: Path) -> None:
    for path in reversed(paths):
        if path.is_file() and not path.is_symlink():
            path.unlink()
        parent = path.parent
        while parent != target_home and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


def apply_project_home_merge(
    plan: ProjectHomeMergePlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> ProjectHomeMergeResult:
    """Write both backups first, then add only conflict-free user-data records."""

    _require_authorizations(plan.effect_plans, authorizations)
    _apply_local_backup(
        plan.source_backup,
        authorizations[plan.source_backup.mutation.plan_id],
    )
    _apply_local_backup(
        plan.target_backup,
        authorizations[plan.target_backup.mutation.plan_id],
    )

    current_source, current_source_excluded = _collect_backup_entries(plan.source_home)
    current_target, current_target_excluded = _collect_backup_entries(plan.target_home)
    if _snapshot_digest(current_source, current_source_excluded) != plan.source_snapshot_digest:
        raise ProjectHomeMergeError("merge source changed after planning")
    if _snapshot_digest(current_target, current_target_excluded) != plan.target_snapshot_digest:
        raise ProjectHomeMergeError("merge target changed after planning")

    created: list[Path] = []
    try:
        for entry in plan.merge_entries:
            target = plan.target_home.joinpath(*PurePosixPath(entry.path).parts)
            if target.exists():
                raise ProjectHomeMergeError("merge target appeared after planning")
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                temporary.write_bytes(entry.content)
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
            created.append(target)
        for entry in plan.merge_entries:
            restored = plan.target_home.joinpath(*PurePosixPath(entry.path).parts)
            if hashlib.sha256(restored.read_bytes()).hexdigest() != entry.sha256:
                raise ProjectHomeMergeError("merged record verification failed")
    except Exception:
        _remove_created_files(created, plan.target_home)
        raise

    verification_digest = hashlib.sha256(
        _canonical_json(
            [{"path": entry.path, "sha256": entry.sha256} for entry in plan.merge_entries]
        )
    ).hexdigest()
    return ProjectHomeMergeResult(
        plan.plan_id,
        plan.source_backup.backup_id,
        plan.target_backup.backup_id,
        len(plan.merge_entries),
        plan.identical_entry_count,
        verification_digest,
    )
