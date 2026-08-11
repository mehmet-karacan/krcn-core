"""Deterministic, secret-safe task intent normalization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping

from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ORIGINS = {"explicit-user", "safe-assumption"}
OWNERSHIP_CLASSES = {"core", "runtime", "user-data", "derived", "secrets", "unmanaged"}
AMBIGUITY_IMPACTS = {
    "scope",
    "authority",
    "user-data",
    "external-system",
    "irreversible-effect",
}
SENSITIVE_TEXT = re.compile(
    r"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*[:=]|"
    r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+|"
    r"(?:secret|keyring|env)://|"
    r"://[^/\s:@]+:[^/@\s]+@"
)
MAX_TEXT = 4096
MAX_ITEMS = 100


class TaskIntentError(ValueError):
    """Raised when normalized intent is incomplete, unsafe, or ambiguous."""


@dataclass(frozen=True)
class IntentValue:
    value: str
    origin: str
    reversible: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "origin": self.origin,
            "reversible": self.reversible,
        }


@dataclass(frozen=True)
class IntentAssumption:
    assumption_id: str
    statement: str
    rationale: str
    reversible: bool
    impact: str

    def as_dict(self) -> dict[str, object]:
        return {
            "assumption_id": self.assumption_id,
            "statement": self.statement,
            "rationale": self.rationale,
            "reversible": self.reversible,
            "impact": self.impact,
        }


@dataclass(frozen=True)
class IntentAmbiguity:
    ambiguity_id: str
    question: str
    impact_categories: tuple[str, ...]
    blocking: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "ambiguity_id": self.ambiguity_id,
            "question": self.question,
            "impact_categories": list(self.impact_categories),
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class TaskIntent:
    task_id: str
    request_digest: str
    goal: IntentValue
    scope: tuple[IntentValue, ...]
    sources: tuple[IntentValue, ...]
    constraints: tuple[IntentValue, ...]
    acceptance_criteria: tuple[IntentValue, ...]
    ownership_impact: tuple[str, ...]
    verification_requirements: tuple[IntentValue, ...]
    assumptions: tuple[IntentAssumption, ...]
    ambiguities: tuple[IntentAmbiguity, ...]
    clarification_required: bool
    status: str
    intent_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/task-intent.schema.json",
            "schema_version": 1,
            "task_id": self.task_id,
            "request_digest": self.request_digest,
            "goal": self.goal.as_dict(),
            "scope": [item.as_dict() for item in self.scope],
            "sources": [item.as_dict() for item in self.sources],
            "constraints": [item.as_dict() for item in self.constraints],
            "acceptance_criteria": [
                item.as_dict() for item in self.acceptance_criteria
            ],
            "ownership_impact": list(self.ownership_impact),
            "verification_requirements": [
                item.as_dict() for item in self.verification_requirements
            ],
            "assumptions": [item.as_dict() for item in self.assumptions],
            "ambiguities": [item.as_dict() for item in self.ambiguities],
            "clarification_required": self.clarification_required,
            "status": self.status,
            "intent_digest": self.intent_digest,
        }


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TaskIntentError(f"{label} must be text")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > MAX_TEXT or SENSITIVE_TEXT.search(normalized):
        raise TaskIntentError(f"{label} is invalid or sensitive")
    return normalized


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise TaskIntentError(f"{label} must be a portable identifier")
    return value


def _intent_value(payload: object, label: str, *, logical_ref: bool = False) -> IntentValue:
    if not isinstance(payload, dict) or set(payload) != {
        "value",
        "origin",
        "reversible",
    }:
        raise TaskIntentError(f"{label} fields are invalid")
    value = _text(payload.get("value"), label)
    if logical_ref and (
        not LOGICAL_REF.fullmatch(value)
        or ".." in value.split(":", 1)[1].split("/")
        or "://" in value
    ):
        raise TaskIntentError(f"{label} must be a portable logical reference")
    origin = payload.get("origin")
    reversible = payload.get("reversible")
    if origin not in ORIGINS:
        raise TaskIntentError(f"{label} origin is invalid")
    if not isinstance(reversible, bool):
        raise TaskIntentError(f"{label} reversible must be boolean")
    if origin == "safe-assumption" and reversible is not True:
        raise TaskIntentError("safe assumptions must be reversible")
    return IntentValue(value, str(origin), reversible)


def _intent_values(
    payload: object,
    label: str,
    *,
    required: bool,
    logical_ref: bool = False,
) -> tuple[IntentValue, ...]:
    if not isinstance(payload, list) or len(payload) > MAX_ITEMS:
        raise TaskIntentError(f"{label} must be a bounded list")
    if required and not payload:
        raise TaskIntentError(f"{label} must not be empty")
    values = tuple(
        _intent_value(item, label, logical_ref=logical_ref) for item in payload
    )
    identities = {(item.value, item.origin) for item in values}
    if len(identities) != len(values):
        raise TaskIntentError(f"{label} must be unique")
    return tuple(sorted(values, key=lambda item: (item.value.casefold(), item.origin)))


def _assumptions(payload: object) -> tuple[IntentAssumption, ...]:
    if not isinstance(payload, list) or len(payload) > MAX_ITEMS:
        raise TaskIntentError("assumptions must be a bounded list")
    assumptions = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {
            "assumption_id",
            "statement",
            "rationale",
            "reversible",
            "impact",
        }:
            raise TaskIntentError("assumption fields are invalid")
        if item.get("reversible") is not True or item.get("impact") != "minor":
            raise TaskIntentError("assumptions must be minor and reversible")
        assumptions.append(
            IntentAssumption(
                _identifier(item.get("assumption_id"), "assumption_id"),
                _text(item.get("statement"), "assumption statement"),
                _text(item.get("rationale"), "assumption rationale"),
                True,
                "minor",
            )
        )
    if len({item.assumption_id for item in assumptions}) != len(assumptions):
        raise TaskIntentError("assumption ids must be unique")
    return tuple(sorted(assumptions, key=lambda item: item.assumption_id))


def _ambiguities(payload: object) -> tuple[IntentAmbiguity, ...]:
    if not isinstance(payload, list) or len(payload) > MAX_ITEMS:
        raise TaskIntentError("ambiguities must be a bounded list")
    ambiguities = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {
            "ambiguity_id",
            "question",
            "impact_categories",
            "blocking",
        }:
            raise TaskIntentError("ambiguity fields are invalid")
        impacts = item.get("impact_categories")
        if (
            not isinstance(impacts, list)
            or not impacts
            or len(set(impacts)) != len(impacts)
            or any(value not in AMBIGUITY_IMPACTS for value in impacts)
        ):
            raise TaskIntentError("ambiguity impacts are invalid")
        if item.get("blocking") is not True:
            raise TaskIntentError("material ambiguity must block planning")
        ambiguities.append(
            IntentAmbiguity(
                _identifier(item.get("ambiguity_id"), "ambiguity_id"),
                _text(item.get("question"), "ambiguity question"),
                tuple(sorted(impacts)),
                True,
            )
        )
    if len({item.ambiguity_id for item in ambiguities}) != len(ambiguities):
        raise TaskIntentError("ambiguity ids must be unique")
    return tuple(sorted(ambiguities, key=lambda item: item.ambiguity_id))


def _intent_digest(payload: Mapping[str, object]) -> str:
    identity = dict(payload)
    identity.pop("intent_digest", None)
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def parse_task_intent(payload: object) -> TaskIntent:
    expected = {
        "schema_ref",
        "schema_version",
        "task_id",
        "request_digest",
        "goal",
        "scope",
        "sources",
        "constraints",
        "acceptance_criteria",
        "ownership_impact",
        "verification_requirements",
        "assumptions",
        "ambiguities",
        "clarification_required",
        "status",
        "intent_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise TaskIntentError("task intent fields are invalid")
    if payload.get("schema_ref") != "schemas/task-intent.schema.json":
        raise TaskIntentError("task intent schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise TaskIntentError("task intent schema_version must be 1")
    task_id = _identifier(payload.get("task_id"), "task_id")
    request_digest = payload.get("request_digest")
    if not isinstance(request_digest, str) or not SHA256.fullmatch(request_digest):
        raise TaskIntentError("request_digest is invalid")
    goal = _intent_value(payload.get("goal"), "goal")
    if goal.origin != "explicit-user":
        raise TaskIntentError("goal must come from explicit user input")
    scope = _intent_values(payload.get("scope"), "scope", required=True)
    sources = _intent_values(
        payload.get("sources"),
        "sources",
        required=False,
        logical_ref=True,
    )
    constraints = _intent_values(
        payload.get("constraints"), "constraints", required=False
    )
    acceptance = _intent_values(
        payload.get("acceptance_criteria"),
        "acceptance_criteria",
        required=True,
    )
    verification = _intent_values(
        payload.get("verification_requirements"),
        "verification_requirements",
        required=True,
    )
    ownership = payload.get("ownership_impact")
    if (
        not isinstance(ownership, list)
        or not ownership
        or len(set(ownership)) != len(ownership)
        or any(item not in OWNERSHIP_CLASSES for item in ownership)
    ):
        raise TaskIntentError("ownership_impact is invalid")
    ownership_impact = tuple(sorted(ownership))
    assumptions = _assumptions(payload.get("assumptions"))
    ambiguities = _ambiguities(payload.get("ambiguities"))
    safe_values = tuple(
        item
        for values in (scope, sources, constraints, acceptance, verification)
        for item in values
        if item.origin == "safe-assumption"
    )
    if bool(safe_values) != bool(assumptions):
        raise TaskIntentError("safe assumptions require explicit assumption evidence")
    clarification_required = payload.get("clarification_required")
    status = payload.get("status")
    expected_clarification = bool(ambiguities)
    if clarification_required is not expected_clarification:
        raise TaskIntentError("clarification state does not match ambiguities")
    expected_status = "needs-clarification" if ambiguities else "ready"
    if status != expected_status:
        raise TaskIntentError("task intent status is invalid")
    digest = payload.get("intent_digest")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise TaskIntentError("intent_digest is invalid")
    if digest != _intent_digest(payload):
        raise TaskIntentError("intent_digest does not match")
    return TaskIntent(
        task_id,
        request_digest,
        goal,
        scope,
        sources,
        constraints,
        acceptance,
        ownership_impact,
        verification,
        assumptions,
        ambiguities,
        expected_clarification,
        expected_status,
        digest,
    )


def create_task_intent(
    request_text: str,
    extraction: Mapping[str, object],
) -> TaskIntent:
    normalized_request = _text(request_text, "request")
    expected = {
        "task_id",
        "goal",
        "scope",
        "sources",
        "constraints",
        "acceptance_criteria",
        "ownership_impact",
        "verification_requirements",
        "assumptions",
        "ambiguities",
    }
    if not isinstance(extraction, Mapping) or set(extraction) != expected:
        raise TaskIntentError("intent extraction fields are invalid")
    goal = _intent_value(extraction.get("goal"), "goal")
    scope = _intent_values(extraction.get("scope"), "scope", required=True)
    sources = _intent_values(
        extraction.get("sources"),
        "sources",
        required=False,
        logical_ref=True,
    )
    constraints = _intent_values(
        extraction.get("constraints"), "constraints", required=False
    )
    acceptance = _intent_values(
        extraction.get("acceptance_criteria"),
        "acceptance_criteria",
        required=True,
    )
    verification = _intent_values(
        extraction.get("verification_requirements"),
        "verification_requirements",
        required=True,
    )
    ownership = extraction.get("ownership_impact")
    if not isinstance(ownership, list):
        raise TaskIntentError("ownership_impact must be a list")
    assumptions = _assumptions(extraction.get("assumptions"))
    ambiguities = _ambiguities(extraction.get("ambiguities"))
    payload = {
        "schema_ref": "schemas/task-intent.schema.json",
        "schema_version": 1,
        "task_id": _identifier(extraction.get("task_id"), "task_id"),
        "request_digest": hashlib.sha256(
            normalized_request.encode("utf-8")
        ).hexdigest(),
        "goal": goal.as_dict(),
        "scope": [item.as_dict() for item in scope],
        "sources": [item.as_dict() for item in sources],
        "constraints": [item.as_dict() for item in constraints],
        "acceptance_criteria": [item.as_dict() for item in acceptance],
        "ownership_impact": sorted(ownership),
        "verification_requirements": [item.as_dict() for item in verification],
        "assumptions": [item.as_dict() for item in assumptions],
        "ambiguities": [item.as_dict() for item in ambiguities],
        "clarification_required": bool(ambiguities),
        "status": "needs-clarification" if ambiguities else "ready",
    }
    payload["intent_digest"] = _intent_digest(payload)
    return parse_task_intent(payload)
