"""Digest-bound execution governance and environment transition gates.

The module is deliberately storage, transport, and deployment neutral.  It
creates immutable records and reuses the existing mutation gate, but never
writes a registry, changes an environment, invokes a provider, or rolls back a
deployment by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .agent_execution_identity import (
    AgentExecutionIdentity,
    AgentExecutionIdentityError,
    parse_agent_execution_identity,
)
from .json_documents import canonical_json_bytes
from .mutation_gate import (
    ApprovalEvidence,
    DryRunEvidence,
    MutationGateError,
    MutationPlan,
    OwnershipResolver,
    authorize_mutation,
    plan_mutation,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")

ENTRY_KINDS = {"assumption", "deviation", "known", "unknown"}
SEVERITIES = {"critical", "high", "low", "medium"}
DISPOSITIONS = {
    "accepted",
    "blocked",
    "invalidated",
    "mitigated",
    "open",
    "resolved",
}
DISPOSITIONS_BY_KIND = {
    "known": {"accepted", "resolved"},
    "unknown": {"blocked", "open", "resolved"},
    "assumption": {"accepted", "invalidated", "open"},
    "deviation": {"accepted", "blocked", "mitigated", "open", "resolved"},
}
TRANSITION_KINDS = {"promotion", "rollback"}


class ExecutionGovernanceError(ValueError):
    """Raised when an execution-governance record fails closed."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _strict(payload: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ExecutionGovernanceError(f"{label} fields are invalid")
    return payload


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ExecutionGovernanceError(f"{label} must be a portable identifier")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ExecutionGovernanceError(f"{label} must be a SHA-256 digest")
    return value


def _ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not LOGICAL_REF.fullmatch(value):
        raise ExecutionGovernanceError(f"{label} must be a logical reference")
    return value


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ExecutionGovernanceError(f"{label} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecutionGovernanceError(f"{label} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ExecutionGovernanceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _unique_refs(values: object, label: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ExecutionGovernanceError(f"{label} must be a list")
    result = sorted(_ref(value, f"{label} entry") for value in values)
    if not result or len(result) != len(set(result)):
        raise ExecutionGovernanceError(f"{label} must be non-empty and unique")
    return result


@dataclass(frozen=True)
class ExecutionGovernancePolicy:
    payload: Mapping[str, object]

    @property
    def policy_digest(self) -> str:
        return _digest(self.payload)

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


@dataclass(frozen=True)
class GovernanceRecord:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload))


def parse_execution_governance_policy(payload: object) -> ExecutionGovernancePolicy:
    fields = {
        "schema_ref",
        "schema_version",
        "entry_kinds",
        "severities",
        "dispositions",
        "blocking_severities",
        "blocking_dispositions",
        "environment_stages",
        "require_adjacent_promotion",
        "require_independent_verifier",
        "require_exact_mutation_plan",
        "require_rollback_evidence",
        "transition_target_template",
        "grants_authority",
    }
    data = _strict(payload, fields, "execution governance policy")
    if (
        data.get("schema_ref") != "schemas/execution-governance-policy.schema.json"
        or data.get("schema_version") != 1
        or data.get("entry_kinds") != sorted(ENTRY_KINDS)
        or data.get("severities") != sorted(SEVERITIES)
        or data.get("dispositions") != sorted(DISPOSITIONS)
        or data.get("blocking_severities") != ["critical", "high"]
        or data.get("blocking_dispositions") != ["blocked", "open"]
        or data.get("environment_stages") != ["dev", "test", "pilot", "production"]
        or any(
            data.get(key) is not True
            for key in (
                "require_adjacent_promotion",
                "require_independent_verifier",
                "require_exact_mutation_plan",
                "require_rollback_evidence",
            )
        )
        or data.get("transition_target_template")
        != ".krcn/projects/{project_id}/local-data/execution-governance/transitions/{transition_id}.json"
        or data.get("grants_authority") is not False
    ):
        raise ExecutionGovernanceError("execution governance policy is unsafe")
    return ExecutionGovernancePolicy(dict(data))


