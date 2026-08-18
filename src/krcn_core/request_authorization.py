"""Request-bound authorization for one explicit local user mutation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from .mutation_gate import MutationPlan


SHA256 = re.compile(r"^[a-f0-9]{64}$")
SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DANGEROUS_PREFIXES = (
    "database.", "deployment.", "release.", "portability.", "research.dispatch",
)
_DANGEROUS_OPERATIONS = {
    "project.rebind", "research.cancel", "runtime.queue.fail",
    "runtime.queue.recover", "runtime.queue.reconcile", "work.import",
    "work.documents.copy-initial", "work.documents.migrate-layout",
}
_EXPLICIT_LOCAL_OPERATIONS = {
    "work.item.put", "client.bootstrap", "implementation.apply",
}
_WORK_ITEM_TARGET = re.compile(
    r"^\.krcn/projects/[a-z][a-z0-9-]*/(?:work/(?:items|events)/[a-z][a-z0-9-]*\.json|derived/(?:retrieval/work-graph-v1\.sqlite|work/WORK-INDEX\.md))$"
)
_CLIENT_BOOTSTRAP_TARGET = re.compile(
    r"^(?:local-client-bootstrap/[a-z][a-z0-9-]*-global-instructions|\.krcn/local-data/client-bootstrap-backups/[a-z][a-z0-9-]*/[a-f0-9]{64}\.md)$"
)
_IMPLEMENTATION_TARGET = re.compile(r"^(?!\.git/|\.github/|\.krcn/)[^/].+$")


class RequestAuthorizationError(ValueError):
    """Raised when current-turn authority does not match the exact local effects."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RequestAuthorizationError("request authorization timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise RequestAuthorizationError("request authorization timestamp needs timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class InitiatingRequestEvidence:
    session_id: str
    intent_request_id: str
    user_turn_digest: str
    source: str
    issued_at: str
    expires_at: str
    evidence_digest: str

    def is_current(self, now: datetime | None = None) -> bool:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return _timestamp(self.issued_at) <= current <= _timestamp(self.expires_at)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/initiating-request-evidence.schema.json",
            "schema_version": 1,
            "session_id": self.session_id,
            "intent_request_id": self.intent_request_id,
            "user_turn_digest": self.user_turn_digest,
            "source": self.source,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "evidence_digest": self.evidence_digest,
        }


def mint_initiating_request_evidence(
    *,
    session_id: str,
    intent_request_id: str,
    user_turn_digest: str,
    source: str,
    now: datetime | None = None,
    lifetime_seconds: int = 300,
) -> InitiatingRequestEvidence:
    if not SESSION.fullmatch(session_id) or not SHA256.fullmatch(intent_request_id):
        raise RequestAuthorizationError("initiating request identity is invalid")
    if not SHA256.fullmatch(user_turn_digest) or source not in {"typed-cli", "trusted-host"}:
        raise RequestAuthorizationError("initiating request proof is invalid")
    if not isinstance(lifetime_seconds, int) or not 1 <= lifetime_seconds <= 900:
        raise RequestAuthorizationError("initiating request lifetime is invalid")
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "schema_ref": "schemas/initiating-request-evidence.schema.json",
        "schema_version": 1,
        "session_id": session_id,
        "intent_request_id": intent_request_id,
        "user_turn_digest": user_turn_digest,
        "source": source,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued + timedelta(seconds=lifetime_seconds)).isoformat().replace("+00:00", "Z"),
    }
    payload["evidence_digest"] = _digest(payload)
    return parse_initiating_request_evidence(payload)


