"""Trusted local release manifest and payload validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .foundation import scan_tree
from .mutation_gate import OwnershipResolver


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
RELEASE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9.-]*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")


class ReleaseError(ValueError):
    """Raised when a release package is invalid, untrusted, or incompatible."""


@dataclass(frozen=True)
class ReleaseFile:
    path: str
    operation: str
    sha256: str | None = None
    size: int | None = None
    previous_sha256: str | None = None

    def as_dict(self) -> dict[str, object]:
        if self.operation == "upsert":
            return {
                "path": self.path,
                "operation": "upsert",
                "sha256": self.sha256,
                "size": self.size,
            }
        return {
            "path": self.path,
            "operation": "delete",
            "previous_sha256": self.previous_sha256,
        }


@dataclass(frozen=True)
class ReleaseManifest:
    release_id: str
    core_version: str
    minimum_core_version: str
    maximum_core_version: str
    source_commit: str
    files: tuple[ReleaseFile, ...]
    migrations: tuple[str, ...]
    derived_actions: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/release-manifest.schema.json",
            "schema_version": 1,
            "release_id": self.release_id,
            "core_version": self.core_version,
            "compatibility": {
                "minimum_core_version": self.minimum_core_version,
                "maximum_core_version": self.maximum_core_version,
            },
            "source_commit": self.source_commit,
            "files": [item.as_dict() for item in self.files],
            "migrations": list(self.migrations),
            "derived_actions": list(self.derived_actions),
        }


@dataclass(frozen=True)
class ReleaseBundle:
    manifest: ReleaseManifest
    manifest_sha256: str
    payload_files: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        upsert_count = sum(
            item.operation == "upsert" for item in self.manifest.files
        )
        return {
            "schema_version": 1,
            "release_id": self.manifest.release_id,
            "core_version": self.manifest.core_version,
            "compatibility": {
                "minimum_core_version": self.manifest.minimum_core_version,
                "maximum_core_version": self.manifest.maximum_core_version,
            },
            "source_commit": self.manifest.source_commit,
            "manifest_sha256": self.manifest_sha256,
            "file_counts": {
                "upsert": upsert_count,
                "delete": len(self.manifest.files) - upsert_count,
            },
            "migrations": list(self.manifest.migrations),
            "derived_actions": list(self.manifest.derived_actions),
        }


def _portable_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReleaseError("release file path must be portable")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ".." in path.parts
        or "." in path.parts
    ):
        raise ReleaseError("release file path must stay within the installation")
    return path.as_posix()


def _unique_identifiers(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ReleaseError(f"{label} must be a list")
    result = []
    for item in value:
        if not isinstance(item, str) or not IDENTIFIER.fullmatch(item):
            raise ReleaseError(f"{label} must contain portable identifiers")
        result.append(item)
    if len(set(result)) != len(result):
        raise ReleaseError(f"{label} must be unique")
    return tuple(result)


def _version(value: object, label: str) -> str:
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ReleaseError(f"{label} must be a semantic version")
    return value


def version_tuple(value: str) -> tuple[int, int, int]:
    if not SEMVER.fullmatch(value):
        raise ReleaseError("core version must be semantic")
    return tuple(int(part) for part in value.split("."))


def parse_release_manifest(payload: object) -> ReleaseManifest:
    """Validate release metadata without reading or executing payload content."""

    if not isinstance(payload, dict):
        raise ReleaseError("release manifest must be an object")
    expected_fields = {
        "schema_ref",
        "schema_version",
        "release_id",
        "core_version",
        "compatibility",
        "source_commit",
        "files",
        "migrations",
        "derived_actions",
    }
    if set(payload) != expected_fields:
        raise ReleaseError("release manifest fields are invalid")
    if payload.get("schema_ref") != "schemas/release-manifest.schema.json":
        raise ReleaseError("release manifest schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ReleaseError("release manifest schema version must be 1")
    release_id = payload.get("release_id")
    if not isinstance(release_id, str) or not RELEASE_IDENTIFIER.fullmatch(release_id):
        raise ReleaseError("release id is invalid")
    core_version = _version(payload.get("core_version"), "release core version")
    compatibility = payload.get("compatibility")
    if not isinstance(compatibility, dict) or set(compatibility) != {
        "minimum_core_version",
        "maximum_core_version",
    }:
        raise ReleaseError("release compatibility fields are invalid")
    minimum = _version(
        compatibility.get("minimum_core_version"),
        "minimum core version",
    )
    maximum = _version(
        compatibility.get("maximum_core_version"),
        "maximum core version",
    )
    if version_tuple(minimum) > version_tuple(maximum):
        raise ReleaseError("release compatibility range is invalid")
    source_commit = payload.get("source_commit")
    if not isinstance(source_commit, str) or not COMMIT.fullmatch(source_commit):
        raise ReleaseError("release source commit is invalid")
    files_payload = payload.get("files")
    if not isinstance(files_payload, list):
        raise ReleaseError("release files must be a list")
    if len(files_payload) > 100_000:
        raise ReleaseError("release exceeds the managed file limit")
    files: list[ReleaseFile] = []
    seen_paths: set[str] = set()
    for item in files_payload:
        if not isinstance(item, dict):
            raise ReleaseError("release file entry must be an object")
        operation = item.get("operation")
        if operation == "upsert" and set(item) == {
            "path",
            "operation",
            "sha256",
            "size",
        }:
            path = _portable_path(item.get("path"))
            sha256 = item.get("sha256")
            size = item.get("size")
            if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
                raise ReleaseError("release upsert hash is invalid")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise ReleaseError("release upsert size is invalid")
            release_file = ReleaseFile(path, operation, sha256, size)
        elif operation == "delete" and set(item) == {
            "path",
            "operation",
            "previous_sha256",
        }:
            path = _portable_path(item.get("path"))
            previous_sha256 = item.get("previous_sha256")
            if (
                not isinstance(previous_sha256, str)
                or not SHA256.fullmatch(previous_sha256)
            ):
                raise ReleaseError("release delete previous hash is invalid")
            release_file = ReleaseFile(
                path,
                operation,
                previous_sha256=previous_sha256,
            )
        else:
            raise ReleaseError("release file operation fields are invalid")
        if release_file.path in seen_paths:
            raise ReleaseError("release file paths must be unique")
        seen_paths.add(release_file.path)
        files.append(release_file)
    return ReleaseManifest(
        release_id=release_id,
        core_version=core_version,
        minimum_core_version=minimum,
        maximum_core_version=maximum,
        source_commit=source_commit,
        files=tuple(sorted(files, key=lambda item: item.path)),
        migrations=_unique_identifiers(payload.get("migrations"), "migrations"),
        derived_actions=_unique_identifiers(
            payload.get("derived_actions"),
            "derived actions",
        ),
    )


def manifest_sha256(manifest: ReleaseManifest | object) -> str:
    parsed = (
        manifest
        if isinstance(manifest, ReleaseManifest)
        else parse_release_manifest(manifest)
    )
    document = json.dumps(
        parsed.as_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(document).hexdigest()


def _safe_release_root(root: Path) -> Path:
    if not root.is_absolute():
        raise ReleaseError("release root must be absolute")
    if root.is_symlink():
        raise ReleaseError("release root may not be a symbolic link")
    resolved = root.resolve()
    if not resolved.is_dir():
        raise ReleaseError("release root must be an existing directory")
    return resolved


def safe_payload_target(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve(strict=False)
    portable = _portable_path(relative_path)
    candidate = root / "payload"
    if candidate.is_symlink():
        raise ReleaseError("release payload may not be a symbolic link")
    for part in PurePosixPath(portable).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ReleaseError("release payload path may not use symbolic links")
    try:
        candidate.resolve(strict=False).relative_to(resolved_root)
    except ValueError as exc:
        raise ReleaseError("release payload path escapes the release root") from exc
    return candidate


def _stable_payload_hash(path: Path) -> tuple[int, str]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ReleaseError("release payload changed during validation")
    return after.st_size, digest.hexdigest()


def _payload_paths(root: Path) -> tuple[str, ...]:
    payload_root = root / "payload"
    if not payload_root.exists():
        return ()
    if payload_root.is_symlink() or not payload_root.is_dir():
        raise ReleaseError("release payload must be a regular directory")
    paths = []
    for directory, directory_names, file_names in os.walk(
        payload_root,
        followlinks=False,
    ):
        directory_path = Path(directory)
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise ReleaseError("release payload may not contain symbolic links")
        for name in file_names:
            path = directory_path / name
            if path.is_symlink() or not path.is_file():
                raise ReleaseError("release payload may contain only regular files")
            paths.append(path.relative_to(payload_root).as_posix())
    return tuple(sorted(paths))


def validate_release_bundle(
    release_root: Path,
    ownership: OwnershipResolver,
    *,
    trusted_manifest_sha256: str,
    installed_core_version: str,
    import_policy: dict,
) -> ReleaseBundle:
    """Validate trust, compatibility, ownership, safety, and payload integrity."""

    root = _safe_release_root(release_root)
    if not SHA256.fullmatch(trusted_manifest_sha256):
        raise ReleaseError("trusted manifest digest must be SHA-256")
    manifest_path = root / "release-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ReleaseError("release manifest must be a regular file")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseError("release manifest JSON is invalid") from exc
    manifest = parse_release_manifest(payload)
    digest = manifest_sha256(manifest)
    if not hmac.compare_digest(digest, trusted_manifest_sha256):
        raise ReleaseError("release manifest does not match the trusted digest")
    installed = version_tuple(installed_core_version)
    if not (
        version_tuple(manifest.minimum_core_version)
        <= installed
        <= version_tuple(manifest.maximum_core_version)
    ):
        raise ReleaseError("installed core version is outside release compatibility")
    if version_tuple(manifest.core_version) < installed:
        raise ReleaseError("release downgrade is not permitted by merge")
    for item in manifest.files:
        if ownership.resolve(item.path) != "core":
            raise ReleaseError("release files must belong to core ownership")
    expected_payload = {
        item.path for item in manifest.files if item.operation == "upsert"
    }
    actual_payload = set(_payload_paths(root))
    if actual_payload != expected_payload:
        raise ReleaseError("release payload files do not match the manifest")
    payload_root = root / "payload"
    if payload_root.exists():
        findings = scan_tree(payload_root, import_policy)
        if findings:
            codes = ", ".join(sorted({item.code for item in findings}))
            raise ReleaseError("release payload failed safety scan: " + codes)
    for item in manifest.files:
        if item.operation == "delete":
            continue
        target = safe_payload_target(root, item.path)
        if not target.is_file():
            raise ReleaseError("release upsert payload is missing")
        size, file_digest = _stable_payload_hash(target)
        if size != item.size or file_digest != item.sha256:
            raise ReleaseError("release payload does not match manifest evidence")
    return ReleaseBundle(
        manifest=manifest,
        manifest_sha256=digest,
        payload_files=tuple(sorted(actual_payload)),
    )
