"""Ownership-aware and non-mutating release diff generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .installation import (
    InstallationInspection,
    InstallationState,
    inspect_installation,
    load_installation_state,
    safe_installation_target,
)
from .mutation_gate import OwnershipResolver
from .release import ReleaseBundle, ReleaseFile


class ReleaseDiffError(ValueError):
    """Raised when a release diff cannot be produced safely."""


@dataclass(frozen=True)
class FileChange:
    path: str
    action: str
    ownership: str
    previous_sha256: str | None
    target_sha256: str | None
    target_size: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "action": self.action,
            "ownership": self.ownership,
            "previous_sha256": self.previous_sha256,
            "target_sha256": self.target_sha256,
            "target_size": self.target_size,
        }


@dataclass(frozen=True)
class DiffConflict:
    conflict_code: str
    subject: str
    path: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "conflict_code": self.conflict_code,
            "subject": self.subject,
            "path": self.path,
        }


@dataclass(frozen=True)
class ReleaseDiff:
    diff_id: str
    inspection_id: str
    installation_id: str
    from_core_version: str
    release_id: str
    to_core_version: str
    manifest_sha256: str
    changes: tuple[FileChange, ...]
    conflicts: tuple[DiffConflict, ...]
    pending_migrations: tuple[str, ...]
    derived_actions: tuple[str, ...]

    @property
    def applicable(self) -> bool:
        return not self.conflicts

    def public_summary(self) -> dict[str, object]:
        counts = {name: 0 for name in ("create", "update", "delete", "unchanged")}
        for item in self.changes:
            counts[item.action] += 1
        return {
            "schema_version": 1,
            "diff_id": self.diff_id,
            "inspection_id": self.inspection_id,
            "installation_id": self.installation_id,
            "from_core_version": self.from_core_version,
            "release_id": self.release_id,
            "to_core_version": self.to_core_version,
            "manifest_sha256": self.manifest_sha256,
            "applicable": self.applicable,
            "change_counts": counts,
            "changes": [item.as_dict() for item in self.changes],
            "conflicts": [item.as_dict() for item in self.conflicts],
            "pending_migrations": list(self.pending_migrations),
            "derived_actions": list(self.derived_actions),
        }


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _installed_files(state: InstallationState) -> dict[str, object]:
    return {item.path: item for item in state.managed_files}


def _existing_conflicts(
    inspection: InstallationInspection,
) -> list[DiffConflict]:
    conflicts = [
        DiffConflict("managed-missing", path, path)
        for path in inspection.managed_missing
    ]
    conflicts.extend(
        DiffConflict("managed-modified", path, path)
        for path in inspection.managed_modified
    )
    conflicts.extend(
        DiffConflict(
            "interrupted-deployment",
            item["deployment_id"],
            None,
        )
        for item in inspection.interrupted_deployments
    )
    return conflicts


def _upsert_change(
    root: Path,
    item: ReleaseFile,
    installed: dict[str, object],
    clean_paths: set[str],
) -> tuple[FileChange | None, DiffConflict | None]:
    previous = installed.get(item.path)
    target = safe_installation_target(root, item.path)
    if previous is None:
        if target.exists():
            return None, DiffConflict("unmanaged-overlap", item.path, item.path)
        return (
            FileChange(
                item.path,
                "create",
                "core",
                None,
                item.sha256,
                item.size,
            ),
            None,
        )
    if item.path not in clean_paths:
        return None, None
    if previous.sha256 == item.sha256 and previous.size == item.size:
        action = "unchanged"
    else:
        action = "update"
    return (
        FileChange(
            item.path,
            action,
            "core",
            previous.sha256,
            item.sha256,
            item.size,
        ),
        None,
    )


def _delete_change(
    root: Path,
    item: ReleaseFile,
    installed: dict[str, object],
    clean_paths: set[str],
) -> tuple[FileChange | None, DiffConflict | None]:
    previous = installed.get(item.path)
    target = safe_installation_target(root, item.path)
    if previous is None:
        code = "unmanaged-overlap" if target.exists() else "untracked-delete"
        return None, DiffConflict(code, item.path, item.path)
    if previous.sha256 != item.previous_sha256:
        return None, DiffConflict("release-base-mismatch", item.path, item.path)
    if item.path not in clean_paths:
        return None, None
    return (
        FileChange(
            item.path,
            "delete",
            "core",
            previous.sha256,
            None,
            None,
        ),
        None,
    )


def create_release_diff(
    installation_root: Path,
    bundle: ReleaseBundle,
    ownership: OwnershipResolver,
) -> ReleaseDiff:
    """Compare a validated release to a read-only installation inspection."""

    root = installation_root.resolve()
    inspection = inspect_installation(root, ownership)
    state, _ = load_installation_state(root)
    if state is None:
        raise ReleaseDiffError("release diff requires registered installation state")
    conflicts = _existing_conflicts(inspection)
    conflicted_paths = {
        item.path for item in conflicts if item.path is not None
    }
    clean_paths = set(inspection.managed_verified)
    installed = _installed_files(state)
    changes: list[FileChange] = []
    for item in bundle.manifest.files:
        if item.path in conflicted_paths:
            continue
        if item.operation == "upsert":
            change, conflict = _upsert_change(
                root,
                item,
                installed,
                clean_paths,
            )
        else:
            change, conflict = _delete_change(
                root,
                item,
                installed,
                clean_paths,
            )
        if conflict is not None:
            conflicts.append(conflict)
        if change is not None:
            changes.append(change)
    changes.sort(key=lambda item: item.path)
    conflicts.sort(key=lambda item: (item.conflict_code, item.subject))
    pending_migrations = tuple(
        item
        for item in bundle.manifest.migrations
        if item not in state.completed_migrations
    )
    identity = {
        "inspection_id": inspection.inspection_id,
        "manifest_sha256": bundle.manifest_sha256,
        "changes": [item.as_dict() for item in changes],
        "conflicts": [item.as_dict() for item in conflicts],
        "pending_migrations": list(pending_migrations),
        "derived_actions": list(bundle.manifest.derived_actions),
    }
    return ReleaseDiff(
        diff_id=_canonical_sha256(identity),
        inspection_id=inspection.inspection_id,
        installation_id=state.installation_id,
        from_core_version=state.core_version,
        release_id=bundle.manifest.release_id,
        to_core_version=bundle.manifest.core_version,
        manifest_sha256=bundle.manifest_sha256,
        changes=tuple(changes),
        conflicts=tuple(conflicts),
        pending_migrations=pending_migrations,
        derived_actions=bundle.manifest.derived_actions,
    )
