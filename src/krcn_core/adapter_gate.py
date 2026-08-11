"""Shared capability and user-policy gate for integration adapters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from .policies import PolicyDecisionEffect, UserPolicy, evaluate_policies
from .source_bindings import CAPABILITIES, SOURCE_KINDS, SourceBinding


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class AdapterGateError(ValueError):
    """Raised when an adapter operation violates capability or policy rules."""


@dataclass(frozen=True)
class AdapterOperation:
    operation_id: str
    required_capabilities: tuple[str, ...]
    default_effect: Literal["allow", "deny"]
    mutation_effect: bool
    network_effect: bool


@dataclass(frozen=True)
class AdapterDescriptor:
    adapter_id: str
    version: str
    source_kinds: tuple[str, ...]
    resource_type: str
    operations: tuple[AdapterOperation, ...]

    def operation(self, operation_id: str) -> AdapterOperation:
        for operation in self.operations:
            if operation.operation_id == operation_id:
                return operation
        raise AdapterGateError("adapter operation is not declared")


@dataclass(frozen=True)
class AdapterOperationRequest:
    request_id: str
    adapter_id: str
    operation: str
    binding_id: str
    binding_revision: int
    required_capabilities: tuple[str, ...]
    policy_effect: Literal["allow", "deny", "require-approval"]
    matched_policy_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]
    mutation_effect: bool
    network_effect: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "request_id": self.request_id,
            "adapter_id": self.adapter_id,
            "operation": self.operation,
            "binding_id": self.binding_id,
            "binding_revision": self.binding_revision,
            "required_capabilities": list(self.required_capabilities),
            "policy_effect": self.policy_effect,
            "matched_policy_ids": list(self.matched_policy_ids),
            "matched_rule_ids": list(self.matched_rule_ids),
            "mutation_effect": self.mutation_effect,
            "network_effect": self.network_effect,
        }


@dataclass(frozen=True)
class AdapterApproval:
    request_id: str
    approval_id: str
    approved: bool


@dataclass(frozen=True)
class AdapterAuthorization:
    request: AdapterOperationRequest
    approval_verified: bool


def parse_adapter_descriptor(payload: object) -> AdapterDescriptor:
    """Validate a versioned adapter descriptor."""

    if not isinstance(payload, dict):
        raise AdapterGateError("adapter descriptor must be an object")
    if payload.get("schema_ref") != "schemas/adapter.schema.json":
        raise AdapterGateError("adapter schema reference is invalid")
    adapter_id = payload.get("adapter_id")
    version = payload.get("version")
    resource_type = payload.get("resource_type")
    if not isinstance(adapter_id, str) or not IDENTIFIER.fullmatch(adapter_id):
        raise AdapterGateError("adapter id is invalid")
    if not isinstance(version, str) or not SEMANTIC_VERSION.fullmatch(version):
        raise AdapterGateError("adapter version is invalid")
    if not isinstance(resource_type, str) or not IDENTIFIER.fullmatch(resource_type):
        raise AdapterGateError("adapter resource type is invalid")
    source_kinds_payload = payload.get("source_kinds")
    if not isinstance(source_kinds_payload, list) or not source_kinds_payload:
        raise AdapterGateError("adapter source kinds are required")
    source_kinds = tuple(source_kinds_payload)
    if len(set(source_kinds)) != len(source_kinds) or any(
        item not in SOURCE_KINDS for item in source_kinds
    ):
        raise AdapterGateError("adapter source kinds are invalid")

    operations_payload = payload.get("operations")
    if not isinstance(operations_payload, list) or not operations_payload:
        raise AdapterGateError("adapter operations are required")
    operations: list[AdapterOperation] = []
    seen_operations: set[str] = set()
    for item in operations_payload:
        if not isinstance(item, dict):
            raise AdapterGateError("adapter operation must be an object")
        operation_id = item.get("operation_id")
        required = item.get("required_capabilities")
        default_effect = item.get("default_effect")
        mutation_effect = item.get("mutation_effect")
        network_effect = item.get("network_effect")
        if not isinstance(operation_id, str) or not IDENTIFIER.fullmatch(operation_id):
            raise AdapterGateError("adapter operation id is invalid")
        if operation_id in seen_operations:
            raise AdapterGateError("adapter operation ids must be unique")
        seen_operations.add(operation_id)
        if not isinstance(required, list) or any(item not in CAPABILITIES for item in required):
            raise AdapterGateError("required capabilities are invalid")
        if len(set(required)) != len(required):
            raise AdapterGateError("required capabilities must be unique")
        if default_effect not in {"allow", "deny"}:
            raise AdapterGateError("adapter default effect is invalid")
        if not isinstance(mutation_effect, bool) or not isinstance(network_effect, bool):
            raise AdapterGateError("adapter effect declarations must be boolean")
        if mutation_effect and "write" not in required:
            raise AdapterGateError("mutating adapter operation must require write capability")
        operations.append(
            AdapterOperation(
                operation_id=operation_id,
                required_capabilities=tuple(required),
                default_effect=default_effect,
                mutation_effect=mutation_effect,
                network_effect=network_effect,
            )
        )
    return AdapterDescriptor(
        adapter_id=adapter_id,
        version=version,
        source_kinds=source_kinds,
        resource_type=resource_type,
        operations=tuple(operations),
    )


def prepare_adapter_operation(
    descriptor: AdapterDescriptor,
    binding: SourceBinding,
    operation_id: str,
    policies: Sequence[UserPolicy],
) -> AdapterOperationRequest:
    """Resolve capability and user-policy effects before adapter execution."""

    if binding.source_kind not in descriptor.source_kinds:
        raise AdapterGateError("source kind is not supported by this adapter")
    operation = descriptor.operation(operation_id)
    missing_capabilities = set(operation.required_capabilities) - set(binding.capabilities)
    if missing_capabilities:
        raise AdapterGateError(
            "source binding is missing required capabilities: "
            + ", ".join(sorted(missing_capabilities))
        )
    if operation.mutation_effect and binding.default_access != "read-write":
        raise AdapterGateError("read-only source binding cannot authorize mutation")

    policies_by_id = {policy.policy_id: policy for policy in policies}
    if len(policies_by_id) != len(policies):
        raise AdapterGateError("policy ids must be unique")
    missing_policy_refs = set(binding.policy_refs) - set(policies_by_id)
    if missing_policy_refs:
        raise AdapterGateError(
            "source binding references unavailable policies: "
            + ", ".join(sorted(missing_policy_refs))
        )
    scope_refs = {"source": binding.source_id}
    if binding.source_kind == "project":
        scope_refs["project"] = binding.source_id
    if binding.source_kind == "integration":
        scope_refs["integration"] = binding.source_id
    decision = evaluate_policies(
        policies,
        resource_type=descriptor.resource_type,
        operation=operation_id,
        scope_refs=scope_refs,
    )
    if decision.effect == "not-applicable":
        policy_effect: PolicyDecisionEffect = operation.default_effect
    else:
        policy_effect = decision.effect
    identity = {
        "adapter_id": descriptor.adapter_id,
        "adapter_version": descriptor.version,
        "operation": operation_id,
        "binding_id": binding.binding_id,
        "binding_revision": binding.revision,
        "required_capabilities": list(operation.required_capabilities),
        "policy_effect": policy_effect,
        "matched_policy_ids": list(decision.matched_policy_ids),
        "matched_rule_ids": list(decision.matched_rule_ids),
        "policy_revisions": sorted(
            (policy.policy_id, policy.revision) for policy in policies
        ),
        "mutation_effect": operation.mutation_effect,
        "network_effect": operation.network_effect,
    }
    request_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return AdapterOperationRequest(
        request_id=request_id,
        adapter_id=descriptor.adapter_id,
        operation=operation_id,
        binding_id=binding.binding_id,
        binding_revision=binding.revision,
        required_capabilities=operation.required_capabilities,
        policy_effect=policy_effect,
        matched_policy_ids=decision.matched_policy_ids,
        matched_rule_ids=decision.matched_rule_ids,
        mutation_effect=operation.mutation_effect,
        network_effect=operation.network_effect,
    )


def authorize_adapter_operation(
    request: AdapterOperationRequest,
    approval: AdapterApproval | None = None,
) -> AdapterAuthorization:
    """Authorize an adapter request or fail before the adapter runs."""

    if request.policy_effect == "deny":
        raise AdapterGateError("adapter operation is denied by effective policy")
    approval_verified = False
    if request.policy_effect == "require-approval":
        approval_verified = bool(
            approval
            and approval.approved
            and approval.request_id == request.request_id
            and approval.approval_id.strip()
        )
        if not approval_verified:
            raise AdapterGateError("adapter operation requires matching approval")
    return AdapterAuthorization(request=request, approval_verified=approval_verified)