def load_execution_governance_policy(repo_root: Path) -> ExecutionGovernancePolicy:
    try:
        payload = json.loads(
            (repo_root / "config" / "execution-governance.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionGovernanceError("execution governance policy cannot be loaded") from exc
    return parse_execution_governance_policy(payload)


def _governance_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in payload
        if key not in {"schema_ref", "schema_version", "plan_digest"}
    }


def create_governance_plan(
    policy: ExecutionGovernancePolicy,
    *,
    governance_id: str,
    project_id: str,
    task_id: str,
    task_plan_id: str,
    objective_ref: str,
    objective_digest: str,
    constraint_refs: Sequence[str],
    created_at: str,
) -> GovernanceRecord:
    payload: dict[str, object] = {
        "schema_ref": "schemas/execution-governance-plan.schema.json",
        "schema_version": 1,
        "governance_id": _identifier(governance_id, "governance id"),
        "project_id": _identifier(project_id, "project id"),
        "task_id": _identifier(task_id, "task id"),
        "task_plan_id": _sha(task_plan_id, "task plan id"),
        "policy_digest": policy.policy_digest,
        "created_at": _timestamp(created_at, "created at"),
        "objective_ref": _ref(objective_ref, "objective ref"),
        "objective_digest": _sha(objective_digest, "objective digest"),
        "constraint_refs": _unique_refs(constraint_refs, "constraint refs"),
        "grants_authority": False,
    }
    payload["plan_digest"] = _digest(_governance_identity(payload))
    return parse_governance_plan(payload, policy)


def parse_governance_plan(
    payload: object, policy: ExecutionGovernancePolicy
) -> GovernanceRecord:
    fields = {
        "schema_ref",
        "schema_version",
        "governance_id",
        "project_id",
        "task_id",
        "task_plan_id",
        "policy_digest",
        "created_at",
        "objective_ref",
        "objective_digest",
        "constraint_refs",
        "grants_authority",
        "plan_digest",
    }
    data = _strict(payload, fields, "governance plan")
    if (
        data.get("schema_ref") != "schemas/execution-governance-plan.schema.json"
        or data.get("schema_version") != 1
        or data.get("grants_authority") is not False
    ):
        raise ExecutionGovernanceError("governance plan contract is invalid")
    _identifier(data.get("governance_id"), "governance id")
    _identifier(data.get("project_id"), "project id")
    _identifier(data.get("task_id"), "task id")
    _sha(data.get("task_plan_id"), "task plan id")
    if _sha(data.get("policy_digest"), "policy digest") != policy.policy_digest:
        raise ExecutionGovernanceError("governance policy digest is stale")
    _timestamp(data.get("created_at"), "created at")
    _ref(data.get("objective_ref"), "objective ref")
    _sha(data.get("objective_digest"), "objective digest")
    _unique_refs(data.get("constraint_refs"), "constraint refs")
    if _sha(data.get("plan_digest"), "plan digest") != _digest(_governance_identity(data)):
        raise ExecutionGovernanceError("governance plan digest does not match")
    return GovernanceRecord(dict(data))


def _entry_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in payload
        if key not in {"schema_ref", "schema_version", "entry_digest"}
    }


