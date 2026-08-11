"""Offline-first provider selection and session-scoped remote approval."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .foundation import load_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")


class ProviderGateError(ValueError):
    """Raised when a provider request violates offline-first policy."""


@dataclass(frozen=True)
class ProviderRequest:
    request_id: str
    provider: str
    endpoint: str
    data_categories: tuple[str, ...]
    operation_scope: str
    retention_assumptions: str
    session_id: str
    remote: bool

    def public_summary(self) -> dict[str, object]:
        """Describe approval scope without exposing the endpoint value."""

        return {
            "schema_version": 1,
            "request_id": self.request_id,
            "provider": self.provider,
            "endpoint_disclosed": bool(self.endpoint),
            "data_categories": list(self.data_categories),
            "operation_scope": self.operation_scope,
            "retention_assumptions": self.retention_assumptions,
            "session_id": self.session_id,
            "remote": self.remote,
        }


@dataclass(frozen=True)
class ProviderApproval:
    request_id: str
    session_id: str
    approval_id: str
    approved: bool


@dataclass(frozen=True)
class ProviderAuthorization:
    request: ProviderRequest
    approval_verified: bool


def load_provider_gate_policy(repo_root: Path) -> dict:
    policy = load_json(repo_root / "config" / "provider-policy.json")
    if policy.get("default_mode") != "offline":
        raise ProviderGateError("provider policy must be offline by default")
    if policy.get("implicit_provider_discovery") is not False:
        raise ProviderGateError("implicit provider discovery must remain disabled")
    return policy


def select_default_provider(policy: dict, requested_provider: str | None = None) -> str:
    """Select only an explicit provider or the declared local default."""

    if requested_provider is not None:
        if not IDENTIFIER.fullmatch(requested_provider):
            raise ProviderGateError("provider id must be portable")
        return requested_provider
    local = policy.get("local_providers", {}).get("deterministic_hashing", {})
    if local != {"enabled": True, "data_leaves_device": False}:
        raise ProviderGateError("safe local default provider is unavailable")
    return "deterministic-hashing"


def create_provider_request(
    *,
    provider: str,
    endpoint: str,
    data_categories: tuple[str, ...],
    operation_scope: str,
    retention_assumptions: str,
    session_id: str,
    remote: bool,
) -> ProviderRequest:
    """Create a deterministic approval request with mandatory disclosures."""

    if not IDENTIFIER.fullmatch(provider):
        raise ProviderGateError("provider id must be portable")
    if not endpoint.strip():
        raise ProviderGateError("provider endpoint disclosure is required")
    if not data_categories or any(not IDENTIFIER.fullmatch(item) for item in data_categories):
        raise ProviderGateError("data category disclosures are required")
    if len(set(data_categories)) != len(data_categories):
        raise ProviderGateError("data categories must be unique")
    if not IDENTIFIER.fullmatch(operation_scope):
        raise ProviderGateError("operation scope disclosure is required")
    if not retention_assumptions.strip():
        raise ProviderGateError("retention assumptions disclosure is required")
    if not session_id.strip():
        raise ProviderGateError("session id is required")
    identity = {
        "provider": provider,
        "endpoint": endpoint,
        "data_categories": list(data_categories),
        "operation_scope": operation_scope,
        "retention_assumptions": retention_assumptions,
        "session_id": session_id,
        "remote": remote,
    }
    request_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ProviderRequest(
        request_id=request_id,
        provider=provider,
        endpoint=endpoint,
        data_categories=data_categories,
        operation_scope=operation_scope,
        retention_assumptions=retention_assumptions,
        session_id=session_id,
        remote=remote,
    )


def authorize_provider_request(
    policy: dict,
    request: ProviderRequest,
    *,
    approval: ProviderApproval | None = None,
) -> ProviderAuthorization:
    """Authorize local use or exact session-scoped approval for remote use."""

    if policy.get("default_mode") != "offline":
        raise ProviderGateError("unsafe provider default mode")
    if policy.get("implicit_provider_discovery") is not False:
        raise ProviderGateError("implicit provider discovery is prohibited")
    if not request.remote:
        local = policy.get("local_providers", {}).get("deterministic_hashing", {})
        if request.provider != "deterministic-hashing" or local.get("enabled") is not True:
            raise ProviderGateError("unapproved local provider")
        if local.get("data_leaves_device") is not False:
            raise ProviderGateError("local provider may not transmit data")
        return ProviderAuthorization(request=request, approval_verified=False)

    remote = policy.get("remote_providers", {})
    if remote.get("explicit_opt_in_required") is not True:
        raise ProviderGateError("remote provider policy must require explicit opt-in")
    required_disclosures = set(remote.get("required_disclosures", []))
    if required_disclosures != {
        "provider",
        "endpoint",
        "data_categories",
        "operation_scope",
        "retention_assumptions",
    }:
        raise ProviderGateError("remote provider disclosures are incomplete")
    approved = bool(
        approval
        and approval.approved
        and approval.request_id == request.request_id
        and approval.session_id == request.session_id
        and approval.approval_id.strip()
    )
    if not approved:
        raise ProviderGateError("matching session approval is required")
    return ProviderAuthorization(request=request, approval_verified=True)
