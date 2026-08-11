"""Explicit non-destructive migration from repository-local .krcn state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .portable_backup import (
    PortableBackupPlan,
    apply_portable_backup,
    portable_archive_bytes,
    prepare_portable_backup,
)
from .portable_restore import apply_portable_restore, prepare_portable_restore


class RepoLocalMigrationError(ValueError):
    """Raised when repository-local state cannot be migrated safely."""


@dataclass(frozen=True)
class RepoLocalMigrationPlan:
    plan_id: str
    repository_root: Path
    source_home: Path
    target_home: Path
    backup_plan: PortableBackupPlan
    restore_mutation: MutationPlan
    ownership: OwnershipResolver

    @property
    def effect_plans(self) -> tuple[MutationPlan, MutationPlan]:
        return self.backup_plan.mutation, self.restore_mutation

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "backup_id": self.backup_plan.backup_id,
            "entry_count": len(self.backup_plan.entries),
            "external_dependency_count": len(self.backup_plan.external_dependencies),
            "source_preserved": True,
            "source_deleted": False,
            "target_must_be_empty": True,
            "paths_disclosed": False,
            "effect_plans": [item.as_dict() for item in self.effect_plans],
            "rollback": {
                "kind": "select-preserved-source",
                "source_preserved": True,
                "automatic_delete": False,
            },
        }


@dataclass(frozen=True)
class RepoLocalMigrationResult:
    plan_id: str
    backup_id: str
    restored_entry_count: int
    rebind_required_count: int
    source_preserved: bool
    rollback_ready: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "backup_id": self.backup_id,
            "restored_entry_count": self.restored_entry_count,
            "rebind_required_count": self.rebind_required_count,
            "source_preserved": self.source_preserved,
            "rollback_ready": self.rollback_ready,
            "source_deleted": False,
        }


def _outside(path: Path, root: Path, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError:
        return
    raise RepoLocalMigrationError(message)


def prepare_repo_local_migration(
    repository_root: Path,
    target_home: Path,
    backup_path: Path,
    ownership: OwnershipResolver,
) -> RepoLocalMigrationPlan:
    """Plan backup and restore while keeping the legacy source untouched."""

    if not repository_root.is_absolute() or not target_home.is_absolute() or not backup_path.is_absolute():
        raise RepoLocalMigrationError("migration paths must be absolute")
    repository = repository_root.resolve()
    source = repository / ".krcn"
    target = target_home.resolve(strict=False)
    backup = backup_path.resolve(strict=False)
    if not source.is_dir() or source.is_symlink():
        raise RepoLocalMigrationError("repository-local .krcn source was not found")
    _outside(target, repository, "portable KRCN user home must be outside the repository")
    _outside(backup, repository, "migration backup must be outside the repository")
    _outside(backup, target, "migration backup must be outside the target user home")
    backup_plan = prepare_portable_backup(source, backup, ownership)
    archive_digest = hashlib.sha256(portable_archive_bytes(backup_plan)).hexdigest()
    target_digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()
    restore_digest = hashlib.sha256(
        f"{backup_plan.backup_id}:{archive_digest}:{target_digest}".encode("utf-8")
    ).hexdigest()
    restore_mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=f"portable-restores/{backup_plan.backup_id}",
        expected_ownership="unmanaged",
        change_digest=restore_digest,
        reversible=True,
    )
    identity = {
        "backup_plan_id": backup_plan.plan_id,
        "restore_plan_id": restore_mutation.plan_id,
        "source_home_sha256": hashlib.sha256(str(source).encode("utf-8")).hexdigest(),
        "target_home_sha256": target_digest,
        "source_preserved": True,
    }
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return RepoLocalMigrationPlan(
        plan_id,
        repository,
        source,
        target,
        backup_plan,
        restore_mutation,
        ownership,
    )


def apply_repo_local_migration(
    plan: RepoLocalMigrationPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> RepoLocalMigrationResult:
    """Create a recovery backup, restore the target, and retain the old source."""

    for mutation in plan.effect_plans:
        authorization = authorizations.get(mutation.plan_id)
        if authorization is None or authorization.plan.plan_id != mutation.plan_id:
            raise RepoLocalMigrationError("every migration effect requires exact authorization")
        if not authorization.dry_run_verified or not authorization.approval_verified:
            raise RepoLocalMigrationError("migration requires dry-run and user approval")
    apply_portable_backup(
        plan.backup_plan,
        authorizations[plan.backup_plan.mutation.plan_id],
    )
    restore_plan = prepare_portable_restore(
        plan.backup_plan.archive_path,
        plan.target_home,
        plan.ownership,
    )
    if restore_plan.mutation.plan_id != plan.restore_mutation.plan_id:
        raise RepoLocalMigrationError("restore effect changed after migration planning")
    restored = apply_portable_restore(
        restore_plan,
        authorizations[plan.restore_mutation.plan_id],
    )
    if not plan.source_home.is_dir():
        raise RepoLocalMigrationError("legacy source was not preserved")
    return RepoLocalMigrationResult(
        plan.plan_id,
        plan.backup_plan.backup_id,
        restored.restored_entry_count,
        restored.rebind_required_count,
        source_preserved=True,
        rollback_ready=True,
    )
