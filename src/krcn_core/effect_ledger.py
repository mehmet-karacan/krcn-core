"""Immutable effect claim, terminal receipt, and reconciliation contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from .json_documents import canonical_json_bytes
from .validation_gate import ValidationGate, parse_validation_gate


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
CODE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EFFECT_TYPES = {"write", "execute", "network"}
OUTCOMES = {"completed", "failed", "denied", "timed-out", "uncertain"}
RETRY_SAFETY = {"replay-safe", "reconciliation-required", "non-replayable"}
RECONCILIATION_OUTCOMES = {"effect-confirmed", "effect-not-applied", "effect-state-unknown"}
EVIDENCE_TYPES = {"artifact-digest", "policy-decision", "provider-receipt", "state-observation", "test-result"}


class EffectLedgerError(ValueError):
    """Raised when an effect ledger contract is unsafe or tampered."""


@dataclass(frozen=True)
class EffectClaim:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))

    @property
    def claim_id(self) -> str:
        return str(self.payload["claim_id"])


@dataclass(frozen=True)
class EffectReceipt:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))

    @property
    def receipt_id(self) -> str:
        return str(self.payload["receipt_id"])


@dataclass(frozen=True)
class EffectReconciliation:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))


def _strict(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise EffectLedgerError(f"{label} fields are invalid")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise EffectLedgerError(f"{label} is invalid")
    return value


def _sha(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise EffectLedgerError(f"{label} is invalid")
    return value


def _positive(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EffectLedgerError(f"{label} is invalid")
    return value


def _time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EffectLedgerError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EffectLedgerError(f"{label} is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise EffectLedgerError(f"{label} must use UTC")
    if parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise EffectLedgerError(f"{label} is not canonical")
    return parsed


def _digest(payload: Mapping[str, object], identity_field: str, digest_field: str) -> str:
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    normalized[identity_field] = ""
    normalized[digest_field] = ""
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def build_effect_claim(
    *,
    project_id: str,
    work_item_id: str,
    task_id: str,
    task_plan_id: str,
    step_id: str,
    queue_id: str,
    attempt_id: str,
    attempt_number: int,
    execution_identity_id: str,
    lease_id: str,
    fencing_token: int,
    effect_id: str,
    effect_type: str,
    effect_digest: str,
    idempotency_key: str,
    effect_authorization_id: str,
    validation_gate: ValidationGate | Mapping[str, object],
    host_digest: str,
    claimed_at: str,
    mutation_plan_id: str | None = None,
    provider_request_id: str | None = None,
) -> EffectClaim:
    gate = parse_validation_gate(validation_gate.as_dict() if isinstance(validation_gate, ValidationGate) else validation_gate)
    payload: dict[str, object] = {
        "schema_ref": "schemas/effect-claim.schema.json",
        "schema_version": 1,
        "claim_id": "",
        "bindings": {
            "project_id": project_id, "work_item_id": work_item_id, "task_id": task_id,
            "task_plan_id": task_plan_id, "step_id": step_id, "queue_id": queue_id,
            "attempt_id": attempt_id, "attempt_number": attempt_number,
            "execution_identity_id": execution_identity_id, "lease_id": lease_id,
            "fencing_token": fencing_token,
        },
        "effect": {
            "effect_id": effect_id, "effect_type": effect_type,
            "effect_digest": effect_digest, "idempotency_key": idempotency_key,
            "effect_authorization_id": effect_authorization_id,
            "mutation_plan_id": mutation_plan_id, "provider_request_id": provider_request_id,
        },
        "validation_gate_id": gate.validation_gate_id,
        "runtime": {"host_digest": host_digest, "claimed_at": claimed_at},
        "safety": {
            "grants_authority": False, "effect_performed": False,
            "contains_raw_payload": False, "contains_physical_paths": False,
            "contains_credentials": False,
        },
        "claim_digest": "",
    }
    digest = _digest(payload, "claim_id", "claim_digest")
    payload["claim_id"] = digest
    payload["claim_digest"] = digest
    return parse_effect_claim(payload, validation_gate=gate)


def parse_effect_claim(payload: object, *, validation_gate: ValidationGate | Mapping[str, object] | None = None) -> EffectClaim:
    data = _strict(payload, {"schema_ref", "schema_version", "claim_id", "bindings", "effect", "validation_gate_id", "runtime", "safety", "claim_digest"}, "effect claim")
    if data["schema_ref"] != "schemas/effect-claim.schema.json" or data["schema_version"] != 1:
        raise EffectLedgerError("effect claim contract is invalid")
    bindings = _strict(data["bindings"], {"project_id", "work_item_id", "task_id", "task_plan_id", "step_id", "queue_id", "attempt_id", "attempt_number", "execution_identity_id", "lease_id", "fencing_token"}, "effect claim bindings")
    for field in ("project_id", "work_item_id", "task_id", "step_id", "queue_id", "attempt_id", "lease_id"):
        _id(bindings[field], field.replace("_", " "))
    for field in ("task_plan_id", "execution_identity_id"):
        _sha(bindings[field], field.replace("_", " "))
    _positive(bindings["attempt_number"], "attempt number")
    _positive(bindings["fencing_token"], "fencing token")
    effect = _strict(data["effect"], {"effect_id", "effect_type", "effect_digest", "idempotency_key", "effect_authorization_id", "mutation_plan_id", "provider_request_id"}, "effect claim effect")
    _id(effect["effect_id"], "effect id")
    if effect["effect_type"] not in EFFECT_TYPES:
        raise EffectLedgerError("effect claim type is invalid")
    for field in ("effect_digest", "idempotency_key", "effect_authorization_id"):
        _sha(effect[field], field.replace("_", " "))
    mutation = _sha(effect["mutation_plan_id"], "mutation plan id", nullable=True)
    provider = _sha(effect["provider_request_id"], "provider request id", nullable=True)
    if effect["effect_type"] == "write" and mutation is None:
        raise EffectLedgerError("write effect claim requires mutation plan")
    if effect["effect_type"] == "network" and provider is None:
        raise EffectLedgerError("network effect claim requires provider request")
    _sha(data["validation_gate_id"], "validation gate id")
    runtime = _strict(data["runtime"], {"host_digest", "claimed_at"}, "effect claim runtime")
    _sha(runtime["host_digest"], "host digest")
    _time(runtime["claimed_at"], "claimed at")
    safety = _strict(data["safety"], {"grants_authority", "effect_performed", "contains_raw_payload", "contains_physical_paths", "contains_credentials"}, "effect claim safety")
    if any(value is not False for value in safety.values()):
        raise EffectLedgerError("effect claim safety is invalid")
    if validation_gate is not None:
        gate = parse_validation_gate(validation_gate.as_dict() if isinstance(validation_gate, ValidationGate) else validation_gate)
        gate_bindings = gate.payload["bindings"]
        gate_auth = gate.payload["authorization_bindings"]
        if (
            data["validation_gate_id"] != gate.validation_gate_id
            or bindings["project_id"] != gate_bindings["project_id"]
            or bindings["work_item_id"] != gate_bindings["work_item_id"]
            or bindings["task_id"] != gate_bindings["task_id"]
            or bindings["task_plan_id"] != gate_bindings["task_plan_id"]
            or bindings["step_id"] != gate_bindings["worker_step_id"]
            or bindings["execution_identity_id"] != gate_bindings["worker_execution_identity_id"]
            or effect["effect_id"] != gate_bindings["effect_id"]
            or effect["effect_type"] != gate_bindings["effect_type"]
            or effect["effect_digest"] != gate_bindings["effect_digest"]
            or effect["effect_authorization_id"] != gate_bindings["effect_authorization_id"]
            or mutation != gate_auth["mutation_plan_id"]
            or provider != gate_auth["provider_request_id"]
        ):
            raise EffectLedgerError("effect claim does not match validation gate")
    expected = _digest(data, "claim_id", "claim_digest")
    if data["claim_id"] != expected or data["claim_digest"] != expected:
        raise EffectLedgerError("effect claim digest is invalid")
    return EffectClaim(data)


def build_effect_receipt(
    *,
    claim: EffectClaim | Mapping[str, object],
    outcome: str,
    retry_safety: str,
    finished_at: str,
    observed_fencing_token: int,
    result_digest: str | None = None,
    failure_category: str | None = None,
    failure_digest: str | None = None,
) -> EffectReceipt:
    checked = parse_effect_claim(claim.as_dict() if isinstance(claim, EffectClaim) else claim)
    payload: dict[str, object] = {
        "schema_ref": "schemas/effect-receipt.schema.json", "schema_version": 1,
        "receipt_id": "", "claim_id": checked.claim_id,
        "effect_id": checked.payload["effect"]["effect_id"],
        "effect_digest": checked.payload["effect"]["effect_digest"],
        "idempotency_key": checked.payload["effect"]["idempotency_key"],
        "lease": {"lease_id": checked.payload["bindings"]["lease_id"], "fencing_token": observed_fencing_token},
        "outcome": {"status": outcome, "result_digest": result_digest, "failure_category": failure_category, "failure_digest": failure_digest, "retry_safety": retry_safety},
        "finished_at": finished_at,
        "safety": {"grants_authority": False, "terminal_for_claim": True, "contains_raw_payload": False, "contains_physical_paths": False, "contains_credentials": False},
        "receipt_digest": "",
    }
    digest = _digest(payload, "receipt_id", "receipt_digest")
    payload["receipt_id"] = digest
    payload["receipt_digest"] = digest
    return parse_effect_receipt(payload, claim=checked)


def parse_effect_receipt(payload: object, *, claim: EffectClaim | Mapping[str, object] | None = None) -> EffectReceipt:
    data = _strict(payload, {"schema_ref", "schema_version", "receipt_id", "claim_id", "effect_id", "effect_digest", "idempotency_key", "lease", "outcome", "finished_at", "safety", "receipt_digest"}, "effect receipt")
    if data["schema_ref"] != "schemas/effect-receipt.schema.json" or data["schema_version"] != 1:
        raise EffectLedgerError("effect receipt contract is invalid")
    for field in ("receipt_id", "claim_id", "effect_digest", "idempotency_key", "receipt_digest"):
        _sha(data[field], field.replace("_", " "))
    _id(data["effect_id"], "effect id")
    lease = _strict(data["lease"], {"lease_id", "fencing_token"}, "effect receipt lease")
    _id(lease["lease_id"], "lease id")
    _positive(lease["fencing_token"], "fencing token")
    outcome = _strict(data["outcome"], {"status", "result_digest", "failure_category", "failure_digest", "retry_safety"}, "effect receipt outcome")
    if outcome["status"] not in OUTCOMES or outcome["retry_safety"] not in RETRY_SAFETY:
        raise EffectLedgerError("effect receipt outcome is invalid")
    result = _sha(outcome["result_digest"], "result digest", nullable=True)
    failure = _sha(outcome["failure_digest"], "failure digest", nullable=True)
    category = outcome["failure_category"]
    if category is not None and (not isinstance(category, str) or not CODE.fullmatch(category)):
        raise EffectLedgerError("failure category is invalid")
    if outcome["status"] == "completed":
        if result is None or category is not None or failure is not None or outcome["retry_safety"] != "non-replayable":
            raise EffectLedgerError("completed receipt outcome is invalid")
    elif result is not None or category is None or failure is None:
        raise EffectLedgerError("non-completed receipt outcome is invalid")
    if outcome["status"] == "uncertain" and outcome["retry_safety"] != "reconciliation-required":
        raise EffectLedgerError("uncertain receipt requires reconciliation")
    finished = _time(data["finished_at"], "finished at")
    safety = _strict(data["safety"], {"grants_authority", "terminal_for_claim", "contains_raw_payload", "contains_physical_paths", "contains_credentials"}, "effect receipt safety")
    if safety["terminal_for_claim"] is not True or any(safety[key] is not False for key in safety if key != "terminal_for_claim"):
        raise EffectLedgerError("effect receipt safety is invalid")
    if claim is not None:
        checked = parse_effect_claim(claim.as_dict() if isinstance(claim, EffectClaim) else claim)
        if (
            data["claim_id"] != checked.claim_id or data["effect_id"] != checked.payload["effect"]["effect_id"]
            or data["effect_digest"] != checked.payload["effect"]["effect_digest"]
            or data["idempotency_key"] != checked.payload["effect"]["idempotency_key"]
            or lease["lease_id"] != checked.payload["bindings"]["lease_id"]
        ):
            raise EffectLedgerError("effect receipt does not match claim")
        if lease["fencing_token"] != checked.payload["bindings"]["fencing_token"]:
            raise EffectLedgerError("effect receipt fencing token is stale")
        if finished < _time(checked.payload["runtime"]["claimed_at"], "claimed at"):
            raise EffectLedgerError("effect receipt predates claim")
    expected = _digest(data, "receipt_id", "receipt_digest")
    if data["receipt_id"] != expected or data["receipt_digest"] != expected:
        raise EffectLedgerError("effect receipt digest is invalid")
    return EffectReceipt(data)


def build_effect_reconciliation(
    *,
    claim: EffectClaim | Mapping[str, object],
    receipt: EffectReceipt | Mapping[str, object] | None,
    outcome: str,
    evidence: Sequence[Mapping[str, object]],
    reconciler_execution_identity_id: str,
    observed_at: str,
) -> EffectReconciliation:
    checked_claim = parse_effect_claim(claim.as_dict() if isinstance(claim, EffectClaim) else claim)
    checked_receipt = None if receipt is None else parse_effect_receipt(receipt.as_dict() if isinstance(receipt, EffectReceipt) else receipt, claim=checked_claim)
    payload: dict[str, object] = {
        "schema_ref": "schemas/effect-reconciliation.schema.json", "schema_version": 1,
        "reconciliation_id": "", "claim_id": checked_claim.claim_id,
        "receipt_id": None if checked_receipt is None else checked_receipt.receipt_id,
        "outcome": outcome, "evidence": sorted((dict(item) for item in evidence), key=lambda item: (str(item.get("evidence_type")), str(item.get("evidence_digest")))),
        "reconciler_execution_identity_id": reconciler_execution_identity_id,
        "observed_at": observed_at,
        "safety": {"grants_authority": False, "permits_implicit_replay": False, "contains_raw_payload": False, "contains_physical_paths": False, "contains_credentials": False},
        "reconciliation_digest": "",
    }
    digest = _digest(payload, "reconciliation_id", "reconciliation_digest")
    payload["reconciliation_id"] = digest
    payload["reconciliation_digest"] = digest
    return parse_effect_reconciliation(payload, claim=checked_claim, receipt=checked_receipt)


def parse_effect_reconciliation(payload: object, *, claim: EffectClaim | Mapping[str, object] | None = None, receipt: EffectReceipt | Mapping[str, object] | None = None) -> EffectReconciliation:
    data = _strict(payload, {"schema_ref", "schema_version", "reconciliation_id", "claim_id", "receipt_id", "outcome", "evidence", "reconciler_execution_identity_id", "observed_at", "safety", "reconciliation_digest"}, "effect reconciliation")
    if data["schema_ref"] != "schemas/effect-reconciliation.schema.json" or data["schema_version"] != 1:
        raise EffectLedgerError("effect reconciliation contract is invalid")
    for field in ("reconciliation_id", "claim_id", "reconciler_execution_identity_id", "reconciliation_digest"):
        _sha(data[field], field.replace("_", " "))
    receipt_id = _sha(data["receipt_id"], "receipt id", nullable=True)
    if data["outcome"] not in RECONCILIATION_OUTCOMES:
        raise EffectLedgerError("effect reconciliation outcome is invalid")
    evidence = data["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise EffectLedgerError("effect reconciliation evidence is invalid")
    normalized = []
    for item in evidence:
        entry = _strict(item, {"evidence_type", "evidence_digest"}, "effect reconciliation evidence")
        if entry["evidence_type"] not in EVIDENCE_TYPES:
            raise EffectLedgerError("effect reconciliation evidence type is invalid")
        _sha(entry["evidence_digest"], "reconciliation evidence digest")
        normalized.append(entry)
    if evidence != sorted(normalized, key=lambda item: (item["evidence_type"], item["evidence_digest"])) or len({(item["evidence_type"], item["evidence_digest"]) for item in evidence}) != len(evidence):
        raise EffectLedgerError("effect reconciliation evidence is not canonical")
    _time(data["observed_at"], "reconciliation observed at")
    safety = _strict(data["safety"], {"grants_authority", "permits_implicit_replay", "contains_raw_payload", "contains_physical_paths", "contains_credentials"}, "effect reconciliation safety")
    if any(value is not False for value in safety.values()):
        raise EffectLedgerError("effect reconciliation safety is invalid")
    checked_claim = None if claim is None else parse_effect_claim(claim.as_dict() if isinstance(claim, EffectClaim) else claim)
    checked_receipt = None if receipt is None else parse_effect_receipt(receipt.as_dict() if isinstance(receipt, EffectReceipt) else receipt, claim=checked_claim)
    if checked_claim is not None and data["claim_id"] != checked_claim.claim_id:
        raise EffectLedgerError("effect reconciliation does not match claim")
    if checked_receipt is not None and receipt_id != checked_receipt.receipt_id:
        raise EffectLedgerError("effect reconciliation does not match receipt")
    if checked_receipt is None and receipt_id is not None:
        raise EffectLedgerError("effect reconciliation receipt is unavailable")
    if checked_receipt is not None and checked_receipt.payload["outcome"]["status"] not in {"uncertain", "timed-out", "failed"}:
        raise EffectLedgerError("terminal successful receipt may not be reconciled")
    expected = _digest(data, "reconciliation_id", "reconciliation_digest")
    if data["reconciliation_id"] != expected or data["reconciliation_digest"] != expected:
        raise EffectLedgerError("effect reconciliation digest is invalid")
    return EffectReconciliation(data)
