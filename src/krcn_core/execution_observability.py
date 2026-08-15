"""Canonical execution tracing and user-facing status projection.

Domain services retain their own internal status machines. This module creates
one authority-free observability contract above them without making that
projection authoritative or allowing it to mutate any domain state.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
ABSOLUTE_PATH = re.compile(
    r"(^|[^A-Za-z0-9])([A-Za-z]:[\\/]|\\\\[^\\]|/(?:home|Users|root|mnt|var)/)"
)
SECRET_MARKER = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|"
    r"client[_-]?secret|bearer)\b\s*[:=]"
)

CANONICAL_STATUSES = (
    "preparing",
    "awaiting-approval",
    "queued",
    "running",
    "partially-completed",
    "awaiting-verification",
    "blocked",
    "degraded",
    "cancelled",
    "recovery-required",
    "completed",
    "derived-stale",
    "failed",
)

DELEGATION_MODES = (
    "direct",
    "native-parallel",
    "native-sequential",
    "isolated-role-fallback",
    "delegation-unavailable",
)

DOMAIN_STATUS_MAP = {
    "draft": "preparing",
    "planned": "preparing",
    "preparing": "preparing",
    "awaiting-approval": "awaiting-approval",
    "pending": "queued",
    "ready": "queued",
    "queued": "queued",
    "authorized": "queued",
    "active": "running",
    "in-progress": "running",
    "leased": "running",
    "running": "running",
    "partially-completed": "partially-completed",
    "verifying": "awaiting-verification",
    "awaiting-verification": "awaiting-verification",
    "blocked": "blocked",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "interrupted": "recovery-required",
    "recovery-required": "recovery-required",
    "completed": "completed",
    "succeeded": "completed",
    "verified": "completed",
    "stale": "derived-stale",
    "failed": "failed",
    "error": "failed",
}

STATUS_PRIORITY = {
    "completed": 0,
    "preparing": 10,
    "awaiting-approval": 20,
    "queued": 30,
    "running": 40,
    "partially-completed": 50,
    "awaiting-verification": 60,
    "derived-stale": 70,
    "recovery-required": 80,
    "blocked": 90,
    "cancelled": 100,
    "failed": 110,
}

TRACE_KEYS = {
    "schema_ref",
    "schema_version",
    "correlation_id",
    "request_id",
    "client_id",
    "project_id",
    "work_item_id",
    "intent_digest",
    "context_digest",
    "plan_id",
    "approval_envelope_id",
    "delegation_mode",
    "model_assignment_ids",
    "queue_ids",
    "agent_execution_ids",
    "verification_id",
    "evidence_digest",
    "status",
    "started_at",
    "ended_at",
    "duration_ms",
    "token_usage",
    "estimated_cost",
    "retry_count",
    "cache_hit",
    "failure_code",
    "grants_authority",
    "contains_raw_payload",
    "contains_physical_paths",
    "trace_digest",
}

PROJECTION_KEYS = {
    "schema_ref",
    "schema_version",
    "correlation_id",
    "project_id",
    "work_item_id",
    "status",
    "summary",
    "next_action",
    "reason_codes",
    "degraded",
    "derived_stale",
    "source_status_digest",
    "trace_digest",
    "updated_at",
    "grants_authority",
    "projection_digest",
}


class ExecutionObservabilityError(ValueError):
    """Raised when trace or status evidence is unsafe or internally invalid."""


def _digest(payload: Mapping[str, object], field: str) -> str:
    identity = {key: value for key, value in payload.items() if key != field}
    encoded = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if isinstance(value, str) and ABSOLUTE_PATH.search(value):
        raise ExecutionObservabilityError(f"{label} must not contain a physical path")
    if isinstance(value, str) and SECRET_MARKER.search(value):
        raise ExecutionObservabilityError(f"{label} must not contain a credential")
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ExecutionObservabilityError(f"{label} must be a portable identifier")
    return value


def _digest_value(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ExecutionObservabilityError(f"{label} must be a SHA-256 digest")
    return value


def _safe_text(
    value: object, label: str, *, limit: int = 512, nullable: bool = False
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ExecutionObservabilityError(f"{label} must be non-empty text")
    text = value.strip()
    if len(text) > limit:
        raise ExecutionObservabilityError(f"{label} exceeds {limit} characters")
    if ABSOLUTE_PATH.search(text):
        raise ExecutionObservabilityError(f"{label} must not contain a physical path")
    if SECRET_MARKER.search(text):
        raise ExecutionObservabilityError(f"{label} must not contain a credential")
    return text


def _timestamp(value: object, label: str) -> tuple[str, datetime]:
    if not isinstance(value, str):
        raise ExecutionObservabilityError(f"{label} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecutionObservabilityError(
            f"{label} must be an ISO 8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise ExecutionObservabilityError(f"{label} must carry a timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat().replace("+00:00", "Z"), utc


def _identifiers(values: object, label: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ExecutionObservabilityError(f"{label} must be a list")
    result = tuple(_identifier(value, f"{label} entry") for value in values)
    if len(set(result)) != len(result):
        raise ExecutionObservabilityError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionObservabilityError(f"{label} must be a non-negative integer")
    return value


def _exact_keys(payload: Mapping[str, object], expected: set[str], label: str) -> None:
    keys = set(payload)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ExecutionObservabilityError(
            f"{label} fields are invalid: {'; '.join(details)}"
        )


def _token_usage(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ExecutionObservabilityError("token usage must be an object")
    expected = {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    }
    _exact_keys(value, expected, "token usage")
    usage = {key: _non_negative_int(value.get(key), key) for key in sorted(expected)}
    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def _estimated_cost(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ExecutionObservabilityError("estimated cost must be an object or null")
    _exact_keys(value, {"amount_microunits", "currency"}, "estimated cost")
    amount = _non_negative_int(value.get("amount_microunits"), "cost amount")
    currency = value.get("currency")
    if not isinstance(currency, str) or not CURRENCY.fullmatch(currency):
        raise ExecutionObservabilityError("cost currency must be a three-letter code")
    return {
        "amount_microunits": amount,
        "currency": currency,
        "is_estimate": True,
    }


@dataclass(frozen=True)
class ExecutionTrace:
    """One digest-bound request trace with no raw request or execution payload."""

    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


def build_execution_trace(
    *,
    correlation_id: str,
    request_id: str,
    client_id: str,
    intent_digest: str,
    context_digest: str,
    status: str,
    started_at: str,
    project_id: str | None = None,
    work_item_id: str | None = None,
    plan_id: str | None = None,
    approval_envelope_id: str | None = None,
    delegation_mode: str = "direct",
    model_assignment_ids: Sequence[str] = (),
    queue_ids: Sequence[str] = (),
    agent_execution_ids: Sequence[str] = (),
    verification_id: str | None = None,
    evidence_digest: str | None = None,
    ended_at: str | None = None,
    token_usage: Mapping[str, int] | None = None,
    estimated_cost: Mapping[str, object] | None = None,
    retry_count: int = 0,
    cache_hit: bool = False,
    failure_code: str | None = None,
) -> ExecutionTrace:
    """Build a deterministic execution trace from already-reviewed metadata."""

    if status not in CANONICAL_STATUSES:
        raise ExecutionObservabilityError("execution trace status is invalid")
    if delegation_mode not in DELEGATION_MODES:
        raise ExecutionObservabilityError("delegation mode is invalid")
    if not isinstance(cache_hit, bool):
        raise ExecutionObservabilityError("cache hit must be a boolean")

    normalized_start, start_time = _timestamp(started_at, "started at")
    normalized_end: str | None = None
    duration_ms: int | None = None
    if ended_at is not None:
        normalized_end, end_time = _timestamp(ended_at, "ended at")
        if end_time < start_time:
            raise ExecutionObservabilityError("ended at must not precede started at")
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

    usage_input = token_usage or {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    payload: dict[str, object] = {
        "schema_ref": "schemas/execution-trace.schema.json",
        "schema_version": 1,
        "correlation_id": _identifier(correlation_id, "correlation id"),
        "request_id": _identifier(request_id, "request id"),
        "client_id": _identifier(client_id, "client id"),
        "project_id": _identifier(project_id, "project id", nullable=True),
        "work_item_id": _identifier(work_item_id, "work item id", nullable=True),
        "intent_digest": _digest_value(intent_digest, "intent digest"),
        "context_digest": _digest_value(context_digest, "context digest"),
        "plan_id": _digest_value(plan_id, "plan id", nullable=True),
        "approval_envelope_id": _identifier(
            approval_envelope_id, "approval envelope id", nullable=True
        ),
        "delegation_mode": delegation_mode,
        "model_assignment_ids": list(
            _identifiers(model_assignment_ids, "model assignment ids")
        ),
        "queue_ids": list(_identifiers(queue_ids, "queue ids")),
        "agent_execution_ids": list(
            _identifiers(agent_execution_ids, "agent execution ids")
        ),
        "verification_id": _identifier(
            verification_id, "verification id", nullable=True
        ),
        "evidence_digest": _digest_value(
            evidence_digest, "evidence digest", nullable=True
        ),
        "status": status,
        "started_at": normalized_start,
        "ended_at": normalized_end,
        "duration_ms": duration_ms,
        "token_usage": _token_usage(usage_input),
        "estimated_cost": _estimated_cost(estimated_cost),
        "retry_count": _non_negative_int(retry_count, "retry count"),
        "cache_hit": cache_hit,
        "failure_code": _identifier(
            failure_code, "failure code", nullable=True
        ),
        "grants_authority": False,
        "contains_raw_payload": False,
        "contains_physical_paths": False,
        "trace_digest": "",
    }
    payload["trace_digest"] = _digest(payload, "trace_digest")
    return ExecutionTrace(payload)


def parse_execution_trace(payload: object) -> ExecutionTrace:
    """Parse a stored trace and reject extra, unsafe, or digest-invalid data."""

    if not isinstance(payload, Mapping):
        raise ExecutionObservabilityError("execution trace must be an object")
    _exact_keys(payload, TRACE_KEYS, "execution trace")
    if payload.get("schema_ref") != "schemas/execution-trace.schema.json":
        raise ExecutionObservabilityError("execution trace schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ExecutionObservabilityError("execution trace schema version is invalid")
    for field in ("grants_authority", "contains_raw_payload", "contains_physical_paths"):
        if payload.get(field) is not False:
            raise ExecutionObservabilityError(f"execution trace {field} must be false")

    usage = payload.get("token_usage")
    if not isinstance(usage, Mapping):
        raise ExecutionObservabilityError("token usage must be an object")
    expected_usage = {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_tokens",
    }
    _exact_keys(usage, expected_usage, "token usage")
    input_usage = {
        key: usage.get(key)
        for key in expected_usage
        if key != "total_tokens"
    }
    normalized_usage = _token_usage(input_usage)
    if dict(usage) != normalized_usage:
        raise ExecutionObservabilityError("token usage total is invalid")

    cost = payload.get("estimated_cost")
    cost_input = None
    if cost is not None:
        if not isinstance(cost, Mapping):
            raise ExecutionObservabilityError("estimated cost is invalid")
        _exact_keys(
            cost, {"amount_microunits", "currency", "is_estimate"}, "estimated cost"
        )
        if cost.get("is_estimate") is not True:
            raise ExecutionObservabilityError("estimated cost must remain an estimate")
        cost_input = {
            "amount_microunits": cost.get("amount_microunits"),
            "currency": cost.get("currency"),
        }

    rebuilt = build_execution_trace(
        correlation_id=payload.get("correlation_id"),
        request_id=payload.get("request_id"),
        client_id=payload.get("client_id"),
        project_id=payload.get("project_id"),
        work_item_id=payload.get("work_item_id"),
        intent_digest=payload.get("intent_digest"),
        context_digest=payload.get("context_digest"),
        plan_id=payload.get("plan_id"),
        approval_envelope_id=payload.get("approval_envelope_id"),
        delegation_mode=payload.get("delegation_mode"),
        model_assignment_ids=payload.get("model_assignment_ids"),
        queue_ids=payload.get("queue_ids"),
        agent_execution_ids=payload.get("agent_execution_ids"),
        verification_id=payload.get("verification_id"),
        evidence_digest=payload.get("evidence_digest"),
        status=payload.get("status"),
        started_at=payload.get("started_at"),
        ended_at=payload.get("ended_at"),
        token_usage=input_usage,
        estimated_cost=cost_input,
        retry_count=payload.get("retry_count"),
        cache_hit=payload.get("cache_hit"),
        failure_code=payload.get("failure_code"),
    )
    if rebuilt.as_dict() != dict(payload):
        raise ExecutionObservabilityError("execution trace content or digest is invalid")
    return rebuilt


@dataclass(frozen=True)
class StatusProjection:
    """One path-redacted user status derived from internal domain statuses."""

    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


def project_execution_status(
    *,
    correlation_id: str,
    project_id: str | None,
    work_item_id: str | None,
    source_statuses: Mapping[str, str],
    summary: str,
    updated_at: str,
    next_action: str | None = None,
    reason_codes: Sequence[str] = (),
    degraded: bool = False,
    derived_stale: bool = False,
    trace_digest: str | None = None,
) -> StatusProjection:
    """Map domain states to one canonical user-facing status.

    Raw domain states are hashed into `source_status_digest` and are not exposed
    by the projection. Domain adapters remain responsible for supplying their
    actual current state rather than inferring it from chat text.
    """

    if not isinstance(source_statuses, Mapping) or not source_statuses:
        raise ExecutionObservabilityError("source statuses must be a non-empty object")
    if not isinstance(degraded, bool) or not isinstance(derived_stale, bool):
        raise ExecutionObservabilityError("status flags must be booleans")

    normalized_sources: dict[str, str] = {}
    canonical: list[str] = []
    for domain, status in source_statuses.items():
        domain_id = _identifier(domain, "status domain")
        if not isinstance(status, str) or status not in DOMAIN_STATUS_MAP:
            raise ExecutionObservabilityError(
                f"status domain {domain_id} has an unsupported state"
            )
        normalized_sources[str(domain_id)] = status
        canonical.append(DOMAIN_STATUS_MAP[status])

    status = max(canonical, key=lambda item: STATUS_PRIORITY[item])
    if derived_stale and STATUS_PRIORITY[status] < STATUS_PRIORITY["derived-stale"]:
        status = "derived-stale"
    if degraded and status in {
        "preparing",
        "awaiting-approval",
        "queued",
        "running",
        "partially-completed",
        "awaiting-verification",
    }:
        status = "degraded"

    source_status_digest = hashlib.sha256(
        json.dumps(
            normalized_sources,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload: dict[str, object] = {
        "schema_ref": "schemas/status-projection.schema.json",
        "schema_version": 1,
        "correlation_id": _identifier(correlation_id, "correlation id"),
        "project_id": _identifier(project_id, "project id", nullable=True),
        "work_item_id": _identifier(work_item_id, "work item id", nullable=True),
        "status": status,
        "summary": _safe_text(summary, "status summary", limit=280),
        "next_action": _safe_text(
            next_action, "next action", limit=280, nullable=True
        ),
        "reason_codes": list(_identifiers(reason_codes, "reason codes")),
        "degraded": degraded,
        "derived_stale": derived_stale,
        "source_status_digest": source_status_digest,
        "trace_digest": _digest_value(trace_digest, "trace digest", nullable=True),
        "updated_at": _timestamp(updated_at, "updated at")[0],
        "grants_authority": False,
        "projection_digest": "",
    }
    payload["projection_digest"] = _digest(payload, "projection_digest")
    return StatusProjection(payload)


def parse_status_projection(payload: object) -> StatusProjection:
    """Validate persisted projection fields and its digest without raw states."""

    if not isinstance(payload, Mapping):
        raise ExecutionObservabilityError("status projection must be an object")
    _exact_keys(payload, PROJECTION_KEYS, "status projection")
    if payload.get("schema_ref") != "schemas/status-projection.schema.json":
        raise ExecutionObservabilityError("status projection schema reference is invalid")
    if payload.get("schema_version") != 1:
        raise ExecutionObservabilityError("status projection schema version is invalid")
    if payload.get("status") not in CANONICAL_STATUSES:
        raise ExecutionObservabilityError("status projection state is invalid")
    if payload.get("grants_authority") is not False:
        raise ExecutionObservabilityError("status projection must not grant authority")
    for field in ("degraded", "derived_stale"):
        if not isinstance(payload.get(field), bool):
            raise ExecutionObservabilityError(f"status projection {field} must be boolean")
    if payload.get("status") == "degraded" and payload.get("degraded") is not True:
        raise ExecutionObservabilityError(
            "degraded status requires the degraded evidence flag"
        )
    if (
        payload.get("status") == "derived-stale"
        and payload.get("derived_stale") is not True
    ):
        raise ExecutionObservabilityError(
            "derived-stale status requires the derived stale evidence flag"
        )

    _identifier(payload.get("correlation_id"), "correlation id")
    _identifier(payload.get("project_id"), "project id", nullable=True)
    _identifier(payload.get("work_item_id"), "work item id", nullable=True)
    _safe_text(payload.get("summary"), "status summary", limit=280)
    _safe_text(payload.get("next_action"), "next action", limit=280, nullable=True)
    _identifiers(payload.get("reason_codes"), "reason codes")
    _digest_value(payload.get("source_status_digest"), "source status digest")
    _digest_value(payload.get("trace_digest"), "trace digest", nullable=True)
    _timestamp(payload.get("updated_at"), "updated at")
    projection_digest = payload.get("projection_digest")
    if not isinstance(projection_digest, str) or not DIGEST.fullmatch(projection_digest):
        raise ExecutionObservabilityError("projection digest is invalid")
    if _digest(payload, "projection_digest") != projection_digest:
        raise ExecutionObservabilityError("projection digest does not match its content")
    return StatusProjection(dict(payload))
