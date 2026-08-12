"""Exact-plan restore of a validated portable KRCN user-home backup."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .portable_backup import _assert_portable_content, _canonical_json, _is_secret_path


MAX_ARCHIVE_ENTRIES = 100_000
MAX_ARCHIVE_BYTES = 2_000_000_000


class PortableRestoreError(ValueError):
    """Raised when a portable restore archive or target is unsafe."""


@dataclass(frozen=True)
class PortableRestoreEntry:
    path: str
    ownership: str
    size: int
    sha256: str
    content: bytes


@dataclass(frozen=True)
class PortableRestorePlan:
    plan_id: str
    backup_id: str
    archive_path: Path
    target_home: Path
    archive_sha256: str
    entries: tuple[PortableRestoreEntry, ...]
    external_dependencies: tuple[dict[str, object], ...]
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "backup_id": self.backup_id,
            "archive_sha256": self.archive_sha256,
            "entry_count": len(self.entries),
            "external_dependency_count": len(self.external_dependencies),
            "rebind_required_count": sum(
                bool(item.get("rebind_required")) for item in self.external_dependencies
            ),
            "target_must_be_empty": True,
            "paths_disclosed": False,
            "mutation": self.mutation.as_dict(),
        }


@dataclass(frozen=True)
class PortableRestoreResult:
    plan_id: str
    backup_id: str
    restored_entry_count: int
    rebind_required_count: int
    verification_digest: str

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "backup_id": self.backup_id,
            "restored_entry_count": self.restored_entry_count,
            "rebind_required_count": self.rebind_required_count,
            "verification_digest": self.verification_digest,
            "existing_data_overwritten": False,
        }


def _portable_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PortableRestoreError("restore entry path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in path.parts:
        raise PortableRestoreError("restore entry path is not portable")
    return path.as_posix()


def _read_archive(
    archive_path: Path,
) -> tuple[str, tuple[PortableRestoreEntry, ...], tuple[dict[str, object], ...]]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PortableRestoreError("portable backup archive is invalid") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise PortableRestoreError("portable backup exceeds entry limit")
        if sum(item.file_size for item in infos) > MAX_ARCHIVE_BYTES:
            raise PortableRestoreError("portable backup exceeds size limit")
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise PortableRestoreError("portable backup entries are invalid")
        if any(item.flag_bits & 0x1 for item in infos):
            raise PortableRestoreError("encrypted portable backup is not supported")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise PortableRestoreError("portable backup manifest is invalid") from exc
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema_version",
            "backup_id",
            "layout_version",
            "entries",
            "external_dependencies",
            "exclusions",
        }:
            raise PortableRestoreError("portable backup manifest fields are invalid")
        layout_version = manifest.get("layout_version")
        if manifest.get("schema_version") != 1 or layout_version not in {1, 2}:
            raise PortableRestoreError("portable backup version is unsupported")
        exclusions = manifest.get("exclusions")
        if not isinstance(exclusions, dict) or not exclusions.get("secret_values") or not exclusions.get("external_source_content"):
            raise PortableRestoreError("portable backup exclusions are not trusted")
        entry_payload = manifest.get("entries")
        if not isinstance(entry_payload, list):
            raise PortableRestoreError("portable backup manifest entries are invalid")
        entries: list[PortableRestoreEntry] = []
        expected_names = {"manifest.json"}
        for item in entry_payload:
            if not isinstance(item, dict) or set(item) != {
                "path",
                "ownership",
                "size",
                "sha256",
                "transformed",
            }:
                raise PortableRestoreError("portable backup entry metadata is invalid")
            relative = _portable_path(item.get("path"))
            if _is_secret_path(relative):
                raise PortableRestoreError("portable backup contains a secret path")
            ownership = item.get("ownership")
            if ownership not in {"user-data", "runtime", "derived"}:
                raise PortableRestoreError("portable backup ownership is invalid")
            member = f"payload/{relative}"
            _portable_path(member)
            expected_names.add(member)
            try:
                content = archive.read(member)
            except KeyError as exc:
                raise PortableRestoreError("portable backup payload is missing") from exc
            size = item.get("size")
            digest = item.get("sha256")
            if size != len(content) or digest != hashlib.sha256(content).hexdigest():
                raise PortableRestoreError("portable backup payload digest is invalid")
            _assert_portable_content(relative, content)
            entries.append(PortableRestoreEntry(relative, ownership, size, digest, content))
        if set(names) != expected_names:
            raise PortableRestoreError("portable backup contains undeclared payload")
        dependencies = manifest.get("external_dependencies")
        if not isinstance(dependencies, list) or any(not isinstance(item, dict) for item in dependencies):
            raise PortableRestoreError("external dependency manifest is invalid")
        identity = {
            "layout_version": layout_version,
            "entries": entry_payload,
            "external_dependencies": dependencies,
            "excluded_secret_count": exclusions.get("excluded_secret_count"),
        }
        backup_id = hashlib.sha256(_canonical_json(identity)).hexdigest()
        if manifest.get("backup_id") != backup_id:
            raise PortableRestoreError("portable backup identity is invalid")
        return backup_id, tuple(entries), tuple(dict(item) for item in dependencies)


def _assert_empty_target(target: Path) -> None:
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise PortableRestoreError("restore target must be a regular directory")
        if any(target.iterdir()):
            raise PortableRestoreError("restore target must be empty")


def prepare_portable_restore(
    archive_path: Path,
    target_home: Path,
    ownership: OwnershipResolver,
) -> PortableRestorePlan:
    """Validate a backup and plan restoration into a new empty user home."""

    if not archive_path.is_absolute() or not target_home.is_absolute():
        raise PortableRestoreError("archive and target paths must be absolute")
    archive = archive_path.resolve()
    target = target_home.resolve(strict=False)
    if not archive.is_file() or archive.is_symlink():
        raise PortableRestoreError("portable backup archive must be a regular file")
    try:
        archive.relative_to(target)
    except ValueError:
        pass
    else:
        raise PortableRestoreError("portable backup archive must be outside restore target")
    _assert_empty_target(target)
    backup_id, entries, dependencies = _read_archive(archive)
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    target_digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()
    change_digest = hashlib.sha256(
        f"{backup_id}:{archive_digest}:{target_digest}".encode("utf-8")
    ).hexdigest()
    mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=f"portable-restores/{backup_id}",
        expected_ownership="unmanaged",
        change_digest=change_digest,
        reversible=True,
    )
    return PortableRestorePlan(
        mutation.plan_id,
        backup_id,
        archive,
        target,
        archive_digest,
        entries,
        dependencies,
        mutation,
    )


def apply_portable_restore(
    plan: PortableRestorePlan,
    authorization: MutationAuthorization,
) -> PortableRestoreResult:
    """Restore the exact archive through a staging directory and verify every file."""

    if authorization.plan.plan_id != plan.mutation.plan_id:
        raise PortableRestoreError("restore authorization does not match exact plan")
    if not authorization.dry_run_verified or not authorization.approval_verified:
        raise PortableRestoreError("portable restore requires dry-run and user approval")
    _assert_empty_target(plan.target_home)
    if hashlib.sha256(plan.archive_path.read_bytes()).hexdigest() != plan.archive_sha256:
        raise PortableRestoreError("portable backup archive changed after planning")
    backup_id, entries, dependencies = _read_archive(plan.archive_path)
    if backup_id != plan.backup_id or entries != plan.entries or dependencies != plan.external_dependencies:
        raise PortableRestoreError("portable backup plan is stale")
    plan.target_home.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{plan.target_home.name}.", dir=plan.target_home.parent))
    try:
        for entry in plan.entries:
            target = staging.joinpath(*PurePosixPath(entry.path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(entry.content)
        for entry in plan.entries:
            restored = staging.joinpath(*PurePosixPath(entry.path).parts)
            if hashlib.sha256(restored.read_bytes()).hexdigest() != entry.sha256:
                raise PortableRestoreError("restored payload verification failed")
        if plan.target_home.exists():
            plan.target_home.rmdir()
        os.replace(staging, plan.target_home)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    verification_digest = hashlib.sha256(
        _canonical_json(
            [{"path": item.path, "sha256": item.sha256} for item in plan.entries]
        )
    ).hexdigest()
    return PortableRestoreResult(
        plan.plan_id,
        plan.backup_id,
        len(plan.entries),
        sum(bool(item.get("rebind_required")) for item in plan.external_dependencies),
        verification_digest,
    )
