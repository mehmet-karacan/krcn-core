"""Coordinator-only delegation decisions for meaningful project work."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .client_capabilities import ClientCapabilityProfile, EXECUTION_MODES
from .foundation import load_json
from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")


class DelegationPolicyError(ValueError):
    """Raised when delegation cannot be classified safely."""


@dataclass(frozen=True)
class DelegationPolicy:
    revision: int
    meaningful_project_work: tuple[str, ...]
    coordinator_exceptions: tuple[str, ...]
    coordinator_responsibilities: tuple[str, ...]
    coordinator_prohibited_actions: tuple[str, ...]
    minimum_parallel_agents: int
    policy_digest: str


@dataclass(frozen=True)
class DelegationDecision:
    session_id: str
    client_id: str
    work_class: str
    project_matched: bool
    delegation_required: bool
    selected_mode: str
    execution_allowed: bool
    parallel_preferred: bool
    coordinator_only: bool
    decision_basis: str
    profile_digest: str
    policy_digest: str
    decision_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/delegation-decision.schema.json",
            "schema_version": 1,
            "session_id": self.session_id,
            "client_id": self.client_id,
            "work_class": self.work_class,
            "project_matched": self.project_matched,
            "delegation_required": self.delegation_required,
            "selected_mode": self.selected_mode,
            "execution_allowed": self.execution_allowed,
            "parallel_preferred": self.parallel_preferred,
            "coordinator_only": self.coordinator_only,
            "decision_basis": self.decision_basis,
            "profile_digest": self.profile_digest,
            "policy_digest": self.policy_digest,
            "decision_digest": self.decision_digest,
            "client_declaration_grants_authority": False,
        }


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _identifier_list(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise DelegationPolicyError(f"{label} is invalid")
    return tuple(value)


def parse_delegation_policy(payload: object) -> DelegationPolicy:
    expected = {
        "schema_ref",
        "schema_version",
        "revision",
        "meaningful_project_work",
        "coordinator_exceptions",
        "coordinator_boundary",
        "parallelism",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise DelegationPolicyError("delegation policy fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/delegation-policy.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise DelegationPolicyError("delegation policy schema is invalid")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise DelegationPolicyError("delegation policy revision is invalid")
    meaningful = _identifier_list(
        payload.get("meaningful_project_work"), "meaningful project work"
    )
    exceptions = _identifier_list(
        payload.get("coordinator_exceptions"), "coordinator exceptions"
    )
    if set(meaningful) & set(exceptions):
        raise DelegationPolicyError("delegation work classes must not overlap")
    boundary = payload.get("coordinator_boundary")
    if not isinstance(boundary, dict) or set(boundary) != {
        "responsibilities",
        "prohibited_direct_actions",
    }:
        raise DelegationPolicyError("coordinator boundary is invalid")
    responsibilities = _identifier_list(
        boundary.get("responsibilities"), "coordinator responsibilities"
    )
    prohibited = _identifier_list(
        boundary.get("prohibited_direct_actions"), "coordinator prohibited actions"
    )
    parallelism = payload.get("parallelism")
    minimum = (
        parallelism.get("minimum_parallel_agents")
        if isinstance(parallelism, dict)
        else None
    )
    if (
        not isinstance(parallelism, dict)
        or set(parallelism) != {"prefer_parallel_when_independent", "minimum_parallel_agents"}
        or parallelism.get("prefer_parallel_when_independent") is not True
        or not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or minimum < 2
    ):
        raise DelegationPolicyError("delegation parallelism policy is invalid")
    if payload.get("invariants") != {
        "meaningful_project_work_requires_delegation": True,
        "coordinator_performs_project_work": False,
        "unknown_work_class_allowed": False,
        "client_declaration_grants_authority": False,
        "delegation_unavailable_blocks_project_work": True,
    }:
        raise DelegationPolicyError("delegation policy invariants are invalid")
    return DelegationPolicy(
        int(revision),
        meaningful,
        exceptions,
        responsibilities,
        prohibited,
        int(minimum),
        _digest(payload),
    )


def load_delegation_policy(repo_root: Path) -> DelegationPolicy:
    return parse_delegation_policy(
        load_json(repo_root / "config" / "delegation-policy.json")
    )


def decide_delegation(
    policy: DelegationPolicy,
    profile: ClientCapabilityProfile,
    *,
    work_class: str,
    project_matched: bool,
) -> DelegationDecision:
    """Classify work before routing it and block unsupported delegation."""

    if not isinstance(work_class, str) or not IDENTIFIER.fullmatch(work_class):
        raise DelegationPolicyError("work_class is invalid")
    known = set(policy.meaningful_project_work) | set(policy.coordinator_exceptions)
    if work_class not in known:
        raise DelegationPolicyError("unknown work_class is denied")
    if not isinstance(project_matched, bool):
        raise DelegationPolicyError("project_matched must be boolean")
    if profile.selected_mode not in EXECUTION_MODES:
        raise DelegationPolicyError("client execution mode is invalid")

    required = project_matched and work_class in policy.meaningful_project_work
    if required:
        allowed = profile.selected_mode != "delegation-unavailable"
        basis = "delegated-project-work" if allowed else "delegation-capability-unavailable"
        coordinator_only = True
        parallel_preferred = True
    else:
        allowed = True
        basis = (
            "coordinator-exception"
            if work_class in policy.coordinator_exceptions
            else "project-context-unmatched"
        )
        coordinator_only = False
        parallel_preferred = False
    digest_payload: Mapping[str, object] = {
        "schema_version": 1,
        "session_id": profile.session_id,
        "client_id": profile.client_id,
        "work_class": work_class,
        "project_matched": project_matched,
        "delegation_required": required,
        "selected_mode": profile.selected_mode,
        "execution_allowed": allowed,
        "parallel_preferred": parallel_preferred,
        "coordinator_only": coordinator_only,
        "decision_basis": basis,
        "profile_digest": profile.profile_digest,
        "policy_digest": policy.policy_digest,
    }
    return DelegationDecision(
        profile.session_id,
        profile.client_id,
        work_class,
        project_matched,
        required,
        profile.selected_mode,
        allowed,
        parallel_preferred,
        coordinator_only,
        basis,
        profile.profile_digest,
        policy.policy_digest,
        _digest(digest_payload),
    )
