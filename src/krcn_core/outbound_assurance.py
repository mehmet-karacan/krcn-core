"""Content-free provider assurance and outbound data decisions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .foundation import load_json
from .json_documents import canonical_json_bytes
from .provider_gate import ProviderAuthorization


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
PORTABLE_REF = re.compile(r"^[a-z][a-z0-9-]*:[a-zA-Z0-9][a-zA-Z0-9._/@-]*$")
CATEGORIES = {"public", "internal", "confidential-ip", "secret"}


class OutboundAssuranceError(ValueError):
    """Raised when an assurance or outbound record is unsafe."""


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OutboundAssuranceError(f"{label} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise OutboundAssuranceError(f"{label} is invalid") from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise OutboundAssuranceError(f"{label} must be second precision UTC")
    return parsed


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _exact(payload: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(payload) != fields:
        raise OutboundAssuranceError(f"{label} fields are invalid")


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise OutboundAssuranceError(f"{label} must be portable")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise OutboundAssuranceError(f"{label} must be a SHA-256 digest")
    return value


@dataclass(frozen=True)
class SecretBrokerRef:
    broker_ref_id: str
    broker_id: str
    secret_ref: str
    operation_scope: str
    expires_at: str
    ref_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/secret-broker-ref.schema.json",
            "schema_version": 1,
            "broker_ref_id": self.broker_ref_id,
            "broker_id": self.broker_id,
            "secret_ref": self.secret_ref,
            "operation_scope": self.operation_scope,
            "expires_at": self.expires_at,
            "contains_secret_value": False,
            "grants_authority": False,
            "ref_digest": self.ref_digest,
        }


@dataclass(frozen=True)
class ProviderAssuranceProfile:
    profile_id: str
    provider_id: str
    observed_at: str
    valid_until: str
    accepted_categories: tuple[str, ...]
    retention_class: str
    training_opt_out_verified: bool
    regional_processing_verified: bool
    canary_credential_test_passed: bool
    evidence_ref: str
    evidence_digest: str
    profile_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/provider-assurance-profile.schema.json",
            "schema_version": 1,
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
            "accepted_categories": list(self.accepted_categories),
            "retention_class": self.retention_class,
            "training_opt_out_verified": self.training_opt_out_verified,
            "regional_processing_verified": self.regional_processing_verified,
            "canary_credential_test_passed": self.canary_credential_test_passed,
            "evidence_ref": self.evidence_ref,
            "evidence_digest": self.evidence_digest,
            "contains_payload": False,
            "grants_authority": False,
            "profile_digest": self.profile_digest,
        }


@dataclass(frozen=True)
class OutboundDataDecision:
    decision_id: str
    provider_request_id: str
    provider_id: str
    payload_digest: str
    data_categories: tuple[str, ...]
    assurance_profile_id: str | None
    assurance_profile_digest: str | None
    evaluated_at: str
    verdict: str
    reason_codes: tuple[str, ...]
    decision_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/outbound-data-decision.schema.json",
            "schema_version": 1,
            "decision_id": self.decision_id,
            "provider_request_id": self.provider_request_id,
            "provider_id": self.provider_id,
            "payload_digest": self.payload_digest,
            "data_categories": list(self.data_categories),
            "assurance_profile_id": self.assurance_profile_id,
            "assurance_profile_digest": self.assurance_profile_digest,
            "evaluated_at": self.evaluated_at,
            "verdict": self.verdict,
            "reason_codes": list(self.reason_codes),
            "contains_payload": False,
            "grants_authority": False,
            "decision_digest": self.decision_digest,
        }


def load_outbound_assurance_policy(repo_root: Path) -> dict[str, object]:
    payload = load_json(repo_root / "config" / "outbound-assurance.json")
    required = {
        "schema_version",
        "default_action",
        "classifications",
        "assurance_required_for",
        "maximum_assurance_age_seconds",
        "secret_remote_action",
        "canary_required",
    }
    _exact(payload, required, "outbound assurance policy")
    if payload["schema_version"] != 1 or payload["default_action"] != "deny":
        raise OutboundAssuranceError("outbound policy must default deny")
    if set(payload["classifications"]) != CATEGORIES:
        raise OutboundAssuranceError("outbound classifications are incomplete")
    if payload["secret_remote_action"] != "deny":
        raise OutboundAssuranceError("secret remote action must remain deny")
    if payload["canary_required"] is not True:
        raise OutboundAssuranceError("provider canary must be required")
    maximum = payload["maximum_assurance_age_seconds"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise OutboundAssuranceError("assurance freshness limit is invalid")
    required_for = payload["assurance_required_for"]
    if not isinstance(required_for, list) or set(required_for) != {
        "internal",
        "confidential-ip",
    }:
        raise OutboundAssuranceError("assurance-required categories are invalid")
    return payload


def create_secret_broker_ref(
    *, broker_id: str, secret_ref: str, operation_scope: str, expires_at: str
) -> SecretBrokerRef:
    broker_id = _identifier(broker_id, "broker id")
    operation_scope = _identifier(operation_scope, "operation scope")
    if not isinstance(secret_ref, str) or not PORTABLE_REF.fullmatch(secret_ref):
        raise OutboundAssuranceError("secret ref must be logical and portable")
    _time(expires_at, "secret ref expiry")
    identity = {
        "broker_id": broker_id,
        "secret_ref": secret_ref,
        "operation_scope": operation_scope,
        "expires_at": expires_at,
    }
    digest = _digest(identity)
    return SecretBrokerRef(digest, broker_id, secret_ref, operation_scope, expires_at, digest)


def parse_secret_broker_ref(payload: Mapping[str, object]) -> SecretBrokerRef:
    fields = {
        "schema_ref", "schema_version", "broker_ref_id", "broker_id",
        "secret_ref", "operation_scope", "expires_at", "contains_secret_value",
        "grants_authority", "ref_digest",
    }
    _exact(payload, fields, "secret broker ref")
    if payload["schema_ref"] != "schemas/secret-broker-ref.schema.json" or payload["schema_version"] != 1:
        raise OutboundAssuranceError("secret broker schema identity is invalid")
    if payload["contains_secret_value"] is not False or payload["grants_authority"] is not False:
        raise OutboundAssuranceError("secret broker ref may not contain authority or values")
    record = create_secret_broker_ref(
        broker_id=str(payload["broker_id"]),
        secret_ref=str(payload["secret_ref"]),
        operation_scope=str(payload["operation_scope"]),
        expires_at=str(payload["expires_at"]),
    )
    if payload["broker_ref_id"] != record.broker_ref_id or payload["ref_digest"] != record.ref_digest:
        raise OutboundAssuranceError("secret broker ref digest is invalid")
    return record


def create_provider_assurance_profile(
    *,
    profile_id: str,
    provider_id: str,
    observed_at: str,
    valid_until: str,
    accepted_categories: Sequence[str],
    retention_class: str,
    training_opt_out_verified: bool,
    regional_processing_verified: bool,
    canary_credential_test_passed: bool,
    evidence_ref: str,
    evidence_digest: str,
) -> ProviderAssuranceProfile:
    profile_id = _identifier(profile_id, "profile id")
    provider_id = _identifier(provider_id, "provider id")
    retention_class = _identifier(retention_class, "retention class")
    observed = _time(observed_at, "observed at")
    valid = _time(valid_until, "valid until")
    if valid <= observed:
        raise OutboundAssuranceError("assurance validity must follow observation")
    categories = tuple(sorted(accepted_categories))
    if not categories or len(set(categories)) != len(categories) or not set(categories) <= CATEGORIES - {"secret"}:
        raise OutboundAssuranceError("assurance categories are invalid")
    if not isinstance(evidence_ref, str) or not PORTABLE_REF.fullmatch(evidence_ref):
        raise OutboundAssuranceError("assurance evidence ref must be logical")
    evidence_digest = _sha(evidence_digest, "evidence digest")
    for value, label in (
        (training_opt_out_verified, "training opt-out"),
        (regional_processing_verified, "regional processing"),
        (canary_credential_test_passed, "canary test"),
    ):
        if not isinstance(value, bool):
            raise OutboundAssuranceError(f"{label} must be boolean")
    identity = {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "observed_at": observed_at,
        "valid_until": valid_until,
        "accepted_categories": list(categories),
        "retention_class": retention_class,
        "training_opt_out_verified": training_opt_out_verified,
        "regional_processing_verified": regional_processing_verified,
        "canary_credential_test_passed": canary_credential_test_passed,
        "evidence_ref": evidence_ref,
        "evidence_digest": evidence_digest,
        "contains_payload": False,
        "grants_authority": False,
    }
    return ProviderAssuranceProfile(
        profile_id, provider_id, observed_at, valid_until, categories,
        retention_class, training_opt_out_verified, regional_processing_verified,
        canary_credential_test_passed, evidence_ref, evidence_digest, _digest(identity),
    )


def parse_provider_assurance_profile(payload: Mapping[str, object]) -> ProviderAssuranceProfile:
    fields = {
        "schema_ref", "schema_version", "profile_id", "provider_id",
        "observed_at", "valid_until", "accepted_categories", "retention_class",
        "training_opt_out_verified", "regional_processing_verified",
        "canary_credential_test_passed", "evidence_ref", "evidence_digest",
        "contains_payload", "grants_authority", "profile_digest",
    }
    _exact(payload, fields, "provider assurance profile")
    if payload["schema_ref"] != "schemas/provider-assurance-profile.schema.json" or payload["schema_version"] != 1:
        raise OutboundAssuranceError("provider assurance schema identity is invalid")
    if payload["contains_payload"] is not False or payload["grants_authority"] is not False:
        raise OutboundAssuranceError("provider assurance may not contain payload or authority")
    categories = payload["accepted_categories"]
    if not isinstance(categories, list):
        raise OutboundAssuranceError("accepted categories must be a list")
    record = create_provider_assurance_profile(
        profile_id=str(payload["profile_id"]), provider_id=str(payload["provider_id"]),
        observed_at=str(payload["observed_at"]), valid_until=str(payload["valid_until"]),
        accepted_categories=[str(item) for item in categories],
        retention_class=str(payload["retention_class"]),
        training_opt_out_verified=payload["training_opt_out_verified"],
        regional_processing_verified=payload["regional_processing_verified"],
        canary_credential_test_passed=payload["canary_credential_test_passed"],
        evidence_ref=str(payload["evidence_ref"]), evidence_digest=str(payload["evidence_digest"]),
    )
    if payload["profile_digest"] != record.profile_digest:
        raise OutboundAssuranceError("provider assurance digest is invalid")
    return record


def decide_outbound_data(
    policy: Mapping[str, object],
    authorization: ProviderAuthorization,
    *,
    payload_digest: str,
    data_categories: Sequence[str],
    evaluated_at: str,
    assurance: ProviderAssuranceProfile | None = None,
) -> OutboundDataDecision:
    if policy.get("default_action") != "deny" or policy.get("secret_remote_action") != "deny":
        raise OutboundAssuranceError("unsafe outbound policy")
    payload_digest = _sha(payload_digest, "payload digest")
    now = _time(evaluated_at, "evaluated at")
    categories = tuple(sorted(data_categories))
    if not categories or len(set(categories)) != len(categories) or not set(categories) <= CATEGORIES:
        raise OutboundAssuranceError("outbound data categories are invalid")
    request = authorization.request
    if tuple(sorted(request.data_categories)) != categories:
        raise OutboundAssuranceError("outbound categories do not match ProviderRequest")

    reasons: list[str] = []
    if not request.remote:
        verdict = "allowed-local"
        reasons.append("data-does-not-leave-device")
    elif "secret" in categories:
        verdict = "blocked"
        reasons.append("secret-remote-prohibited")
    elif not authorization.approval_verified:
        verdict = "blocked"
        reasons.append("provider-authorization-required")
    else:
        assurance_required = bool(set(categories) & set(policy["assurance_required_for"]))
        if assurance_required and assurance is None:
            reasons.append("provider-assurance-required")
        elif assurance is not None:
            maximum = int(policy["maximum_assurance_age_seconds"])
            observed = _time(assurance.observed_at, "assurance observed at")
            valid = _time(assurance.valid_until, "assurance valid until")
            if assurance.provider_id != request.provider:
                reasons.append("provider-assurance-mismatch")
            if not (observed <= now <= valid) or (now - observed).total_seconds() > maximum:
                reasons.append("provider-assurance-stale")
            if not set(categories) <= set(assurance.accepted_categories):
                reasons.append("data-category-not-assured")
            if policy.get("canary_required") is True and not assurance.canary_credential_test_passed:
                reasons.append("provider-canary-failed")
            if "confidential-ip" in categories and not (
                assurance.training_opt_out_verified and assurance.regional_processing_verified
            ):
                reasons.append("confidential-controls-unverified")
        verdict = "blocked" if reasons else "allowed-remote"
        if not reasons:
            reasons.append("assurance-and-provider-authorization-verified")

    profile_id = assurance.profile_id if assurance else None
    profile_digest = assurance.profile_digest if assurance else None
    identity = {
        "provider_request_id": request.request_id,
        "provider_id": request.provider,
        "payload_digest": payload_digest,
        "data_categories": list(categories),
        "assurance_profile_id": profile_id,
        "assurance_profile_digest": profile_digest,
        "evaluated_at": evaluated_at,
        "verdict": verdict,
        "reason_codes": reasons,
        "contains_payload": False,
        "grants_authority": False,
    }
    digest = _digest(identity)
    return OutboundDataDecision(
        digest, request.request_id, request.provider, payload_digest, categories,
        profile_id, profile_digest, evaluated_at, verdict, tuple(reasons), digest,
    )


def parse_outbound_data_decision(payload: Mapping[str, object]) -> OutboundDataDecision:
    fields = {
        "schema_ref", "schema_version", "decision_id", "provider_request_id",
        "provider_id", "payload_digest", "data_categories", "assurance_profile_id",
        "assurance_profile_digest", "evaluated_at", "verdict", "reason_codes",
        "contains_payload", "grants_authority", "decision_digest",
    }
    _exact(payload, fields, "outbound data decision")
    if payload["schema_ref"] != "schemas/outbound-data-decision.schema.json" or payload["schema_version"] != 1:
        raise OutboundAssuranceError("outbound decision schema identity is invalid")
    if payload["contains_payload"] is not False or payload["grants_authority"] is not False:
        raise OutboundAssuranceError("outbound decision may not contain payload or authority")
    _identifier(payload["provider_id"], "provider id")
    _sha(payload["provider_request_id"], "provider request id")
    _sha(payload["payload_digest"], "payload digest")
    _time(payload["evaluated_at"], "evaluated at")
    categories = payload["data_categories"]
    reasons = payload["reason_codes"]
    if not isinstance(categories, list) or not categories or set(categories) - CATEGORIES:
        raise OutboundAssuranceError("outbound decision categories are invalid")
    if categories != sorted(set(categories)):
        raise OutboundAssuranceError("outbound decision categories must be canonical")
    if not isinstance(reasons, list) or not reasons or any(not IDENTIFIER.fullmatch(str(item)) for item in reasons):
        raise OutboundAssuranceError("outbound reason codes are invalid")
    if payload["verdict"] not in {"allowed-local", "allowed-remote", "blocked"}:
        raise OutboundAssuranceError("outbound verdict is invalid")
    profile_id = payload["assurance_profile_id"]
    profile_digest = payload["assurance_profile_digest"]
    if (profile_id is None) != (profile_digest is None):
        raise OutboundAssuranceError("assurance identity must be complete")
    if profile_id is not None:
        _identifier(profile_id, "assurance profile id")
        _sha(profile_digest, "assurance profile digest")
    identity = {key: payload[key] for key in fields - {"schema_ref", "schema_version", "decision_id", "decision_digest"}}
    digest = _digest(identity)
    if payload["decision_id"] != digest or payload["decision_digest"] != digest:
        raise OutboundAssuranceError("outbound decision digest is invalid")
    return OutboundDataDecision(
        digest, str(payload["provider_request_id"]), str(payload["provider_id"]),
        str(payload["payload_digest"]), tuple(str(item) for item in categories),
        None if profile_id is None else str(profile_id),
        None if profile_digest is None else str(profile_digest),
        str(payload["evaluated_at"]), str(payload["verdict"]),
        tuple(str(item) for item in reasons), digest,
    )