def create_register_entry(
    policy: ExecutionGovernancePolicy,
    plan: GovernanceRecord,
    *,
    entry_id: str,
    kind: str,
    topic_ref: str,
    statement_digest: str,
    evidence_digest: str,
    severity: str,
    disposition: str,
    owner_ref: str,
    related_ref: str,
    recorded_at: str,
    supersedes_entry_digest: str | None = None,
) -> GovernanceRecord:
    parsed_plan = parse_governance_plan(plan.as_dict(), policy)
    if kind not in ENTRY_KINDS or severity not in SEVERITIES or disposition not in DISPOSITIONS:
        raise ExecutionGovernanceError("register classification is invalid")
    if disposition not in DISPOSITIONS_BY_KIND[kind]:
        raise ExecutionGovernanceError("register disposition is invalid for its kind")
    payload: dict[str, object] = {
        "schema_ref": "schemas/execution-governance-entry.schema.json",
        "schema_version": 1,
        "entry_id": _identifier(entry_id, "entry id"),
        "governance_plan_digest": str(parsed_plan.payload["plan_digest"]),
        "kind": kind,
        "topic_ref": _ref(topic_ref, "topic ref"),
        "statement_digest": _sha(statement_digest, "statement digest"),
        "evidence_digest": _sha(evidence_digest, "evidence digest"),
        "severity": severity,
        "disposition": disposition,
        "owner_ref": _ref(owner_ref, "owner ref"),
        "related_ref": _ref(related_ref, "related ref"),
        "recorded_at": _timestamp(recorded_at, "recorded at"),
        "supersedes_entry_digest": (
            None
            if supersedes_entry_digest is None
            else _sha(supersedes_entry_digest, "supersedes entry digest")
        ),
        "contains_raw_content": False,
        "contains_secrets": False,
        "contains_physical_paths": False,
        "grants_authority": False,
    }
    payload["entry_digest"] = _digest(_entry_identity(payload))
    return parse_register_entry(payload)


def parse_register_entry(payload: object) -> GovernanceRecord:
    fields = {
        "schema_ref",
        "schema_version",
        "entry_id",
        "governance_plan_digest",
        "kind",
        "topic_ref",
        "statement_digest",
        "evidence_digest",
        "severity",
        "disposition",
        "owner_ref",
        "related_ref",
        "recorded_at",
        "supersedes_entry_digest",
        "contains_raw_content",
        "contains_secrets",
        "contains_physical_paths",
        "grants_authority",
        "entry_digest",
    }
    data = _strict(payload, fields, "governance entry")
    if (
        data.get("schema_ref") != "schemas/execution-governance-entry.schema.json"
        or data.get("schema_version") != 1
        or any(
            data.get(key) is not False
            for key in (
                "contains_raw_content",
                "contains_secrets",
                "contains_physical_paths",
                "grants_authority",
            )
        )
    ):
        raise ExecutionGovernanceError("governance entry contract is invalid")
    _identifier(data.get("entry_id"), "entry id")
    for key in ("governance_plan_digest", "statement_digest", "evidence_digest"):
        _sha(data.get(key), key)
    if data.get("supersedes_entry_digest") is not None:
        _sha(data.get("supersedes_entry_digest"), "supersedes entry digest")
    if data.get("kind") not in ENTRY_KINDS or data.get("severity") not in SEVERITIES:
        raise ExecutionGovernanceError("governance entry classification is invalid")
    if data.get("disposition") not in DISPOSITIONS:
        raise ExecutionGovernanceError("governance entry disposition is invalid")
    if data.get("disposition") not in DISPOSITIONS_BY_KIND[str(data["kind"])]:
        raise ExecutionGovernanceError("governance entry disposition is invalid for its kind")
    _ref(data.get("topic_ref"), "topic ref")
    _ref(data.get("owner_ref"), "owner ref")
    _ref(data.get("related_ref"), "related ref")
    _timestamp(data.get("recorded_at"), "recorded at")
    if _sha(data.get("entry_digest"), "entry digest") != _digest(_entry_identity(data)):
        raise ExecutionGovernanceError("governance entry digest does not match")
    return GovernanceRecord(dict(data))


