"""Validation and effective evaluation for preserved user policies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SCOPE_KINDS = {"global", "project", "source", "integration"}
EFFECTS = {"allow", "deny", "require-approval"}
PROVENANCE_KINDS = {"explicit-user", "approved-memory", "approved-import"}

PolicyEffect = Literal["allow", "deny", "require-approval"]
PolicyDecisionEffect = Literal["allow", "deny", "require-approval", "not-applicable"]


class UserPolicyError(ValueError):
    """Raised when a preserved user policy is invalid."""


@dataclass(frozen=True)
class PolicyScope:
    kind: str
    ref: str | None


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    resource_type: str
    operations: tuple[str, ...]
    effect: PolicyEffect
    constraints: Mapping[str, object]
    provenance: str
    evidence_ref: str | None
    active: bool


@dataclass(frozen=True)
class UserPolicy:
    policy_id: str
    scope: PolicyScope
    revision: int
    rules: tuple[PolicyRule, ...]


@dataclass(frozen=True)
class PolicyDecision:
    effect: PolicyDecisionEffect
    matched_policy_ids: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]

    @property
    def permitted(self) -> bool:
        return self.effect == "allow"


def _portable_identifier(value: object, label: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        errors.append(f"{label} must be a portable identifier")
        return ""
    return value


def parse_user_policy(payload: object) -> UserPolicy:
    """Validate a user-owned policy record without changing it."""

    if not isinstance(payload, dict):
        raise UserPolicyError("user policy must be an object")
    errors: list[str] = []
    allowed_fields = {
        "schema_version",
        "policy_id",
        "scope",
        "revision",
        "rules",
        "created_at",
        "updated_at",
    }
    extra = set(payload) - allowed_fields
    if extra:
        errors.append("unexpected fields: " + ", ".join(sorted(extra)))
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    policy_id = _portable_identifier(payload.get("policy_id"), "policy_id", errors)

    scope_payload = payload.get("scope")
    scope = PolicyScope("global", None)
    if not isinstance(scope_payload, dict):
        errors.append("scope must be an object")
    else:
        scope_kind = scope_payload.get("kind")
        scope_ref = scope_payload.get("ref")
        if scope_kind not in SCOPE_KINDS:
            errors.append("scope kind is invalid")
        if scope_kind == "global" and scope_ref is not None:
            errors.append("global scope must not contain ref")
        if scope_kind != "global":
            scope_ref = _portable_identifier(scope_ref, "scope ref", errors)
        scope = PolicyScope(str(scope_kind), scope_ref)

    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        errors.append("revision must be a positive integer")

    rules_payload = payload.get("rules")
    rules: list[PolicyRule] = []
    if not isinstance(rules_payload, list) or not rules_payload:
        errors.append("rules must be a non-empty list")
    else:
        seen_rule_ids: set[str] = set()
        for index, rule_payload in enumerate(rules_payload):
            if not isinstance(rule_payload, dict):
                errors.append(f"rules[{index}] must be an object")
                continue
            rule_id = _portable_identifier(
                rule_payload.get("rule_id"), f"rules[{index}].rule_id", errors
            )
            if rule_id in seen_rule_ids:
                errors.append(f"duplicate rule id: {rule_id}")
            seen_rule_ids.add(rule_id)
            resource_type = _portable_identifier(
                rule_payload.get("resource_type"),
                f"rules[{index}].resource_type",
                errors,
            )
            operations_payload = rule_payload.get("operations")
            if not isinstance(operations_payload, list) or not operations_payload:
                errors.append(f"rules[{index}].operations must be a non-empty list")
                operations: tuple[str, ...] = ()
            else:
                operations = tuple(
                    _portable_identifier(item, f"rules[{index}].operation", errors)
                    for item in operations_payload
                )
                if len(set(operations)) != len(operations):
                    errors.append(f"rules[{index}].operations must be unique")
            effect = rule_payload.get("effect")
            if effect not in EFFECTS:
                errors.append(f"rules[{index}].effect is invalid")
            constraints = rule_payload.get("constraints", {})
            if not isinstance(constraints, dict):
                errors.append(f"rules[{index}].constraints must be an object")
                constraints = {}
            provenance = rule_payload.get("provenance")
            provenance_kind = ""
            evidence_ref = None
            if not isinstance(provenance, dict):
                errors.append(f"rules[{index}].provenance must be an object")
            else:
                provenance_kind = provenance.get("kind", "")
                evidence_ref = provenance.get("evidence_ref")
                if provenance_kind not in PROVENANCE_KINDS:
                    errors.append(f"rules[{index}].provenance kind is invalid")
                if evidence_ref is not None and (
                    not isinstance(evidence_ref, str) or not evidence_ref.strip()
                ):
                    errors.append(f"rules[{index}].evidence_ref is invalid")
            active = rule_payload.get("active")
            if not isinstance(active, bool):
                errors.append(f"rules[{index}].active must be boolean")
            rules.append(
                PolicyRule(
                    rule_id=rule_id,
                    resource_type=resource_type,
                    operations=operations,
                    effect=str(effect),
                    constraints=constraints,
                    provenance=provenance_kind,
                    evidence_ref=evidence_ref,
                    active=bool(active),
                )
            )

    if errors:
        raise UserPolicyError("; ".join(errors))
    return UserPolicy(
        policy_id=policy_id,
        scope=scope,
        revision=int(revision),
        rules=tuple(rules),
    )


def load_user_policies(directory: Path) -> tuple[UserPolicy, ...]:
    """Load active policy documents from preserved local user data."""

    if not directory.exists():
        return ()
    policies: list[UserPolicy] = []
    seen_ids: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise UserPolicyError(f"invalid policy JSON: {path.name}: {exc}") from exc
        policy = parse_user_policy(payload)
        if policy.policy_id in seen_ids:
            raise UserPolicyError(f"duplicate policy id: {policy.policy_id}")
        seen_ids.add(policy.policy_id)
        policies.append(policy)
    return tuple(policies)


def _scope_matches(scope: PolicyScope, scope_refs: Mapping[str, str]) -> bool:
    if scope.kind == "global":
        return True
    return scope_refs.get(scope.kind) == scope.ref


def evaluate_policies(
    policies: Sequence[UserPolicy],
    *,
    resource_type: str,
    operation: str,
    scope_refs: Mapping[str, str] | None = None,
) -> PolicyDecision:
    """Evaluate approved policy records with deny-overrides semantics."""

    refs = scope_refs or {}
    matches: list[tuple[UserPolicy, PolicyRule]] = []
    for policy in policies:
        if not _scope_matches(policy.scope, refs):
            continue
        for rule in policy.rules:
            if (
                rule.active
                and rule.resource_type == resource_type
                and operation in rule.operations
            ):
                matches.append((policy, rule))

    effects = {rule.effect for _, rule in matches}
    if "deny" in effects:
        effect: PolicyDecisionEffect = "deny"
    elif "require-approval" in effects:
        effect = "require-approval"
    elif "allow" in effects:
        effect = "allow"
    else:
        effect = "not-applicable"
    return PolicyDecision(
        effect=effect,
        matched_policy_ids=tuple(sorted({policy.policy_id for policy, _ in matches})),
        matched_rule_ids=tuple(sorted({rule.rule_id for _, rule in matches})),
    )
