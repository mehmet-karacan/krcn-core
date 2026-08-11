"""Authorized atomic core file application and planned migration writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .deployment import (
    DeploymentAuthorization,
    DeploymentPlan,
    _atomic_write,
    write_deployment_status,
)
from .installation import safe_installation_target
from .release import ReleaseBundle, safe_payload_target


class MergeApplyError(ValueError):
    """Raised when planned merge effects cannot be applied exactly."""


@dataclass(frozen=True)
class ManagedApplyResult:
    deployment_id: str
    applied_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "applied_paths": list(self.applied_paths),
            "deleted_paths": list(self.deleted_paths),
        }


@dataclass(frozen=True)
class MigrationApplyResult:
    deployment_id: str
    completed_migrations: tuple[str, ...]
    updated_records: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "completed_migrations": list(self.completed_migrations),
            "updated_records": list(self.updated_records),
        }


@dataclass(frozen=True)
class DerivedApplyResult:
    deployment_id: str
    completed_actions: tuple[str, ...]
    written_records: tuple[str, ...]
    deleted_records: tuple[str, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "completed_actions": list(self.completed_actions),
            "written_records": list(self.written_records),
            "deleted_records": list(self.deleted_records),
        }


def _stable_hash(path: Path) -> tuple[int, str]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise MergeApplyError("file changed during merge validation")
    return after.st_size, digest.hexdigest()


def _journal_status(root: Path, plan: DeploymentPlan) -> str:
    path = safe_installation_target(
        root,
        f".krcn/runtime/deployments/{plan.deployment_id}.json",
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise MergeApplyError("deployment journal is invalid") from exc
    if (
        payload.get("deployment_id") != plan.deployment_id
        or payload.get("merge_plan_id") != plan.merge_plan.plan_id
    ):
        raise MergeApplyError("deployment journal identity is invalid")
    status = payload.get("status")
    if not isinstance(status, str):
        raise MergeApplyError("deployment journal status is invalid")
    return status


def _assert_mutation_authorized(plan, authorization) -> None:
    if (
        authorization is None
        or authorization.plan.plan_id != plan.plan_id
        or not authorization.dry_run_verified
        or (plan.approval_required and not authorization.approval_verified)
    ):
        raise MergeApplyError("merge mutation lacks matching authorization")


def apply_managed_files(
    installation_root: Path,
    release_root: Path,
    bundle: ReleaseBundle,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
) -> ManagedApplyResult:
    """Apply only prevalidated managed core mutations after verified backup."""

    root = installation_root.resolve()
    release = release_root.resolve()
    if authorization.plan_id != plan.plan_id:
        raise MergeApplyError("deployment authorization does not match plan")
    if (
        bundle.manifest_sha256 != plan.merge_plan.manifest_sha256
        or bundle.manifest.release_id != plan.merge_plan.release_id
        or bundle.manifest.source_commit != plan.merge_plan.desired_state.source_commit
    ):
        raise MergeApplyError("release bundle does not match deployment plan")
    if _journal_status(root, plan) != "backed-up":
        raise MergeApplyError("managed apply requires backed-up deployment")
    changes = {item.path: item for item in plan.merge_plan.file_changes}
    prepared_payloads: dict[str, bytes] = {}
    for mutation in plan.merge_plan.file_mutations:
        auth = authorization.merge_authorization.mutation_authorizations.get(
            mutation.plan_id
        )
        _assert_mutation_authorized(mutation, auth)
        change = changes.get(mutation.target_ref)
        if change is None:
            raise MergeApplyError("file mutation lacks diff evidence")
        target = safe_installation_target(root, mutation.target_ref)
        if mutation.operation == "create":
            if target.exists():
                raise MergeApplyError("planned create target now exists")
        else:
            if not target.is_file() or target.is_symlink():
                raise MergeApplyError("managed mutation target is missing")
            _, digest = _stable_hash(target)
            if digest != change.previous_sha256:
                raise MergeApplyError("managed target changed after backup")
        if mutation.operation in {"create", "update"}:
            payload_path = safe_payload_target(release, mutation.target_ref)
            if not payload_path.is_file() or payload_path.is_symlink():
                raise MergeApplyError("release payload target is invalid")
            content = payload_path.read_bytes()
            if (
                hashlib.sha256(content).hexdigest() != mutation.change_digest
                or len(content) != change.target_size
            ):
                raise MergeApplyError("release payload changed after dry-run")
            prepared_payloads[mutation.target_ref] = content
    write_deployment_status(root, plan, authorization, "applying")
    applied = []
    deleted = []
    for mutation in plan.merge_plan.file_mutations:
        target = safe_installation_target(root, mutation.target_ref)
        if mutation.operation in {"create", "update"}:
            _atomic_write(target, prepared_payloads[mutation.target_ref])
            _, digest = _stable_hash(target)
            if digest != mutation.change_digest:
                raise MergeApplyError("managed file verification failed after write")
            applied.append(mutation.target_ref)
        else:
            target.unlink()
            if target.exists():
                raise MergeApplyError("managed delete verification failed")
            deleted.append(mutation.target_ref)
    return ManagedApplyResult(
        deployment_id=plan.deployment_id,
        applied_paths=tuple(applied),
        deleted_paths=tuple(deleted),
    )


def apply_migrations(
    installation_root: Path,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
) -> MigrationApplyResult:
    """Apply exact, idempotent migration documents planned before backup."""

    root = installation_root.resolve()
    if authorization.plan_id != plan.plan_id:
        raise MergeApplyError("deployment authorization does not match plan")
    if _journal_status(root, plan) != "applying":
        raise MergeApplyError("migration requires completed managed apply stage")
    for write in plan.migration_writes:
        auth = authorization.migration_authorizations.get(write.mutation.plan_id)
        _assert_mutation_authorized(write.mutation, auth)
        target = safe_installation_target(root, write.target_ref)
        if not target.is_file() or target.is_symlink():
            raise MergeApplyError("migration target is missing")
        _, digest = _stable_hash(target)
        if digest != write.previous_sha256:
            raise MergeApplyError("migration target changed after dry-run")
        if hashlib.sha256(write.document).hexdigest() != write.target_sha256:
            raise MergeApplyError("planned migration document is invalid")
    write_deployment_status(root, plan, authorization, "migrating")
    updated = []
    for write in plan.migration_writes:
        target = safe_installation_target(root, write.target_ref)
        _atomic_write(target, write.document)
        _, digest = _stable_hash(target)
        if digest != write.target_sha256:
            raise MergeApplyError("migration verification failed after write")
        updated.append(write.target_ref)
    return MigrationApplyResult(
        deployment_id=plan.deployment_id,
        completed_migrations=tuple(
            item.migration_id for item in plan.merge_plan.migrations
        ),
        updated_records=tuple(updated),
    )


def apply_derived_actions(
    installation_root: Path,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
) -> DerivedApplyResult:
    """Apply only the exact JSON rebuild effects captured by the dry-run."""

    root = installation_root.resolve()
    if authorization.plan_id != plan.plan_id:
        raise MergeApplyError("deployment authorization does not match plan")
    expected_status = "migrating" if plan.merge_plan.migrations else "applying"
    if _journal_status(root, plan) != expected_status:
        raise MergeApplyError("derived rebuild requires the preceding apply stage")
    for write in plan.derived_writes:
        auth = authorization.derived_authorizations.get(write.mutation.plan_id)
        _assert_mutation_authorized(write.mutation, auth)
        target = safe_installation_target(root, write.target_ref)
        if write.action == "create":
            if target.exists():
                raise MergeApplyError("planned derived create target now exists")
        else:
            if not target.is_file() or target.is_symlink():
                raise MergeApplyError("derived target is missing")
            _, digest = _stable_hash(target)
            if digest != write.previous_sha256:
                raise MergeApplyError("derived target changed after dry-run")
        if write.action in {"create", "update"}:
            if write.document is None or write.target_sha256 is None:
                raise MergeApplyError("planned derived document is missing")
            if hashlib.sha256(write.document).hexdigest() != write.target_sha256:
                raise MergeApplyError("planned derived document is invalid")
    write_deployment_status(root, plan, authorization, "rebuilding")
    written = []
    deleted = []
    for write in plan.derived_writes:
        target = safe_installation_target(root, write.target_ref)
        if write.action in {"create", "update"}:
            _atomic_write(target, write.document or b"")
            _, digest = _stable_hash(target)
            if digest != write.target_sha256:
                raise MergeApplyError("derived verification failed after write")
            written.append(write.target_ref)
        else:
            target.unlink()
            if target.exists():
                raise MergeApplyError("derived delete verification failed")
            deleted.append(write.target_ref)
    return DerivedApplyResult(
        deployment_id=plan.deployment_id,
        completed_actions=tuple(
            item.action_id for item in plan.merge_plan.derived_actions
        ),
        written_records=tuple(written),
        deleted_records=tuple(deleted),
    )
