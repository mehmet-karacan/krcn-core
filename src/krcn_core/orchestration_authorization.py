"""Exact-plan authorization across policy, ownership, mutation, and provider gates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .capability_registry import CapabilitySelection
from .information_records import canonical_json
from .mutation_gate import (
    ApprovalEvidence,
    DryRunEvidence,
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    authorize_mutation,
)
from .orchestration_intent import TaskIntent
from .orchestration_plan import TaskPlan, TaskPlanStep, create_task_plan
from .policies import PolicyDecision, UserPolicy, evaluate_policies
from .provider_gate import (
    ProviderApproval,
    ProviderAuthorization,
    ProviderRequest,
    authorize_provider_request,
    load_provider_gate_policy,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
MUTATING_OPERATIONS = {
    "create",
    "ddl",
    "delete",
    "insert",
    "merge",
    "move",
    "policy-change",
    "update",
}


class TaskAuthorizationError(ValueError):
    """Raised when a task plan cannot pass every existing safety gate."""


@dataclass(frozen=True)
class TaskApproval:
    plan_id: str
    task_id: str
    session_id: str
    approval_id: str
    approved: bool
    approved_triggers: tuple[str, ...]
    mutation_plan_ids: tuple[str, ...]
    provider_request_ids: tuple[str, ...]


@dataclass(frozen=True)
class TaskOperationRequest:
    step_id: str
    resource_type: str
    operation: str
    scope_refs: tuple[tuple[str, str], ...]
    require_policy_match: bool
    approval_trigger: str | None


@dataclass(frozen=True)
class TaskMutationRequest:
    step_id: str
    mutation: MutationPlan
    dry_run: DryRunEvidence


@dataclass(frozen=True)
class TaskProviderRequest:
    step_id: str
    request: ProviderRequest


@dataclass(frozen=True)
class OperationAuthorization:
    step_id: str
    resource_type: str
    operation: str
    scope_refs: tuple[tuple[str, str], ...]
    policy_effect: str
    matched_policy_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "resource_type": self.resource_type,
            "operation": self.operation,
            "scope_refs": dict(self.scope_refs),
            "policy_effect": self.policy_effect,
            "matched_policy_ids": list(self.matched_policy_ids),
            "matched_rule_ids": list(self.matched_rule_ids),
        }


@dataclass(frozen=True)
class StepAuthorization:
    step_id: str
    step_digest: str
    operations: tuple[OperationAuthorization, ...]
    mutation_plan_ids: tuple[str, ...]
    provider_request_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "step_digest": self.step_digest,
            "operations": [item.as_dict() for item in self.operations],
            "mutation_plan_ids": list(self.mutation_plan_ids),
            "provider_request_ids": list(self.provider_request_ids),
        }


@dataclass(frozen=True)
class TaskAuthorization:
    task_id: str
    plan_id: str
    intent_digest: str
    selection_digest: str
    session_id: str
    approval_id: str | None
    steps: tuple[StepAuthorization, ...]
    authorization_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/task-authorization.schema.json",
            "schema_version": 1,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "intent_digest": self.intent_digest,
            "selection_digest": self.selection_digest,
            "session_id": self.session_id,
            "approval_id": self.approval_id,
            "steps": [step.as_dict() for step in self.steps],
            "authorized": True,
            "authorization_id": self.authorization_id,
        }


def create_operation_request(
    *,
    step_id: str,
    resource_type: str,
    operation: str,
    scope_refs: Mapping[str, str] | None = None,
    require_policy_match: bool = False,
    approval_trigger: str | None = None,
) -> TaskOperationRequest:
    """Create a validated, portable operation binding for one worker step."""

    if not IDENTIFIER.fullmatch(step_id):
        raise TaskAuthorizationError("operation step_id is invalid")
    if not IDENTIFIER.fullmatch(resource_type):
        raise TaskAuthorizationError("operation resource_type is invalid")
    if not IDENTIFIER.fullmatch(operation):
        raise TaskAuthorizationError("operation is invalid")
    refs = scope_refs or {}
    if any(
        key not in {"project", "source", "integration"}
        or not IDENTIFIER.fullmatch(value)
        for key, value in refs.items()
    ):
        raise TaskAuthorizationError("operation scope is invalid")
    if not isinstance(require_policy_match, bool):
        raise TaskAuthorizationError("require_policy_match must be boolean")
    if resource_type == "database" and not require_policy_match:
        raise TaskAuthorizationError("database operations must require a policy match")
    if approval_trigger is not None and not IDENTIFIER.fullmatch(approval_trigger):
        raise TaskAuthorizationError("operation approval trigger is invalid")
    return TaskOperationRequest(
        step_id,
        resource_type,
        operation,
        tuple(sorted(refs.items())),
        require_policy_match,
        approval_trigger,
    )


def _rebuild_plan(
    intent: TaskIntent,
    selection: CapabilitySelection,
    plan: TaskPlan,
) -> TaskPlan:
    payloads = []
    for step in plan.steps:
        payload = step.as_dict()
        payload.pop("step_digest")
        payloads.append(payload)
    try:
        rebuilt = create_task_plan(intent, selection, payloads)
    except ValueError as exc:
        raise TaskAuthorizationError("task plan context is invalid") from exc
    if rebuilt.as_dict() != plan.as_dict():
        raise TaskAuthorizationError("task plan does not match current intent and capability selection")
    return rebuilt


def _validate_approval(
    plan: TaskPlan,
    session_id: str,
    approval: TaskApproval | None,
) -> TaskApproval | None:
    if not session_id.strip():
        raise TaskAuthorizationError("session_id is required")
    if not plan.requires_approval:
        if approval is not None:
            raise TaskAuthorizationError("approval cannot expand an approval-free plan")
        return None
    if not (
        approval
        and approval.approved
        and approval.plan_id == plan.plan_id
        and approval.task_id == plan.task_id
        and approval.session_id == session_id
        and approval.approval_id.strip()
    ):
        raise TaskAuthorizationError("matching exact-plan user approval is required")
    if tuple(sorted(set(approval.approved_triggers))) != plan.approval_triggers:
        raise TaskAuthorizationError("approval triggers must match the exact task plan")
    if len(set(approval.mutation_plan_ids)) != len(approval.mutation_plan_ids):
        raise TaskAuthorizationError("approved mutation plan ids must be unique")
    if len(set(approval.provider_request_ids)) != len(approval.provider_request_ids):
        raise TaskAuthorizationError("approved provider request ids must be unique")
    if any(not SHA256.fullmatch(item) for item in approval.mutation_plan_ids):
        raise TaskAuthorizationError("approved mutation plan id is invalid")
    if any(not SHA256.fullmatch(item) for item in approval.provider_request_ids):
        raise TaskAuthorizationError("approved provider request id is invalid")
    return approval


def _authorize_operation(
    step: TaskPlanStep,
    request: TaskOperationRequest,
    policies: Sequence[UserPolicy],
    approval: TaskApproval | None,
) -> OperationAuthorization:
    if request.step_id != step.step_id:
        raise TaskAuthorizationError("operation is bound to the wrong task step")
    decision: PolicyDecision = evaluate_policies(
        policies,
        resource_type=request.resource_type,
        operation=request.operation,
        scope_refs=dict(request.scope_refs),
    )
    if decision.effect == "deny":
        raise TaskAuthorizationError("effective user policy denies the task operation")
    if request.operation in MUTATING_OPERATIONS and "write" not in step.side_effects:
        raise TaskAuthorizationError("mutating operation exceeds task step side effects")
    if request.require_policy_match and decision.effect == "not-applicable":
        raise TaskAuthorizationError("required user policy is not applicable")
    if decision.effect == "require-approval":
        if not (
            approval
            and request.approval_trigger
            and request.approval_trigger in step.approval_triggers
            and request.approval_trigger in approval.approved_triggers
        ):
            raise TaskAuthorizationError("policy decision requires matching user approval")
    return OperationAuthorization(
        request.step_id,
        request.resource_type,
        request.operation,
        request.scope_refs,
        decision.effect,
        decision.matched_policy_ids,
        decision.matched_rule_ids,
    )


def authorize_task_plan(
    repo_root: Path,
    *,
    intent: TaskIntent,
    selection: CapabilitySelection,
    plan: TaskPlan,
    session_id: str,
    policies: Sequence[UserPolicy] = (),
    operations: Sequence[TaskOperationRequest],
    mutations: Sequence[TaskMutationRequest] = (),
    providers: Sequence[TaskProviderRequest] = (),
    approval: TaskApproval | None = None,
) -> TaskAuthorization:
    """Authorize an exact task plan without weakening any underlying gate."""

    plan = _rebuild_plan(intent, selection, plan)
    approval = _validate_approval(plan, session_id, approval)
    steps = {step.step_id: step for step in plan.steps}
    worker_ids = {step.step_id for step in plan.steps if step.role == "worker"}

    operation_groups: dict[str, list[TaskOperationRequest]] = {}
    seen_operations: set[tuple[object, ...]] = set()
    for request in operations:
        if request.step_id not in worker_ids:
            raise TaskAuthorizationError("operations must bind to worker steps")
        identity = (
            request.step_id,
            request.resource_type,
            request.operation,
            request.scope_refs,
        )
        if identity in seen_operations:
            raise TaskAuthorizationError("duplicate task operation binding")
        seen_operations.add(identity)
        operation_groups.setdefault(request.step_id, []).append(request)
    if set(operation_groups) != worker_ids:
        raise TaskAuthorizationError("every worker step requires an operation binding")

    ownership = OwnershipResolver.from_repository(repo_root)
    mutation_groups: dict[str, list[TaskMutationRequest]] = {}
    for binding in mutations:
        step = steps.get(binding.step_id)
        if step is None or step.role != "worker" or "write" not in step.side_effects:
            raise TaskAuthorizationError("mutation must bind to a writing worker step")
        if ownership.resolve(binding.mutation.target_ref) != binding.mutation.ownership:
            raise TaskAuthorizationError("mutation ownership does not match the repository manifest")
        if binding.mutation.ownership not in step.ownership_impacts:
            raise TaskAuthorizationError("mutation ownership exceeds task step scope")
        if binding.mutation.reversible != step.reversible:
            raise TaskAuthorizationError("mutation reversibility does not match the task step")
        mutation_groups.setdefault(binding.step_id, []).append(binding)
    writing_workers = {
        step.step_id for step in plan.steps if step.role == "worker" and "write" in step.side_effects
    }
    if set(mutation_groups) != writing_workers:
        raise TaskAuthorizationError("every writing worker step requires a mutation plan")

    provider_groups: dict[str, list[TaskProviderRequest]] = {}
    for binding in providers:
        step = steps.get(binding.step_id)
        if step is None or step.role != "worker" or step.provider_mode == "none":
            raise TaskAuthorizationError("provider request must bind to a provider worker step")
        expected_remote = step.provider_mode == "remote"
        if binding.request.remote != expected_remote:
            raise TaskAuthorizationError("provider request mode does not match the task step")
        provider_groups.setdefault(binding.step_id, []).append(binding)
    provider_workers = {
        step.step_id
        for step in plan.steps
        if step.role == "worker" and step.provider_mode != "none"
    }
    if set(provider_groups) != provider_workers:
        raise TaskAuthorizationError("every provider worker step requires a provider request")

    required_mutation_approvals = {
        item.mutation.plan_id
        for bindings in mutation_groups.values()
        for item in bindings
        if item.mutation.approval_required
    }
    required_provider_approvals = {
        item.request.request_id
        for bindings in provider_groups.values()
        for item in bindings
        if item.request.remote
    }
    approved_mutations = set(approval.mutation_plan_ids) if approval else set()
    approved_providers = set(approval.provider_request_ids) if approval else set()
    if approved_mutations != required_mutation_approvals:
        raise TaskAuthorizationError("approval mutation scope does not match the task plan")
    if approved_providers != required_provider_approvals:
        raise TaskAuthorizationError("approval provider scope does not match the task plan")

    provider_policy = load_provider_gate_policy(repo_root)
    mutation_results: dict[str, list[MutationAuthorization]] = {}
    for step_id, bindings in mutation_groups.items():
        for binding in bindings:
            evidence = None
            if binding.mutation.approval_required and approval:
                evidence = ApprovalEvidence(
                    binding.mutation.plan_id,
                    approval.approval_id,
                    True,
                )
            try:
                result = authorize_mutation(
                    binding.mutation,
                    dry_run=binding.dry_run,
                    approval=evidence,
                )
            except ValueError as exc:
                raise TaskAuthorizationError("mutation gate rejected the task plan") from exc
            mutation_results.setdefault(step_id, []).append(result)

    provider_results: dict[str, list[ProviderAuthorization]] = {}
    for step_id, bindings in provider_groups.items():
        for binding in bindings:
            evidence = None
            if binding.request.remote and approval:
                evidence = ProviderApproval(
                    binding.request.request_id,
                    session_id,
                    approval.approval_id,
                    True,
                )
            try:
                result = authorize_provider_request(
                    provider_policy,
                    binding.request,
                    approval=evidence,
                )
            except ValueError as exc:
                raise TaskAuthorizationError("provider gate rejected the task plan") from exc
            provider_results.setdefault(step_id, []).append(result)

    authorizations = []
    for step in plan.steps:
        operation_results = tuple(
            sorted(
                (
                    _authorize_operation(step, request, policies, approval)
                    for request in operation_groups.get(step.step_id, ())
                ),
                key=lambda item: (
                    item.resource_type,
                    item.operation,
                    item.scope_refs,
                ),
            )
        )
        authorizations.append(
            StepAuthorization(
                step.step_id,
                step.step_digest,
                operation_results,
                tuple(
                    sorted(
                        item.plan.plan_id
                        for item in mutation_results.get(step.step_id, ())
                    )
                ),
                tuple(
                    sorted(
                        item.request.request_id
                        for item in provider_results.get(step.step_id, ())
                    )
                ),
            )
        )
    identity = {
        "task_id": plan.task_id,
        "plan_id": plan.plan_id,
        "intent_digest": plan.intent_digest,
        "selection_digest": plan.selection_digest,
        "session_id": session_id,
        "approval_id": approval.approval_id if approval else None,
        "steps": [item.as_dict() for item in authorizations],
        "authorized": True,
    }
    authorization_id = hashlib.sha256(canonical_json(identity)).hexdigest()
    return TaskAuthorization(
        plan.task_id,
        plan.plan_id,
        plan.intent_digest,
        plan.selection_digest,
        session_id,
        approval.approval_id if approval else None,
        tuple(authorizations),
        authorization_id,
    )
