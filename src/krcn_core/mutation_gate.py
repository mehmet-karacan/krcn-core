"""Ownership-aware dry-run and approval gate for mutations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from .foundation import load_json


MutationOperation = Literal["create", "update", "delete", "move"]
OwnershipClass = Literal[
    "core", "runtime", "user-data", "derived", "secrets", "unmanaged"
]
ApprovalScope = Literal[
    "standard",
    "local-observation-reconciliation",
    "verified-work-completion",
]

_LOCAL_RECONCILIATION_TARGETS = (
    re.compile(r"^\.krcn/projects/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/projects/integration-states/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/derived/source-states/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/knowledge/(?:authoritative-sources|records)/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/projects/[a-z][a-z0-9-]*/project\.json$"),
    re.compile(r"^\.krcn/projects/[a-z][a-z0-9-]*/integration/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/projects/[a-z][a-z0-9-]*/derived/source-states/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/projects/[a-z][a-z0-9-]*/knowledge/(?:authoritative-sources|records)/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/global/derived/source-states/[a-z][a-z0-9-]*\.json$"),
)

_VERIFIED_WORK_COMPLETION_TARGETS = (
    re.compile(r"^\.krcn/work-(?:items|events)/[a-z][a-z0-9-]*\.json$"),
    re.compile(r"^\.krcn/projects/[a-z][a-z0-9-]*/work/(?:items|events)/[a-z][a-z0-9-]*\.json$"),
)


class MutationGateError(ValueError):
    """Raised when a mutation does not satisfy its safety gate."""


@dataclass(frozen=True)
class MutationPlan:
    plan_id: str
    operation: MutationOperation
    target_ref: str
    ownership: OwnershipClass
    change_digest: str
    dry_run_required: bool
    approval_required: bool
    reversible: bool
    approval_scope: ApprovalScope = "standard"

    def as_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "operation": self.operation,
            "target_ref": self.target_ref,
            "ownership": self.ownership,
            "change_digest": self.change_digest,
            "dry_run_required": self.dry_run_required,
            "approval_required": self.approval_required,
            "reversible": self.reversible,
        }
        if self.approval_scope != "standard":
            payload["approval_scope"] = self.approval_scope
        return payload


@dataclass(frozen=True)
class DryRunEvidence:
    plan_id: str
    verified: bool


@dataclass(frozen=True)
class ApprovalEvidence:
    plan_id: str
    approval_id: str
    approved: bool


@dataclass(frozen=True)
class MutationAuthorization:
    plan: MutationPlan
    dry_run_verified: bool
    approval_verified: bool


def _portable_target_ref(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationGateError("target reference must be non-empty")
    if "\\" in value:
        raise MutationGateError("target reference must use forward slashes")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).is_absolute() or ".." in path.parts:
        raise MutationGateError("target reference must stay within the repository")
    return path.as_posix()


def _matches(relative_path: str, pattern: str) -> bool:
    expression = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                expression.append(".*")
                index += 2
                continue
            expression.append("[^/]*")
        elif character == "?":
            expression.append("[^/]")
        else:
            expression.append(re.escape(character))
        index += 1
    return re.fullmatch("".join(expression), relative_path) is not None


class OwnershipResolver:
    """Resolve a portable repository reference to one ownership class."""

    def __init__(self, manifest: dict) -> None:
        self._classes = tuple(manifest["classes"])
        self._default = manifest["default_unmatched"]["ownership"]

    @classmethod
    def from_repository(cls, repo_root: Path) -> "OwnershipResolver":
        return cls(load_json(repo_root / "config" / "ownership-manifest.json"))

    def resolve(self, target_ref: str) -> OwnershipClass:
        relative = _portable_target_ref(target_ref)
        matches = [
            item["id"]
            for item in self._classes
            if any(_matches(relative, pattern) for pattern in item["paths"])
        ]
        if len(matches) > 1:
            raise MutationGateError("target matches multiple ownership classes")
        return (matches[0] if matches else self._default)


def plan_mutation(
    resolver: OwnershipResolver,
    *,
    operation: MutationOperation,
    target_ref: str,
    expected_ownership: OwnershipClass | None = None,
    change_digest: str,
    reversible: bool,
    approval_scope: ApprovalScope = "standard",
) -> MutationPlan:
    """Create a deterministic plan before any filesystem mutation."""

    if operation not in {"create", "update", "delete", "move"}:
        raise MutationGateError("mutation operation is invalid")
    if approval_scope not in {
        "standard",
        "local-observation-reconciliation",
    }:
        raise MutationGateError("mutation approval scope is invalid")
    portable_ref = _portable_target_ref(target_ref)
    if not re.fullmatch(r"[a-f0-9]{64}", change_digest):
        raise MutationGateError("change digest must be a SHA-256 value")
    ownership = resolver.resolve(portable_ref)
    if expected_ownership is not None and ownership != expected_ownership:
        raise MutationGateError("resolved ownership does not match the expected class")
    approval_required = ownership in {"user-data", "secrets", "unmanaged"} or operation in {
        "delete",
        "move",
    }
    if approval_scope == "local-observation-reconciliation":
        if operation not in {"create", "update"}:
            raise MutationGateError(
                "local observation reconciliation cannot delete or move data"
            )
        if ownership not in {"user-data", "derived", "runtime"} or not reversible:
            raise MutationGateError(
                "local observation reconciliation must be reversible KRCN-owned state"
            )
        if not any(pattern.fullmatch(portable_ref) for pattern in _LOCAL_RECONCILIATION_TARGETS):
            raise MutationGateError(
                "target is outside local observation reconciliation bookkeeping"
            )
        approval_required = False
    identity = {
        "operation": operation,
        "target_ref": portable_ref,
        "ownership": ownership,
        "change_digest": change_digest,
        "reversible": reversible,
    }
    if approval_scope != "standard":
        identity["approval_scope"] = approval_scope
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MutationPlan(
        plan_id=plan_id,
        operation=operation,
        target_ref=portable_ref,
        ownership=ownership,
        change_digest=change_digest,
        dry_run_required=True,
        approval_required=approval_required,
        reversible=reversible,
        approval_scope=approval_scope,
    )


def plan_verified_work_completion_mutation(
    resolver: OwnershipResolver,
    *,
    operation: MutationOperation,
    target_ref: str,
    expected_ownership: OwnershipClass,
    change_digest: str,
    reversible: bool,
    attestation_digest: str,
) -> MutationPlan:
    """Plan only a proof-bound Work Graph completion record mutation."""

    if operation not in {"create", "update"} or not reversible:
        raise MutationGateError(
            "verified work completion must be a reversible create or update"
        )
    portable_ref = _portable_target_ref(target_ref)
    if (
        expected_ownership != "user-data"
        or resolver.resolve(portable_ref) != "user-data"
        or not any(
            pattern.fullmatch(portable_ref)
            for pattern in _VERIFIED_WORK_COMPLETION_TARGETS
        )
    ):
        raise MutationGateError(
            "target is outside verified work completion records"
        )
    if not re.fullmatch(r"[a-f0-9]{64}", change_digest) or not re.fullmatch(
        r"[a-f0-9]{64}", attestation_digest
    ):
        raise MutationGateError("verified work completion digest is invalid")
    identity = {
        "operation": operation,
        "target_ref": portable_ref,
        "ownership": "user-data",
        "change_digest": change_digest,
        "reversible": True,
        "approval_scope": "verified-work-completion",
        "attestation_digest": attestation_digest,
    }
    plan_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MutationPlan(
        plan_id,
        operation,
        portable_ref,
        "user-data",
        change_digest,
        True,
        False,
        True,
        "verified-work-completion",
    )


def authorize_mutation(
    plan: MutationPlan,
    *,
    dry_run: DryRunEvidence | None,
    approval: ApprovalEvidence | None = None,
) -> MutationAuthorization:
    """Authorize the exact plan only after required evidence is present."""

    if plan.ownership == "secrets":
        raise MutationGateError("direct secret mutation is prohibited")
    if not plan.reversible:
        raise MutationGateError("irreversible mutation is prohibited")
    if dry_run is None or dry_run.plan_id != plan.plan_id or not dry_run.verified:
        raise MutationGateError("verified dry-run evidence is required for this plan")
    approval_verified = False
    if plan.approval_required:
        approval_verified = bool(
            approval
            and approval.approved
            and approval.plan_id == plan.plan_id
            and approval.approval_id.strip()
        )
        if not approval_verified:
            raise MutationGateError("matching user approval evidence is required")
    return MutationAuthorization(
        plan=plan,
        dry_run_verified=True,
        approval_verified=approval_verified,
    )
