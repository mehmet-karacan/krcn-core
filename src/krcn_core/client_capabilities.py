"""Session-bound client capability profiles and fail-closed mode selection."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .foundation import detect_content_findings, load_json
from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
EXECUTION_MODES = (
    "native-parallel",
    "native-sequential",
    "isolated-role-fallback",
    "delegation-unavailable",
)
CAPABILITY_NAMES = (
    "native_subagents",
    "parallel_subagents",
    "per_agent_model_selection",
    "agent_cancellation",
    "structured_results",
    "isolated_role_execution",
)


class ClientCapabilityError(ValueError):
    """Raised when a client capability declaration is incomplete or unsafe."""


@dataclass(frozen=True)
class ClientCapabilityPolicy:
    revision: int
    mode_order: tuple[str, ...]
    mode_requirements: Mapping[str, tuple[str, ...]]
    maximum_parallel_agents: int
    policy_digest: str


@dataclass(frozen=True)
class ClientCapabilityProfile:
    session_id: str
    client_id: str
    capabilities: Mapping[str, bool]
    max_parallel_agents: int
    selected_mode: str
    policy_digest: str
    profile_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/client-capability-profile.schema.json",
            "schema_version": 1,
            "session_id": self.session_id,
            "client_id": self.client_id,
            "capabilities": dict(sorted(self.capabilities.items())),
            "max_parallel_agents": self.max_parallel_agents,
            "selected_mode": self.selected_mode,
            "policy_digest": self.policy_digest,
            "profile_digest": self.profile_digest,
            "session_bound": True,
            "declaration_grants_authority": False,
            "secret_values_included": False,
            "absolute_paths_included": False,
        }


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ClientCapabilityError(f"{label} is invalid")
    return value


def parse_client_capability_policy(payload: object) -> ClientCapabilityPolicy:
    expected = {
        "schema_ref",
        "schema_version",
        "revision",
        "capabilities",
        "mode_order",
        "mode_requirements",
        "limits",
        "invariants",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ClientCapabilityError("client capability policy fields are invalid")
    if (
        payload.get("schema_ref")
        != "schemas/client-capability-policy.schema.json"
        or payload.get("schema_version") != 1
    ):
        raise ClientCapabilityError("client capability policy schema is invalid")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ClientCapabilityError("client capability policy revision is invalid")
    capabilities = payload.get("capabilities")
    if capabilities != list(CAPABILITY_NAMES):
        raise ClientCapabilityError("client capability catalog is invalid")
    mode_order = payload.get("mode_order")
    if mode_order != list(EXECUTION_MODES):
        raise ClientCapabilityError("client capability mode order is invalid")
    requirements = payload.get("mode_requirements")
    if not isinstance(requirements, dict) or set(requirements) != set(EXECUTION_MODES):
        raise ClientCapabilityError("client capability mode requirements are invalid")
    normalized_requirements: dict[str, tuple[str, ...]] = {}
    for mode in EXECUTION_MODES:
        values = requirements.get(mode)
        if (
            not isinstance(values, list)
            or any(value not in CAPABILITY_NAMES for value in values)
            or len(set(values)) != len(values)
        ):
            raise ClientCapabilityError("client capability mode requirement is invalid")
        normalized_requirements[mode] = tuple(values)
    expected_requirements = {
        "native-parallel": (
            "native_subagents",
            "parallel_subagents",
        ),
        "native-sequential": ("native_subagents",),
        "isolated-role-fallback": (
            "structured_results",
            "isolated_role_execution",
        ),
        "delegation-unavailable": (),
    }
    if normalized_requirements != expected_requirements:
        raise ClientCapabilityError("client capability mode boundary is invalid")
    limits = payload.get("limits")
    maximum = limits.get("maximum_parallel_agents") if isinstance(limits, dict) else None
    if (
        not isinstance(limits, dict)
        or set(limits) != {"maximum_parallel_agents"}
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not 2 <= maximum <= 128
    ):
        raise ClientCapabilityError("client capability limits are invalid")
    if payload.get("invariants") != {
        "session_bound": True,
        "declaration_grants_authority": False,
        "secret_values_persisted": False,
        "absolute_paths_persisted": False,
        "mode_selection_fail_closed": True,
    }:
        raise ClientCapabilityError("client capability invariants are invalid")
    return ClientCapabilityPolicy(
        int(revision),
        tuple(mode_order),
        normalized_requirements,
        int(maximum),
        _digest(payload),
    )


def load_client_capability_policy(repo_root: Path) -> ClientCapabilityPolicy:
    return parse_client_capability_policy(
        load_json(repo_root / "config" / "client-capabilities.json")
    )


def _select_mode(
    policy: ClientCapabilityPolicy,
    capabilities: Mapping[str, bool],
    max_parallel_agents: int,
) -> str:
    for mode in policy.mode_order[:-1]:
        requirements = policy.mode_requirements[mode]
        if not all(capabilities[name] for name in requirements):
            continue
        if mode == "native-parallel" and max_parallel_agents < 2:
            continue
        return mode
    return "delegation-unavailable"


def create_client_capability_profile(
    policy: ClientCapabilityPolicy,
    *,
    session_id: str,
    client_id: str,
    capabilities: Mapping[str, bool],
    max_parallel_agents: int,
) -> ClientCapabilityProfile:
    """Validate one session declaration without converting it into authority."""

    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        raise ClientCapabilityError("session_id is invalid")
    if detect_content_findings(
        session_id,
        "session-id",
        {"github-token", "aws-access-key"},
    ):
        raise ClientCapabilityError("session_id contains secret-like content")
    client_id = _identifier(client_id, "client_id")
    if not isinstance(capabilities, Mapping) or set(capabilities) != set(CAPABILITY_NAMES):
        raise ClientCapabilityError("client capability declaration is incomplete")
    normalized: dict[str, bool] = {}
    for name in CAPABILITY_NAMES:
        value = capabilities[name]
        if not isinstance(value, bool):
            raise ClientCapabilityError("client capability values must be boolean")
        normalized[name] = value
    if (
        not isinstance(max_parallel_agents, int)
        or isinstance(max_parallel_agents, bool)
        or not 1 <= max_parallel_agents <= policy.maximum_parallel_agents
    ):
        raise ClientCapabilityError("max_parallel_agents is invalid")
    if normalized["parallel_subagents"] and not normalized["native_subagents"]:
        raise ClientCapabilityError("parallel subagents require native subagents")
    if normalized["parallel_subagents"] and max_parallel_agents < 2:
        raise ClientCapabilityError("parallel subagents require at least two agent slots")
    if not normalized["parallel_subagents"] and max_parallel_agents != 1:
        raise ClientCapabilityError("non-parallel clients must declare one agent slot")
    selected_mode = _select_mode(policy, normalized, max_parallel_agents)
    digest_payload = {
        "schema_version": 1,
        "session_id": session_id,
        "client_id": client_id,
        "capabilities": dict(sorted(normalized.items())),
        "max_parallel_agents": max_parallel_agents,
        "selected_mode": selected_mode,
        "policy_digest": policy.policy_digest,
    }
    return ClientCapabilityProfile(
        session_id,
        client_id,
        normalized,
        max_parallel_agents,
        selected_mode,
        policy.policy_digest,
        _digest(digest_payload),
    )
