"""Read-only inspection of a local KRCN Core installation."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from .mutation_gate import OwnershipResolver


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
RELEASE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9.-]*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
INCOMPLETE_DEPLOYMENT_STATUSES = {
    "preparing",
    "backing-up",
    "backed-up",
    "applying",
    "migrating",
    "rebuilding",
    "verifying",
    "rolling-back",
}


class InstallationError(ValueError):
    """Raised when installation state is invalid or unsafe to inspect."""


@dataclass(frozen=True)
class ManagedFile:
    path: str
    sha256: str
    size: int

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class InstallationState:
    installation_id: str
    core_version: str
    release_id: str
    source_commit: str
    managed_files: tuple[ManagedFile, ...]
    schema_versions: Mapping[str, int]
    completed_migrations: tuple[str, ...]
    pending_derived_actions: tuple[str, ...]
    revision: int

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/installation-state.schema.json",
            "schema_version": 1,
            "installation_id": self.installation_id,
            "core_version": self.core_version,
            "release_id": self.release_id,
            "source_commit": self.source_commit,
            "managed_files": [item.as_dict() for item in self.managed_files],
            "schema_versions": dict(self.schema_versions),
            "completed_migrations": list(self.completed_migrations),
            "pending_derived_actions": list(self.pending_derived_actions),
            "revision": self.revision,
        }


@dataclass(frozen=True)
class InstallationInspection:
    inspection_id: str
    state_present: bool
    installation_id: str | None
    core_version: str | None
    release_id: str | None
    state_revision: int | None
    state_sha256: str | None
    managed_verified: tuple[str, ...]
    managed_missing: tuple[str, ...]
    managed_modified: tuple[str, ...]
    ownership_counts: Mapping[str, int]
    symlink_count: int
    interrupted_deployments: tuple[Mapping[str, str], ...]

    @property
    def managed_clean(self) -> bool:
        return not self.managed_missing and not self.managed_modified

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "inspection_id": self.inspection_id,
            "state_present": self.state_present,
            "installation_id": self.installation_id,
            "core_version": self.core_version,
            "release_id": self.release_id,
            "state_revision": self.state_revision,
            "state_sha256": self.state_sha256,
            "managed_clean": self.managed_clean,
            "managed_files": {
                "verified": list(self.managed_verified),
                "missing": list(self.managed_missing),
                "modified": list(self.managed_modified),
            },
            "ownership_counts": dict(self.ownership_counts),
            "symlink_count": self.symlink_count,
            "interrupted_deployments": [
                dict(item) for item in self.interrupted_deployments
            ],
        }


def _portable_path(value: object, label: str = "path") -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise InstallationError(f"{label} must be a portable relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ".." in path.parts
        or "." in path.parts
    ):
        raise InstallationError(f"{label} must stay within the installation")
    return path.as_posix()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise InstallationError(f"{label} must be a portable identifier")
    return value


def _unique_identifiers(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise InstallationError(f"{label} must be a list")
    result = tuple(_identifier(item, label) for item in value)
    if len(set(result)) != len(result):
        raise InstallationError(f"{label} must be unique")
    return result


def parse_installation_state(payload: object) -> InstallationState:
    """Validate a local installation state document."""

    if not isinstance(payload, dict):
        raise InstallationError("installation state must be an object")
    expected_fields = {
        "schema_ref",
        "schema_version",
        "installation_id",
        "core_version",
        "release_id",
        "source_commit",
        "managed_files",
        "schema_versions",
        "completed_migrations",
        "pending_derived_actions",
        "revision",
    }
    if set(payload) != expected_fields:
        raise InstallationError("installation state fields are invalid")
    if payload.get("schema_ref") != "schemas/installation-state.schema.json":
        raise InstallationError("installation state schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise InstallationError("installation state schema version must be 1")
    installation_id = _identifier(payload.get("installation_id"), "installation id")
    core_version = payload.get("core_version")
    if not isinstance(core_version, str) or not SEMVER.fullmatch(core_version):
        raise InstallationError("installation core version is invalid")
    release_id = payload.get("release_id")
    if not isinstance(release_id, str) or not RELEASE_IDENTIFIER.fullmatch(release_id):
        raise InstallationError("installation release id is invalid")
    source_commit = payload.get("source_commit")
    if not isinstance(source_commit, str) or not COMMIT.fullmatch(source_commit):
        raise InstallationError("installation source commit is invalid")
    files_payload = payload.get("managed_files")
    if not isinstance(files_payload, list):
        raise InstallationError("managed files must be a list")
    managed_files: list[ManagedFile] = []
    seen_paths: set[str] = set()
    for item in files_payload:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise InstallationError("managed file entry is invalid")
        path = _portable_path(item.get("path"), "managed file path")
        if path in seen_paths:
            raise InstallationError("managed file paths must be unique")
        seen_paths.add(path)
        sha256 = item.get("sha256")
        size = item.get("size")
        if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
            raise InstallationError("managed file hash is invalid")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise InstallationError("managed file size is invalid")
        managed_files.append(ManagedFile(path, sha256, size))
    schema_versions = payload.get("schema_versions")
    if not isinstance(schema_versions, dict):
        raise InstallationError("schema versions must be an object")
    parsed_versions: dict[str, int] = {}
    for name, version in schema_versions.items():
        parsed_name = _identifier(name, "schema version name")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise InstallationError("schema version must be positive")
        parsed_versions[parsed_name] = version
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise InstallationError("installation state revision must be positive")
    return InstallationState(
        installation_id=installation_id,
        core_version=core_version,
        release_id=release_id,
        source_commit=source_commit,
        managed_files=tuple(sorted(managed_files, key=lambda item: item.path)),
        schema_versions=parsed_versions,
        completed_migrations=_unique_identifiers(
            payload.get("completed_migrations"),
            "completed migrations",
        ),
        pending_derived_actions=_unique_identifiers(
            payload.get("pending_derived_actions"),
            "pending derived actions",
        ),
        revision=revision,
    )


def _canonical_sha256(payload: object) -> str:
    document = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(document).hexdigest()


def installation_state_sha256(state: InstallationState) -> str:
    """Return the canonical digest used to bind installation state mutations."""

    return _canonical_sha256(state.as_payload())


def _stable_file_hash(path: Path) -> tuple[int, str]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise InstallationError("installation file changed during inspection")
    return after.st_size, digest.hexdigest()


def _safe_installation_root(root: Path) -> Path:
    if not root.is_absolute():
        raise InstallationError("installation root must be absolute")
    if root.is_symlink():
        raise InstallationError("installation root may not be a symbolic link")
    resolved = root.resolve()
    if not resolved.is_dir():
        raise InstallationError("installation root must be an existing directory")
    return resolved


def safe_installation_target(root: Path, relative_path: str) -> Path:
    """Resolve a portable path without accepting symlink traversal."""

    portable = _portable_path(relative_path)
    candidate = root.joinpath(*PurePosixPath(portable).parts)
    current = root
    for part in PurePosixPath(portable).parts:
        current = current / part
        if current.is_symlink():
            raise InstallationError("installation path may not use symbolic links")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise InstallationError("installation path escapes the root") from exc
    return candidate


def load_installation_state(root: Path) -> tuple[InstallationState | None, str | None]:
    state_path = safe_installation_target(
        root,
        ".krcn/runtime/installation-state.json",
    )
    if not state_path.exists():
        return None, None
    if not state_path.is_file():
        raise InstallationError("installation state must be a regular file")
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallationError("installation state JSON is invalid") from exc
    return parse_installation_state(payload), _canonical_sha256(payload)


def _ownership_counts(
    root: Path,
    ownership: OwnershipResolver,
) -> tuple[dict[str, int], int]:
    counts = {
        "core": 0,
        "runtime": 0,
        "user-data": 0,
        "derived": 0,
        "secrets": 0,
        "unmanaged": 0,
    }
    symlink_count = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        retained_directories = []
        for name in directory_names:
            path = directory_path / name
            if path.is_symlink():
                symlink_count += 1
            else:
                retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in file_names:
            path = directory_path / name
            if path.is_symlink():
                symlink_count += 1
                continue
            relative = path.relative_to(root).as_posix()
            counts[ownership.resolve(relative)] += 1
    return counts, symlink_count


def _interrupted_deployments(root: Path) -> tuple[Mapping[str, str], ...]:
    directory = safe_installation_target(root, ".krcn/runtime/deployments")
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise InstallationError("deployment journal location must be a directory")
    interrupted = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink():
            raise InstallationError("deployment journal may not be a symbolic link")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InstallationError("deployment journal JSON is invalid") from exc
        if not isinstance(payload, dict):
            raise InstallationError("deployment journal must be an object")
        deployment_id = payload.get("deployment_id")
        status = payload.get("status")
        if (
            not isinstance(deployment_id, str)
            or not IDENTIFIER.fullmatch(deployment_id)
            or not isinstance(status, str)
            or not IDENTIFIER.fullmatch(status)
        ):
            raise InstallationError("deployment journal identity is invalid")
        if status in INCOMPLETE_DEPLOYMENT_STATUSES:
            interrupted.append(
                {"deployment_id": deployment_id, "status": status}
            )
    return tuple(interrupted)


def inspect_installation(
    installation_root: Path,
    ownership: OwnershipResolver,
) -> InstallationInspection:
    """Inspect managed integrity and ownership without changing the installation."""

    root = _safe_installation_root(installation_root)
    state, state_sha256 = load_installation_state(root)
    verified: list[str] = []
    missing: list[str] = []
    modified: list[str] = []
    if state is not None:
        for item in state.managed_files:
            if ownership.resolve(item.path) != "core":
                raise InstallationError("managed file must belong to core ownership")
            target = safe_installation_target(root, item.path)
            if not target.exists():
                missing.append(item.path)
                continue
            if not target.is_file():
                modified.append(item.path)
                continue
            size, digest = _stable_file_hash(target)
            if size == item.size and digest == item.sha256:
                verified.append(item.path)
            else:
                modified.append(item.path)
    counts, symlink_count = _ownership_counts(root, ownership)
    interrupted = _interrupted_deployments(root)
    identity = {
        "state_sha256": state_sha256,
        "verified": verified,
        "missing": missing,
        "modified": modified,
        "ownership_counts": counts,
        "symlink_count": symlink_count,
        "interrupted_deployments": [dict(item) for item in interrupted],
    }
    return InstallationInspection(
        inspection_id=_canonical_sha256(identity),
        state_present=state is not None,
        installation_id=state.installation_id if state else None,
        core_version=state.core_version if state else None,
        release_id=state.release_id if state else None,
        state_revision=state.revision if state else None,
        state_sha256=state_sha256,
        managed_verified=tuple(verified),
        managed_missing=tuple(missing),
        managed_modified=tuple(modified),
        ownership_counts=counts,
        symlink_count=symlink_count,
        interrupted_deployments=interrupted,
    )
