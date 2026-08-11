"""Exact backup plans and interruption-aware deployment journals."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .installation import (
    InstallationState,
    installation_state_sha256,
    load_installation_state,
    safe_installation_target,
)
from .derived_actions import (
    DerivedActionHandlerRegistry,
    DerivedWrite,
    plan_derived_writes,
)
from .merge_plan import (
    MergeAuthorization,
    MergePlan,
    authorize_merge_plan,
)
from .migrations import (
    MigrationHandlerRegistry,
    MigrationWrite,
    plan_migration_writes,
)
from .mutation_gate import (
    ApprovalEvidence,
    DryRunEvidence,
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    authorize_mutation,
    plan_mutation,
)


JOURNAL_STATUSES = (
    "preparing",
    "backed-up",
    "applying",
    "migrating",
    "rebuilding",
    "verifying",
    "completed",
    "rolling-back",
    "rolled-back",
    "failed",
)
JOURNAL_TRANSITIONS = {
    "preparing": {"backed-up", "failed"},
    "backed-up": {"applying", "rolling-back", "failed"},
    "applying": {"migrating", "rebuilding", "verifying", "rolling-back", "failed"},
    "migrating": {"rebuilding", "verifying", "rolling-back", "failed"},
    "rebuilding": {"verifying", "rolling-back", "failed"},
    "verifying": {"completed", "rolling-back", "failed"},
    "completed": {"rolling-back"},
    "failed": {"rolling-back"},
    "rolling-back": {"rolled-back", "failed"},
    "rolled-back": set(),
}


class DeploymentError(ValueError):
    """Raised when backup or deployment journal guarantees cannot be met."""


@dataclass(frozen=True)
class BackupEntry:
    target_ref: str
    existed: bool
    sha256: str | None
    size: int | None
    content_ref: str | None
    expected_post_existed: bool
    expected_post_sha256: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "target_ref": self.target_ref,
            "existed": self.existed,
            "sha256": self.sha256,
            "size": self.size,
            "content_ref": self.content_ref,
            "expected_post_existed": self.expected_post_existed,
            "expected_post_sha256": self.expected_post_sha256,
        }


@dataclass(frozen=True)
class BackupScope:
    target_ref: str
    ownership: str
    remove_created_on_rollback: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "target_ref": self.target_ref,
            "ownership": self.ownership,
            "remove_created_on_rollback": self.remove_created_on_rollback,
        }


@dataclass(frozen=True)
class BackupManifest:
    deployment_id: str
    merge_plan_id: str
    installation_id: str
    source_state_sha256: str
    entries: tuple[BackupEntry, ...]
    scopes: tuple[BackupScope, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/backup-manifest.schema.json",
            "schema_version": 1,
            "deployment_id": self.deployment_id,
            "merge_plan_id": self.merge_plan_id,
            "installation_id": self.installation_id,
            "source_state_sha256": self.source_state_sha256,
            "entries": [item.as_dict() for item in self.entries],
            "scopes": [item.as_dict() for item in self.scopes],
        }


@dataclass(frozen=True)
class DeploymentPlan:
    plan_id: str
    deployment_id: str
    merge_plan: MergePlan
    backup_manifest: BackupManifest
    backup_manifest_sha256: str
    migration_writes: tuple[MigrationWrite, ...]
    derived_writes: tuple[DerivedWrite, ...]
    content_mutations: tuple[MutationPlan, ...]
    backup_manifest_mutation: MutationPlan
    journal_mutations: Mapping[str, MutationPlan]

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "deployment_id": self.deployment_id,
            "merge_plan": self.merge_plan.public_summary(),
            "backup_manifest_sha256": self.backup_manifest_sha256,
            "backup_entries": [
                item.as_dict() for item in self.backup_manifest.entries
            ],
            "backup_scopes": [
                item.as_dict() for item in self.backup_manifest.scopes
            ],
            "migration_writes": [
                item.public_summary() for item in self.migration_writes
            ],
            "derived_writes": [
                item.public_summary() for item in self.derived_writes
            ],
            "support_mutations": {
                "content": [item.as_dict() for item in self.content_mutations],
                "manifest": self.backup_manifest_mutation.as_dict(),
                "journal": {
                    status: mutation.as_dict()
                    for status, mutation in self.journal_mutations.items()
                },
            },
            "approval_required": self.approval_required,
        }

    @property
    def approval_required(self) -> bool:
        return self.merge_plan.approval_required or any(
            item.mutation.approval_required for item in self.derived_writes
        )


@dataclass(frozen=True)
class DeploymentAuthorization:
    plan_id: str
    approval_id: str | None
    merge_authorization: MergeAuthorization
    support_authorizations: Mapping[str, MutationAuthorization]
    migration_authorizations: Mapping[str, MutationAuthorization]
    derived_authorizations: Mapping[str, MutationAuthorization]


@dataclass(frozen=True)
class DeploymentStartResult:
    deployment_id: str
    status: str
    backup_manifest_sha256: str

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "status": self.status,
            "backup_manifest_sha256": self.backup_manifest_sha256,
        }


def _canonical_document(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _document_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_document(payload)).hexdigest()


def _stable_file_hash(path: Path) -> tuple[int, str]:
    before = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise DeploymentError("backup source changed while it was inspected")
    return after.st_size, digest.hexdigest()


def _deployment_root(root: Path) -> Path:
    if not root.is_absolute():
        raise DeploymentError("installation root must be absolute")
    if root.is_symlink():
        raise DeploymentError("installation root may not be a symbolic link")
    resolved = root.resolve()
    if not resolved.is_dir():
        raise DeploymentError("installation root must be an existing directory")
    return resolved


def _existing_deployment_ids(root: Path) -> tuple[str, ...]:
    directory = safe_installation_target(root, ".krcn/runtime/deployments")
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise DeploymentError("deployment journal location must be a directory")
    ids = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink():
            raise DeploymentError("deployment journal may not be a symbolic link")
        ids.append(path.stem)
    return tuple(ids)


def _deployment_id(root: Path, merge_plan: MergePlan) -> str:
    identity = {
        "merge_plan_id": merge_plan.plan_id,
        "existing_deployments": list(_existing_deployment_ids(root)),
    }
    digest = hashlib.sha256(_canonical_document(identity)).hexdigest()
    return f"deploy-{digest[:24]}"


def _content_ref(deployment_id: str, digest: str) -> str:
    return f".krcn/checkpoints/{deployment_id}/content/{digest}"


def _add_existing_entry(
    root: Path,
    target_ref: str,
    entries: dict[str, BackupEntry],
) -> None:
    if target_ref in entries:
        return
    target = safe_installation_target(root, target_ref)
    if not target.exists() or target.is_symlink() or not target.is_file():
        raise DeploymentError("required backup source must be a regular file")
    size, digest = _stable_file_hash(target)
    entries[target_ref] = BackupEntry(
        target_ref=target_ref,
        existed=True,
        sha256=digest,
        size=size,
        content_ref=None,
        expected_post_existed=True,
        expected_post_sha256=digest,
    )


def _add_scope_entries(
    root: Path,
    scope: BackupScope,
    ownership: OwnershipResolver,
    entries: dict[str, BackupEntry],
) -> None:
    target = safe_installation_target(root, scope.target_ref)
    if not target.exists():
        return
    if target.is_symlink():
        raise DeploymentError("backup scope may not be a symbolic link")
    if target.is_file():
        paths = [target]
    elif target.is_dir():
        paths = []
        for directory, directory_names, file_names in os.walk(
            target,
            followlinks=False,
        ):
            directory_path = Path(directory)
            for name in directory_names:
                if (directory_path / name).is_symlink():
                    raise DeploymentError("backup scope may not contain symbolic links")
            for name in file_names:
                path = directory_path / name
                if path.is_symlink() or not path.is_file():
                    raise DeploymentError("backup scope may contain only regular files")
                paths.append(path)
    else:
        raise DeploymentError("backup scope must be a file or directory")
    for path in paths:
        target_ref = path.relative_to(root).as_posix()
        if ownership.resolve(target_ref) != scope.ownership:
            raise DeploymentError("backup scope contains unexpected ownership")
        _add_existing_entry(root, target_ref, entries)


def _journal_payload(
    deployment_id: str,
    merge_plan: MergePlan,
    backup_manifest_sha256: str,
    status: str,
) -> dict[str, object]:
    return {
        "schema_ref": "schemas/deployment-journal.schema.json",
        "schema_version": 1,
        "deployment_id": deployment_id,
        "merge_plan_id": merge_plan.plan_id,
        "installation_id": merge_plan.installation_id,
        "release_id": merge_plan.release_id,
        "backup_manifest_sha256": backup_manifest_sha256,
        "status": status,
    }


def prepare_deployment_plan(
    installation_root: Path,
    merge_plan: MergePlan,
    ownership: OwnershipResolver,
    migration_handlers: MigrationHandlerRegistry | None = None,
    derived_handlers: DerivedActionHandlerRegistry | None = None,
) -> DeploymentPlan:
    """Plan exact backup and journal writes without changing the installation."""

    root = _deployment_root(installation_root)
    if not merge_plan.has_effects:
        raise DeploymentError("no-op merge does not require a deployment")
    state, state_sha256 = load_installation_state(root)
    if state is None or state_sha256 != merge_plan.source_state_sha256:
        raise DeploymentError("installation state changed after merge planning")
    handlers = migration_handlers or MigrationHandlerRegistry()
    migration_writes = plan_migration_writes(
        root,
        merge_plan.migrations,
        handlers,
        ownership,
    )
    resolved_derived_handlers = derived_handlers or DerivedActionHandlerRegistry()
    derived_writes = plan_derived_writes(
        root,
        merge_plan.derived_actions,
        resolved_derived_handlers,
        ownership,
    )
    deployment_id = _deployment_id(root, merge_plan)
    checkpoint_ref = f".krcn/checkpoints/{deployment_id}"
    journal_ref = f".krcn/runtime/deployments/{deployment_id}.json"
    if safe_installation_target(root, checkpoint_ref).exists():
        raise DeploymentError("deployment checkpoint already exists")
    if safe_installation_target(root, journal_ref).exists():
        raise DeploymentError("deployment journal already exists")
    entries: dict[str, BackupEntry] = {}
    state_ref = ".krcn/runtime/installation-state.json"
    _add_existing_entry(root, state_ref, entries)
    changes = {item.path: item for item in merge_plan.file_changes}
    for mutation in merge_plan.file_mutations:
        change = changes.get(mutation.target_ref)
        if change is None:
            raise DeploymentError("file mutation lacks diff evidence")
        target = safe_installation_target(root, mutation.target_ref)
        if mutation.operation == "create":
            if target.exists():
                raise DeploymentError("planned create target now exists")
            entries[mutation.target_ref] = BackupEntry(
                target_ref=mutation.target_ref,
                existed=False,
                sha256=None,
                size=None,
                content_ref=None,
                expected_post_existed=False,
                expected_post_sha256=None,
            )
            continue
        if change.previous_sha256 is None:
            raise DeploymentError("planned mutation lacks previous hash")
        _add_existing_entry(root, mutation.target_ref, entries)
        if entries[mutation.target_ref].sha256 != change.previous_sha256:
            raise DeploymentError("managed file changed after merge planning")
    scopes = []
    for migration in merge_plan.migrations:
        scopes.append(
            BackupScope(
                migration.target_ref,
                migration.ownership,
                False,
            )
        )
    for action in merge_plan.derived_actions:
        scopes.append(BackupScope(action.target_ref, "derived", True))
    unique_scopes = {
        (item.target_ref, item.ownership, item.remove_created_on_rollback): item
        for item in scopes
    }
    scopes_tuple = tuple(
        sorted(unique_scopes.values(), key=lambda item: item.target_ref)
    )
    for scope in scopes_tuple:
        _add_scope_entries(root, scope, ownership, entries)
    for target_ref, entry in tuple(entries.items()):
        if entry.existed and entry.sha256 is not None:
            entries[target_ref] = BackupEntry(
                target_ref=entry.target_ref,
                existed=True,
                sha256=entry.sha256,
                size=entry.size,
                content_ref=_content_ref(deployment_id, entry.sha256),
                expected_post_existed=entry.expected_post_existed,
                expected_post_sha256=entry.expected_post_sha256,
            )
    for write in derived_writes:
        if write.target_ref not in entries and write.action == "create":
            entries[write.target_ref] = BackupEntry(
                target_ref=write.target_ref,
                existed=False,
                sha256=None,
                size=None,
                content_ref=None,
                expected_post_existed=False,
                expected_post_sha256=None,
            )
    expected_post = {
        target_ref: (entry.existed, entry.sha256)
        for target_ref, entry in entries.items()
    }
    for change in merge_plan.file_changes:
        if change.action in {"create", "update", "unchanged"}:
            expected_post[change.path] = (True, change.target_sha256)
        elif change.action == "delete":
            expected_post[change.path] = (False, None)
    for write in migration_writes:
        expected_post[write.target_ref] = (True, write.target_sha256)
    for write in derived_writes:
        expected_post[write.target_ref] = (
            write.action != "delete",
            write.target_sha256,
        )
    expected_post[state_ref] = (
        True,
        _document_sha256(merge_plan.desired_state.as_payload()),
    )
    entries = {
        target_ref: BackupEntry(
            target_ref=entry.target_ref,
            existed=entry.existed,
            sha256=entry.sha256,
            size=entry.size,
            content_ref=entry.content_ref,
            expected_post_existed=expected_post[target_ref][0],
            expected_post_sha256=expected_post[target_ref][1],
        )
        for target_ref, entry in entries.items()
    }
    backup_manifest = BackupManifest(
        deployment_id=deployment_id,
        merge_plan_id=merge_plan.plan_id,
        installation_id=merge_plan.installation_id,
        source_state_sha256=merge_plan.source_state_sha256,
        entries=tuple(sorted(entries.values(), key=lambda item: item.target_ref)),
        scopes=scopes_tuple,
    )
    manifest_digest = _document_sha256(backup_manifest.as_payload())
    unique_content = {
        item.sha256: item
        for item in backup_manifest.entries
        if item.existed and item.sha256 is not None
    }
    content_mutations = tuple(
        plan_mutation(
            ownership,
            operation="create",
            target_ref=_content_ref(deployment_id, digest),
            expected_ownership="runtime",
            change_digest=digest,
            reversible=True,
        )
        for digest in sorted(unique_content)
    )
    backup_manifest_mutation = plan_mutation(
        ownership,
        operation="create",
        target_ref=f"{checkpoint_ref}/backup-manifest.json",
        expected_ownership="runtime",
        change_digest=manifest_digest,
        reversible=True,
    )
    journal_mutations = {}
    for index, status in enumerate(JOURNAL_STATUSES):
        payload = _journal_payload(
            deployment_id,
            merge_plan,
            manifest_digest,
            status,
        )
        journal_mutations[status] = plan_mutation(
            ownership,
            operation="create" if index == 0 else "update",
            target_ref=journal_ref,
            expected_ownership="runtime",
            change_digest=_document_sha256(payload),
            reversible=True,
        )
    identity = {
        "merge_plan_id": merge_plan.plan_id,
        "deployment_id": deployment_id,
        "backup_manifest_sha256": manifest_digest,
        "content_mutation_ids": [item.plan_id for item in content_mutations],
        "backup_manifest_mutation_id": backup_manifest_mutation.plan_id,
        "migration_mutation_ids": [
            item.mutation.plan_id for item in migration_writes
        ],
        "derived_mutation_ids": [
            item.mutation.plan_id for item in derived_writes
        ],
        "journal_mutation_ids": {
            status: item.plan_id for status, item in journal_mutations.items()
        },
    }
    plan_id = hashlib.sha256(_canonical_document(identity)).hexdigest()
    return DeploymentPlan(
        plan_id=plan_id,
        deployment_id=deployment_id,
        merge_plan=merge_plan,
        backup_manifest=backup_manifest,
        backup_manifest_sha256=manifest_digest,
        migration_writes=migration_writes,
        derived_writes=derived_writes,
        content_mutations=content_mutations,
        backup_manifest_mutation=backup_manifest_mutation,
        journal_mutations=journal_mutations,
    )


def authorize_deployment_plan(
    plan: DeploymentPlan,
    *,
    expected_plan_id: str,
    approval_id: str | None,
) -> DeploymentAuthorization:
    """Authorize the exact deployment, merge, backup, and journal plans."""

    if expected_plan_id != plan.plan_id:
        raise DeploymentError("deployment requires the exact dry-run plan id")
    if plan.approval_required and not (approval_id and approval_id.strip()):
        raise DeploymentError("deployment effects require explicit approval")
    merge_authorization = authorize_merge_plan(
        plan.merge_plan,
        expected_plan_id=plan.merge_plan.plan_id,
        approval_id=approval_id,
    )
    support_authorizations = {}
    support_mutations = [
        *plan.content_mutations,
        plan.backup_manifest_mutation,
        *plan.journal_mutations.values(),
    ]
    for mutation in support_mutations:
        support_authorizations[mutation.plan_id] = authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, True),
        )
    migration_authorizations = {}
    for write in plan.migration_writes:
        mutation = write.mutation
        approval = None
        if mutation.approval_required:
            approval = ApprovalEvidence(
                mutation.plan_id,
                approval_id or "",
                approved=True,
            )
        migration_authorizations[mutation.plan_id] = authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, True),
            approval=approval,
        )
    derived_authorizations = {}
    for write in plan.derived_writes:
        mutation = write.mutation
        approval = None
        if mutation.approval_required:
            approval = ApprovalEvidence(
                mutation.plan_id,
                approval_id or "",
                approved=True,
            )
        derived_authorizations[mutation.plan_id] = authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, True),
            approval=approval,
        )
    return DeploymentAuthorization(
        plan_id=plan.plan_id,
        approval_id=approval_id,
        merge_authorization=merge_authorization,
        support_authorizations=support_authorizations,
        migration_authorizations=migration_authorizations,
        derived_authorizations=derived_authorizations,
    )


def _assert_authorized(
    mutation: MutationPlan,
    authorization: MutationAuthorization | None,
) -> None:
    if (
        authorization is None
        or authorization.plan.plan_id != mutation.plan_id
        or not authorization.dry_run_verified
    ):
        raise DeploymentError("support mutation requires matching authorization")


def _atomic_write(target: Path, document: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.is_symlink():
        raise DeploymentError("deployment write may not use symbolic links")
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(document)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _write_planned_document(
    root: Path,
    mutation: MutationPlan,
    authorization: MutationAuthorization | None,
    payload: object,
) -> None:
    _assert_authorized(mutation, authorization)
    document = _canonical_document(payload)
    if hashlib.sha256(document).hexdigest() != mutation.change_digest:
        raise DeploymentError("planned document digest changed before write")
    target = safe_installation_target(root, mutation.target_ref)
    if mutation.operation == "create" and target.exists():
        raise DeploymentError("planned support create target already exists")
    if mutation.operation == "update" and not target.is_file():
        raise DeploymentError("planned support update target is missing")
    _atomic_write(target, document)


def write_deployment_status(
    installation_root: Path,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
    status: str,
) -> None:
    if authorization.plan_id != plan.plan_id:
        raise DeploymentError("deployment authorization does not match plan")
    mutation = plan.journal_mutations.get(status)
    if mutation is None:
        raise DeploymentError("deployment journal status is invalid")
    root = _deployment_root(installation_root)
    journal_target = safe_installation_target(root, mutation.target_ref)
    if mutation.operation == "update":
        try:
            current_payload = json.loads(journal_target.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise DeploymentError("current deployment journal is invalid") from exc
        current_status = current_payload.get("status")
        if status not in JOURNAL_TRANSITIONS.get(current_status, set()):
            raise DeploymentError("deployment journal transition is invalid")
        if (
            current_payload.get("deployment_id") != plan.deployment_id
            or current_payload.get("merge_plan_id") != plan.merge_plan.plan_id
        ):
            raise DeploymentError("deployment journal identity changed")
    payload = _journal_payload(
        plan.deployment_id,
        plan.merge_plan,
        plan.backup_manifest_sha256,
        status,
    )
    _write_planned_document(
        root,
        mutation,
        authorization.support_authorizations.get(mutation.plan_id),
        payload,
    )


def _copy_backup_content(
    root: Path,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
) -> None:
    entries_by_hash = {
        item.sha256: item
        for item in plan.backup_manifest.entries
        if item.existed and item.sha256 is not None
    }
    mutations_by_hash = {
        item.change_digest: item for item in plan.content_mutations
    }
    for digest, entry in sorted(entries_by_hash.items()):
        mutation = mutations_by_hash[digest]
        auth = authorization.support_authorizations.get(mutation.plan_id)
        _assert_authorized(mutation, auth)
        source = safe_installation_target(root, entry.target_ref)
        size, current_digest = _stable_file_hash(source)
        if current_digest != digest or size != entry.size:
            raise DeploymentError("backup source changed after dry-run")
        destination = safe_installation_target(root, mutation.target_ref)
        if destination.exists():
            raise DeploymentError("backup content target already exists")
        document = source.read_bytes()
        if hashlib.sha256(document).hexdigest() != mutation.change_digest:
            raise DeploymentError("backup content digest changed during copy")
        _atomic_write(destination, document)
        copied_size, copied_digest = _stable_file_hash(destination)
        if copied_size != size or copied_digest != digest:
            raise DeploymentError("backup content verification failed")


def start_deployment(
    installation_root: Path,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
) -> DeploymentStartResult:
    """Create the journal and verified backup before any managed mutation."""

    root = _deployment_root(installation_root)
    if authorization.plan_id != plan.plan_id:
        raise DeploymentError("deployment authorization does not match plan")
    state, state_sha256 = load_installation_state(root)
    if (
        state is None
        or state_sha256 != plan.merge_plan.source_state_sha256
        or installation_state_sha256(state) != plan.merge_plan.source_state_sha256
    ):
        raise DeploymentError("installation state changed before backup")
    for entry in plan.backup_manifest.entries:
        target = safe_installation_target(root, entry.target_ref)
        if not entry.existed:
            if target.exists():
                raise DeploymentError("planned create target changed before backup")
            continue
        if not target.is_file():
            raise DeploymentError("backup source is missing before deployment")
        size, digest = _stable_file_hash(target)
        if size != entry.size or digest != entry.sha256:
            raise DeploymentError("backup source changed before deployment")
    write_deployment_status(root, plan, authorization, "preparing")
    _copy_backup_content(root, plan, authorization)
    _write_planned_document(
        root,
        plan.backup_manifest_mutation,
        authorization.support_authorizations.get(
            plan.backup_manifest_mutation.plan_id
        ),
        plan.backup_manifest.as_payload(),
    )
    write_deployment_status(root, plan, authorization, "backed-up")
    return DeploymentStartResult(
        deployment_id=plan.deployment_id,
        status="backed-up",
        backup_manifest_sha256=plan.backup_manifest_sha256,
    )
