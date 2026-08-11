"""End-to-end deployment execution with mandatory automatic rollback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .deployment import (
    DeploymentAuthorization,
    DeploymentPlan,
    DeploymentStartResult,
    start_deployment,
)
from .merge_apply import (
    DerivedApplyResult,
    ManagedApplyResult,
    MigrationApplyResult,
    apply_derived_actions,
    apply_managed_files,
    apply_migrations,
)
from .mutation_gate import OwnershipResolver
from .release import ReleaseBundle
from .rollback import (
    RollbackResult,
    apply_rollback,
    authorize_rollback_plan,
    prepare_rollback_plan,
)
from .verification import VerificationResult, verify_and_commit


class MergeExecutionError(RuntimeError):
    """Report deployment failure and whether recovery restored the installation."""

    def __init__(
        self,
        message: str,
        *,
        deployment_id: str,
        rolled_back: bool,
        rollback_error: str | None = None,
    ) -> None:
        super().__init__(message)
        self.deployment_id = deployment_id
        self.rolled_back = rolled_back
        self.rollback_error = rollback_error

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "status": "rolled-back" if self.rolled_back else "recovery-failed",
            "rolled_back": self.rolled_back,
            "rollback_error": self.rollback_error,
        }


@dataclass(frozen=True)
class MergeExecutionResult:
    deployment_id: str
    start: DeploymentStartResult
    managed: ManagedApplyResult
    migration: MigrationApplyResult | None
    derived: DerivedApplyResult | None
    verification: VerificationResult

    def public_summary(self) -> dict[str, object]:
        return {
            "deployment_id": self.deployment_id,
            "status": self.verification.status,
            "start": self.start.public_summary(),
            "managed": self.managed.public_summary(),
            "migration": (
                self.migration.public_summary() if self.migration else None
            ),
            "derived": self.derived.public_summary() if self.derived else None,
            "verification": self.verification.public_summary(),
        }


def _automatic_rollback(
    installation_root: Path,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
    ownership: OwnershipResolver,
) -> RollbackResult:
    rollback_plan = prepare_rollback_plan(
        installation_root,
        plan.deployment_id,
        ownership,
    )
    rollback_authorization = authorize_rollback_plan(
        rollback_plan,
        expected_plan_id=rollback_plan.plan_id,
        approval_id=(
            authorization.approval_id
            or f"automatic-rollback-{plan.deployment_id}"
        ),
    )
    return apply_rollback(
        installation_root,
        rollback_plan,
        rollback_authorization,
    )


def execute_deployment(
    installation_root: Path,
    release_root: Path,
    bundle: ReleaseBundle,
    plan: DeploymentPlan,
    authorization: DeploymentAuthorization,
    ownership: OwnershipResolver,
) -> MergeExecutionResult:
    """Run every planned stage and automatically restore on post-backup failure."""

    started = False
    try:
        start = start_deployment(installation_root, plan, authorization)
        started = True
        managed = apply_managed_files(
            installation_root,
            release_root,
            bundle,
            plan,
            authorization,
        )
        migration = None
        if plan.merge_plan.migrations:
            migration = apply_migrations(
                installation_root,
                plan,
                authorization,
            )
        derived = None
        if plan.merge_plan.derived_actions:
            derived = apply_derived_actions(
                installation_root,
                plan,
                authorization,
            )
        verification = verify_and_commit(
            installation_root,
            plan,
            authorization,
        )
        return MergeExecutionResult(
            deployment_id=plan.deployment_id,
            start=start,
            managed=managed,
            migration=migration,
            derived=derived,
            verification=verification,
        )
    except Exception as exc:
        if not started:
            raise
        try:
            rollback = _automatic_rollback(
                installation_root,
                plan,
                authorization,
                ownership,
            )
        except Exception as rollback_exc:
            raise MergeExecutionError(
                "deployment failed and automatic rollback could not complete",
                deployment_id=plan.deployment_id,
                rolled_back=False,
                rollback_error=str(rollback_exc),
            ) from exc
        raise MergeExecutionError(
            "deployment failed and the original state was restored",
            deployment_id=plan.deployment_id,
            rolled_back=rollback.status == "rolled-back",
        ) from exc
