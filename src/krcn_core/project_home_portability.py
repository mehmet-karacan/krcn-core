"""Backup-backed migration and clean recovery for project-scoped homes."""

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
from .portable_restore import (
    PortableRestorePlan,
    apply_portable_restore,
    prepare_portable_restore,
)
from .project_home import ProjectHomeResolution
from .project_home_initialization import (
    MANIFEST_NAME,
    ProjectHomeInitializationPlan,
    apply_git_exclusion,
    prepare_project_home_initialization,
    rollback_git_exclusion,
    validate_initialized_project_home,
    validate_project_home_manifest_content,
)


class ProjectHomePortabilityError(ValueError):
    """Raised when project-home migration or recovery cannot remain safe."""


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _restore_mutation(
    backup: PortableBackupPlan,
    target_home: Path,
    ownership: OwnershipResolver,
) -> MutationPlan:
    archive_digest = hashlib.sha256(portable_archive_bytes(backup)).hexdigest()
    target_digest = hashlib.sha256(str(target_home).encode("utf-8")).hexdigest()
    change_digest = hashlib.sha256(
        f"{backup.backup_id}:{archive_digest}:{target_digest}".encode("utf-8")
    ).hexdigest()
    return plan_mutation(
        ownership,
        operation="create",
        target_ref=f"portable-restores/{backup.backup_id}",
        expected_ownership="unmanaged",
        change_digest=change_digest,
        reversible=True,
    )


def _assert_separate(path: Path, root: Path, message: str) -> None:
    try:
        path.relative_to(root)
    except ValueError:
        return
    raise ProjectHomePortabilityError(message)


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
            or not authorization.approval_verified
        ):
            raise ProjectHomePortabilityError(
                "every portability effect requires exact authorization"
            )


@dataclass(frozen=True)
class ProjectHomeMigrationPlan:
    plan_id: str
    source_home: Path
    initialization: ProjectHomeInitializationPlan
    backup: PortableBackupPlan
    restore_mutation: MutationPlan
    ownership: OwnershipResolver

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        effects = [self.backup.mutation]
        if self.initialization.git_exclusion is not None:
            effects.append(self.initialization.git_exclusion.mutation)
        effects.append(self.restore_mutation)
        return tuple(effects)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-home-migration-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "backup_id": self.backup.backup_id,
            "entry_count": len(self.backup.entries),
            "external_dependency_count": len(self.backup.external_dependencies),
            "source_preserved": True,
            "source_deleted": False,
            "target_must_be_empty": True,
            "project_manifest_included": True,
            "source_content_included": False,
            "secret_values_included": False,
            "paths_disclosed": False,
            "effect_plans": [item.as_dict() for item in self.effect_plans],
            "rollback": {
                "kind": "select-preserved-source-or-restore-backup",
                "source_preserved": True,
                "backup_required_before_restore": True,
                "automatic_source_delete": False,
            },
        }


@dataclass(frozen=True)
class ProjectHomeMigrationResult:
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
            "source_deleted": False,
            "rollback_ready": self.rollback_ready,
            "project_home_verified": True,
        }


def prepare_project_home_migration(
    source_home: Path,
    resolution: ProjectHomeResolution,
    backup_path: Path,
    ownership: OwnershipResolver,
) -> ProjectHomeMigrationPlan:
    """Freeze a source-preserving backup and project-home restore plan."""

    if not source_home.is_absolute() or not backup_path.is_absolute():
        raise ProjectHomePortabilityError("migration paths must be absolute")
    source = source_home.resolve()
    backup_target = backup_path.resolve(strict=False)
    if not source.is_dir() or source.is_symlink():
        raise ProjectHomePortabilityError(
            "migration source must be an existing regular KRCN home"
        )
    target = resolution.path
    if target.exists() and any(target.iterdir()):
        raise ProjectHomePortabilityError("migration target must be empty")
    initialization = prepare_project_home_initialization(resolution, ownership)
    _assert_separate(target, source, "migration target must be outside source home")
    _assert_separate(source, target, "migration source must be outside target home")
    _assert_separate(
        backup_target,
        target,
        "migration backup must be outside target home",
    )
    source_manifest = source / MANIFEST_NAME
    generated: dict[str, bytes] | None = {MANIFEST_NAME: initialization.manifest_content}
    if source_manifest.exists():
        if not source_manifest.is_file() or source_manifest.is_symlink():
            raise ProjectHomePortabilityError("source project-home manifest is unsafe")
        validate_project_home_manifest_content(source_manifest.read_bytes())
        generated = None
    backup = prepare_portable_backup(
        source,
        backup_target,
        ownership,
        generated_files=generated,
    )
    restore = _restore_mutation(backup, target, ownership)
    identity = {
        "source_home_sha256": hashlib.sha256(str(source).encode("utf-8")).hexdigest(),
        "target_home_sha256": hashlib.sha256(str(target).encode("utf-8")).hexdigest(),
        "backup_plan_id": backup.plan_id,
        "restore_plan_id": restore.plan_id,
        "git_exclusion_plan_id": (
            initialization.git_exclusion.mutation.plan_id
            if initialization.git_exclusion is not None
            else None
        ),
        "source_preserved": True,
    }
    return ProjectHomeMigrationPlan(
        hashlib.sha256(_canonical_json(identity)).hexdigest(),
        source,
        initialization,
        backup,
        restore,
        ownership,
    )