def validate_register(
    plan: GovernanceRecord, entries: Sequence[Mapping[str, object]]
) -> tuple[GovernanceRecord, ...]:
    plan_digest = str(plan.payload["plan_digest"])
    parsed = tuple(parse_register_entry(item) for item in entries)
    ids = [str(item.payload["entry_id"]) for item in parsed]
    digests = [str(item.payload["entry_digest"]) for item in parsed]
    if len(ids) != len(set(ids)) or len(digests) != len(set(digests)):
        raise ExecutionGovernanceError("governance register contains duplicates")
    if any(item.payload["governance_plan_digest"] != plan_digest for item in parsed):
        raise ExecutionGovernanceError("governance entry belongs to another plan")
    known_digests = set(digests)
    by_digest = {str(item.payload["entry_digest"]): item for item in parsed}
    for item in parsed:
        previous = item.payload["supersedes_entry_digest"]
        if previous is not None and previous not in known_digests:
            raise ExecutionGovernanceError("superseded governance entry is missing")
        if previous == item.payload["entry_digest"]:
            raise ExecutionGovernanceError("governance entry cannot supersede itself")
        if previous is not None:
            previous_time = _timestamp(by_digest[str(previous)].payload["recorded_at"], "recorded at")
            current_time = _timestamp(item.payload["recorded_at"], "recorded at")
            if current_time <= previous_time:
                raise ExecutionGovernanceError("governance supersession must move forward in time")
    for digest in digests:
        seen: set[str] = set()
        current: str | None = digest
        while current is not None:
            if current in seen:
                raise ExecutionGovernanceError("governance supersession contains a cycle")
            seen.add(current)
            previous = by_digest[current].payload["supersedes_entry_digest"]
            current = None if previous is None else str(previous)
    return tuple(sorted(parsed, key=lambda item: str(item.payload["entry_id"])))


def _identity(payload: object, role: str) -> AgentExecutionIdentity:
    try:
        identity = parse_agent_execution_identity(payload)
    except AgentExecutionIdentityError as exc:
        raise ExecutionGovernanceError("execution identity is invalid") from exc
    if identity.role != role:
        raise ExecutionGovernanceError(f"{role} execution identity is required")
    return identity


def _provider_gate(payload: object) -> dict[str, object]:
    data = _strict(
        payload,
        {"required", "provider_ref", "approval_ref", "authorization_digest"},
        "provider gate",
    )
    if not isinstance(data.get("required"), bool):
        raise ExecutionGovernanceError("provider gate required flag is invalid")
    required = bool(data["required"])
    values = (data.get("provider_ref"), data.get("approval_ref"), data.get("authorization_digest"))
    if required:
        provider_ref = _ref(values[0], "provider ref")
        approval_ref = _ref(values[1], "provider approval ref")
        authorization_digest = _sha(values[2], "provider authorization digest")
    else:
        if any(value is not None for value in values):
            raise ExecutionGovernanceError("unused provider gate values must be null")
        provider_ref = approval_ref = authorization_digest = None
    return {
        "required": required,
        "provider_ref": provider_ref,
        "approval_ref": approval_ref,
        "authorization_digest": authorization_digest,
    }


def _parse_mutation(payload: object) -> MutationPlan:
    fields = {
        "schema_version",
        "plan_id",
        "operation",
        "target_ref",
        "ownership",
        "change_digest",
        "dry_run_required",
        "approval_required",
        "reversible",
    }
    data = _strict(payload, fields, "transition mutation")
    if (
        data.get("schema_version") != 1
        or data.get("operation") not in {"create", "update"}
        or data.get("ownership") != "user-data"
        or data.get("dry_run_required") is not True
        or data.get("approval_required") is not True
        or data.get("reversible") is not True
    ):
        raise ExecutionGovernanceError("transition mutation contract is unsafe")
    plan = MutationPlan(
        _sha(data.get("plan_id"), "mutation plan id"),
        str(data["operation"]),
        str(data["target_ref"]),
        str(data["ownership"]),
        _sha(data.get("change_digest"), "mutation change digest"),
        True,
        True,
        True,
    )
    identity = {
        "operation": plan.operation,
        "target_ref": plan.target_ref,
        "ownership": plan.ownership,
        "change_digest": plan.change_digest,
        "reversible": plan.reversible,
    }
    expected = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if plan.plan_id != expected:
        raise ExecutionGovernanceError("transition mutation plan id does not match")
    return plan


def _transition_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in payload
        if key not in {"schema_ref", "schema_version", "mutation", "transition_digest"}
    }


