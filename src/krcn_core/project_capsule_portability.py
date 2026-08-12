"""Secret-safe export and conflict-free import of one project capsule."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from .home_layout import home_layout_version, project_capsule_root
from .json_documents import canonical_json_bytes, pretty_json_bytes
from .local_store import LocalWorkspaceStore
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .portable_backup import (
    _assert_portable_content,
    _is_secret_path,
    _sanitize_source_binding,
)


CAPSULE_FORMAT_VERSION = 1
CAPSULE_MODES = {"thin", "ready"}
MAX_CAPSULE_ENTRIES = 100_000
MAX_CAPSULE_BYTES = 2_000_000_000
NON_PORTABLE_RUNTIME_PREFIXES = (
    "runtime/queue/",
    "runtime/leases/",
    "runtime/active/",
)


class ProjectCapsulePortabilityError(ValueError):
    """Raised when a project capsule cannot be exported or imported safely."""


def _canonical_json(payload: object) -> bytes:
    return canonical_json_bytes(payload, trailing_newline=True)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _portable_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ProjectCapsulePortabilityError("capsule entry path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in path.parts:
        raise ProjectCapsulePortabilityError("capsule entry path is not portable")
    return path.as_posix()


def _verify_sqlite(content: bytes, label: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".krcn-capsule-", suffix=".sqlite")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(content)
        connection = sqlite3.connect(temporary.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ProjectCapsulePortabilityError(
                    f"derived SQLite entry is corrupt: {label}"
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ProjectCapsulePortabilityError(
            f"derived SQLite entry is invalid: {label}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ProjectCapsuleEntry:
    path: str
    ownership: str
    content: bytes
    sha256: str
    transformed: bool

    def manifest_entry(self) -> dict[str, object]:
        return {
            "path": self.path,
            "ownership": self.ownership,
            "size": len(self.content),
            "sha256": self.sha256,
            "transformed": self.transformed,
        }


@dataclass(frozen=True)
class ProjectCapsuleExportPlan:
    plan_id: str
    project_id: str
    mode: str
    capsule_root: Path
    archive_path: Path
    capsule_id: str
    entries: tuple[ProjectCapsuleEntry, ...]
    external_dependencies: tuple[dict[str, object], ...]
    excluded_derived_count: int
    excluded_runtime_count: int
    mutation: MutationPlan

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "capsule_format_version": CAPSULE_FORMAT_VERSION,
            "capsule_id": self.capsule_id,
            "project_id": self.project_id,
            "mode": self.mode,
            "entries": [item.manifest_entry() for item in self.entries],
            "external_dependencies": list(self.external_dependencies),
            "exclusions": {
                "source_content": True,
                "secret_values": True,
                "machine_locators": True,
                "active_locks": True,
                "active_runtime_ownership": True,
                "excluded_derived_count": self.excluded_derived_count,
                "excluded_runtime_count": self.excluded_runtime_count,
            },
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-capsule-export-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "capsule_id": self.capsule_id,
            "project_id": self.project_id,
            "mode": self.mode,
            "entry_count": len(self.entries),
            "external_dependency_count": len(self.external_dependencies),
            "excluded_derived_count": self.excluded_derived_count,
            "excluded_runtime_count": self.excluded_runtime_count,
            "source_content_included": False,
            "secret_values_included": False,
            "machine_locators_included": False,
            "paths_disclosed": False,
            "mutation": self.mutation.as_dict(),
        }


@dataclass(frozen=True)
class ProjectCapsuleExportResult:
    plan_id: str
    capsule_id: str
    archive_sha256: str
    entry_count: int

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "capsule_id": self.capsule_id,
            "archive_sha256": self.archive_sha256,
            "entry_count": self.entry_count,
            "source_content_included": False,
            "secret_values_included": False,
        }


def _entry_ownership(relative: str) -> str:
    first = PurePosixPath(relative).parts[0]
    if first == "derived":
        return "derived"
    if first == "runtime":
        return "runtime"
    return "user-data"


def _collect_capsule_entries(
    capsule_root: Path,
    mode: str,
) -> tuple[
    tuple[ProjectCapsuleEntry, ...],
    tuple[dict[str, object], ...],
    int,
    int,
]:
    if mode not in CAPSULE_MODES:
        raise ProjectCapsulePortabilityError("capsule mode is invalid")
    entries = []
    dependencies = []
    excluded_derived = 0
    excluded_runtime = 0
    for path in sorted(capsule_root.rglob("*")):
        relative = path.relative_to(capsule_root).as_posix()
        if path.is_symlink():
            raise ProjectCapsulePortabilityError(
                f"symbolic link blocks capsule export: {relative}"
            )
        if not path.is_file():
            continue
        if _is_secret_path(relative):
            raise ProjectCapsulePortabilityError("secret path blocks capsule export")
        if (
            relative.startswith("derived/")
            and not relative.startswith("derived/source-states/")
            and mode == "thin"
        ):
            excluded_derived += 1
            continue
        if relative.startswith("runtime/") and (
            mode == "thin"
            or any(relative.startswith(prefix) for prefix in NON_PORTABLE_RUNTIME_PREFIXES)
        ):
            excluded_runtime += 1
            continue
        content = path.read_bytes()
        sanitized, dependency = _sanitize_source_binding(content)
        transformed = dependency is not None
        if dependency is not None:
            dependencies.append(dependency)
        _assert_portable_content(relative, sanitized)
        if relative.endswith(".sqlite"):
            _verify_sqlite(sanitized, relative)
        entries.append(
            ProjectCapsuleEntry(
                relative,
                _entry_ownership(relative),
                sanitized,
                _sha256(sanitized),
                transformed,
            )
        )
    dependencies.sort(key=lambda item: str(item.get("binding_id")))
    return (
        tuple(entries),
        tuple(dependencies),
        excluded_derived,
        excluded_runtime,
    )


def _capsule_identity(
    project_id: str,
    mode: str,
    entries: tuple[ProjectCapsuleEntry, ...],
    dependencies: tuple[dict[str, object], ...],
    excluded_derived: int,
    excluded_runtime: int,
) -> str:
    return _sha256(
        _canonical_json(
            {
                "capsule_format_version": CAPSULE_FORMAT_VERSION,
                "project_id": project_id,
                "mode": mode,
                "entries": [item.manifest_entry() for item in entries],
                "external_dependencies": list(dependencies),
                "excluded_derived_count": excluded_derived,
                "excluded_runtime_count": excluded_runtime,
            }
        )
    )


def prepare_project_capsule_export(
    data_root: Path,
    project_id: str,
    archive_path: Path,
    mode: str,
    ownership: OwnershipResolver,
) -> ProjectCapsuleExportPlan:
    """Plan one sanitized project capsule archive without writing it."""

    if not data_root.is_absolute() or not archive_path.is_absolute():
        raise ProjectCapsulePortabilityError("capsule export paths must be absolute")
    root = data_root.resolve()
    if home_layout_version(root) != 2:
        raise ProjectCapsulePortabilityError("capsule export requires layout v2")
    store = LocalWorkspaceStore(root, ownership)
    project = store.read("projects", project_id)
    manifest = store.read("project-capsules", project_id)
    if project is None or manifest is None:
        raise ProjectCapsulePortabilityError("project capsule is incomplete")
    capsule_root = project_capsule_root(root, project_id)
    if not capsule_root.is_dir() or capsule_root.is_symlink():
        raise ProjectCapsulePortabilityError("project capsule must be a regular directory")
    archive = archive_path.resolve(strict=False)
    try:
        archive.relative_to(root)
    except ValueError:
        pass
    else:
        raise ProjectCapsulePortabilityError("capsule archive must be outside KRCN home")
    if archive.exists():
        raise ProjectCapsulePortabilityError("capsule archive already exists")
    entries, dependencies, excluded_derived, excluded_runtime = _collect_capsule_entries(
        capsule_root,
        mode,
    )
    capsule_id = _capsule_identity(
        project_id,
        mode,
        entries,
        dependencies,
        excluded_derived,
        excluded_runtime,
    )
    mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=f"project-capsule-exports/{archive.name}",
        expected_ownership="unmanaged",
        change_digest=_sha256(
            f"{capsule_id}:{_sha256(str(archive).encode('utf-8'))}".encode("utf-8")
        ),
        reversible=True,
    )
    return ProjectCapsuleExportPlan(
        mutation.plan_id,
        project_id,
        mode,
        capsule_root,
        archive,
        capsule_id,
        entries,
        dependencies,
        excluded_derived,
        excluded_runtime,
        mutation,
    )


def _archive_bytes(plan: ProjectCapsuleExportPlan) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        items = [("manifest.json", pretty_json_bytes(plan.manifest()))]
        items.extend((f"payload/{item.path}", item.content) for item in plan.entries)
        for name, content in items:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def apply_project_capsule_export(
    plan: ProjectCapsuleExportPlan,
    authorization: MutationAuthorization,
) -> ProjectCapsuleExportResult:
    if authorization.plan.plan_id != plan.mutation.plan_id:
        raise ProjectCapsulePortabilityError("capsule export authorization is invalid")
    if not authorization.dry_run_verified or not authorization.approval_verified:
        raise ProjectCapsulePortabilityError("capsule export requires approval")
    if plan.archive_path.exists():
        raise ProjectCapsulePortabilityError("capsule archive appeared after planning")
    current = _collect_capsule_entries(plan.capsule_root, plan.mode)
    if _capsule_identity(plan.project_id, plan.mode, *current) != plan.capsule_id:
        raise ProjectCapsulePortabilityError("project capsule changed after planning")
    plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{plan.archive_path.name}.",
        suffix=".tmp",
        dir=plan.archive_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(_archive_bytes(plan))
        os.replace(temporary, plan.archive_path)
    finally:
        temporary.unlink(missing_ok=True)
    archive_digest = _sha256(plan.archive_path.read_bytes())
    return ProjectCapsuleExportResult(
        plan.plan_id,
        plan.capsule_id,
        archive_digest,
        len(plan.entries),
    )


@dataclass(frozen=True)
class ProjectCapsuleImportEntry:
    path: str
    ownership: str
    content: bytes
    sha256: str
    target: Path
    mutation: MutationPlan


@dataclass(frozen=True)
class ProjectCapsuleImportPlan:
    plan_id: str
    archive_path: Path
    archive_sha256: str
    data_root: Path
    project_id: str
    mode: str
    capsule_id: str
    entries: tuple[ProjectCapsuleImportEntry, ...]
    external_dependencies: tuple[dict[str, object], ...]

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        return tuple(item.mutation for item in self.entries)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-capsule-import-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "capsule_id": self.capsule_id,
            "project_id": self.project_id,
            "mode": self.mode,
            "entry_count": len(self.entries),
            "external_dependency_count": len(self.external_dependencies),
            "rebind_required_count": sum(
                bool(item.get("rebind_required")) for item in self.external_dependencies
            ),
            "source_content_included": False,
            "secret_values_included": False,
            "existing_project_overwritten": False,
            "paths_disclosed": False,
            "effect_plans": [item.as_dict() for item in self.effect_plans],
        }


@dataclass(frozen=True)
class ProjectCapsuleImportResult:
    plan_id: str
    capsule_id: str
    project_id: str
    restored_entry_count: int
    rebind_required_count: int
    verification_digest: str

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "capsule_id": self.capsule_id,
            "project_id": self.project_id,
            "restored_entry_count": self.restored_entry_count,
            "rebind_required_count": self.rebind_required_count,
            "verification_digest": self.verification_digest,
            "existing_project_overwritten": False,
        }


def _read_archive(
    archive_path: Path,
) -> tuple[
    str,
    str,
    str,
    tuple[ProjectCapsuleEntry, ...],
    tuple[dict[str, object], ...],
    int,
    int,
]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProjectCapsulePortabilityError("project capsule archive is invalid") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_CAPSULE_ENTRIES:
            raise ProjectCapsulePortabilityError("project capsule exceeds entry limit")
        if sum(item.file_size for item in infos) > MAX_CAPSULE_BYTES:
            raise ProjectCapsulePortabilityError("project capsule exceeds size limit")
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ProjectCapsulePortabilityError("project capsule entries are invalid")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectCapsulePortabilityError("project capsule manifest is invalid") from exc
        required = {
            "schema_version",
            "capsule_format_version",
            "capsule_id",
            "project_id",
            "mode",
            "entries",
            "external_dependencies",
            "exclusions",
        }
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise ProjectCapsulePortabilityError("project capsule manifest fields are invalid")
        project_id = manifest.get("project_id")
        mode = manifest.get("mode")
        if (
            manifest.get("schema_version") != 1
            or manifest.get("capsule_format_version") != CAPSULE_FORMAT_VERSION
            or mode not in CAPSULE_MODES
            or not isinstance(project_id, str)
        ):
            raise ProjectCapsulePortabilityError("project capsule identity is invalid")
        exclusions = manifest.get("exclusions")
        if (
            not isinstance(exclusions, dict)
            or exclusions.get("source_content") is not True
            or exclusions.get("secret_values") is not True
            or exclusions.get("machine_locators") is not True
            or exclusions.get("active_locks") is not True
            or exclusions.get("active_runtime_ownership") is not True
        ):
            raise ProjectCapsulePortabilityError("project capsule exclusions are invalid")
        entry_payload = manifest.get("entries")
        if not isinstance(entry_payload, list):
            raise ProjectCapsulePortabilityError("project capsule entries are invalid")
        entries = []
        expected_names = {"manifest.json"}
        for item in entry_payload:
            if not isinstance(item, dict) or set(item) != {
                "path",
                "ownership",
                "size",
                "sha256",
                "transformed",
            }:
                raise ProjectCapsulePortabilityError("capsule entry metadata is invalid")
            relative = _portable_path(item.get("path"))
            if _is_secret_path(relative):
                raise ProjectCapsulePortabilityError("project capsule contains secret path")
            ownership = item.get("ownership")
            if ownership not in {"user-data", "runtime", "derived"}:
                raise ProjectCapsulePortabilityError("capsule ownership is invalid")
            member = f"payload/{relative}"
            expected_names.add(member)
            try:
                content = archive.read(member)
            except KeyError as exc:
                raise ProjectCapsulePortabilityError("capsule payload is missing") from exc
            if item.get("size") != len(content) or item.get("sha256") != _sha256(content):
                raise ProjectCapsulePortabilityError("capsule payload digest is invalid")
            _assert_portable_content(relative, content)
            if relative.endswith(".sqlite"):
                _verify_sqlite(content, relative)
            entries.append(
                ProjectCapsuleEntry(
                    relative,
                    str(ownership),
                    content,
                    str(item.get("sha256")),
                    bool(item.get("transformed")),
                )
            )
        if set(names) != expected_names:
            raise ProjectCapsulePortabilityError("capsule contains undeclared payload")
        dependencies = manifest.get("external_dependencies")
        if not isinstance(dependencies, list) or any(
            not isinstance(item, dict) for item in dependencies
        ):
            raise ProjectCapsulePortabilityError("capsule dependencies are invalid")
        excluded_derived = exclusions.get("excluded_derived_count")
        excluded_runtime = exclusions.get("excluded_runtime_count")
        if (
            not isinstance(excluded_derived, int)
            or isinstance(excluded_derived, bool)
            or excluded_derived < 0
            or not isinstance(excluded_runtime, int)
            or isinstance(excluded_runtime, bool)
            or excluded_runtime < 0
        ):
            raise ProjectCapsulePortabilityError("capsule exclusion counts are invalid")
        entries_tuple = tuple(entries)
        dependencies_tuple = tuple(dict(item) for item in dependencies)
        capsule_id = _capsule_identity(
            project_id,
            mode,
            entries_tuple,
            dependencies_tuple,
            excluded_derived,
            excluded_runtime,
        )
        if manifest.get("capsule_id") != capsule_id:
            raise ProjectCapsulePortabilityError("project capsule identity is invalid")
        return (
            capsule_id,
            project_id,
            mode,
            entries_tuple,
            dependencies_tuple,
            excluded_derived,
            excluded_runtime,
        )


def prepare_project_capsule_import(
    archive_path: Path,
    data_root: Path,
    ownership: OwnershipResolver,
) -> ProjectCapsuleImportPlan:
    """Plan a conflict-free capsule import into an existing layout v2 home."""

    if not archive_path.is_absolute() or not data_root.is_absolute():
        raise ProjectCapsulePortabilityError("capsule import paths must be absolute")
    archive = archive_path.resolve()
    root = data_root.resolve()
    if not archive.is_file() or archive.is_symlink():
        raise ProjectCapsulePortabilityError("capsule archive must be a regular file")
    if home_layout_version(root) != 2:
        raise ProjectCapsulePortabilityError("capsule import requires layout v2")
    capsule_id, project_id, mode, entries, dependencies, _, _ = _read_archive(archive)
    capsule_root = project_capsule_root(root, project_id)
    if capsule_root.exists():
        raise ProjectCapsulePortabilityError("project capsule already exists")
    import_entries = []
    for entry in entries:
        target = capsule_root.joinpath(*PurePosixPath(entry.path).parts)
        target_ref = f".krcn/projects/{project_id}/{entry.path}"
        mutation = plan_mutation(
            ownership,
            operation="create",
            target_ref=target_ref,
            expected_ownership=entry.ownership,
            change_digest=entry.sha256,
            reversible=True,
        )
        import_entries.append(
            ProjectCapsuleImportEntry(
                entry.path,
                entry.ownership,
                entry.content,
                entry.sha256,
                target,
                mutation,
            )
        )
    archive_sha256 = _sha256(archive.read_bytes())
    identity = {
        "capsule_id": capsule_id,
        "archive_sha256": archive_sha256,
        "project_id": project_id,
        "effects": [item.mutation.plan_id for item in import_entries],
    }
    plan_id = _sha256(_canonical_json(identity))
    return ProjectCapsuleImportPlan(
        plan_id,
        archive,
        archive_sha256,
        root,
        project_id,
        mode,
        capsule_id,
        tuple(import_entries),
        dependencies,
    )


def _require_import_authorizations(
    plan: ProjectCapsuleImportPlan,
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
            raise ProjectCapsulePortabilityError(
                "every capsule import effect requires exact authorization"
            )


def apply_project_capsule_import(
    plan: ProjectCapsuleImportPlan,
    authorizations: Mapping[str, MutationAuthorization],
    ownership: OwnershipResolver,
) -> ProjectCapsuleImportResult:
    _require_import_authorizations(plan, authorizations)
    if _sha256(plan.archive_path.read_bytes()) != plan.archive_sha256:
        raise ProjectCapsulePortabilityError("capsule archive changed after planning")
    current = prepare_project_capsule_import(plan.archive_path, plan.data_root, ownership)
    if current.plan_id != plan.plan_id:
        raise ProjectCapsulePortabilityError("capsule import plan changed before apply")
    capsule_root = project_capsule_root(plan.data_root, plan.project_id)
    capsule_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{plan.project_id}.", dir=capsule_root.parent)
    )
    try:
        for entry in plan.entries:
            target = staging.joinpath(*PurePosixPath(entry.path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(entry.content)
        for entry in plan.entries:
            restored = staging.joinpath(*PurePosixPath(entry.path).parts)
            if _sha256(restored.read_bytes()) != entry.sha256:
                raise ProjectCapsulePortabilityError("restored capsule entry is invalid")
        os.replace(staging, capsule_root)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    store = LocalWorkspaceStore(plan.data_root, ownership)
    if (
        store.read("projects", plan.project_id) is None
        or store.read("project-capsules", plan.project_id) is None
    ):
        shutil.rmtree(capsule_root)
        raise ProjectCapsulePortabilityError("imported project capsule is incomplete")
    verification_digest = _sha256(
        _canonical_json(
            [{"path": item.path, "sha256": item.sha256} for item in plan.entries]
        )
    )
    return ProjectCapsuleImportResult(
        plan.plan_id,
        plan.capsule_id,
        plan.project_id,
        len(plan.entries),
        sum(bool(item.get("rebind_required")) for item in plan.external_dependencies),
        verification_digest,
    )