def parse_initiating_request_evidence(value: object) -> InitiatingRequestEvidence:
    fields = {
        "schema_ref", "schema_version", "session_id", "intent_request_id",
        "user_turn_digest", "source", "issued_at", "expires_at", "evidence_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise RequestAuthorizationError("initiating request evidence fields are invalid")
    payload = dict(value)
    if payload["schema_ref"] != "schemas/initiating-request-evidence.schema.json" or payload["schema_version"] != 1:
        raise RequestAuthorizationError("initiating request evidence header is invalid")
    identity = dict(payload)
    digest = identity.pop("evidence_digest")
    if not isinstance(digest, str) or digest != _digest(identity):
        raise RequestAuthorizationError("initiating request evidence digest does not match")
    result = InitiatingRequestEvidence(
        str(payload["session_id"]), str(payload["intent_request_id"]),
        str(payload["user_turn_digest"]), str(payload["source"]),
        str(payload["issued_at"]), str(payload["expires_at"]), digest,
    )
    if not SESSION.fullmatch(result.session_id) or result.source not in {"typed-cli", "trusted-host"}:
        raise RequestAuthorizationError("initiating request evidence identity is invalid")
    if not SHA256.fullmatch(result.intent_request_id) or not SHA256.fullmatch(result.user_turn_digest):
        raise RequestAuthorizationError("initiating request evidence digest field is invalid")
    if _timestamp(result.expires_at) <= _timestamp(result.issued_at):
        raise RequestAuthorizationError("initiating request evidence expiry is invalid")
    return result


@dataclass(frozen=True)
class RequestBoundAuthorization:
    authorization_id: str
    evidence: InitiatingRequestEvidence
    operation: str
    plan_id: str
    project_id: str | None
    target_refs: tuple[str, ...]
    effect_plan_ids: tuple[str, ...]
    scope_digest: str
    effect_digest: str
    effects: tuple[Mapping[str, object], ...]

    def receipt(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "session_id": self.evidence.session_id,
            "intent_request_id": self.evidence.intent_request_id,
            "operation": self.operation,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "scope_digest": self.scope_digest,
            "effect_digest": self.effect_digest,
            "single_use": True,
            "status": "consumed",
        }

    def permits(self, plan: MutationPlan, *, now: datetime | None = None) -> bool:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return bool(
            current <= _timestamp(self.evidence.expires_at)
            and plan.plan_id in self.effect_plan_ids
            and plan.target_ref in self.target_refs
            and plan.operation in {"create", "update"}
            and plan.reversible
            and plan.ownership not in {"secrets"}
        )


def build_consumed_receipt(
    authorization: RequestBoundAuthorization,
    *,
    request_id: str,
    response: Mapping[str, object],
) -> dict[str, object]:
    response_payload = dict(response)
    payload = {
        "schema_ref": "schemas/request-authorization-receipt.schema.json",
        "schema_version": 1,
        "receipt_id": authorization.authorization_id,
        "authorization_id": authorization.authorization_id,
        "request_id": request_id,
        "intent_request_id": authorization.evidence.intent_request_id,
        "session_id": authorization.evidence.session_id,
        "user_turn_digest": authorization.evidence.user_turn_digest,
        "evidence_digest": authorization.evidence.evidence_digest,
        "issued_at": authorization.evidence.issued_at,
        "expires_at": authorization.evidence.expires_at,
        "operation": authorization.operation,
        "project_id": authorization.project_id,
        "plan_id": authorization.plan_id,
        "scope_digest": authorization.scope_digest,
        "effect_digest": authorization.effect_digest,
        "effects": [dict(effect) for effect in authorization.effects],
        "status": "consumed",
        "single_use": True,
        "response": response_payload,
        "result_digest": _digest(response_payload),
    }
    payload["receipt_digest"] = _digest(payload)
    return parse_consumed_receipt(payload)


def build_pending_receipt(
    authorization: RequestBoundAuthorization,
    *,
    request_id: str,
) -> dict[str, object]:
    payload = {
        "schema_ref": "schemas/request-authorization-receipt.schema.json",
        "schema_version": 1,
        "receipt_id": authorization.authorization_id,
        "authorization_id": authorization.authorization_id,
        "request_id": request_id,
        "intent_request_id": authorization.evidence.intent_request_id,
        "session_id": authorization.evidence.session_id,
        "user_turn_digest": authorization.evidence.user_turn_digest,
        "evidence_digest": authorization.evidence.evidence_digest,
        "issued_at": authorization.evidence.issued_at,
        "expires_at": authorization.evidence.expires_at,
        "operation": authorization.operation,
        "project_id": authorization.project_id,
        "plan_id": authorization.plan_id,
        "scope_digest": authorization.scope_digest,
        "effect_digest": authorization.effect_digest,
        "effects": [dict(effect) for effect in authorization.effects],
        "status": "pending",
        "single_use": True,
        "response": None,
        "result_digest": None,
    }
    payload["receipt_digest"] = _digest(payload)
    return parse_consumed_receipt(payload)


def complete_pending_receipt(
    receipt: Mapping[str, object],
    response: Mapping[str, object],
) -> dict[str, object]:
    payload = parse_consumed_receipt(receipt)
    if payload["status"] != "pending":
        raise RequestAuthorizationError("only a pending receipt can be completed")
    payload["status"] = "consumed"
    payload["response"] = dict(response)
    payload["result_digest"] = _digest(payload["response"])
    payload.pop("receipt_digest")
    payload["receipt_digest"] = _digest(payload)
    return parse_consumed_receipt(payload)


def parse_consumed_receipt(value: object) -> dict[str, object]:
    fields = {
        "schema_ref", "schema_version", "receipt_id", "authorization_id",
        "request_id", "intent_request_id", "session_id", "user_turn_digest",
        "evidence_digest", "issued_at", "expires_at",
        "operation", "project_id", "plan_id", "scope_digest", "effect_digest",
        "effects",
        "status", "single_use", "response", "result_digest", "receipt_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise RequestAuthorizationError("request authorization receipt fields are invalid")
    payload = dict(value)
    if (
        payload["schema_ref"] != "schemas/request-authorization-receipt.schema.json"
        or payload["schema_version"] != 1
        or payload["status"] not in {"pending", "consumed"}
        or payload["single_use"] is not True
    ):
        raise RequestAuthorizationError("request authorization receipt state is invalid")
    for field in (
        "request_id", "intent_request_id", "user_turn_digest", "plan_id",
        "scope_digest", "effect_digest", "receipt_digest",
        "evidence_digest",
    ):
        if not isinstance(payload[field], str) or not SHA256.fullmatch(payload[field]):
            raise RequestAuthorizationError("request authorization receipt digest is invalid")
    if (
        not isinstance(payload["receipt_id"], str)
        or payload["receipt_id"] != payload["authorization_id"]
        or not re.fullmatch(r"request-auth-[a-f0-9]{64}", payload["receipt_id"])
        or not SESSION.fullmatch(str(payload["session_id"]))
        or not isinstance(payload["operation"], str)
        or not isinstance(payload["effects"], list)
        or payload["project_id"] is not None and not isinstance(payload["project_id"], str)
    ):
        raise RequestAuthorizationError("request authorization receipt identity is invalid")
    if _timestamp(str(payload["expires_at"])) <= _timestamp(str(payload["issued_at"])):
        raise RequestAuthorizationError("request authorization receipt expiry is invalid")
    if payload["effect_digest"] != _digest(payload["effects"]):
        raise RequestAuthorizationError("request authorization receipt effects changed")
    receipt_digest = payload.pop("receipt_digest")
    payload["receipt_digest"] = receipt_digest
    identity = dict(payload)
    identity.pop("receipt_digest")
    if payload["status"] == "consumed":
        if (
            not isinstance(payload["response"], Mapping)
            or not isinstance(payload["result_digest"], str)
            or not SHA256.fullmatch(payload["result_digest"])
            or payload["result_digest"] != _digest(payload["response"])
        ):
            raise RequestAuthorizationError("consumed authorization result is invalid")
    elif payload["response"] is not None or payload["result_digest"] is not None:
        raise RequestAuthorizationError("pending authorization cannot contain a result")
    if receipt_digest != _digest(identity):
        raise RequestAuthorizationError("request authorization receipt digest does not match")
    return payload


def authorize_explicit_local_request(
    *,
    evidence: InitiatingRequestEvidence,
    intent_request_id: str,
    operation: str,
    plan_id: str,
    project_id: str | None,
    effects: Sequence[MutationPlan],
    now: datetime | None = None,
) -> RequestBoundAuthorization:
    evidence = parse_initiating_request_evidence(evidence.as_dict())
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if evidence.intent_request_id != intent_request_id or not evidence.is_current(current):
        raise RequestAuthorizationError("initiating request is stale or belongs to another request")
    if operation in _DANGEROUS_OPERATIONS or operation.startswith(_DANGEROUS_PREFIXES):
        raise RequestAuthorizationError("operation keeps its explicit dangerous-action gate")
    if operation not in _EXPLICIT_LOCAL_OPERATIONS:
        raise RequestAuthorizationError(
            "operation is outside reviewed explicit local request authorization"
        )
    if not SHA256.fullmatch(plan_id) or not effects:
        raise RequestAuthorizationError("request authorization needs one exact effect plan")
    if any(
        effect.operation not in {"create", "update"}
        or not effect.reversible
        or effect.ownership == "secrets"
        for effect in effects
    ):
        raise RequestAuthorizationError("destructive or secret effects keep their approval gate")
    target_refs = tuple(sorted({effect.target_ref for effect in effects}))
    target_pattern = {
        "work.item.put": _WORK_ITEM_TARGET,
        "client.bootstrap": _CLIENT_BOOTSTRAP_TARGET,
        "implementation.apply": _IMPLEMENTATION_TARGET,
    }[operation]
    if any(not target_pattern.fullmatch(target) for target in target_refs):
        raise RequestAuthorizationError(
            "effect target is outside the reviewed operation scope"
        )
    if operation == "implementation.apply" and len(effects) > 20:
        raise RequestAuthorizationError("bulk implementation keeps its approval gate")
    effect_ids = tuple(sorted({effect.plan_id for effect in effects}))
    project_refs = {
        parts[2]
        for target in target_refs
        if (parts := target.split("/"))[:2] == [".krcn", "projects"] and len(parts) > 2
    }
    if len(project_refs) > 1 or (project_id and project_refs and project_refs != {project_id}):
        raise RequestAuthorizationError("cross-project scope keeps its approval gate")
    scope_digest = _digest(target_refs)
    effect_digest = _digest([
        effect.as_dict() for effect in sorted(effects, key=lambda item: item.plan_id)
    ])
    identity = {
        "evidence_digest": evidence.evidence_digest,
        "operation": operation,
        "plan_id": plan_id,
        "project_id": project_id,
        "target_refs": target_refs,
        "effect_plan_ids": effect_ids,
        "scope_digest": scope_digest,
        "effect_digest": effect_digest,
        "single_use": True,
    }
    effect_summaries = tuple(
        effect.as_dict() for effect in sorted(effects, key=lambda item: item.plan_id)
    )
    return RequestBoundAuthorization(
        "request-auth-" + _digest(identity), evidence, operation, plan_id, project_id,
        target_refs, effect_ids, scope_digest, effect_digest, effect_summaries,
    )
