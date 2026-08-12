"""Read-only project onboarding through preserved local records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .local_store import LocalWorkspaceStore, RecordWritePlan, StoredRecord
from .mutation_gate import MutationAuthorization
from .project_home_initialization import validate_initialized_project_home
from .source_identity import SourceIdentityError, assert_external_source


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")


class OnboardingError(ValueError):
    """Raised when read-only onboarding cannot be planned or applied safely."""


@dataclass(frozen=True)
class OnboardingRequest:
    workspace_id: str
    project_id: str
    binding_id: str
    project_name: str
    description: str
    source_root: Path
    policy_refs: tuple[str, ...] = ()
    expected_workspace_revision: int = 0


@dataclass(frozen=True)
class OnboardingPlan:
    plan_id: str
    workspace_id: str
    project_id: str
    binding_id: str
    source_root: Path
    record_plans: tuple[RecordWritePlan, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "binding_id": self.binding_id,
            "source_access": "read-only",
            "record_plans": [
                {
                    "record_type": item.record_type,
                    "record_id": item.record_id,
                    "previous_revision": item.previous_revision,
                    "next_revision": item.next_revision,
                    "payload_sha256": item.payload_sha256,
                    "mutation_plan_id": item.mutation.plan_id,
                }
                for item in self.record_plans
            ],
        }


@dataclass(frozen=True)
class OnboardingResult:
    plan_id: str
    records: tuple[StoredRecord, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "records": [record.public_summary() for record in self.records],
        }


def _validate_request(request: OnboardingRequest, store: LocalWorkspaceStore) -> Path:
    for label, value in (
        ("workspace_id", request.workspace_id),
        ("project_id", request.project_id),
        ("binding_id", request.binding_id),
    ):
        if not IDENTIFIER.fullmatch(value):
            raise OnboardingError(f"{label} must be a portable identifier")
    if not request.project_name.strip():
        raise OnboardingError("project name must be non-empty")
    if request.expected_workspace_revision < 0:
        raise OnboardingError("expected workspace revision must not be negative")
    if not request.source_root.is_absolute():
        raise OnboardingError("source root must be an absolute local path")
    if request.source_root.is_symlink():
        raise OnboardingError("source root may not be a symbolic link")
    source_root = request.source_root.resolve()
    if not source_root.is_dir():
        raise OnboardingError("source root must be an existing directory")
    project_local_home = store.data_root.resolve(strict=False) == source_root / ".krcn"
    try:
        if project_local_home:
            validate_initialized_project_home(store.data_root)
        assert_external_source(
            source_root,
            store.data_root,
            allow_project_local_home=project_local_home,
        )
    except (SourceIdentityError, ValueError) as exc:
        raise OnboardingError(str(exc)) from exc
    return source_root


def prepare_read_only_onboarding(
    store: LocalWorkspaceStore,
    request: OnboardingRequest,
) -> OnboardingPlan:
    """Create a dry-run plan without writing to the source or local store."""

    source_root = _validate_request(request, store)
    existing_workspace = store.read("workspaces", request.workspace_id)
    if existing_workspace is None:
        workspace_payload: dict[str, object] = {
            "schema_version": 1,
            "workspace_id": request.workspace_id,
            "project_refs": [request.project_id],
            "policy_refs": [],
            "metadata": {},
        }
    else:
        if existing_workspace.revision != request.expected_workspace_revision:
            raise OnboardingError("workspace revision changed before onboarding")
        workspace_payload = dict(existing_workspace.payload)
        project_refs = list(workspace_payload.get("project_refs", []))
        if request.project_id in project_refs:
            raise OnboardingError("project is already registered in the workspace")
        project_refs.append(request.project_id)
        workspace_payload["project_refs"] = project_refs

    source_binding_payload = {
        "schema_version": 1,
        "binding_id": request.binding_id,
        "source_id": request.project_id,
        "source_kind": "project",
        "locator": {"kind": "local-path", "value": str(source_root)},
        "default_access": "read-only",
        "capabilities": ["read", "metadata"],
        "policy_refs": list(request.policy_refs),
        "revision": 1,
    }
    project_payload = {
        "schema_version": 1,
        "project_id": request.project_id,
        "name": request.project_name,
        "description": request.description,
        "source_refs": [request.binding_id],
        "technologies": [],
        "modules": [],
        "skill_refs": [],
        "status": "active",
    }
    binding_plan = store.prepare_put(
        "source-bindings",
        request.binding_id,
        source_binding_payload,
        expected_revision=0,
    )
    project_plan = store.prepare_put(
        "projects",
        request.project_id,
        project_payload,
        expected_revision=0,
    )
    workspace_plan = store.prepare_put(
        "workspaces",
        request.workspace_id,
        workspace_payload,
        expected_revision=request.expected_workspace_revision,
    )
    record_plans = (binding_plan, project_plan, workspace_plan)
    identity = [item.mutation.plan_id for item in record_plans]
    plan_id = hashlib.sha256(
        json.dumps(identity, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return OnboardingPlan(
        plan_id=plan_id,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        binding_id=request.binding_id,
        source_root=source_root,
        record_plans=record_plans,
    )


def apply_read_only_onboarding(
    store: LocalWorkspaceStore,
    plan: OnboardingPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> OnboardingResult:
    """Apply approved local records while keeping the source read-only."""

    if not plan.source_root.is_dir() or plan.source_root.is_symlink():
        raise OnboardingError("source root is no longer a safe directory")
    for record_plan in plan.record_plans:
        store.assert_plan_current(record_plan)
        authorization = authorizations.get(record_plan.mutation.plan_id)
        if (
            authorization is None
            or authorization.plan.plan_id != record_plan.mutation.plan_id
            or not authorization.dry_run_verified
            or not authorization.approval_verified
        ):
            raise OnboardingError("every record plan requires matching authorization")

    records = tuple(
        store.apply_put(
            record_plan,
            authorizations[record_plan.mutation.plan_id],
        )
        for record_plan in plan.record_plans
    )
    return OnboardingResult(plan_id=plan.plan_id, records=records)