def _blocking_entries(
    policy: ExecutionGovernancePolicy, entries: Sequence[GovernanceRecord]
) -> list[str]:
    blocking_severities = set(policy.payload["blocking_severities"])
    blocking_dispositions = set(policy.payload["blocking_dispositions"])
    superseded = {
        str(item.payload["supersedes_entry_digest"])
        for item in entries
        if item.payload["supersedes_entry_digest"] is not None
    }
    return sorted(
        str(item.payload["entry_digest"])
        for item in entries
        if item.payload["entry_digest"] not in superseded
        and item.payload["kind"] in {"unknown", "deviation"}
        and item.payload["severity"] in blocking_severities
        and item.payload["disposition"] in blocking_dispositions
    )


def _build_transition_plan(
    resolver: OwnershipResolver,
    policy: ExecutionGovernancePolicy,
    governance_plan: GovernanceRecord,
    *,
    transition_id: str,
    transition_kind: str,
    source_stage: str,
    target_stage: str,
    source_environment_digest: str,
    target_environment_digest: str,
    artifact_digest: str,
    test_digest: str,
    verifier_evidence_digest: str,
    rollback_digest: str,
    worker_execution_identity: Mapping[str, object],
    verifier_execution_identity: Mapping[str, object],
    provider_gate: Mapping[str, object],
    register_entries: Sequence[Mapping[str, object]],
    created_at: str,
    rollback_of_transition_digest: str | None,
) -> GovernanceRecord:
    plan = parse_governance_plan(governance_plan.as_dict(), policy)
    if transition_kind not in TRANSITION_KINDS:
        raise ExecutionGovernanceError("environment transition kind is invalid")
    stages = list(policy.payload["environment_stages"])
    if source_stage not in stages or target_stage not in stages:
        raise ExecutionGovernanceError("environment stage is invalid")
    source_index, target_index = stages.index(source_stage), stages.index(target_stage)
    if transition_kind == "promotion" and target_index != source_index + 1:
        raise ExecutionGovernanceError("environment promotion must use adjacent stages")
    if transition_kind == "rollback" and target_index != source_index - 1:
        raise ExecutionGovernanceError("environment rollback must return one adjacent stage")
    worker = _identity(worker_execution_identity, "worker")
    verifier = _identity(verifier_execution_identity, "verifier")
    if any(identity.task_id != plan.payload["task_id"] for identity in (worker, verifier)):
        raise ExecutionGovernanceError("execution identities do not match the governed task")
    if any(identity.plan_id != plan.payload["task_plan_id"] for identity in (worker, verifier)):
        raise ExecutionGovernanceError("execution identities do not match the governed task plan")
    if (
        worker.step_id == verifier.step_id
        or worker.actor_digest == verifier.actor_digest
        or worker.assignment_digest == verifier.assignment_digest
        or worker.execution_identity_id == verifier.execution_identity_id
    ):
        raise ExecutionGovernanceError("independent verifier identity is required")
    entries = validate_register(plan, register_entries)
    blockers = _blocking_entries(policy, entries)
    if blockers:
        raise ExecutionGovernanceError("unresolved high-severity register entries block transition")
    entry_digests = sorted(str(item.payload["entry_digest"]) for item in entries)
    source_digest = _sha(source_environment_digest, "source environment digest")
    target_digest = _sha(target_environment_digest, "target environment digest")
    if source_digest == target_digest:
        raise ExecutionGovernanceError("source and target environment digests must differ")
    base: dict[str, object] = {
        "transition_id": _identifier(transition_id, "transition id"),
        "governance_plan_digest": str(plan.payload["plan_digest"]),
        "project_id": str(plan.payload["project_id"]),
        "task_id": str(plan.payload["task_id"]),
        "task_plan_id": str(plan.payload["task_plan_id"]),
        "transition_kind": transition_kind,
        "source_stage": source_stage,
        "target_stage": target_stage,
        "source_environment_digest": source_digest,
        "target_environment_digest": target_digest,
        "artifact_digest": _sha(artifact_digest, "artifact digest"),
        "test_digest": _sha(test_digest, "test digest"),
        "verifier_evidence_digest": _sha(verifier_evidence_digest, "verifier evidence digest"),
        "rollback_digest": _sha(rollback_digest, "rollback digest"),
        "worker_execution_identity": worker.as_dict(),
        "verifier_execution_identity": verifier.as_dict(),
        "provider_gate": _provider_gate(provider_gate),
        "register_snapshot_digest": _digest(entry_digests),
        "blocking_entry_digests": [],
        "rollback_of_transition_digest": (
            None
            if rollback_of_transition_digest is None
            else _sha(rollback_of_transition_digest, "rollback transition digest")
        ),
        "created_at": _timestamp(created_at, "created at"),
        "does_not_execute": True,
        "grants_authority": False,
    }
    if (transition_kind == "promotion") != (base["rollback_of_transition_digest"] is None):
        raise ExecutionGovernanceError("rollback binding is inconsistent")
    change_digest = _digest(base)
    target_ref = str(policy.payload["transition_target_template"]).format(
        project_id=base["project_id"], transition_id=base["transition_id"]
    )
    mutation = plan_mutation(
        resolver,
        operation="create",
        target_ref=target_ref,
        expected_ownership="user-data",
        change_digest=change_digest,
        reversible=True,
    )
    payload = {
        "schema_ref": "schemas/execution-environment-transition-plan.schema.json",
        "schema_version": 1,
        **base,
        "mutation": mutation.as_dict(),
    }
    payload["transition_digest"] = _digest(
        {**_transition_identity(payload), "mutation": mutation.as_dict()}
    )
    return parse_environment_transition_plan(payload, policy, plan, resolver)


