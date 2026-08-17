"""Immutable pre-execution validation obligations for one authorized effect."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from .agent_execution_identity import AgentExecutionIdentity, parse_agent_execution_identity
from .json_documents import canonical_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
CODE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EFFECT_TYPES = {"write", "execute", "network"}
SUBJECT_KINDS = {"acceptance-criterion", "constraint", "verification-requirement"}
ACTOR_KINDS = {"code", "verifier"}
METHODS = {"command", "evidence-review", "artifact-review", "state-check"}
EVIDENCE_TYPES = {"artifact-digest", "policy-decision", "preservation-check", "state-observation", "test-result"}


class ValidationGateError(ValueError):
    """Raised when a validation gate is incomplete, unsafe, or tampered."""


@dataclass(frozen=True)
class ValidationGate:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))

    @property
    def validation_gate_id(self) -> str:
        return str(self.payload["validation_gate_id"])


def _strict(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValidationGateError(f"{label} fields are invalid")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationGateError(f"{label} is invalid")
    return value


def _sha(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValidationGateError(f"{label} is invalid")
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationGateError("validation gate created_at is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValidationGateError("validation gate created_at is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed) or parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") != value:
        raise ValidationGateError("validation gate created_at is not canonical")
    return value


def _digest(payload: Mapping[str, object]) -> str:
    semantic = {key: value for key, value in payload.items() if key not in {"validation_gate_id", "gate_digest"}}
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


def build_validation_gate(
    *,
    project_id: str,
    work_item_id: str,
    task_id: str,
    task_plan_id: str,
    worker_step_id: str,
    effect_id: str,
    effect_type: str,
    effect_digest: str,
    effect_authorization_id: str,
    worker_execution_identity_id: str,
    worker_actor_digest: str,
    verifier_execution_identity: AgentExecutionIdentity | Mapping[str, object],
    subjects: Sequence[Mapping[str, object]],
    checks: Sequence[Mapping[str, object]],
    policy_revision: str,
    source_revision_digest: str,
    created_at: str,
    mutation_plan_id: str | None = None,
    provider_request_id: str | None = None,
) -> ValidationGate:
    identity = (
        verifier_execution_identity.as_dict()
        if isinstance(verifier_execution_identity, AgentExecutionIdentity)
        else dict(verifier_execution_identity)
    )
    payload: dict[str, object] = {
        "schema_ref": "schemas/validation-gate.schema.json",
        "schema_version": 1,
        "validation_gate_id": "",
        "bindings": {
            "project_id": project_id, "work_item_id": work_item_id, "task_id": task_id,
            "task_plan_id": task_plan_id, "worker_step_id": worker_step_id,
            "effect_id": effect_id, "effect_type": effect_type, "effect_digest": effect_digest,
            "effect_authorization_id": effect_authorization_id,
            "worker_execution_identity_id": worker_execution_identity_id,
            "worker_actor_digest": worker_actor_digest,
            "verifier_execution_identity": identity,
        },
        "authorization_bindings": {
            "mutation_plan_id": mutation_plan_id,
            "provider_request_id": provider_request_id,
        },
        "subjects": sorted((dict(item) for item in subjects), key=lambda item: (str(item.get("subject_kind")), str(item.get("subject_digest")))),
        "checks": sorted((dict(item) for item in checks), key=lambda item: str(item.get("check_id"))),
        "policy": {
            "policy_revision": policy_revision,
            "source_revision_digest": source_revision_digest,
            "created_at": created_at,
        },
        "safety": {
            "grants_authority": False,
            "derived_after_execution": False,
            "contains_raw_payload": False,
            "contains_physical_paths": False,
            "contains_credentials": False,
        },
        "gate_digest": "",
    }
    gate_digest = _digest(payload)
    payload["validation_gate_id"] = gate_digest
    payload["gate_digest"] = gate_digest
    return parse_validation_gate(payload)


def parse_validation_gate(payload: object) -> ValidationGate:
    fields = {"schema_ref", "schema_version", "validation_gate_id", "bindings", "authorization_bindings", "subjects", "checks", "policy", "safety", "gate_digest"}
    data = _strict(payload, fields, "validation gate")
    if data["schema_ref"] != "schemas/validation-gate.schema.json" or data["schema_version"] != 1:
        raise ValidationGateError("validation gate contract is invalid")
    bindings = _strict(data["bindings"], {"project_id", "work_item_id", "task_id", "task_plan_id", "worker_step_id", "effect_id", "effect_type", "effect_digest", "effect_authorization_id", "worker_execution_identity_id", "worker_actor_digest", "verifier_execution_identity"}, "validation gate bindings")
    for field in ("project_id", "work_item_id", "task_id", "worker_step_id", "effect_id"):
        _id(bindings[field], field.replace("_", " "))
    for field in ("task_plan_id", "effect_digest", "effect_authorization_id", "worker_execution_identity_id", "worker_actor_digest"):
        _sha(bindings[field], field.replace("_", " "))
    if bindings["effect_type"] not in EFFECT_TYPES:
        raise ValidationGateError("validation gate effect type is invalid")
    try:
        verifier = parse_agent_execution_identity(bindings["verifier_execution_identity"])
    except ValueError as exc:
        raise ValidationGateError("validation gate verifier identity is invalid") from exc
    if (
        verifier.role != "verifier" or verifier.task_id != bindings["task_id"]
        or verifier.plan_id != bindings["task_plan_id"]
        or verifier.execution_identity_id == bindings["worker_execution_identity_id"]
        or verifier.actor_digest == bindings["worker_actor_digest"]
    ):
        raise ValidationGateError("validation gate verifier is not independent")
    authorization = _strict(data["authorization_bindings"], {"mutation_plan_id", "provider_request_id"}, "validation gate authorization")
    mutation = _sha(authorization["mutation_plan_id"], "mutation plan id", nullable=True)
    provider = _sha(authorization["provider_request_id"], "provider request id", nullable=True)
    if bindings["effect_type"] == "write" and mutation is None:
        raise ValidationGateError("write validation gate requires mutation plan")
    if bindings["effect_type"] == "network" and provider is None:
        raise ValidationGateError("network validation gate requires provider request")
    subjects = data["subjects"]
    if not isinstance(subjects, list) or not subjects:
        raise ValidationGateError("validation gate subjects are invalid")
    subject_digests = []
    normalized_subjects = []
    for item in subjects:
        subject = _strict(item, {"subject_kind", "subject_digest"}, "validation gate subject")
        if subject["subject_kind"] not in SUBJECT_KINDS:
            raise ValidationGateError("validation gate subject kind is invalid")
        subject_digests.append(_sha(subject["subject_digest"], "validation subject digest"))
        normalized_subjects.append(subject)
    if len(set(subject_digests)) != len(subject_digests) or subjects != sorted(normalized_subjects, key=lambda item: (item["subject_kind"], item["subject_digest"])):
        raise ValidationGateError("validation gate subjects are not canonical")
    checks = data["checks"]
    if not isinstance(checks, list) or not checks:
        raise ValidationGateError("validation gate checks are invalid")
    check_ids = []
    covered: set[str] = set()
    normalized_checks = []
    for item in checks:
        check = _strict(item, {"check_id", "actor_kind", "method", "expected_result", "evidence_required", "subject_digests"}, "validation gate check")
        check_ids.append(_id(check["check_id"], "validation check id"))
        if check["actor_kind"] not in ACTOR_KINDS or check["method"] not in METHODS or not isinstance(check["expected_result"], str) or not CODE.fullmatch(check["expected_result"]):
            raise ValidationGateError("validation gate check method is invalid")
        evidence = check["evidence_required"]
        digests = check["subject_digests"]
        if not isinstance(evidence, list) or not evidence or evidence != sorted(evidence) or len(set(evidence)) != len(evidence) or any(value not in EVIDENCE_TYPES for value in evidence):
            raise ValidationGateError("validation gate check evidence is invalid")
        if not isinstance(digests, list) or not digests or digests != sorted(digests) or len(set(digests)) != len(digests):
            raise ValidationGateError("validation gate check subjects are invalid")
        for value in digests:
            covered.add(str(_sha(value, "validation check subject digest")))
        normalized_checks.append(check)
    if len(set(check_ids)) != len(check_ids) or checks != sorted(normalized_checks, key=lambda item: item["check_id"]):
        raise ValidationGateError("validation gate checks are not canonical")
    if covered != set(subject_digests):
        raise ValidationGateError("validation gate checks do not cover exact subjects")
    policy = _strict(data["policy"], {"policy_revision", "source_revision_digest", "created_at"}, "validation gate policy")
    _sha(policy["policy_revision"], "validation policy revision")
    _sha(policy["source_revision_digest"], "validation source revision")
    _timestamp(policy["created_at"])
    safety = _strict(data["safety"], {"grants_authority", "derived_after_execution", "contains_raw_payload", "contains_physical_paths", "contains_credentials"}, "validation gate safety")
    if any(safety[field] is not False for field in safety):
        raise ValidationGateError("validation gate safety is invalid")
    expected = _digest(data)
    if data["validation_gate_id"] != expected or data["gate_digest"] != expected:
        raise ValidationGateError("validation gate digest is invalid")
    return ValidationGate(data)


def validate_gate_verification(
    gate: ValidationGate | Mapping[str, object],
    verification: object,
) -> bool:
    """Require a verified TaskVerification to satisfy the pre-bound gate exactly."""

    from .orchestration_verifier import TaskVerification

    checked = parse_validation_gate(gate.as_dict() if isinstance(gate, ValidationGate) else gate)
    if not isinstance(verification, TaskVerification):
        raise ValidationGateError("validation gate requires a verified task verification")
    payload = checked.payload
    bindings = payload["bindings"]
    if (
        verification.task_id != bindings["task_id"]
        or verification.plan_id != bindings["task_plan_id"]
        or verification.status != "verified"
        or verification.completion_allowed is not True
        or bindings["worker_execution_identity_id"] not in verification.worker_execution_identity_ids
    ):
        raise ValidationGateError("task verification does not match validation gate")
    verifier_id = bindings["verifier_execution_identity"]["execution_identity_id"]
    if verifier_id not in {
        item.execution_identity_id for item in verification.verifier_execution_identities
    }:
        raise ValidationGateError("validation gate verifier identity is missing")
    expected_subjects = {
        (item["subject_kind"], item["subject_digest"]) for item in payload["subjects"]
    }
    observed_subjects = {(item.kind, item.subject_digest) for item in verification.subjects}
    if expected_subjects != observed_subjects or any(not item.passed for item in verification.subjects):
        raise ValidationGateError("task verification subjects differ from validation gate")
    required: dict[str, set[str]] = {digest: set() for _, digest in expected_subjects}
    for check in payload["checks"]:
        for subject_digest in check["subject_digests"]:
            required[subject_digest].update(check["evidence_required"])
    observed: dict[str, set[str]] = {digest: set() for _, digest in expected_subjects}
    for evidence in verification.evidence:
        if (
            evidence.verifier_execution_identity_id != verifier_id
            or bindings["worker_step_id"] not in evidence.covered_worker_step_ids
            or not evidence.passed
        ):
            raise ValidationGateError("validation gate evidence binding is invalid")
        if evidence.subject_digest in observed:
            observed[evidence.subject_digest].add(evidence.evidence_type)
    if any(not required[digest].issubset(observed[digest]) for digest in required):
        raise ValidationGateError("validation gate evidence requirements are incomplete")
    return True