def apply_project_home_migration(
    plan: ProjectHomeMigrationPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> ProjectHomeMigrationResult:
    """Back up first, restore atomically, and never remove the source home."""

    _require_authorizations(plan.effect_plans, authorizations)
    apply_portable_backup(plan.backup, authorizations[plan.backup.mutation.plan_id])
    restore = prepare_portable_restore(
        plan.backup.archive_path,
        plan.initialization.resolution.path,
        plan.ownership,
    )
    if restore.mutation.plan_id != plan.restore_mutation.plan_id:
        raise ProjectHomePortabilityError("restore effect changed after planning")
    exclusion_applied = False
    try:
        if plan.initialization.git_exclusion is not None:
            apply_git_exclusion(plan.initialization.git_exclusion)
            exclusion_applied = True
        result = apply_portable_restore(
            restore,
            authorizations[plan.restore_mutation.plan_id],
        )
        validate_initialized_project_home(plan.initialization.resolution.path)
    except Exception:
        if exclusion_applied and plan.initialization.git_exclusion is not None:
            rollback_git_exclusion(plan.initialization.git_exclusion)
        raise
    if not plan.source_home.is_dir():
        raise ProjectHomePortabilityError("migration source was not preserved")
    return ProjectHomeMigrationResult(
        plan.plan_id,
        plan.backup.backup_id,
        result.restored_entry_count,
        result.rebind_required_count,
        source_preserved=True,
        rollback_ready=True,
    )


@dataclass(frozen=True)
class ProjectHomeRestorePlan:
    plan_id: str
    initialization: ProjectHomeInitializationPlan
    restore: PortableRestorePlan

    @property
    def effect_plans(self) -> tuple[MutationPlan, ...]:
        effects = []
        if self.initialization.git_exclusion is not None:
            effects.append(self.initialization.git_exclusion.mutation)
        effects.append(self.restore.mutation)
        return tuple(effects)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "backup_id": self.restore.backup_id,
            "entry_count": len(self.restore.entries),
            "rebind_required_count": sum(
                bool(item.get("rebind_required"))
                for item in self.restore.external_dependencies
            ),
            "project_manifest_required": True,
            "target_must_be_empty": True,
            "paths_disclosed": False,
            "effect_plans": [item.as_dict() for item in self.effect_plans],
        }


def prepare_project_home_restore(
    archive_path: Path,
    resolution: ProjectHomeResolution,
    ownership: OwnershipResolver,
) -> ProjectHomeRestorePlan:
    """Plan a clean-clone restore with project Git protection."""

    if resolution.path.exists() and any(resolution.path.iterdir()):
        raise ProjectHomePortabilityError("restore target must be empty")
    initialization = prepare_project_home_initialization(resolution, ownership)
    restore = prepare_portable_restore(
        archive_path,
        initialization.resolution.path,
        ownership,
    )
    marker = next((item for item in restore.entries if item.path == MANIFEST_NAME), None)
    if marker is None:
        raise ProjectHomePortabilityError(
            "portable backup does not contain a project-home manifest"
        )
    validate_project_home_manifest_content(marker.content)
    identity = {
        "restore_plan_id": restore.plan_id,
        "git_exclusion_plan_id": (
            initialization.git_exclusion.mutation.plan_id
            if initialization.git_exclusion is not None
            else None
        ),
    }
    return ProjectHomeRestorePlan(
        hashlib.sha256(_canonical_json(identity)).hexdigest(),
        initialization,
        restore,
    )


def apply_project_home_restore(
    plan: ProjectHomeRestorePlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> dict[str, object]:
    """Apply an exact clean-clone restore and verify its project marker."""

    _require_authorizations(plan.effect_plans, authorizations)
    exclusion_applied = False
    try:
        if plan.initialization.git_exclusion is not None:
            apply_git_exclusion(plan.initialization.git_exclusion)
            exclusion_applied = True
        result = apply_portable_restore(
            plan.restore,
            authorizations[plan.restore.mutation.plan_id],
        )
        validate_initialized_project_home(plan.initialization.resolution.path)
    except Exception:
        if exclusion_applied and plan.initialization.git_exclusion is not None:
            rollback_git_exclusion(plan.initialization.git_exclusion)
        raise
    return {
        **result.public_summary(),
        "project_home_verified": True,
        "rollback_ready": True,
    }