def build_environment_promotion_plan(
    resolver: OwnershipResolver,
    policy: ExecutionGovernancePolicy,
    governance_plan: GovernanceRecord,
    **values: object,
) -> GovernanceRecord:
    """Build an adjacent environment-promotion plan without executing it."""

    return _build_transition_plan(
        resolver,
        policy,
        governance_plan,
        transition_kind="promotion",
        rollback_of_transition_digest=None,
        **values,
    )


def build_environment_rollback_plan(
    resolver: OwnershipResolver,
    policy: ExecutionGovernancePolicy,
    governance_plan: GovernanceRecord,
    original_transition: GovernanceRecord,
    original_authorization: GovernanceRecord,
    *,
    observed_environment_digest: str,
    **values: object,
) -> GovernanceRecord:
    """Build an exact adjacent rollback bound to an authorized promotion."""

    original = parse_environment_transition_plan(
        original_transition.as_dict(), policy, governance_plan, resolver
    )
    if original.payload["transition_kind"] != "promotion":
        raise ExecutionGovernanceError("rollback requires an original promotion")
    authorization = parse_transition_authorization(original_authorization.as_dict())
    if authorization.payload["transition_digest"] != original.payload["transition_digest"]:
        raise ExecutionGovernanceError("rollback authorization does not bind the promotion")
    if _sha(observed_environment_digest, "observed environment digest") != original.payload["target_environment_digest"]:
        raise ExecutionGovernanceError("rollback source environment is stale")
    supplied_source = values.pop("source_stage", original.payload["target_stage"])
    supplied_target = values.pop("target_stage", original.payload["source_stage"])
    supplied_source_digest = values.pop(
        "source_environment_digest", original.payload["target_environment_digest"]
    )
    supplied_target_digest = values.pop(
        "target_environment_digest", original.payload["source_environment_digest"]
    )
    return _build_transition_plan(
        resolver,
        policy,
        governance_plan,
        transition_kind="rollback",
        source_stage=str(supplied_source),
        target_stage=str(supplied_target),
        source_environment_digest=str(supplied_source_digest),
        target_environment_digest=str(supplied_target_digest),
        rollback_of_transition_digest=str(original.payload["transition_digest"]),
        **values,
    )


