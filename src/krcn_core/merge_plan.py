"""Exact dry-run planning for conflict-free KRCN Core merges."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from .installation import (
    InstallationState,
    ManagedFile,
    installation_state_sha256,
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
from .release_diff import ReleaseDiff
from .update_effects import (
    DerivedActionRegistry,
    DerivedActionSpec,
    MigrationRegistry,
    MigrationSpec,
    UpdateEffectError,
)


SHA256 = re.compile(r"^[a-f0-9]{64}$")


class MergePlanError(ValueError):
    """Raised when a merge plan or its authorization is invalid."""


@dataclass(frozen=True)
class MergePlan:
    plan_id: str
    diff_id: str
    installation_id: str
    release_id: str
    from_core_version: str
    to_core_version: str
    manifest_sha256: str
    file_mutations: tuple[MutationPlan, ...]
    state_mutation: MutationPlan | None
    migrations: tuple[MigrationSpec, ...]
    derived_actions: tuple[DerivedActionSpec, ...]
    desired_state: InstallationState
    approval_required: bool

    @property
    def has_effects(self) -> bool:
        return bool(
            self.file_mutations
            or self.state_mutation
            or self.migrations
            or self.derived_actions
        )

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "diff_id": self.diff_id,
            "installation_id": self.installation_id,
            "release_id": self.release_id,
            "from_core_version": self.from_core_version,
            "to_core_version": self.to_core_version,
            "manifest_sha256": self.manifest_sha256,
            "approval_required": self.approval_required,
            "has_effects": self.has_effects,
            "file_mutations": [item.as_dict() for item in self.file_mutations],
            "state_mutation": (
                self.state_mutation.as_dict() if self.state_mutation else None
            ),
            "desired_state_sha256": installation_state_sha256(self.desired_state),
            "migrations": [item.as_dict() for item in self.migrations],
            "derived_actions": [item.as_dict() for item in self.derived_actions],
        }


@dataclass(frozen=True)
class MergeAuthorization:
    plan_id: str
    mutation_authorizations: Mapping[str, MutationAuthorization]
    approval_verified: bool


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _desired_state(
    state: InstallationState,
    release_diff: ReleaseDiff,
    migrations: tuple[MigrationSpec, ...],
    *,
    source_commit: str,
    transition_required: bool,
) -> InstallationState:
    if not transition_required:
        return state
    managed = {item.path: item for item in state.managed_files}
    for change in release_diff.changes:
        if change.action in {"create", "update", "unchanged"}:
            if change.target_sha256 is None or change.target_size is None:
                raise MergePlanError("upsert change lacks target evidence")
            managed[change.path] = ManagedFile(
                change.path,
                change.target_sha256,
                change.target_size,
            )
        elif change.action == "delete":
            managed.pop(change.path, None)
    schema_versions = dict(state.schema_versions)
    for migration in migrations:
        current = schema_versions.get(migration.schema_name)
        if current != migration.from_version:
            raise MergePlanError(
                "migration source version does not match installation state"
            )
        schema_versions[migration.schema_name] = migration.to_version
    completed = tuple(
        dict.fromkeys(
            [
                *state.completed_migrations,
                *(item.migration_id for item in migrations),
            ]
        )
    )
    executed_derived = {item for item in release_diff.derived_actions}
    pending_derived = tuple(
        item
        for item in state.pending_derived_actions
        if item not in executed_derived
    )
    return InstallationState(
        installation_id=state.installation_id,
        core_version=release_diff.to_core_version,
        release_id=release_diff.release_id,
        source_commit=source_commit,
        managed_files=tuple(sorted(managed.values(), key=lambda item: item.path)),
        schema_versions=schema_versions,
        completed_migrations=completed,
        pending_derived_actions=pending_derived,
        revision=state.revision + 1,
    )


def prepare_merge_plan(
    release_diff: ReleaseDiff,
    state: InstallationState,
    ownership: OwnershipResolver,
    migrations: MigrationRegistry,
    derived_actions: DerivedActionRegistry,
    *,
    source_commit: str,
) -> MergePlan:
    """Bind every visible effect to one deterministic dry-run plan."""

    if not release_diff.applicable:
        raise MergePlanError("merge plan cannot be created while conflicts exist")
    if release_diff.installation_id != state.installation_id:
        raise MergePlanError("release diff does not match installation state")
    if release_diff.from_core_version != state.core_version:
        raise MergePlanError("release diff source version is stale")
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise MergePlanError("release source commit is invalid")
    try:
        migration_specs = migrations.resolve(release_diff.pending_migrations)
        derived_specs = derived_actions.resolve(release_diff.derived_actions)
    except UpdateEffectError as exc:
        raise MergePlanError(str(exc)) from exc
    file_mutations = []
    for change in release_diff.changes:
        if change.action == "unchanged":
            continue
        operation = change.action
        digest = (
            change.target_sha256
            if change.action in {"create", "update"}
            else change.previous_sha256
        )
        if digest is None or not SHA256.fullmatch(digest):
            raise MergePlanError("file mutation lacks exact content digest")
        file_mutations.append(
            plan_mutation(
                ownership,
                operation=operation,
                target_ref=change.path,
                expected_ownership="core",
                change_digest=digest,
                reversible=True,
            )
        )
    transition_required = bool(
        file_mutations
        or migration_specs
        or derived_specs
        or state.core_version != release_diff.to_core_version
        or state.release_id != release_diff.release_id
        or state.source_commit != source_commit
    )
    desired_state = _desired_state(
        state,
        release_diff,
        migration_specs,
        source_commit=source_commit,
        transition_required=transition_required,
    )
    state_mutation = None
    if transition_required:
        state_mutation = plan_mutation(
            ownership,
            operation="update",
            target_ref=".krcn/runtime/installation-state.json",
            expected_ownership="runtime",
            change_digest=installation_state_sha256(desired_state),
            reversible=True,
        )
    approval_required = any(
        item.approval_required for item in file_mutations
    ) or any(item.approval_required for item in migration_specs) or any(
        item.approval_required for item in derived_specs
    )
    identity = {
        "diff_id": release_diff.diff_id,
        "installation_id": state.installation_id,
        "release_id": release_diff.release_id,
        "manifest_sha256": release_diff.manifest_sha256,
        "file_mutation_ids": [item.plan_id for item in file_mutations],
        "state_mutation_id": state_mutation.plan_id if state_mutation else None,
        "migrations": [item.as_dict() for item in migration_specs],
        "derived_actions": [item.as_dict() for item in derived_specs],
        "approval_required": approval_required,
    }
    return MergePlan(
        plan_id=_canonical_sha256(identity),
        diff_id=release_diff.diff_id,
        installation_id=state.installation_id,
        release_id=release_diff.release_id,
        from_core_version=release_diff.from_core_version,
        to_core_version=release_diff.to_core_version,
        manifest_sha256=release_diff.manifest_sha256,
        file_mutations=tuple(file_mutations),
        state_mutation=state_mutation,
        migrations=migration_specs,
        derived_actions=derived_specs,
        desired_state=desired_state,
        approval_required=approval_required,
    )


def authorize_merge_plan(
    plan: MergePlan,
    *,
    expected_plan_id: str,
    approval_id: str | None,
) -> MergeAuthorization:
    """Authorize only the exact dry-run plan and every owned mutation inside it."""

    if expected_plan_id != plan.plan_id:
        raise MergePlanError("merge apply requires the exact dry-run plan id")
    approval_verified = bool(approval_id and approval_id.strip())
    if plan.approval_required and not approval_verified:
        raise MergePlanError("merge plan effects require explicit approval")
    authorizations: dict[str, MutationAuthorization] = {}
    mutations = list(plan.file_mutations)
    if plan.state_mutation is not None:
        mutations.append(plan.state_mutation)
    for mutation in mutations:
        approval = None
        if mutation.approval_required:
            approval = ApprovalEvidence(
                mutation.plan_id,
                approval_id or "",
                approved=True,
            )
        authorizations[mutation.plan_id] = authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, verified=True),
            approval=approval,
        )
    return MergeAuthorization(
        plan_id=plan.plan_id,
        mutation_authorizations=authorizations,
        approval_verified=approval_verified,
    )
