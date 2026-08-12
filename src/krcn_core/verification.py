"""Mandatory post-deployment verification and installation state commit."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .deployment import (
    DeploymentAuthorization,
    DeploymentPlan,
    _atomic_write,
    _stored_document,
    write_deployment_status,
)
from .installation import (
    installation_state_sha256,
    load_installation_state,
    safe_installation_target,
)
from .mutation_gate import OwnershipResolver


class VerificationError(ValueError):
    """Raised when mandatory post-deployment verification fails."""


@dataclass(frozen=True)
class VerificationResult:
    deployment_id: str
    managed_files_verified: int
    protected_json_verified: int
    backup_entries_verified: int
    state_sha256: str
    status: str

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "managed_files_verified": self.managed_files_verified,
            "protected_json_verified": self.protected_json_verified,
            "backup_entries_verified": self.backup_entries_verified,
            "state_sha256": self.state_sha256,
            "status": self.status,
        }


@dataclass(frozen=True)
class InstallationVerificationResult:
    inspection_id: str
    installation_id: str
    core_version: str
    managed_files_verified: int
    protected_json_verified: int
    status: str

    def public_summary(self) -> dict[str, object]:
        return {
            "inspection_id": self.inspection_id,
            "installation_id": self.installation_id,
            "core_version": self.core_version,
            "managed_files_verified": self.managed_files_verified,
            "protected_json_verified": self.protected_json_verified,
            "status": self.status,
        }


def _stable_hash(path: Path) -> tuple[int, str]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise VerificationError("file changed during post-deployment verification")
    return after.st_size, digest.hexdigest()


def _assert_file(
    root: Path,
    target_ref: str,
    expected_sha256: str,
    expected_size: int | None = None,
) -> None:
    target = safe_installation_target(root, target_ref)
    if target.is_symlink() or not target.is_file():
        raise VerificationError("required post-deployment file is missing")
    size, digest = _stable_hash(target)
    if digest != expected_sha256 or (
        expected_size is not None and size != expected_size
    ):
        raise VerificationError("post-deployment file evidence does not match")


def _assert_absent(root: Path, target_ref: str) -> None:
    target = safe_installation_target(root, target_ref)
    if target.exists() or target.is_symlink():
        raise VerificationError("deleted target still exists after deployment")


def _verify_checkpoint(root: Path, plan: DeploymentPlan) -> int:
    manifest_ref = (
        f".krcn/checkpoints/{plan.deployment_id}/backup-manifest.json"
    )
    _assert_file(root, manifest_ref, plan.backup_manifest_sha256)
    verified = 0
    seen_digests = set()
    for entry in plan.backup_manifest.entries:
        if not entry.existed or entry.sha256 is None:
            continue
        if entry.content_ref is None or entry.size is None:
            raise VerificationError("backup entry lacks recovery evidence")
        if entry.sha256 not in seen_digests:
            _assert_file(root, entry.content_ref, entry.sha256, entry.size)
            seen_digests.add(entry.sha256)
        verified += 1
    return verified


def _verify_managed_files(root: Path, plan: DeploymentPlan) -> int:
    desired = {item.path: item for item in plan.merge_plan.desired_state.managed_files}
    for item in desired.values():
        _assert_file(root, item.path, item.sha256, item.size)
    for change in plan.merge_plan.file_changes:
        if change.action == "delete":
            _assert_absent(root, change.path)
    return len(desired)


def _verify_effect_writes(root: Path, plan: DeploymentPlan) -> None:
    for write in plan.migration_writes:
        _assert_file(root, write.target_ref, write.target_sha256)
    for write in plan.derived_writes:
        if write.action == "delete":
            _assert_absent(root, write.target_ref)
        elif write.target_sha256 is not None:
            _assert_file(root, write.target_ref, write.target_sha256)
        else:
            raise VerificationError("derived write lacks target evidence")


def _verify_protected_json(root: Path) -> int:
    protected_roots = (
        ".krcn/workspaces",
        ".krcn/projects",
        ".krcn/global",
        ".krcn/local",
        ".krcn/integrations",
        ".krcn/documents",
        ".krcn/work-items",
        ".krcn/decisions",
        ".krcn/memory",
        ".krcn/policies",
        ".krcn/source-bindings",
        ".krcn/derived",
        ".krcn/indexes",
        ".krcn/cache",
    )
    verified = 0
    for target_ref in protected_roots:
        target = safe_installation_target(root, target_ref)
        if not target.exists():
            continue
        if target.is_symlink() or not target.is_dir():
            raise VerificationError("protected data scope is invalid")
        for directory, directory_names, file_names in os.walk(
            target,
            followlinks=False,
        ):
            directory_path = Path(directory)
            for name in directory_names:
                if (directory_path / name).is_symlink():
                    raise VerificationError(
                        "protected data may not contain symbolic links"
                    )
            for name in file_names:
                path = directory_path / name
                if path.is_symlink():
                    raise VerificationError(
                        "protected data may not contain symbolic links"
                    )
                if path.suffix.lower() != ".json":
                    continue
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise VerificationError("protected JSON is invalid") from exc
                verified += 1
    return verified


def _verify_expected_post_state(root: Path, plan: DeploymentPlan) -> int:
    verified = 0
    for entry in plan.backup_manifest.entries:
        if entry.expected_post_existed:
            if entry.expected_post_sha256 is None:
                raise VerificationError("backup entry lacks expected post hash")
            _assert_file(root, entry.target_ref, entry.expected_post_sha256)
        else:
            if entry.expected_post_sha256 is not None:
                raise VerificationError("absent post state may not have a hash")
            _assert_absent(root, entry.target_ref)
        verified += 1
    return verified


def _expected_pre_verification_status(plan: DeploymentPlan) -> str:
    if plan.merge_plan.derived_actions:
        return "rebuilding"
    if plan.merge_plan.migrations:
        return "migrating"
    return "applying"


def _journal_status(root: Path, plan: DeploymentPlan) -> str:
    target = safe_installation_target(
        root,
        f".krcn/runtime/deployments/{plan.deployment_id}.json",
    )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("deployment journal is invalid") from exc
    if (
        payload.get("deployment_id") != plan.deployment_id
        or payload.get("merge_plan_id") != plan.merge_plan.plan_id
    ):
        raise VerificationError("deployment journal identity is invalid")
    status = payload.get("status")
    if not isinstance(status, str):
        raise VerificationError("deployment journal status is invalid")
    return status


def verify_and_commit(
    installation_root: Path,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
) -> VerificationResult:
    """Verify every planned effect, commit state, and complete the journal."""

    root = installation_root.resolve()
    if authorization.plan_id != plan.plan_id:
        raise VerificationError("deployment authorization does not match plan")
    if _journal_status(root, plan) != _expected_pre_verification_status(plan):
        raise VerificationError("deployment is not ready for verification")
    state, state_sha256 = load_installation_state(root)
    if state is None or state_sha256 != plan.merge_plan.source_state_sha256:
        raise VerificationError("installation state changed before verification")
    state_mutation = plan.merge_plan.state_mutation
    if state_mutation is None:
        raise VerificationError("deployment plan lacks state transition")
    state_authorization = (
        authorization.merge_authorization.mutation_authorizations.get(
            state_mutation.plan_id
        )
    )
    if (
        state_authorization is None
        or state_authorization.plan.plan_id != state_mutation.plan_id
        or not state_authorization.dry_run_verified
        or (
            state_mutation.approval_required
            and not state_authorization.approval_verified
        )
    ):
        raise VerificationError("installation state mutation is not authorized")
    write_deployment_status(root, plan, authorization, "verifying")
    backup_verified = _verify_checkpoint(root, plan)
    managed_verified = _verify_managed_files(root, plan)
    _verify_effect_writes(root, plan)
    protected_verified = _verify_protected_json(root)
    desired_digest = installation_state_sha256(plan.merge_plan.desired_state)
    if state_mutation.change_digest != desired_digest:
        raise VerificationError("desired installation state evidence changed")
    state_target = safe_installation_target(root, state_mutation.target_ref)
    _atomic_write(
        state_target,
        _stored_document(plan.merge_plan.desired_state.as_payload()),
    )
    committed_state, committed_sha256 = load_installation_state(root)
    if (
        committed_state != plan.merge_plan.desired_state
        or committed_sha256 != desired_digest
    ):
        raise VerificationError("installation state commit verification failed")
    post_verified = _verify_expected_post_state(root, plan)
    write_deployment_status(root, plan, authorization, "completed")
    return VerificationResult(
        deployment_id=plan.deployment_id,
        managed_files_verified=managed_verified,
        protected_json_verified=protected_verified,
        backup_entries_verified=max(backup_verified, post_verified),
        state_sha256=desired_digest,
        status="completed",
    )


def verify_installation(
    installation_root: Path,
    ownership: OwnershipResolver,
) -> InstallationVerificationResult:
    """Verify the current installation without requiring an in-memory plan."""

    from .installation import inspect_installation

    root = installation_root.resolve()
    inspection = inspect_installation(root, ownership)
    if (
        not inspection.state_present
        or inspection.installation_id is None
        or inspection.core_version is None
    ):
        raise VerificationError("installation state is missing")
    if not inspection.managed_clean:
        raise VerificationError("managed installation files are not clean")
    if inspection.symlink_count:
        raise VerificationError("installation contains symbolic links")
    if inspection.interrupted_deployments:
        raise VerificationError("installation has an interrupted deployment")
    protected_verified = _verify_protected_json(root)
    return InstallationVerificationResult(
        inspection_id=inspection.inspection_id,
        installation_id=inspection.installation_id,
        core_version=inspection.core_version,
        managed_files_verified=len(inspection.managed_verified),
        protected_json_verified=protected_verified,
        status="verified",
    )