def parse_environment_transition_plan(
    payload: object,
    policy: ExecutionGovernancePolicy,
    governance_plan: GovernanceRecord,
    resolver: OwnershipResolver,
) -> GovernanceRecord:
    fields = {
        "schema_ref", "schema_version", "transition_id", "governance_plan_digest",
        "project_id", "task_id", "task_plan_id", "transition_kind", "source_stage",
        "target_stage", "source_environment_digest", "target_environment_digest",
        "artifact_digest", "test_digest", "verifier_evidence_digest", "rollback_digest",
        "worker_execution_identity", "verifier_execution_identity", "provider_gate",
        "register_snapshot_digest", "blocking_entry_digests", "rollback_of_transition_digest",
        "created_at", "does_not_execute", "grants_authority", "mutation", "transition_digest",
    }
    data = _strict(payload, fields, "environment transition plan")
    if (
        data.get("schema_ref") != "schemas/execution-environment-transition-plan.schema.json"
        or data.get("schema_version") != 1
        or data.get("does_not_execute") is not True
        or data.get("grants_authority") is not False
        or data.get("blocking_entry_digests") != []
    ):
        raise ExecutionGovernanceError("environment transition contract is invalid")
    plan = parse_governance_plan(governance_plan.as_dict(), policy)
    for key in ("transition_id", "project_id", "task_id"):
        _identifier(data.get(key), key)
    if (
        data.get("governance_plan_digest") != plan.payload["plan_digest"]
        or data.get("project_id") != plan.payload["project_id"]
        or data.get("task_id") != plan.payload["task_id"]
        or data.get("task_plan_id") != plan.payload["task_plan_id"]
    ):
        raise ExecutionGovernanceError("environment transition has a stale governance binding")
    stages = list(policy.payload["environment_stages"])
    if data.get("source_stage") not in stages or data.get("target_stage") not in stages:
        raise ExecutionGovernanceError("environment transition stage is invalid")
    delta = stages.index(str(data["target_stage"])) - stages.index(str(data["source_stage"]))
    if (data.get("transition_kind"), delta) not in {("promotion", 1), ("rollback", -1)}:
        raise ExecutionGovernanceError("environment transition cannot skip stages")
    rollback_of = data.get("rollback_of_transition_digest")
    if (data.get("transition_kind") == "promotion") != (rollback_of is None):
        raise ExecutionGovernanceError("environment transition rollback binding is invalid")
    if rollback_of is not None:
        _sha(rollback_of, "rollback transition digest")
    for key in (
        "task_plan_id", "source_environment_digest", "target_environment_digest",
        "artifact_digest", "test_digest", "verifier_evidence_digest", "rollback_digest",
        "register_snapshot_digest", "transition_digest",
    ):
        _sha(data.get(key), key)
    worker = _identity(data.get("worker_execution_identity"), "worker")
    verifier = _identity(data.get("verifier_execution_identity"), "verifier")
    if (
        worker.task_id != data["task_id"]
        or verifier.task_id != data["task_id"]
        or worker.plan_id != data["task_plan_id"]
        or verifier.plan_id != data["task_plan_id"]
        or worker.step_id == verifier.step_id
        or worker.actor_digest == verifier.actor_digest
        or worker.assignment_digest == verifier.assignment_digest
    ):
        raise ExecutionGovernanceError("environment verifier is not independent")
    _provider_gate(data.get("provider_gate"))
    _timestamp(data.get("created_at"), "created at")
    mutation = _parse_mutation(data.get("mutation"))
    base = _transition_identity(data)
    if mutation.change_digest != _digest(base):
        raise ExecutionGovernanceError("environment transition mutation is stale")
    expected_target = str(policy.payload["transition_target_template"]).format(
        project_id=data["project_id"], transition_id=data["transition_id"]
    )
    expected_mutation = plan_mutation(
        resolver,
        operation="create",
        target_ref=expected_target,
        expected_ownership="user-data",
        change_digest=mutation.change_digest,
        reversible=True,
    )
    if mutation.as_dict() != expected_mutation.as_dict():
        raise ExecutionGovernanceError("environment transition mutation was tampered")
    semantic = {**base, "mutation": mutation.as_dict()}
    if data["transition_digest"] != _digest(semantic):
        raise ExecutionGovernanceError("environment transition digest does not match")
    return GovernanceRecord(dict(data))


