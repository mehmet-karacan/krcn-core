"""Conflict-safe rollback planning and application from verified checkpoints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .deployment import (
    JOURNAL_STATUSES,
    JOURNAL_TRANSITIONS,
    BackupEntry,
    BackupManifest,
    BackupScope,
    _atomic_write,
    _canonical_document,
    _document_sha256,
    _stored_document,
)
from .installation import safe_installation_target
from .mutation_gate import (
    ApprovalEvidence,
    DryRunEvidence,
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    authorize_mutation,
    plan_mutation,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_ENTRY_OWNERSHIP = {"core", "runtime", "user-data", "derived"}


class RollbackError(ValueError):
    """Raised when an exact and non-destructive rollback is not possible."""


@dataclass(frozen=True)
class RollbackObservation:
    target_ref: str
    existed: bool
    sha256: str | None


@dataclass(frozen=True)
class RollbackWrite:
    target_ref: str
    action: str
    expected_current_sha256: str | None
    restore_content_ref: str | None
    restore_size: int | None
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "target_ref": self.target_ref,
            "action": self.action,
            "expected_current_sha256": self.expected_current_sha256,
            "restore_size": self.restore_size,
            "mutation": self.mutation.as_dict(),
        }


@dataclass(frozen=True)
class RollbackPlan:
    plan_id: str
    deployment_id: str
    merge_plan_id: str
    source_status: str
    backup_manifest: BackupManifest
    observations: tuple[RollbackObservation, ...]
    writes: tuple[RollbackWrite, ...]
    journal_payloads: Mapping[str, Mapping[str, object]]
    journal_mutations: Mapping[str, MutationPlan]

    @property
    def approval_required(self) -> bool:
        return any(item.mutation.approval_required for item in self.writes)

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "deployment_id": self.deployment_id,
            "merge_plan_id": self.merge_plan_id,
            "source_status": self.source_status,
            "writes": [item.public_summary() for item in self.writes],
            "approval_required": self.approval_required,
        }


@dataclass(frozen=True)
class RollbackAuthorization:
    plan_id: str
    write_authorizations: Mapping[str, MutationAuthorization]
    journal_authorizations: Mapping[str, MutationAuthorization]


@dataclass(frozen=True)
class RollbackResult:
    deployment_id: str
    restored_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    status: str

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "restored_paths": list(self.restored_paths),
            "removed_paths": list(self.removed_paths),
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
        raise RollbackError("rollback target changed while it was inspected")
    return after.st_size, digest.hexdigest()


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise RollbackError(f"{label} is invalid")
    return value


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RollbackError(f"{label} is invalid")
    return value


def _parse_backup_entry(
    root: Path,
    deployment_id: str,
    payload: object,
    ownership: OwnershipResolver,
) -> BackupEntry:
    if not isinstance(payload, dict) or set(payload) != {
        "target_ref",
        "existed",
        "sha256",
        "size",
        "content_ref",
        "expected_post_existed",
        "expected_post_sha256",
    }:
        raise RollbackError("backup entry fields are invalid")
    target_ref = payload.get("target_ref")
    if not isinstance(target_ref, str):
        raise RollbackError("backup target reference is invalid")
    safe_installation_target(root, target_ref)
    if ownership.resolve(target_ref) not in ALLOWED_ENTRY_OWNERSHIP:
        raise RollbackError("backup entry ownership is prohibited")
    existed = payload.get("existed")
    expected_post_existed = payload.get("expected_post_existed")
    if not isinstance(existed, bool) or not isinstance(expected_post_existed, bool):
        raise RollbackError("backup existence evidence is invalid")
    sha256 = payload.get("sha256")
    size = payload.get("size")
    content_ref = payload.get("content_ref")
    if existed:
        digest = _require_sha(sha256, "backup content hash")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise RollbackError("backup content size is invalid")
        expected_content_ref = (
            f".krcn/checkpoints/{deployment_id}/content/{digest}"
        )
        if content_ref != expected_content_ref:
            raise RollbackError("backup content reference is invalid")
        safe_installation_target(root, expected_content_ref)
    elif sha256 is not None or size is not None or content_ref is not None:
        raise RollbackError("absent backup entry may not have content evidence")
    expected_post_sha256 = payload.get("expected_post_sha256")
    if expected_post_existed:
        _require_sha(expected_post_sha256, "expected post hash")
    elif expected_post_sha256 is not None:
        raise RollbackError("absent post state may not have a hash")
    return BackupEntry(
        target_ref=target_ref,
        existed=existed,
        sha256=sha256,
        size=size,
        content_ref=content_ref,
        expected_post_existed=expected_post_existed,
        expected_post_sha256=expected_post_sha256,
    )


def _parse_backup_scope(
    root: Path,
    payload: object,
    ownership: OwnershipResolver,
) -> BackupScope:
    if not isinstance(payload, dict) or set(payload) != {
        "target_ref",
        "ownership",
        "remove_created_on_rollback",
    }:
        raise RollbackError("backup scope fields are invalid")
    target_ref = payload.get("target_ref")
    expected_ownership = payload.get("ownership")
    remove_created = payload.get("remove_created_on_rollback")
    if not isinstance(target_ref, str):
        raise RollbackError("backup scope target is invalid")
    safe_installation_target(root, target_ref)
    if expected_ownership not in {"runtime", "user-data", "derived"}:
        raise RollbackError("backup scope ownership is invalid")
    if ownership.resolve(f"{target_ref}/placeholder") != expected_ownership:
        raise RollbackError("backup scope ownership evidence changed")
    if not isinstance(remove_created, bool):
        raise RollbackError("backup scope removal flag is invalid")
    return BackupScope(target_ref, expected_ownership, remove_created)


def _load_journal(root: Path, deployment_id: str) -> dict[str, object]:
    path = safe_installation_target(
        root,
        f".krcn/runtime/deployments/{deployment_id}.json",
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RollbackError("deployment journal is invalid") from exc
    expected_fields = {
        "schema_ref",
        "schema_version",
        "deployment_id",
        "merge_plan_id",
        "installation_id",
        "release_id",
        "backup_manifest_sha256",
        "status",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise RollbackError("deployment journal fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/deployment-journal.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("deployment_id") != deployment_id
    ):
        raise RollbackError("deployment journal identity is invalid")
    _require_sha(payload.get("merge_plan_id"), "merge plan id")
    _require_identifier(payload.get("installation_id"), "installation id")
    release_id = payload.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise RollbackError("release id is invalid")
    _require_sha(payload.get("backup_manifest_sha256"), "backup manifest hash")
    if payload.get("status") not in JOURNAL_STATUSES:
        raise RollbackError("deployment journal status is invalid")
    return payload


def _load_backup_manifest(
    root: Path,
    deployment_id: str,
    expected_sha256: str,
    ownership: OwnershipResolver,
) -> BackupManifest:
    path = safe_installation_target(
        root,
        f".krcn/checkpoints/{deployment_id}/backup-manifest.json",
    )
    try:
        document = path.read_bytes()
        payload = json.loads(document)
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RollbackError("backup manifest is invalid") from exc
    if hashlib.sha256(document).hexdigest() != expected_sha256:
        raise RollbackError("backup manifest hash does not match journal")
    expected_fields = {
        "schema_ref",
        "schema_version",
        "deployment_id",
        "merge_plan_id",
        "installation_id",
        "source_state_sha256",
        "entries",
        "scopes",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise RollbackError("backup manifest fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/backup-manifest.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("deployment_id") != deployment_id
        or _document_sha256(payload) != expected_sha256
    ):
        raise RollbackError("backup manifest identity is invalid")
    merge_plan_id = _require_sha(payload.get("merge_plan_id"), "merge plan id")
    installation_id = _require_identifier(
        payload.get("installation_id"),
        "installation id",
    )
    source_state_sha256 = _require_sha(
        payload.get("source_state_sha256"),
        "source state hash",
    )
    entries_payload = payload.get("entries")
    scopes_payload = payload.get("scopes")
    if not isinstance(entries_payload, list) or not isinstance(scopes_payload, list):
        raise RollbackError("backup manifest collections are invalid")
    entries = tuple(
        _parse_backup_entry(root, deployment_id, item, ownership)
        for item in entries_payload
    )
    scopes = tuple(
        _parse_backup_scope(root, item, ownership) for item in scopes_payload
    )
    if len({item.target_ref for item in entries}) != len(entries):
        raise RollbackError("backup entry targets must be unique")
    if len({item.target_ref for item in scopes}) != len(scopes):
        raise RollbackError("backup scope targets must be unique")
    return BackupManifest(
        deployment_id=deployment_id,
        merge_plan_id=merge_plan_id,
        installation_id=installation_id,
        source_state_sha256=source_state_sha256,
        entries=entries,
        scopes=scopes,
    )


def _observe(root: Path, entry: BackupEntry) -> RollbackObservation:
    target = safe_installation_target(root, entry.target_ref)
    if target.is_symlink():
        raise RollbackError("rollback target may not be a symbolic link")
    if not target.exists():
        return RollbackObservation(entry.target_ref, False, None)
    if not target.is_file():
        raise RollbackError("rollback target must be a regular file")
    _, digest = _stable_hash(target)
    return RollbackObservation(entry.target_ref, True, digest)


def _verify_backup_content(root: Path, entry: BackupEntry) -> None:
    if not entry.existed:
        return
    if entry.content_ref is None or entry.sha256 is None or entry.size is None:
        raise RollbackError("backup content evidence is incomplete")
    content = safe_installation_target(root, entry.content_ref)
    if content.is_symlink() or not content.is_file():
        raise RollbackError("backup content is missing")
    size, digest = _stable_hash(content)
    if size != entry.size or digest != entry.sha256:
        raise RollbackError("backup content verification failed")


def _plan_entry_restore(
    entry: BackupEntry,
    observation: RollbackObservation,
    ownership: OwnershipResolver,
) -> RollbackWrite | None:
    if entry.existed and observation.existed and observation.sha256 == entry.sha256:
        return None
    if not entry.existed and not observation.existed:
        return None
    matches_post = (
        observation.existed == entry.expected_post_existed
        and observation.sha256 == entry.expected_post_sha256
    )
    if not matches_post:
        raise RollbackError(
            "rollback conflict: target differs from original and expected post state"
        )
    if entry.existed:
        if entry.sha256 is None or entry.content_ref is None:
            raise RollbackError("rollback restore lacks backup content")
        action = "update" if observation.existed else "create"
        digest = entry.sha256
        restore_ref = entry.content_ref
        restore_size = entry.size
    else:
        if not observation.existed or observation.sha256 is None:
            raise RollbackError("rollback delete lacks current content evidence")
        action = "delete"
        digest = observation.sha256
        restore_ref = None
        restore_size = None
    mutation = plan_mutation(
        ownership,
        operation=action,
        target_ref=entry.target_ref,
        expected_ownership=ownership.resolve(entry.target_ref),
        change_digest=digest,
        reversible=True,
    )
    return RollbackWrite(
        target_ref=entry.target_ref,
        action=action,
        expected_current_sha256=observation.sha256,
        restore_content_ref=restore_ref,
        restore_size=restore_size,
        mutation=mutation,
    )


def _rollback_journal_payload(
    journal: Mapping[str, object],
    status: str,
) -> dict[str, object]:
    result = dict(journal)
    result["status"] = status
    return result


def prepare_rollback_plan(
    installation_root: Path,
    deployment_id: str,
    ownership: OwnershipResolver,
) -> RollbackPlan:
    """Prepare an exact rollback without changing the installation."""

    if not isinstance(deployment_id, str) or not IDENTIFIER.fullmatch(deployment_id):
        raise RollbackError("deployment id is invalid")
    root = installation_root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise RollbackError("installation root is invalid")
    journal = _load_journal(root, deployment_id)
    source_status = str(journal["status"])
    if "rolling-back" not in JOURNAL_TRANSITIONS.get(source_status, set()):
        raise RollbackError("deployment status cannot start rollback")
    manifest = _load_backup_manifest(
        root,
        deployment_id,
        str(journal["backup_manifest_sha256"]),
        ownership,
    )
    if (
        manifest.merge_plan_id != journal["merge_plan_id"]
        or manifest.installation_id != journal["installation_id"]
    ):
        raise RollbackError("backup manifest does not match deployment journal")
    observations = []
    writes = []
    for entry in manifest.entries:
        _verify_backup_content(root, entry)
        observation = _observe(root, entry)
        observations.append(observation)
        write = _plan_entry_restore(entry, observation, ownership)
        if write is not None:
            writes.append(write)
    writes.sort(
        key=lambda item: (
            item.target_ref == ".krcn/runtime/installation-state.json",
            item.target_ref,
        )
    )
    journal_ref = f".krcn/runtime/deployments/{deployment_id}.json"
    journal_payloads = {
        status: _rollback_journal_payload(journal, status)
        for status in ("rolling-back", "rolled-back", "failed")
    }
    journal_mutations = {
        status: plan_mutation(
            ownership,
            operation="update",
            target_ref=journal_ref,
            expected_ownership="runtime",
            change_digest=_document_sha256(payload),
            reversible=True,
        )
        for status, payload in journal_payloads.items()
    }
    identity = {
        "deployment_id": deployment_id,
        "merge_plan_id": manifest.merge_plan_id,
        "source_status": source_status,
        "observations": [
            {
                "target_ref": item.target_ref,
                "existed": item.existed,
                "sha256": item.sha256,
            }
            for item in observations
        ],
        "write_ids": [item.mutation.plan_id for item in writes],
        "journal_ids": {
            status: item.plan_id for status, item in journal_mutations.items()
        },
    }
    return RollbackPlan(
        plan_id=hashlib.sha256(_canonical_document(identity)).hexdigest(),
        deployment_id=deployment_id,
        merge_plan_id=manifest.merge_plan_id,
        source_status=source_status,
        backup_manifest=manifest,
        observations=tuple(observations),
        writes=tuple(writes),
        journal_payloads=journal_payloads,
        journal_mutations=journal_mutations,
    )


def authorize_rollback_plan(
    plan: RollbackPlan,
    *,
    expected_plan_id: str,
    approval_id: str | None,
) -> RollbackAuthorization:
    """Authorize only the exact rollback dry-run plan."""

    if expected_plan_id != plan.plan_id:
        raise RollbackError("rollback requires the exact dry-run plan id")
    if plan.approval_required and not (approval_id and approval_id.strip()):
        raise RollbackError("rollback effects require explicit approval")
    write_authorizations = {}
    for write in plan.writes:
        mutation = write.mutation
        approval = None
        if mutation.approval_required:
            approval = ApprovalEvidence(
                mutation.plan_id,
                approval_id or "",
                approved=True,
            )
        write_authorizations[mutation.plan_id] = authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, True),
            approval=approval,
        )
    journal_authorizations = {
        mutation.plan_id: authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, True),
        )
        for mutation in plan.journal_mutations.values()
    }
    return RollbackAuthorization(
        plan_id=plan.plan_id,
        write_authorizations=write_authorizations,
        journal_authorizations=journal_authorizations,
    )


def _assert_authorized(
    mutation: MutationPlan,
    authorization: MutationAuthorization | None,
) -> None:
    if (
        authorization is None
        or authorization.plan.plan_id != mutation.plan_id
        or not authorization.dry_run_verified
        or (mutation.approval_required and not authorization.approval_verified)
    ):
        raise RollbackError("rollback mutation lacks matching authorization")


def _current_journal_status(root: Path, plan: RollbackPlan) -> str:
    journal = _load_journal(root, plan.deployment_id)
    if journal.get("merge_plan_id") != plan.merge_plan_id:
        raise RollbackError("deployment journal identity changed")
    return str(journal["status"])


def _write_journal_status(
    root: Path,
    plan: RollbackPlan,
    authorization: RollbackAuthorization,
    status: str,
) -> None:
    mutation = plan.journal_mutations[status]
    _assert_authorized(
        mutation,
        authorization.journal_authorizations.get(mutation.plan_id),
    )
    payload = plan.journal_payloads[status]
    document = _stored_document(payload)
    if hashlib.sha256(document).hexdigest() != mutation.change_digest:
        raise RollbackError("rollback journal evidence changed")
    target = safe_installation_target(root, mutation.target_ref)
    if not target.is_file() or target.is_symlink():
        raise RollbackError("rollback journal is missing")
    _atomic_write(target, document)


def _assert_observations_current(root: Path, plan: RollbackPlan) -> None:
    for observation in plan.observations:
        target = safe_installation_target(root, observation.target_ref)
        if observation.existed:
            if target.is_symlink() or not target.is_file():
                raise RollbackError("rollback target changed after dry-run")
            _, digest = _stable_hash(target)
            if digest != observation.sha256:
                raise RollbackError("rollback target changed after dry-run")
        elif target.exists() or target.is_symlink():
            raise RollbackError("rollback target changed after dry-run")


def _assert_original_state(root: Path, plan: RollbackPlan) -> None:
    for entry in plan.backup_manifest.entries:
        target = safe_installation_target(root, entry.target_ref)
        if entry.existed:
            if target.is_symlink() or not target.is_file():
                raise RollbackError("rollback restore verification failed")
            size, digest = _stable_hash(target)
            if size != entry.size or digest != entry.sha256:
                raise RollbackError("rollback restore verification failed")
        elif target.exists() or target.is_symlink():
            raise RollbackError("rollback removal verification failed")


def apply_rollback(
    installation_root: Path,
    plan: RollbackPlan,
    authorization: RollbackAuthorization,
) -> RollbackResult:
    """Restore the verified pre-deployment state without overwriting conflicts."""

    root = installation_root.resolve()
    if authorization.plan_id != plan.plan_id:
        raise RollbackError("rollback authorization does not match plan")
    if _current_journal_status(root, plan) != plan.source_status:
        raise RollbackError("deployment status changed after rollback dry-run")
    _assert_observations_current(root, plan)
    prepared_content = {}
    for write in plan.writes:
        auth = authorization.write_authorizations.get(write.mutation.plan_id)
        _assert_authorized(write.mutation, auth)
        if write.action in {"create", "update"}:
            if write.restore_content_ref is None or write.restore_size is None:
                raise RollbackError("rollback write lacks restore content")
            source = safe_installation_target(root, write.restore_content_ref)
            size, digest = _stable_hash(source)
            if size != write.restore_size or digest != write.mutation.change_digest:
                raise RollbackError("rollback content changed after dry-run")
            prepared_content[write.target_ref] = source.read_bytes()
    _write_journal_status(root, plan, authorization, "rolling-back")
    restored = []
    removed = []
    try:
        for write in plan.writes:
            target = safe_installation_target(root, write.target_ref)
            if write.action in {"create", "update"}:
                content = prepared_content[write.target_ref]
                _atomic_write(target, content)
                _, digest = _stable_hash(target)
                if digest != write.mutation.change_digest:
                    raise RollbackError("rollback write verification failed")
                restored.append(write.target_ref)
            else:
                target.unlink()
                if target.exists():
                    raise RollbackError("rollback delete verification failed")
                removed.append(write.target_ref)
        _assert_original_state(root, plan)
        _write_journal_status(root, plan, authorization, "rolled-back")
    except Exception:
        try:
            _write_journal_status(root, plan, authorization, "failed")
        except Exception:
            pass
        raise
    return RollbackResult(
        deployment_id=plan.deployment_id,
        restored_paths=tuple(restored),
        removed_paths=tuple(removed),
        status="rolled-back",
    )
