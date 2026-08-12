"""Constrained and exact planning for trusted derived-data rebuilds."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .installation import safe_installation_target
from .json_documents import JsonDocumentError, pretty_json_bytes
from .mutation_gate import MutationPlan, OwnershipResolver, plan_mutation
from .update_effects import DerivedActionSpec


DerivedTransform = Callable[[Mapping[str, object]], Mapping[str, object]]


class DerivedActionError(ValueError):
    """Raised when a derived rebuild cannot be planned safely."""


@dataclass(frozen=True)
class DerivedActionHandler:
    action_id: str
    transform: DerivedTransform


@dataclass(frozen=True)
class DerivedWrite:
    action_id: str
    target_ref: str
    action: str
    previous_sha256: str | None
    target_sha256: str | None
    document: bytes | None
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "target_ref": self.target_ref,
            "action": self.action,
            "previous_sha256": self.previous_sha256,
            "target_sha256": self.target_sha256,
            "mutation": self.mutation.as_dict(),
        }


def _stored_document(payload: object) -> bytes:
    try:
        return pretty_json_bytes(payload)
    except JsonDocumentError as exc:
        raise DerivedActionError("derived output must be JSON-compatible") from exc


def _portable_json_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DerivedActionError("derived output path must be portable")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or path.suffix.lower() != ".json"
    ):
        raise DerivedActionError("derived output must stay in JSON scope")
    return path.as_posix()


def _clone_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    return json.loads(json.dumps(dict(payload), ensure_ascii=False))


class DerivedActionHandlerRegistry:
    def __init__(self, handlers: Iterable[DerivedActionHandler] = ()) -> None:
        self._handlers: dict[str, DerivedActionHandler] = {}
        for handler in handlers:
            if handler.action_id in self._handlers:
                raise DerivedActionError("duplicate derived action handler")
            if not callable(handler.transform):
                raise DerivedActionError("derived transform must be callable")
            self._handlers[handler.action_id] = handler

    def resolve(self, action_id: str) -> DerivedActionHandler:
        try:
            return self._handlers[action_id]
        except KeyError as exc:
            raise DerivedActionError(
                f"trusted derived action handler is not registered: {action_id}"
            ) from exc


def _read_scope(root: Path, spec: DerivedActionSpec) -> dict[str, object]:
    target = safe_installation_target(root, spec.target_ref)
    if not target.exists():
        return {}
    if target.is_symlink() or not target.is_dir():
        raise DerivedActionError("derived action scope must be a regular directory")
    result = {}
    for directory, directory_names, file_names in os.walk(target, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            if (directory_path / name).is_symlink():
                raise DerivedActionError("derived scope may not contain symbolic links")
        for name in file_names:
            path = directory_path / name
            if path.is_symlink() or path.suffix.lower() != ".json":
                raise DerivedActionError("derived scope may contain only JSON files")
            relative = path.relative_to(target).as_posix()
            try:
                result[relative] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise DerivedActionError("derived input JSON is invalid") from exc
    return result


def _normalized_output(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise DerivedActionError("derived transform must return an object")
    result = {}
    for path, document in payload.items():
        portable = _portable_json_path(path)
        if portable in result:
            raise DerivedActionError("derived output paths must be unique")
        _stored_document(document)
        result[portable] = document
    return result


def plan_derived_writes(
    installation_root: Path,
    specs: tuple[DerivedActionSpec, ...],
    handlers: DerivedActionHandlerRegistry,
    ownership: OwnershipResolver,
) -> tuple[DerivedWrite, ...]:
    """Plan exact create, update, and delete effects for derived JSON data."""

    root = installation_root.resolve()
    writes = []
    seen_targets: set[str] = set()
    for spec in specs:
        handler = handlers.resolve(spec.action_id)
        current = _read_scope(root, spec)
        try:
            output = _normalized_output(handler.transform(_clone_mapping(current)))
            repeated = _normalized_output(handler.transform(_clone_mapping(output)))
        except DerivedActionError:
            raise
        except Exception as exc:
            raise DerivedActionError("trusted derived action handler failed") from exc
        if {
            path: _stored_document(value) for path, value in repeated.items()
        } != {path: _stored_document(value) for path, value in output.items()}:
            raise DerivedActionError("derived transform must be idempotent")
        for relative_path in sorted(set(current) | set(output)):
            target_ref = f"{spec.target_ref}/{relative_path}"
            if target_ref in seen_targets:
                raise DerivedActionError("derived action targets must not overlap")
            if ownership.resolve(target_ref) != "derived":
                raise DerivedActionError("derived output ownership is invalid")
            previous_document = (
                _stored_document(current[relative_path])
                if relative_path in current
                else None
            )
            target_document = (
                _stored_document(output[relative_path])
                if relative_path in output
                else None
            )
            previous_digest = (
                hashlib.sha256(previous_document).hexdigest()
                if previous_document is not None
                else None
            )
            target_digest = (
                hashlib.sha256(target_document).hexdigest()
                if target_document is not None
                else None
            )
            actual_path = safe_installation_target(root, target_ref)
            if actual_path.exists():
                actual_digest = hashlib.sha256(actual_path.read_bytes()).hexdigest()
                previous_digest = actual_digest
            if previous_digest == target_digest:
                continue
            if previous_document is None:
                action = "create"
                change_digest = target_digest
            elif target_document is None:
                action = "delete"
                change_digest = previous_digest
            else:
                action = "update"
                change_digest = target_digest
            if change_digest is None:
                raise DerivedActionError("derived write lacks content evidence")
            mutation = plan_mutation(
                ownership,
                operation=action,
                target_ref=target_ref,
                expected_ownership="derived",
                change_digest=change_digest,
                reversible=True,
            )
            writes.append(
                DerivedWrite(
                    action_id=spec.action_id,
                    target_ref=target_ref,
                    action=action,
                    previous_sha256=previous_digest,
                    target_sha256=target_digest,
                    document=target_document,
                    mutation=mutation,
                )
            )
            seen_targets.add(target_ref)
    return tuple(sorted(writes, key=lambda item: item.target_ref))