def _authorization_identity(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: payload[key]
        for key in payload
        if key not in {"schema_ref", "schema_version", "authorization_digest"}
    }


def authorize_environment_transition(
    policy: ExecutionGovernancePolicy,
    governance_plan: GovernanceRecord,
    transition_plan: GovernanceRecord,
    resolver: OwnershipResolver,
    *,
    dry_run: DryRunEvidence | None,
    approval: ApprovalEvidence | None,
    observed_source_stage: str,
    observed_source_environment_digest: str,
    authorized_at: str,
    existing_authorization: Mapping[str, object] | None = None,
) -> GovernanceRecord:
    """Pass the gate for one exact transition; never execute the transition."""

    transition = parse_environment_transition_plan(
        transition_plan.as_dict(), policy, governance_plan, resolver
    )
    if (
        observed_source_stage != transition.payload["source_stage"]
        or _sha(observed_source_environment_digest, "observed source environment digest")
        != transition.payload["source_environment_digest"]
    ):
        raise ExecutionGovernanceError("environment transition source is stale")
    mutation = _parse_mutation(transition.payload["mutation"])
    try:
        authorization = authorize_mutation(
            mutation, dry_run=dry_run, approval=approval
        )
    except MutationGateError as exc:
        raise ExecutionGovernanceError("exact mutation authorization is required") from exc
    payload: dict[str, object] = {
        "schema_ref": "schemas/execution-environment-transition-authorization.schema.json",
        "schema_version": 1,
        "transition_id": str(transition.payload["transition_id"]),
        "transition_digest": str(transition.payload["transition_digest"]),
        "mutation_plan_id": mutation.plan_id,
        "decision": "gate-passed",
        "authorized_at": _timestamp(authorized_at, "authorized at"),
        "dry_run_verified": authorization.dry_run_verified,
        "user_approval_verified": authorization.approval_verified,
        "does_not_execute": True,
        "grants_implicit_authority": False,
    }
    payload["authorization_digest"] = _digest(_authorization_identity(payload))
    candidate = parse_transition_authorization(payload)
    if existing_authorization is not None:
        existing = parse_transition_authorization(existing_authorization)
        if existing.payload["transition_digest"] != transition.payload["transition_digest"]:
            raise ExecutionGovernanceError("existing authorization belongs to another transition")
        if existing.as_dict() != candidate.as_dict():
            raise ExecutionGovernanceError("transition authorization replay is not idempotent")
        return existing
    return candidate


def parse_transition_authorization(payload: object) -> GovernanceRecord:
    fields = {
        "schema_ref", "schema_version", "transition_id", "transition_digest",
        "mutation_plan_id", "decision", "authorized_at", "dry_run_verified",
        "user_approval_verified", "does_not_execute", "grants_implicit_authority",
        "authorization_digest",
    }
    data = _strict(payload, fields, "environment transition authorization")
    if (
        data.get("schema_ref")
        != "schemas/execution-environment-transition-authorization.schema.json"
        or data.get("schema_version") != 1
        or data.get("decision") != "gate-passed"
        or data.get("dry_run_verified") is not True
        or data.get("user_approval_verified") is not True
        or data.get("does_not_execute") is not True
        or data.get("grants_implicit_authority") is not False
    ):
        raise ExecutionGovernanceError("transition authorization contract is invalid")
    _identifier(data.get("transition_id"), "transition id")
    for key in ("transition_digest", "mutation_plan_id", "authorization_digest"):
        _sha(data.get(key), key)
    _timestamp(data.get("authorized_at"), "authorized at")
    if data["authorization_digest"] != _digest(_authorization_identity(data)):
        raise ExecutionGovernanceError("transition authorization digest does not match")
    return GovernanceRecord(dict(data))
