"""Constrained, trusted, and idempotent JSON migration planning."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .installation import safe_installation_target
from .mutation_gate import MutationPlan, OwnershipResolver, plan_mutation
from .update_effects import MigrationSpec


MigrationTransform = Callable[[object], object]


class MigrationError(ValueError):
    """Raised when a migration cannot be planned or applied safely."""


@dataclass(frozen=True)
class MigrationHandler:
    migration_id: str
    transform: MigrationTransform


@dataclass(frozen=True)
class MigrationWrite:
    migration_id: str
    target_ref: str
    ownership: str
    previous_sha256: str
    target_sha256: str
    document: bytes
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "migration_id": self.migration_id,
            "target_ref": self.target_ref,
            "ownership": self.ownership,
            "previous_sha256": self.previous_sha256,
            "target_sha256": self.target_sha256,
            "mutation": self.mutation.as_dict(),
        }


def _canonical_document(payload: object) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MigrationError("migration output must be JSON-compatible") from exc


def _clone_json(payload: object) -> object:
    return json.loads(json.dumps(payload, ensure_ascii=False))


class MigrationHandlerRegistry:
    def __init__(self, handlers: Iterable[MigrationHandler] = ()) -> None:
        self._handlers: dict[str, MigrationHandler] = {}
        for handler in handlers:
            if handler.migration_id in self._handlers:
                raise MigrationError("duplicate migration handler")
            if not callable(handler.transform):
                raise MigrationError("migration transform must be callable")
            self._handlers[handler.migration_id] = handler

    def resolve(self, migration_id: str) -> MigrationHandler:
        try:
            return self._handlers[migration_id]
        except KeyError as exc:
            raise MigrationError(
                f"trusted migration handler is not registered: {migration_id}"
            ) from exc


def _scope_json_files(root: Path, spec: MigrationSpec) -> tuple[Path, ...]:
    target = safe_installation_target(root, spec.target_ref)
    if not target.exists():
        return ()
    if target.is_symlink():
        raise MigrationError("migration scope may not be a symbolic link")
    if target.is_file():
        return (target,) if target.suffix.lower() == ".json" else ()
    if not target.is_dir():
        raise MigrationError("migration scope must be a file or directory")
    files = []
    for directory, directory_names, file_names in os.walk(target, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise MigrationError("migration scope may not contain symbolic links")
        for name in file_names:
            path = directory_path / name
            if path.is_symlink():
                raise MigrationError("migration scope may not contain symbolic links")
            if path.suffix.lower() == ".json":
                files.append(path)
    return tuple(sorted(files))


def plan_migration_writes(
    installation_root: Path,
    specs: tuple[MigrationSpec, ...],
    handlers: MigrationHandlerRegistry,
    ownership: OwnershipResolver,
) -> tuple[MigrationWrite, ...]:
    """Plan exact JSON writes and prove every transform is idempotent."""

    root = installation_root.resolve()
    writes = []
    seen_targets: set[str] = set()
    for spec in specs:
        handler = handlers.resolve(spec.migration_id)
        for path in _scope_json_files(root, spec):
            target_ref = path.relative_to(root).as_posix()
            if target_ref in seen_targets:
                raise MigrationError("migration write targets must not overlap")
            if ownership.resolve(target_ref) != spec.ownership:
                raise MigrationError("migration target ownership changed")
            try:
                original_bytes = path.read_bytes()
                original = json.loads(original_bytes)
            except json.JSONDecodeError as exc:
                raise MigrationError("migration input JSON is invalid") from exc
            try:
                transformed = handler.transform(_clone_json(original))
                repeated = handler.transform(_clone_json(transformed))
            except Exception as exc:
                raise MigrationError("trusted migration handler failed") from exc
            transformed_document = _canonical_document(transformed)
            repeated_document = _canonical_document(repeated)
            if repeated_document != transformed_document:
                raise MigrationError("migration transform must be idempotent")
            original_digest = hashlib.sha256(original_bytes).hexdigest()
            target_digest = hashlib.sha256(transformed_document).hexdigest()
            if target_digest == original_digest:
                continue
            mutation = plan_mutation(
                ownership,
                operation="update",
                target_ref=target_ref,
                expected_ownership=spec.ownership,
                change_digest=target_digest,
                reversible=True,
            )
            writes.append(
                MigrationWrite(
                    migration_id=spec.migration_id,
                    target_ref=target_ref,
                    ownership=spec.ownership,
                    previous_sha256=original_digest,
                    target_sha256=target_digest,
                    document=transformed_document,
                    mutation=mutation,
                )
            )
            seen_targets.add(target_ref)
    return tuple(sorted(writes, key=lambda item: item.target_ref))
