"""Bounded, authority-free semantic results shared by every execution path."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .json_documents import canonical_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ABSOLUTE_PATH = re.compile(
    r"(?i)(?:[A-Z]:[\\/]|(?:^|\s)/(?:[^\s/]+/)*[^\s/]+|(?:^|\s)~[\\/])"
)
SECRET_TEXT = re.compile(
    r"(?i)(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]|"
    r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
ROLES = {"worker", "verifier", "explorer"}
STATUSES = {
    "completed",
    "partial",
    "failed",
    "blocked",
    "recovery-required",
    "abstained",
}
ARTIFACT_TYPES = {
    "patch",
    "report",
    "source",
    "test-result",
    "migration",
    "evidence",
}
EVIDENCE_TYPES = {
    "artifact-digest",
    "test-result",
    "state-observation",
    "policy-decision",
}
EFFECT_TYPES = {"read", "write", "execute", "network"}
SEVERITIES = {"low", "medium", "high", "critical"}
DISPOSITIONS = {"open", "mitigated", "accepted", "blocked"}
NEXT_ROLES = {"coordinator", "worker", "verifier", "human"}
VERDICTS = {"passed", "failed", "abstained"}
RETRY_SAFETY = {"replay-safe", "reconciliation-required", "non-replayable"}


class AgentResultEnvelopeError(ValueError):
    """Raised when an agent result is unsafe or semantically inconsistent."""


def _strict(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise AgentResultEnvelopeError(f"{label} fields are invalid")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _id(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise AgentResultEnvelopeError(f"{label} is invalid")
    return value


def _code(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not CODE.fullmatch(value):
        raise AgentResultEnvelopeError(f"{label} is invalid")
    return value


def _sha(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise AgentResultEnvelopeError(f"{label} is invalid")
    return value


def _safe_text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
        or ABSOLUTE_PATH.search(value)
        or SECRET_TEXT.search(value)
    ):
        raise AgentResultEnvelopeError(f"{label} is unsafe")
    return value


def _digest(payload: Mapping[str, object]) -> str:
    identity = {key: value for key, value in payload.items() if key != "envelope_digest"}
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


@dataclass(frozen=True)
class AgentResultEnvelope:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(json.dumps(self.payload, ensure_ascii=False))

    @property
    def envelope_digest(self) -> str:
        return str(self.payload["envelope_digest"])

    @property
    def status(self) -> str:
        return str(self.payload["result"]["status"])

    @property
    def role(self) -> str:
        return str(self.payload["identity"]["role"])


def build_agent_result_envelope(
    *,
    correlation_id: str,
    project_id: str,
    work_item_id: str,
    task_id: str,
    task_plan_id: str,
    step_id: str,
    execution_identity_id: str,
    role: str,
    route_decision_id: str,
    status: str,
    headline: str,
    recommended_action_code: str,
    recommended_action_statement: str,
    recommended_action_role: str,
    queue_id: str | None = None,
    delegation_decision_id: str | None = None,
    model_assignment_id: str | None = None,
    admission_decision_id: str | None = None,
    findings: Sequence[Mapping[str, object]] = (),
    artifacts: Sequence[Mapping[str, object]] = (),
    evidence: Sequence[Mapping[str, object]] = (),
    effects: Sequence[Mapping[str, object]] = (),
    risks: Sequence[Mapping[str, object]] = (),
    failure: Mapping[str, object] | None = None,
    missing_step_ids: Sequence[str] = (),
    verification_required: bool = False,
    validation_gate_id: str | None = None,
    verification_id: str | None = None,
    covered_worker_step_ids: Sequence[str] = (),
    verdict: str | None = None,
) -> AgentResultEnvelope:
    payload: dict[str, object] = {
        "schema_ref": "schemas/agent-result-envelope.schema.json",
        "schema_version": 2,
        "identity": {
            "envelope_id": "",
            "correlation_id": correlation_id,
            "project_id": project_id,
            "work_item_id": work_item_id,
            "task_id": task_id,
            "task_plan_id": task_plan_id,
            "step_id": step_id,
            "queue_id": queue_id,
            "execution_identity_id": execution_identity_id,
            "role": role,
        },
        "decision_bindings": {
            "route_decision_id": route_decision_id,
            "delegation_decision_id": delegation_decision_id,
            "model_assignment_id": model_assignment_id,
            "admission_decision_id": admission_decision_id,
        },
        "result": {
            "status": status,
            "summary": {
                "headline": headline,
                "findings": [dict(item) for item in findings],
            },
            "artifacts": [dict(item) for item in artifacts],
            "evidence": [dict(item) for item in evidence],
            "effects": [dict(item) for item in effects],
            "risks": [dict(item) for item in risks],
            "failure": None if failure is None else dict(failure),
            "missing_step_ids": list(missing_step_ids),
            "recommended_next_action": {
                "action_code": recommended_action_code,
                "statement": recommended_action_statement,
                "required_role": recommended_action_role,
            },
            "verification": {
                "required": verification_required,
                "validation_gate_id": validation_gate_id,
                "verification_id": verification_id,
                "covered_worker_step_ids": list(covered_worker_step_ids),
                "verdict": verdict,
            },
        },
        "safety": {
            "grants_authority": False,
            "contains_raw_prompt": False,
            "contains_raw_model_output": False,
            "contains_physical_paths": False,
            "contains_credentials": False,
        },
        "envelope_digest": "",
    }
    envelope_id = hashlib.sha256(
        canonical_json_bytes(
            {
                "identity": {
                    key: value
                    for key, value in payload["identity"].items()
                    if key != "envelope_id"
                },
                "result": payload["result"],
                "decision_bindings": payload["decision_bindings"],
            }
        )
    ).hexdigest()
    payload["identity"]["envelope_id"] = envelope_id
    payload["envelope_digest"] = _digest(payload)
    return parse_agent_result_envelope(payload)


def parse_agent_result_envelope(payload: object) -> AgentResultEnvelope:
    data = _strict(
        payload,
        {"schema_ref", "schema_version", "identity", "decision_bindings", "result", "safety", "envelope_digest"},
        "agent result envelope",
    )
    if data.get("schema_ref") != "schemas/agent-result-envelope.schema.json" or data.get("schema_version") != 2:
        raise AgentResultEnvelopeError("agent result envelope contract is invalid")
    identity = _strict(
        data.get("identity"),
        {"envelope_id", "correlation_id", "project_id", "work_item_id", "task_id", "task_plan_id", "step_id", "queue_id", "execution_identity_id", "role"},
        "agent result identity",
    )
    _sha(identity.get("envelope_id"), "envelope id")
    for field in ("correlation_id", "project_id", "work_item_id", "task_id", "step_id"):
        _id(identity.get(field), field.replace("_", " "))
    _id(identity.get("queue_id"), "queue id", nullable=True)
    _sha(identity.get("task_plan_id"), "task plan id")
    _sha(identity.get("execution_identity_id"), "execution identity id")
    role = identity.get("role")
    if role not in ROLES:
        raise AgentResultEnvelopeError("agent result role is invalid")

    bindings = _strict(
        data.get("decision_bindings"),
        {"route_decision_id", "delegation_decision_id", "model_assignment_id", "admission_decision_id"},
        "agent result decision bindings",
    )
    _sha(bindings.get("route_decision_id"), "route decision id")
    _sha(bindings.get("delegation_decision_id"), "delegation decision id", nullable=True)
    _id(bindings.get("model_assignment_id"), "model assignment id", nullable=True)
    _sha(bindings.get("admission_decision_id"), "admission decision id", nullable=True)

    result = _strict(
        data.get("result"),
        {"status", "summary", "artifacts", "evidence", "effects", "risks", "failure", "missing_step_ids", "recommended_next_action", "verification"},
        "agent result",
    )
    status = result.get("status")
    if status not in STATUSES:
        raise AgentResultEnvelopeError("agent result status is invalid")
    summary = _strict(result.get("summary"), {"headline", "findings"}, "agent result summary")
    _safe_text(summary.get("headline"), "agent result headline", 240)
    findings = summary.get("findings")
    if not isinstance(findings, list) or len(findings) > 20:
        raise AgentResultEnvelopeError("agent result findings are invalid")
    for item in findings:
        finding = _strict(item, {"code", "statement"}, "agent result finding")
        _code(finding.get("code"), "finding code")
        _safe_text(finding.get("statement"), "finding statement", 512)

    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > 50:
        raise AgentResultEnvelopeError("agent result artifacts are invalid")
    artifact_ids: set[str] = set()
    for item in artifacts:
        artifact = _strict(item, {"artifact_id", "artifact_type", "artifact_digest"}, "agent artifact")
        artifact_id = str(_id(artifact.get("artifact_id"), "artifact id"))
        if artifact_id in artifact_ids or artifact.get("artifact_type") not in ARTIFACT_TYPES:
            raise AgentResultEnvelopeError("agent artifact identity is invalid")
        artifact_ids.add(artifact_id)
        _sha(artifact.get("artifact_digest"), "artifact digest")

    evidence = result.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > 50:
        raise AgentResultEnvelopeError("agent result evidence is invalid")
    evidence_ids: set[str] = set()
    for item in evidence:
        entry = _strict(item, {"evidence_id", "evidence_type", "evidence_digest"}, "agent evidence")
        evidence_id = str(_id(entry.get("evidence_id"), "evidence id"))
        if evidence_id in evidence_ids or entry.get("evidence_type") not in EVIDENCE_TYPES:
            raise AgentResultEnvelopeError("agent evidence identity is invalid")
        evidence_ids.add(evidence_id)
        _sha(entry.get("evidence_digest"), "evidence digest")

    effects = result.get("effects")
    if not isinstance(effects, list) or len(effects) > 50:
        raise AgentResultEnvelopeError("agent result effects are invalid")
    effect_ids: set[str] = set()
    for item in effects:
        effect = _strict(item, {"effect_id", "effect_type", "claim_id", "receipt_id", "result_digest"}, "agent effect")
        effect_id = str(_id(effect.get("effect_id"), "effect id"))
        effect_type = effect.get("effect_type")
        if effect_id in effect_ids or effect_type not in EFFECT_TYPES:
            raise AgentResultEnvelopeError("agent effect identity is invalid")
        effect_ids.add(effect_id)
        claim = _sha(effect.get("claim_id"), "effect claim id", nullable=True)
        receipt = _sha(effect.get("receipt_id"), "effect receipt id", nullable=True)
        effect_result = _sha(effect.get("result_digest"), "effect result digest", nullable=True)
        if effect_type != "read" and status == "completed" and None in {claim, receipt, effect_result}:
            raise AgentResultEnvelopeError("completed mutation effect lacks claim evidence")
    if role == "explorer" and any(item["effect_type"] != "read" for item in effects):
        raise AgentResultEnvelopeError("explorer cannot report mutation effects")

    risks = result.get("risks")
    if not isinstance(risks, list) or len(risks) > 20:
        raise AgentResultEnvelopeError("agent result risks are invalid")
    for item in risks:
        risk = _strict(item, {"risk_code", "severity", "statement", "disposition"}, "agent risk")
        _code(risk.get("risk_code"), "risk code")
        if risk.get("severity") not in SEVERITIES or risk.get("disposition") not in DISPOSITIONS:
            raise AgentResultEnvelopeError("agent risk classification is invalid")
        _safe_text(risk.get("statement"), "risk statement", 512)

    failure = result.get("failure")
    if status in {"failed", "recovery-required"}:
        parsed_failure = _strict(failure, {"category", "retry_safety", "failure_digest", "last_verified_checkpoint_id"}, "agent failure")
        _code(parsed_failure.get("category"), "failure category")
        if parsed_failure.get("retry_safety") not in RETRY_SAFETY:
            raise AgentResultEnvelopeError("failure retry safety is invalid")
        _sha(parsed_failure.get("failure_digest"), "failure digest")
        _sha(parsed_failure.get("last_verified_checkpoint_id"), "checkpoint id", nullable=True)
    elif failure is not None:
        raise AgentResultEnvelopeError("non-failure result cannot carry failure detail")

    missing = result.get("missing_step_ids")
    if not isinstance(missing, list) or len(set(missing)) != len(missing):
        raise AgentResultEnvelopeError("missing step ids are invalid")
    for item in missing:
        _id(item, "missing step id")
    if (status == "partial") != bool(missing):
        raise AgentResultEnvelopeError("partial result missing-step binding is invalid")

    action = _strict(result.get("recommended_next_action"), {"action_code", "statement", "required_role"}, "recommended action")
    _code(action.get("action_code"), "action code")
    _safe_text(action.get("statement"), "action statement", 512)
    if action.get("required_role") not in NEXT_ROLES:
        raise AgentResultEnvelopeError("recommended action role is invalid")

    verification = _strict(result.get("verification"), {"required", "validation_gate_id", "verification_id", "covered_worker_step_ids", "verdict"}, "agent verification")
    if not isinstance(verification.get("required"), bool):
        raise AgentResultEnvelopeError("verification required flag is invalid")
    _sha(verification.get("validation_gate_id"), "validation gate id", nullable=True)
    _sha(verification.get("verification_id"), "verification id", nullable=True)
    covered = verification.get("covered_worker_step_ids")
    if not isinstance(covered, list) or len(set(covered)) != len(covered):
        raise AgentResultEnvelopeError("covered worker steps are invalid")
    for item in covered:
        _id(item, "covered worker step id")
    verdict = verification.get("verdict")
    if verdict not in VERDICTS | {None}:
        raise AgentResultEnvelopeError("verification verdict is invalid")
    if role == "verifier":
        if not covered or verdict is None or any(item["artifact_type"] not in {"test-result", "evidence"} for item in artifacts):
            raise AgentResultEnvelopeError("verifier result contract is invalid")
    elif covered or verdict is not None:
        raise AgentResultEnvelopeError("non-verifier cannot issue a verdict")

    safety = _strict(data.get("safety"), {"grants_authority", "contains_raw_prompt", "contains_raw_model_output", "contains_physical_paths", "contains_credentials"}, "agent result safety")
    if any(safety.get(field) is not False for field in safety):
        raise AgentResultEnvelopeError("agent result safety assertions are invalid")

    expected_envelope_id = hashlib.sha256(
        canonical_json_bytes(
            {
                "identity": {key: value for key, value in identity.items() if key != "envelope_id"},
                "result": result,
                "decision_bindings": bindings,
            }
        )
    ).hexdigest()
    if identity["envelope_id"] != expected_envelope_id or data.get("envelope_digest") != _digest(data):
        raise AgentResultEnvelopeError("agent result digest is invalid")
    return AgentResultEnvelope(data)
