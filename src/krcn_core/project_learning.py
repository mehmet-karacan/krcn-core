"""Unified exact planning for project onboarding and first discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .adapter_gate import (
    AdapterApproval,
    authorize_adapter_operation,
    prepare_adapter_operation,
)
from .discovery import (
    LOCAL_DISCOVERY_ADAPTER,
    DiscoveryResult,
    discover_local_source,
    load_discovery_policy,
)
from .local_store import LocalWorkspaceStore, RecordWritePlan, StoredRecord
from .mutation_gate import MutationAuthorization
from .onboarding import OnboardingRequest, prepare_read_only_onboarding
from .policies import load_user_policies
from .project_learning_intent import ProjectLearningIntent
from .project_metadata import ProjectMetadata, infer_project_metadata
from .source_bindings import SourceBinding, parse_source_binding
from .source_state import source_state_from_discovery


class ProjectLearningError(ValueError):
    """Raised when a unified project-learning plan is stale or unsafe."""


@dataclass(frozen=True)
class ProjectLearningPlan:
    plan_id: str
    intent: ProjectLearningIntent
    metadata: ProjectMetadata
    binding: SourceBinding
    adapter_request_id: str
    discovery: DiscoveryResult
    record_plans: tuple[RecordWritePlan, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/project-learning-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "action": self.intent.action,
            "intent_origin": self.intent.intent_origin,
            "metadata": self.metadata.public_summary(),
            "discovery": {
                "root_digest": self.discovery.root_digest,
                "file_count": len(self.discovery.files),
                "technologies": list(self.discovery.technologies),
                "skipped": dict(self.discovery.skipped),
            },
            "source_access": "read-only",
            "source_copy": False,
            "record_plans": [
                {
                    "record_type": item.record_type,
                    "record_id": item.record_id,
                    "previous_revision": item.previous_revision,
                    "next_revision": item.next_revision,
                    "ownership": item.mutation.ownership,
                    "approval_required": item.mutation.approval_required,
                    "mutation_plan_id": item.mutation.plan_id,
                }
                for item in self.record_plans
            ],
        }


@dataclass(frozen=True)
class ProjectLearningResult:
    plan_id: str
    records: tuple[StoredRecord, ...]

    def public_summary(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "records": [record.public_summary() for record in self.records],
            "source_copy": False,
        }


def _binding_payload(metadata: ProjectMetadata, source_root: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "binding_id": metadata.binding_id,
        "source_id": metadata.project_id,
        "source_kind": "project",
        "locator": {"kind": "local-path", "value": str(source_root)},
        "default_access": "read-only",
        "capabilities": ["read", "metadata"],
        "policy_refs": [],
        "revision": 1,
    }


def _discover(
    repo_root: Path,
    store: LocalWorkspaceStore,
    intent: ProjectLearningIntent,
    binding: SourceBinding,
) -> tuple[str, DiscoveryResult]:
    policies = load_user_policies(store.data_root / "policies")
    request = prepare_adapter_operation(
        LOCAL_DISCOVERY_ADAPTER,
        binding,
        "discover",
        policies,
    )
    approval = None
    if request.policy_effect == "require-approval":
        approval = AdapterApproval(
            request_id=request.request_id,
            approval_id=f"project-learning-intent-{intent.request_digest[:16]}",
            approved=True,
        )
    authorization = authorize_adapter_operation(request, approval)
    result = discover_local_source(
        binding,
        load_discovery_policy(repo_root),
        authorization,
    )
    return request.request_id, result


def prepare_project_learning(
    repo_root: Path,
    store: LocalWorkspaceStore,
    intent: ProjectLearningIntent,
) -> ProjectLearningPlan:
    """Prepare onboarding and first discovery as one non-mutating exact plan."""

    metadata = infer_project_metadata(intent.source_root, store)
    onboarding = prepare_read_only_onboarding(
        store,
        OnboardingRequest(
            workspace_id=metadata.workspace_id,
            project_id=metadata.project_id,
            binding_id=metadata.binding_id,
            project_name=metadata.project_name,
            description="Yerel kaynak dizini salt okunur incelenerek tanıtıldı.",
            source_root=intent.source_root,
        ),
    )
    binding = parse_source_binding(_binding_payload(metadata, onboarding.source_root))
    adapter_request_id, discovery = _discover(repo_root, store, intent, binding)
    project_payload = {
        "schema_version": 1,
        "project_id": metadata.project_id,
        "name": metadata.project_name,
        "description": "Yerel kaynak dizini salt okunur incelenerek tanıtıldı.",
        "source_refs": [metadata.binding_id],
        "technologies": [
            {"name": technology, "category": "discovered"}
            for technology in discovery.technologies
        ],
        "modules": [],
        "skill_refs": [],
        "status": "active",
    }
    project_plan = store.prepare_put(
        "projects",
        metadata.project_id,
        project_payload,
        expected_revision=0,
    )
    state_plan = store.prepare_put(
        "source-states",
        metadata.binding_id,
        source_state_from_discovery(discovery).as_payload(),
        expected_revision=0,
    )
    binding_plan, _, workspace_plan = onboarding.record_plans
    record_plans = (binding_plan, project_plan, workspace_plan, state_plan)
    identity = {
        "action": intent.action,
        "metadata_digest": metadata.inference_digest,
        "adapter_request_id": adapter_request_id,
        "root_digest": discovery.root_digest,
        "record_plan_ids": [item.mutation.plan_id for item in record_plans],
    }
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ProjectLearningPlan(
        plan_id=plan_id,
        intent=intent,
        metadata=metadata,
        binding=binding,
        adapter_request_id=adapter_request_id,
        discovery=discovery,
        record_plans=record_plans,
    )


def apply_project_learning(
    repo_root: Path,
    store: LocalWorkspaceStore,
    plan: ProjectLearningPlan,
    authorizations: Mapping[str, MutationAuthorization],
) -> ProjectLearningResult:
    """Apply all records only while the exact source and write plans remain current."""

    if not plan.intent.source_root.is_dir() or plan.intent.source_root.is_symlink():
        raise ProjectLearningError("project source is no longer a safe directory")
    current_adapter_id, current_discovery = _discover(
        repo_root,
        store,
        plan.intent,
        plan.binding,
    )
    if (
        current_adapter_id != plan.adapter_request_id
        or current_discovery.root_digest != plan.discovery.root_digest
    ):
        raise ProjectLearningError("project-learning plan is stale")
    for record_plan in plan.record_plans:
        store.assert_plan_current(record_plan)
        authorization = authorizations.get(record_plan.mutation.plan_id)
        if (
            authorization is None
            or authorization.plan.plan_id != record_plan.mutation.plan_id
            or not authorization.dry_run_verified
            or (
                record_plan.mutation.approval_required
                and not authorization.approval_verified
            )
        ):
            raise ProjectLearningError(
                "every project-learning write requires matching authorization"
            )
    records = tuple(
        store.apply_put(item, authorizations[item.mutation.plan_id])
        for item in plan.record_plans
    )
    return ProjectLearningResult(plan_id=plan.plan_id, records=records)
