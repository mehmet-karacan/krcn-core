"""Secret-safe portable backups of one KRCN user home."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation


SECRET_PARTS = {"secrets", ".secrets"}
SECRET_NAMES = {".env"}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(
        rb"(?im)^\s*[\"']?(?:password|passwd|token|api[_-]?key|secret)[\"']?\s*[:=]\s*"
        rb"[\"']?(?!\$\{|env://|keyring://|secret://|<)[A-Za-z0-9+/=_-]{12,}"
    ),
)
MACHINE_PATH_PATTERNS = (
    re.compile(rb"(?i)(?<![A-Za-z0-9_])[A-Z]:\\"),
    re.compile(rb"/(?:Users|home)/[^/\s]+/"),
)


class PortableBackupError(ValueError):
    """Raised when a portable backup would cross a protected boundary."""


@dataclass(frozen=True)
class PortableBackupEntry:
    path: str
    ownership: str
    size: int
    sha256: str
    content: bytes
    transformed: bool

    def manifest_entry(self) -> dict[str, object]:
        return {
            "path": self.path,
            "ownership": self.ownership,
            "size": self.size,
            "sha256": self.sha256,
            "transformed": self.transformed,
        }


@dataclass(frozen=True)
class PortableBackupPlan:
    plan_id: str
    backup_id: str
    user_home: Path
    archive_path: Path
    entries: tuple[PortableBackupEntry, ...]
    generated_entries: tuple[PortableBackupEntry, ...]
    external_dependencies: tuple[dict[str, object], ...]
    excluded_secret_count: int
    mutation: MutationPlan

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "backup_id": self.backup_id,
            "layout_version": 1,
            "entries": [item.manifest_entry() for item in self.entries],
            "external_dependencies": list(self.external_dependencies),
            "exclusions": {
                "secret_values": True,
                "external_source_content": True,
                "excluded_secret_count": self.excluded_secret_count,
            },
        }

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "backup_id": self.backup_id,
            "entry_count": len(self.entries),
            "external_dependency_count": len(self.external_dependencies),
            "excluded_secret_count": self.excluded_secret_count,
            "source_content_included": False,
            "secret_values_included": False,
            "paths_disclosed": False,
            "mutation": self.mutation.as_dict(),
        }


@dataclass(frozen=True)
class PortableBackupResult:
    plan_id: str
    backup_id: str
    archive_sha256: str
    entry_count: int

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "backup_id": self.backup_id,
            "archive_sha256": self.archive_sha256,
            "entry_count": self.entry_count,
            "source_content_included": False,
            "secret_values_included": False,
        }


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _ownership(relative: str) -> str:
    first = PurePosixPath(relative).parts[0]
    if first in {"runtime", "events", "checkpoints", "locks"}:
        return "runtime"
    if first in {"derived", "indexes", "cache"}:
        return "derived"
    return "user-data"


def _is_secret_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    lower_parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    return bool(
        lower_parts & SECRET_PARTS
        or name in SECRET_NAMES
        or name.startswith(".env.")
        or path.suffix.lower() in SECRET_SUFFIXES
    )


def _sanitize_source_binding(content: bytes) -> tuple[bytes, dict[str, object] | None]:
    try:
        envelope = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return content, None
    if not isinstance(envelope, dict) or envelope.get("record_type") != "source-bindings":
        return content, None
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise PortableBackupError("source binding record payload is invalid")
    locator = payload.get("locator")
    if not isinstance(locator, dict):
        raise PortableBackupError("source binding locator is invalid")
    dependency = {
        "binding_id": payload.get("binding_id"),
        "source_id": payload.get("source_id"),
        "locator_kind": locator.get("kind"),
        "rebind_required": True,
    }
    sanitized_payload = dict(payload)
    sanitized_payload["locator"] = {
        "kind": "unbound",
        "value": "external-source-required",
    }
    sanitized = dict(envelope)
    sanitized["payload"] = sanitized_payload
    sanitized["payload_sha256"] = hashlib.sha256(
        _canonical_json(sanitized_payload)
    ).hexdigest()
    return _canonical_json(sanitized), dependency


def _assert_portable_content(relative: str, content: bytes) -> None:
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        raise PortableBackupError(f"secret-like content blocks portable backup: {relative}")
    if any(pattern.search(content) for pattern in MACHINE_PATH_PATTERNS):
        raise PortableBackupError(f"machine-specific path blocks portable backup: {relative}")


def _collect_entries(
    user_home: Path,
) -> tuple[tuple[PortableBackupEntry, ...], tuple[dict[str, object], ...], int]:
    entries: list[PortableBackupEntry] = []
    dependencies: list[dict[str, object]] = []
    excluded_secret_count = 0
    for path in sorted(user_home.rglob("*")):
        relative = path.relative_to(user_home).as_posix()
        if path.is_symlink():
            raise PortableBackupError(f"symbolic link blocks portable backup: {relative}")
        if not path.is_file():
            continue
        if PurePosixPath(relative).parts[0] == "locks":
            continue
        if _is_secret_path(relative):
            excluded_secret_count += 1
            continue
        content = path.read_bytes()
        sanitized, dependency = _sanitize_source_binding(content)
        transformed = dependency is not None
        if dependency is not None:
            dependencies.append(dependency)
        _assert_portable_content(relative, sanitized)
        entries.append(
            PortableBackupEntry(
                path=relative,
                ownership=_ownership(relative),
                size=len(sanitized),
                sha256=hashlib.sha256(sanitized).hexdigest(),
                content=sanitized,
                transformed=transformed,
            )
        )
    dependencies.sort(key=lambda item: str(item["binding_id"]))
    return tuple(entries), tuple(dependencies), excluded_secret_count


def _generated_entries(
    generated_files: Mapping[str, bytes] | None,
    source_entries: tuple[PortableBackupEntry, ...],
) -> tuple[PortableBackupEntry, ...]:
    existing = {item.path for item in source_entries}
    generated: list[PortableBackupEntry] = []
    for relative, content in sorted((generated_files or {}).items()):
        path = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != relative
        ):
            raise PortableBackupError("generated backup path is not portable")
        if relative in existing or _is_secret_path(relative):
            raise PortableBackupError("generated backup path is unsafe or duplicated")
        if not isinstance(content, bytes):
            raise PortableBackupError("generated backup content must be bytes")
        _assert_portable_content(relative, content)
        generated.append(
            PortableBackupEntry(
                path=relative,
                ownership=_ownership(relative),
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
                transformed=False,
            )
        )
    return tuple(generated)


def prepare_portable_backup(
    user_home: Path,
    archive_path: Path,
    ownership: OwnershipResolver,
    *,
    generated_files: Mapping[str, bytes] | None = None,
) -> PortableBackupPlan:
    """Inspect and freeze a portable backup without writing the archive."""

    if not user_home.is_absolute() or not archive_path.is_absolute():
        raise PortableBackupError("user home and archive path must be absolute")
    home = user_home.resolve()
    target = archive_path.resolve(strict=False)
    if not home.is_dir() or home.is_symlink():
        raise PortableBackupError("KRCN user home must be an existing regular directory")
    try:
        target.relative_to(home)
    except ValueError:
        pass
    else:
        raise PortableBackupError("portable backup archive must be outside KRCN user home")
    if target.exists():
        raise PortableBackupError("portable backup archive already exists")
    source_entries, dependencies, excluded_count = _collect_entries(home)
    generated_entries = _generated_entries(generated_files, source_entries)
    entries = tuple(
        sorted((*source_entries, *generated_entries), key=lambda item: item.path)
    )
    identity = {
        "layout_version": 1,
        "entries": [item.manifest_entry() for item in entries],
        "external_dependencies": list(dependencies),
        "excluded_secret_count": excluded_count,
    }
    backup_id = hashlib.sha256(_canonical_json(identity)).hexdigest()
    target_identity = hashlib.sha256(str(target).encode("utf-8")).hexdigest()
    change_digest = hashlib.sha256(
        f"{backup_id}:{target_identity}".encode("utf-8")
    ).hexdigest()
    mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=f"portable-backups/{target.name}",
        expected_ownership="unmanaged",
        change_digest=change_digest,
        reversible=True,
    )
    return PortableBackupPlan(
        plan_id=mutation.plan_id,
        backup_id=backup_id,
        user_home=home,
        archive_path=target,
        entries=entries,
        generated_entries=generated_entries,
        external_dependencies=dependencies,
        excluded_secret_count=excluded_count,
        mutation=mutation,
    )


def portable_archive_bytes(plan: PortableBackupPlan) -> bytes:
    """Build deterministic archive bytes for verification and composed migrations."""

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        items = [("manifest.json", _canonical_json(plan.manifest()))]
        items.extend((f"payload/{item.path}", item.content) for item in plan.entries)
        for name, content in items:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return stream.getvalue()


def apply_portable_backup(
    plan: PortableBackupPlan,
    authorization: MutationAuthorization,
) -> PortableBackupResult:
    """Write the exact reviewed backup atomically after rechecking its snapshot."""

    if authorization.plan.plan_id != plan.mutation.plan_id:
        raise PortableBackupError("backup authorization does not match exact plan")
    if not authorization.dry_run_verified or not authorization.approval_verified:
        raise PortableBackupError("portable backup requires dry-run and user approval")
    if plan.archive_path.exists():
        raise PortableBackupError("portable backup archive appeared after planning")
    current_source_entries, current_dependencies, current_excluded = _collect_entries(
        plan.user_home
    )
    current_entries = tuple(
        sorted(
            (*current_source_entries, *plan.generated_entries),
            key=lambda item: item.path,
        )
    )
    current_identity = {
        "layout_version": 1,
        "entries": [item.manifest_entry() for item in current_entries],
        "external_dependencies": list(current_dependencies),
        "excluded_secret_count": current_excluded,
    }
    if hashlib.sha256(_canonical_json(current_identity)).hexdigest() != plan.backup_id:
        raise PortableBackupError("KRCN user home changed after backup planning")
    plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{plan.archive_path.name}.",
        suffix=".tmp",
        dir=plan.archive_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(portable_archive_bytes(plan))
        os.replace(temporary, plan.archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    archive_sha256 = hashlib.sha256(plan.archive_path.read_bytes()).hexdigest()
    return PortableBackupResult(
        plan.plan_id,
        plan.backup_id,
        archive_sha256,
        len(plan.entries),
    )
