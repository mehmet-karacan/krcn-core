"""Bounded measured-loop records and adaptive admission decisions.

This module is deliberately transport and scheduler neutral. It creates and
validates authority-free records that a later application adapter can persist
through the existing exact-plan boundaries. It never starts, kills, or resumes
a process by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from .agent_execution_identity import (
    AgentExecutionIdentity,
    AgentExecutionIdentityError,
    parse_agent_execution_identity,
)
from .json_documents import canonical_json_bytes


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
LOGICAL_REF = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/-]*$")
SAFE_TEXT = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]{1,512}$")
ABSOLUTE_PATH = re.compile(
    r"(^|[^A-Za-z0-9._~-])(?:[A-Za-z]:[\\/]|\\\\[^\\]|"
    r"/(?!/)[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)"
)
SECRET_MARKER = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|"
    r"client[_-]?secret|bearer)\b\s*[:=]"
)

DEFAULT_EFFECTS = ("plan", "read", "research")
EFFECTS = {
    "database",
    "execute",
    "network",
    "plan",
    "read",
    "research",
    "user-data",
    "write",
}
DIRECTIONS = {"maximize", "minimize"}
ITERATION_DECISIONS = {"accept", "continue", "revert"}
STOP_REASONS = {"accept", "budget", "cancel", "continue", "plateau", "revert", "zombie"}
STATES = {"cancelled", "completed", "planned", "recovery-required", "running", "stopped"}
TERMINAL_STATES = {"cancelled", "completed", "recovery-required", "stopped"}


class MeasuredLoopError(ValueError):
    """Raised when a measured-loop record is unsafe or internally inconsistent."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _exact(payload: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise MeasuredLoopError(f"{label} fields are invalid")


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise MeasuredLoopError(f"{label} must be a portable identifier")
    return value


def _digest_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise MeasuredLoopError(f"{label} must be a SHA-256 digest")
    return value


def _logical_ref(value: object, label: str) -> str:
    if not isinstance(value, str) or not LOGICAL_REF.fullmatch(value):
        raise MeasuredLoopError(f"{label} must be a portable logical reference")
    if ABSOLUTE_PATH.search(value):
        raise MeasuredLoopError(f"{label} must not contain a physical path")
    return value


def _safe_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise MeasuredLoopError(f"{label} must be text")
    text = value.strip()
    if not SAFE_TEXT.fullmatch(text):
        raise MeasuredLoopError(f"{label} is empty, too long, or contains control characters")
    if ABSOLUTE_PATH.search(text) or SECRET_MARKER.search(text):
        raise MeasuredLoopError(f"{label} contains unsafe content")
    return text


def _integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MeasuredLoopError(f"{label} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise MeasuredLoopError(f"{label} exceeds {maximum}")
    return value


def _timestamp(value: object, label: str) -> tuple[str, datetime]:
    if not isinstance(value, str):
        raise MeasuredLoopError(f"{label} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MeasuredLoopError(f"{label} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise MeasuredLoopError(f"{label} must include a timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat().replace("+00:00", "Z"), utc


def _sorted_unique(values: object, label: str, validator) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise MeasuredLoopError(f"{label} must be a list")
    normalized = tuple(validator(value, f"{label} entry") for value in values)
    if not normalized or len(normalized) != len(set(normalized)):
        raise MeasuredLoopError(f"{label} must be non-empty and unique")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class MeasuredLoopPolicy:
    payload: Mapping[str, object]

    @property
    def policy_digest(self) -> str:
        return _digest(self.payload)

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


@dataclass(frozen=True)
class MeasuredLoopRecord:
    payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return dict(self.payload)


def parse_measured_loop_policy(payload: object) -> MeasuredLoopPolicy:
    expected = {
        "schema_ref",
        "schema_version",
        "max_rounds_ceiling",
        "max_wall_time_seconds_ceiling",
        "max_input_tokens_ceiling",
        "max_output_tokens_ceiling",
        "max_cost_microunits_ceiling",
        "max_attempts_ceiling",
        "max_concurrency_ceiling",
        "plateau_rounds",
        "cooldown_seconds",
        "zombie_after_seconds",
        "default_allowed_effects",
        "max_cpu_pressure_basis_points",
        "max_ram_pressure_basis_points",
        "min_provider_quota_basis_points",
        "min_cost_headroom_microunits",
        "max_failure_pressure_basis_points",
    }
    if not isinstance(payload, Mapping):
        raise MeasuredLoopError("measured loop policy must be an object")
    _exact(payload, expected, "measured loop policy")
    if (
        payload.get("schema_ref") != "schemas/measured-loop-policy.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("default_allowed_effects") != list(DEFAULT_EFFECTS)
    ):
        raise MeasuredLoopError("measured loop policy contract is invalid")
    positive = (
        "max_rounds_ceiling",
        "max_wall_time_seconds_ceiling",
        "max_input_tokens_ceiling",
        "max_output_tokens_ceiling",
        "max_cost_microunits_ceiling",
        "max_attempts_ceiling",
        "max_concurrency_ceiling",
        "plateau_rounds",
        "zombie_after_seconds",
    )
    for key in positive:
        _integer(payload.get(key), key, minimum=1)
    _integer(payload.get("cooldown_seconds"), "cooldown_seconds")
    for key in (
        "max_cpu_pressure_basis_points",
        "max_ram_pressure_basis_points",
        "min_provider_quota_basis_points",
        "max_failure_pressure_basis_points",
    ):
        _integer(payload.get(key), key, maximum=10_000)
    _integer(payload.get("min_cost_headroom_microunits"), "min_cost_headroom_microunits")
    if int(payload["plateau_rounds"]) > int(payload["max_rounds_ceiling"]):
        raise MeasuredLoopError("plateau rounds exceed the round ceiling")
    return MeasuredLoopPolicy(dict(payload))


def load_measured_loop_policy(repo_root: Path) -> MeasuredLoopPolicy:
    try:
        payload = json.loads(
            (repo_root / "config" / "measured-loop.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise MeasuredLoopError("measured loop policy cannot be loaded") from exc
    return parse_measured_loop_policy(payload)


def _metric(metric: object) -> dict[str, object]:
    expected = {
        "metric_id",
        "owner_ref",
        "source_ref",
        "direction",
        "unit",
        "baseline",
        "target",
        "minimum_delta",
    }
    if not isinstance(metric, Mapping):
        raise MeasuredLoopError("metric must be an object")
    _exact(metric, expected, "metric")
    metric_id = _identifier(metric.get("metric_id"), "metric id")
    owner_ref = _logical_ref(metric.get("owner_ref"), "metric owner")
    source_ref = _logical_ref(metric.get("source_ref"), "metric source")
    direction = metric.get("direction")
    if direction not in DIRECTIONS:
        raise MeasuredLoopError("metric direction is invalid")
    unit = _identifier(metric.get("unit"), "metric unit")
    baseline = _integer(metric.get("baseline"), "metric baseline", minimum=-10**15)
    target = _integer(metric.get("target"), "metric target", minimum=-10**15)
    minimum_delta = _integer(metric.get("minimum_delta"), "metric minimum delta", minimum=1)
    if direction == "maximize" and target < baseline:
        raise MeasuredLoopError("maximize target must not be below baseline")
    if direction == "minimize" and target > baseline:
        raise MeasuredLoopError("minimize target must not be above baseline")
    return {
        "metric_id": metric_id,
        "owner_ref": owner_ref,
        "source_ref": source_ref,
        "direction": direction,
        "unit": unit,
        "baseline": baseline,
        "target": target,
        "minimum_delta": minimum_delta,
    }


def _budget(value: object, policy: MeasuredLoopPolicy) -> dict[str, int]:
    expected = {
        "max_rounds",
        "max_wall_time_seconds",
        "max_input_tokens",
        "max_output_tokens",
        "max_cost_microunits",
        "max_attempts",
        "max_concurrency",
    }
    if not isinstance(value, Mapping):
        raise MeasuredLoopError("loop budget must be an object")
    _exact(value, expected, "loop budget")
    limits = {
        "max_rounds": "max_rounds_ceiling",
        "max_wall_time_seconds": "max_wall_time_seconds_ceiling",
        "max_input_tokens": "max_input_tokens_ceiling",
        "max_output_tokens": "max_output_tokens_ceiling",
        "max_cost_microunits": "max_cost_microunits_ceiling",
        "max_attempts": "max_attempts_ceiling",
        "max_concurrency": "max_concurrency_ceiling",
    }
    result = {}
    for key, ceiling in limits.items():
        result[key] = _integer(value.get(key), key, minimum=1, maximum=int(policy.payload[ceiling]))
    return result


def _bounded_budget(value: object) -> dict[str, int]:
    """Validate a persisted budget without silently inventing policy ceilings."""
    expected = {
        "max_rounds",
        "max_wall_time_seconds",
        "max_input_tokens",
        "max_output_tokens",
        "max_cost_microunits",
        "max_attempts",
        "max_concurrency",
    }
    if not isinstance(value, Mapping):
        raise MeasuredLoopError("loop budget must be an object")
    _exact(value, expected, "loop budget")
    return {key: _integer(value.get(key), key, minimum=1) for key in sorted(expected)}


def _effect_authorizations(
    effects: tuple[str, ...], authorizations: object
) -> list[dict[str, str]]:
    if isinstance(authorizations, (str, bytes)) or not isinstance(authorizations, Sequence):
        raise MeasuredLoopError("effect authorizations must be a list")
    result: list[dict[str, str]] = []
    for item in authorizations:
        if not isinstance(item, Mapping):
            raise MeasuredLoopError("effect authorization must be an object")
        _exact(item, {"effect", "approval_ref", "authorization_digest"}, "effect authorization")
        effect = item.get("effect")
        if effect not in EFFECTS or effect in DEFAULT_EFFECTS:
            raise MeasuredLoopError("effect authorization must name a non-default effect")
        result.append(
            {
                "effect": str(effect),
                "approval_ref": _logical_ref(item.get("approval_ref"), "approval ref"),
                "authorization_digest": _digest_value(
                    item.get("authorization_digest"), "authorization digest"
                ),
            }
        )
    result.sort(key=lambda item: item["effect"])
    if len({item["effect"] for item in result}) != len(result):
        raise MeasuredLoopError("effect authorizations must be unique")
    required = set(effects) - set(DEFAULT_EFFECTS)
    if required != {item["effect"] for item in result}:
        raise MeasuredLoopError("every non-default effect requires an existing approval reference")
    return result


def _execution_identity(value: object, role: str) -> AgentExecutionIdentity:
    try:
        identity = parse_agent_execution_identity(value)
    except AgentExecutionIdentityError as exc:
        raise MeasuredLoopError("loop execution identity is invalid") from exc
    if identity.role != role:
        raise MeasuredLoopError(f"{role} execution identity has the wrong role")
    return identity


def _previous_run(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    expected = {"run_id", "state", "stop_reason", "ended_at", "status_digest"}
    if not isinstance(value, Mapping):
        raise MeasuredLoopError("previous run must be an object or null")
    _exact(value, expected, "previous run")
    state = value.get("state")
    stop_reason = value.get("stop_reason")
    if state not in TERMINAL_STATES or stop_reason not in STOP_REASONS - {"continue"}:
        raise MeasuredLoopError("previous run must be terminal")
    ended_at, _ = _timestamp(value.get("ended_at"), "previous run ended at")
    return {
        "run_id": _identifier(value.get("run_id"), "previous run id"),
        "state": state,
        "stop_reason": stop_reason,
        "ended_at": ended_at,
        "status_digest": _digest_value(value.get("status_digest"), "previous status digest"),
    }


def build_measured_loop_plan(
    policy: MeasuredLoopPolicy,
    *,
    run_id: str,
    project_id: str,
    work_item_id: str,
    task_id: str,
    task_plan_id: str,
    task_authorization_id: str,
    objective_id: str,
    objective_statement: str,
    constraint_refs: Sequence[str],
    acceptance_refs: Sequence[str],
    metrics: Sequence[Mapping[str, object]],
    budget: Mapping[str, object],
    worker_execution_identity: Mapping[str, object],
    verifier_execution_identity: Mapping[str, object],
    created_at: str,
    allowed_effects: Sequence[str] = DEFAULT_EFFECTS,
    effect_authorizations: Sequence[Mapping[str, object]] = (),
    previous_status: Mapping[str, object] | None = None,
) -> MeasuredLoopRecord:
    created, created_time = _timestamp(created_at, "plan created at")
    effects = _sorted_unique(allowed_effects, "allowed effects", lambda value, _: str(value))
    if any(effect not in EFFECTS for effect in effects):
        raise MeasuredLoopError("allowed effect is invalid")
    authorizations = _effect_authorizations(effects, effect_authorizations)
    metric_items = [_metric(item) for item in metrics]
    metric_items.sort(key=lambda item: str(item["metric_id"]))
    if not metric_items or len({item["metric_id"] for item in metric_items}) != len(metric_items):
        raise MeasuredLoopError("metrics must be non-empty and unique")
    worker = _execution_identity(worker_execution_identity, "worker")
    verifier = _execution_identity(verifier_execution_identity, "verifier")
    normalized_task = _identifier(task_id, "task id")
    normalized_task_plan = _digest_value(task_plan_id, "task plan id")
    if any(identity.task_id != normalized_task for identity in (worker, verifier)):
        raise MeasuredLoopError("execution identities do not match the task")
    if any(identity.plan_id != normalized_task_plan for identity in (worker, verifier)):
        raise MeasuredLoopError("execution identities do not match the task plan")
    if (
        worker.step_id == verifier.step_id
        or worker.actor_digest == verifier.actor_digest
        or worker.assignment_digest == verifier.assignment_digest
        or worker.execution_identity_id == verifier.execution_identity_id
    ):
        raise MeasuredLoopError("worker and verifier identities are not independent")
    previous = None
    if previous_status is not None:
        previous_record = parse_measured_loop_status(previous_status).payload
        previous = _previous_run(
            {
                "run_id": previous_record["run_id"],
                "state": previous_record["state"],
                "stop_reason": previous_record["stop_reason"],
                "ended_at": previous_record["ended_at"],
                "status_digest": previous_record["status_digest"],
            }
        )
        _, previous_end = _timestamp(previous["ended_at"], "previous run ended at")
        available_at = previous_end + timedelta(seconds=int(policy.payload["cooldown_seconds"]))
        if created_time < available_at:
            raise MeasuredLoopError("measured loop cooldown has not elapsed")
    objective = {
        "objective_id": _identifier(objective_id, "objective id"),
        "statement": _safe_text(objective_statement, "objective statement"),
        "constraint_refs": list(
            _sorted_unique(constraint_refs, "constraint refs", _logical_ref)
        ),
        "acceptance_refs": list(
            _sorted_unique(acceptance_refs, "acceptance refs", _logical_ref)
        ),
    }
    objective["objective_digest"] = _digest(objective)
    body: dict[str, object] = {
        "schema_ref": "schemas/measured-loop-plan.schema.json",
        "schema_version": 1,
        "run_id": _identifier(run_id, "run id"),
        "project_id": _identifier(project_id, "project id"),
        "work_item_id": _identifier(work_item_id, "work item id"),
        "task_id": normalized_task,
        "task_plan_id": normalized_task_plan,
        "task_authorization_id": _digest_value(
            task_authorization_id, "task authorization id"
        ),
        "policy_digest": policy.policy_digest,
        "created_at": created,
        "objective": objective,
        "metrics": metric_items,
        "budget": _budget(budget, policy),
        "allowed_effects": list(effects),
        "effect_authorizations": authorizations,
        "worker_execution_identity": worker.as_dict(),
        "verifier_execution_identity": verifier.as_dict(),
        "previous_run": previous,
        "unattended_mode": True,
        "grants_authority": False,
    }
    body["plan_digest"] = _digest(body)
    return MeasuredLoopRecord(body)


def parse_measured_loop_plan(
    payload: object, policy: MeasuredLoopPolicy | None = None
) -> MeasuredLoopRecord:
    expected = {
        "schema_ref",
        "schema_version",
        "run_id",
        "project_id",
        "work_item_id",
        "task_id",
        "task_plan_id",
        "task_authorization_id",
        "policy_digest",
        "created_at",
        "objective",
        "metrics",
        "budget",
        "allowed_effects",
        "effect_authorizations",
        "worker_execution_identity",
        "verifier_execution_identity",
        "previous_run",
        "unattended_mode",
        "grants_authority",
        "plan_digest",
    }
    if not isinstance(payload, Mapping):
        raise MeasuredLoopError("measured loop plan must be an object")
    _exact(payload, expected, "measured loop plan")
    if (
        payload.get("schema_ref") != "schemas/measured-loop-plan.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("unattended_mode") is not True
        or payload.get("grants_authority") is not False
    ):
        raise MeasuredLoopError("measured loop plan contract is invalid")
    for key in ("run_id", "project_id", "work_item_id", "task_id"):
        _identifier(payload.get(key), key)
    for key in ("task_plan_id", "task_authorization_id", "policy_digest"):
        _digest_value(payload.get(key), key)
    _timestamp(payload.get("created_at"), "plan created at")
    objective = payload.get("objective")
    if not isinstance(objective, Mapping):
        raise MeasuredLoopError("objective must be an object")
    _exact(
        objective,
        {"objective_id", "statement", "constraint_refs", "acceptance_refs", "objective_digest"},
        "objective",
    )
    _identifier(objective.get("objective_id"), "objective id")
    _safe_text(objective.get("statement"), "objective statement")
    constraint_refs = _sorted_unique(objective.get("constraint_refs"), "constraint refs", _logical_ref)
    acceptance_refs = _sorted_unique(objective.get("acceptance_refs"), "acceptance refs", _logical_ref)
    if list(constraint_refs) != objective.get("constraint_refs") or list(acceptance_refs) != objective.get("acceptance_refs"):
        raise MeasuredLoopError("objective references must use canonical order")
    objective_body = {key: value for key, value in objective.items() if key != "objective_digest"}
    if objective.get("objective_digest") != _digest(objective_body):
        raise MeasuredLoopError("objective digest is invalid")
    metrics = payload.get("metrics")
    if isinstance(metrics, (str, bytes)) or not isinstance(metrics, Sequence):
        raise MeasuredLoopError("metrics must be a list")
    normalized_metrics = [_metric(item) for item in metrics]
    if normalized_metrics != sorted(normalized_metrics, key=lambda item: str(item["metric_id"])):
        raise MeasuredLoopError("metrics must use canonical order")
    if not normalized_metrics or len({item["metric_id"] for item in normalized_metrics}) != len(normalized_metrics):
        raise MeasuredLoopError("metrics must be non-empty and unique")
    effects = _sorted_unique(payload.get("allowed_effects"), "allowed effects", lambda value, _: str(value))
    if list(effects) != payload.get("allowed_effects") or any(effect not in EFFECTS for effect in effects):
        raise MeasuredLoopError("allowed effects are invalid or non-canonical")
    authorizations = _effect_authorizations(effects, payload.get("effect_authorizations"))
    if authorizations != payload.get("effect_authorizations"):
        raise MeasuredLoopError("effect authorizations must use canonical order")
    worker = _execution_identity(payload.get("worker_execution_identity"), "worker")
    verifier = _execution_identity(payload.get("verifier_execution_identity"), "verifier")
    if (
        worker.task_id != payload["task_id"]
        or verifier.task_id != payload["task_id"]
        or worker.plan_id != payload["task_plan_id"]
        or verifier.plan_id != payload["task_plan_id"]
        or worker.step_id == verifier.step_id
        or worker.actor_digest == verifier.actor_digest
        or worker.assignment_digest == verifier.assignment_digest
    ):
        raise MeasuredLoopError("execution identity binding or independence is invalid")
    _previous_run(payload.get("previous_run"))
    if policy is not None:
        if payload["policy_digest"] != policy.policy_digest:
            raise MeasuredLoopError("measured loop policy changed after planning")
        _budget(payload.get("budget"), policy)
    else:
        _bounded_budget(payload.get("budget"))
    claimed = payload.get("plan_digest")
    _digest_value(claimed, "plan digest")
    if claimed != _digest({key: value for key, value in payload.items() if key != "plan_digest"}):
        raise MeasuredLoopError("measured loop plan digest is invalid")
    return MeasuredLoopRecord(dict(payload))


def _metric_observations(
    plan: Mapping[str, object],
    values: Mapping[str, object],
    prior: Mapping[str, int],
) -> list[dict[str, object]]:
    metrics = {str(item["metric_id"]): item for item in plan["metrics"]}  # type: ignore[index]
    if set(values) != set(metrics):
        raise MeasuredLoopError("iteration metric values do not match the plan")
    result = []
    for metric_id in sorted(metrics):
        metric = metrics[metric_id]
        value = _integer(values[metric_id], f"{metric_id} value", minimum=-10**15)
        previous = prior.get(metric_id, int(metric["baseline"]))
        delta = value - previous
        improvement = (
            delta >= int(metric["minimum_delta"])
            if metric["direction"] == "maximize"
            else -delta >= int(metric["minimum_delta"])
        )
        target_met = (
            value >= int(metric["target"])
            if metric["direction"] == "maximize"
            else value <= int(metric["target"])
        )
        result.append(
            {
                "metric_id": metric_id,
                "owner_ref": metric["owner_ref"],
                "source_ref": metric["source_ref"],
                "direction": metric["direction"],
                "unit": metric["unit"],
                "value": value,
                "delta_from_previous": delta,
                "minimum_delta_met": improvement,
                "target_met": target_met,
            }
        )
    return result


def _iteration_usage(value: object) -> dict[str, int]:
    expected = {"input_tokens", "output_tokens", "cost_microunits", "attempts", "peak_concurrency"}
    if not isinstance(value, Mapping):
        raise MeasuredLoopError("iteration usage must be an object")
    _exact(value, expected, "iteration usage")
    return {
        "input_tokens": _integer(value.get("input_tokens"), "input tokens"),
        "output_tokens": _integer(value.get("output_tokens"), "output tokens"),
        "cost_microunits": _integer(value.get("cost_microunits"), "cost microunits"),
        "attempts": _integer(value.get("attempts"), "attempts", minimum=1),
        "peak_concurrency": _integer(value.get("peak_concurrency"), "peak concurrency", minimum=1),
    }


def parse_iteration_record(payload: object) -> MeasuredLoopRecord:
    expected = {
        "schema_ref",
        "schema_version",
        "run_id",
        "plan_digest",
        "iteration_number",
        "previous_iteration_digest",
        "started_at",
        "ended_at",
        "duration_ms",
        "worker_execution_identity_id",
        "verifier_execution_identity_id",
        "metrics",
        "improvement_observed",
        "usage",
        "decision",
        "verification_passed",
        "evidence_digest",
        "checkpoint_digest",
        "verifier_evidence_digest",
        "grants_authority",
        "iteration_digest",
    }
    if not isinstance(payload, Mapping):
        raise MeasuredLoopError("iteration record must be an object")
    _exact(payload, expected, "iteration record")
    if (
        payload.get("schema_ref") != "schemas/measured-loop-iteration.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("grants_authority") is not False
    ):
        raise MeasuredLoopError("iteration record contract is invalid")
    _identifier(payload.get("run_id"), "run id")
    _digest_value(payload.get("plan_digest"), "plan digest")
    _integer(payload.get("iteration_number"), "iteration number", minimum=1)
    previous = payload.get("previous_iteration_digest")
    if previous is not None:
        _digest_value(previous, "previous iteration digest")
    started, start_time = _timestamp(payload.get("started_at"), "iteration started at")
    ended, end_time = _timestamp(payload.get("ended_at"), "iteration ended at")
    if end_time < start_time:
        raise MeasuredLoopError("iteration ends before it starts")
    if payload.get("started_at") != started or payload.get("ended_at") != ended:
        raise MeasuredLoopError("iteration timestamps are not canonical UTC")
    duration = _integer(payload.get("duration_ms"), "duration ms")
    if duration != int((end_time - start_time).total_seconds() * 1000):
        raise MeasuredLoopError("iteration duration is invalid")
    for key in (
        "worker_execution_identity_id",
        "verifier_execution_identity_id",
        "evidence_digest",
        "checkpoint_digest",
        "verifier_evidence_digest",
    ):
        _digest_value(payload.get(key), key)
    metrics = payload.get("metrics")
    if isinstance(metrics, (str, bytes)) or not isinstance(metrics, Sequence) or not metrics:
        raise MeasuredLoopError("iteration metrics must be a non-empty list")
    metric_ids = []
    any_improvement = False
    for item in metrics:
        if not isinstance(item, Mapping):
            raise MeasuredLoopError("iteration metric must be an object")
        _exact(
            item,
            {
                "metric_id", "owner_ref", "source_ref", "direction", "unit", "value",
                "delta_from_previous", "minimum_delta_met", "target_met",
            },
            "iteration metric",
        )
        metric_ids.append(_identifier(item.get("metric_id"), "metric id"))
        _logical_ref(item.get("owner_ref"), "metric owner")
        _logical_ref(item.get("source_ref"), "metric source")
        if item.get("direction") not in DIRECTIONS:
            raise MeasuredLoopError("metric direction is invalid")
        _identifier(item.get("unit"), "metric unit")
        _integer(item.get("value"), "metric value", minimum=-10**15)
        _integer(item.get("delta_from_previous"), "metric delta", minimum=-2 * 10**15)
        if not isinstance(item.get("minimum_delta_met"), bool) or not isinstance(item.get("target_met"), bool):
            raise MeasuredLoopError("metric flags must be boolean")
        any_improvement = any_improvement or bool(item["minimum_delta_met"])
    if metric_ids != sorted(metric_ids) or len(metric_ids) != len(set(metric_ids)):
        raise MeasuredLoopError("iteration metrics are non-canonical or duplicated")
    if payload.get("improvement_observed") is not any_improvement:
        raise MeasuredLoopError("iteration improvement flag is invalid")
    _iteration_usage(payload.get("usage"))
    decision = payload.get("decision")
    verified = payload.get("verification_passed")
    if decision not in ITERATION_DECISIONS or not isinstance(verified, bool):
        raise MeasuredLoopError("iteration decision or verification is invalid")
    if decision in {"accept", "continue"} and not verified:
        raise MeasuredLoopError("accepted or continuing iteration requires verification")
    if decision == "accept" and not all(bool(item["target_met"]) for item in metrics):
        raise MeasuredLoopError("accepted iteration has unmet targets")
    claimed = _digest_value(payload.get("iteration_digest"), "iteration digest")
    if claimed != _digest({key: value for key, value in payload.items() if key != "iteration_digest"}):
        raise MeasuredLoopError("iteration digest is invalid")
    return MeasuredLoopRecord(dict(payload))


def validate_iteration_chain(
    plan: Mapping[str, object] | MeasuredLoopRecord,
    iterations: Sequence[Mapping[str, object]],
) -> tuple[MeasuredLoopRecord, ...]:
    plan_record = parse_measured_loop_plan(
        plan.payload if isinstance(plan, MeasuredLoopRecord) else plan
    ).payload
    parsed: list[MeasuredLoopRecord] = []
    previous_digest: str | None = None
    previous_values: dict[str, int] = {}
    previous_end: datetime | None = None
    totals = {"input_tokens": 0, "output_tokens": 0, "cost_microunits": 0, "attempts": 0}
    budget = plan_record["budget"]
    _, plan_time = _timestamp(plan_record["created_at"], "plan created at")
    deadline = plan_time + timedelta(
        seconds=int(plan_record["budget"]["max_wall_time_seconds"])
    )
    for index, raw in enumerate(iterations, start=1):
        record = parse_iteration_record(raw)
        item = record.payload
        if (
            item["run_id"] != plan_record["run_id"]
            or item["plan_digest"] != plan_record["plan_digest"]
            or item["iteration_number"] != index
            or item["previous_iteration_digest"] != previous_digest
            or item["worker_execution_identity_id"]
            != plan_record["worker_execution_identity"]["execution_identity_id"]
            or item["verifier_execution_identity_id"]
            != plan_record["verifier_execution_identity"]["execution_identity_id"]
        ):
            raise MeasuredLoopError("iteration chain binding is invalid")
        expected_metrics = _metric_observations(
            plan_record,
            {str(metric["metric_id"]): metric["value"] for metric in item["metrics"]},
            previous_values,
        )
        if item["metrics"] != expected_metrics:
            raise MeasuredLoopError("iteration metric evidence is invalid")
        _, current_start = _timestamp(item["started_at"], "iteration started at")
        _, current_end = _timestamp(item["ended_at"], "iteration ended at")
        if current_start < plan_time or current_end > deadline:
            raise MeasuredLoopError("iteration is outside the immutable wall-time window")
        if previous_end is not None and current_start < previous_end:
            raise MeasuredLoopError("iteration chronology overlaps a previous record")
        previous_end = current_end
        previous_values = {
            str(metric["metric_id"]): int(metric["value"]) for metric in item["metrics"]
        }
        usage = item["usage"]
        for key in totals:
            totals[key] += int(usage[key])
        if (
            totals["input_tokens"] > int(budget["max_input_tokens"])
            or totals["output_tokens"] > int(budget["max_output_tokens"])
            or totals["cost_microunits"] > int(budget["max_cost_microunits"])
            or totals["attempts"] > int(budget["max_attempts"])
            or index > int(budget["max_rounds"])
            or int(usage["peak_concurrency"]) > int(budget["max_concurrency"])
        ):
            raise MeasuredLoopError("iteration chain exceeds an immutable budget")
        if parsed and parsed[-1].payload["decision"] in {"accept", "revert"}:
            raise MeasuredLoopError("iteration exists after a terminal decision")
        previous_digest = str(item["iteration_digest"])
        parsed.append(record)
    return tuple(parsed)


def create_iteration_record(
    plan: Mapping[str, object] | MeasuredLoopRecord,
    previous_iterations: Sequence[Mapping[str, object]],
    *,
    started_at: str,
    ended_at: str,
    metric_values: Mapping[str, object],
    usage: Mapping[str, object],
    decision: str,
    verification_passed: bool,
    evidence_digest: str,
    checkpoint_digest: str,
    verifier_evidence_digest: str,
    cancellation_record: Mapping[str, object] | None = None,
) -> MeasuredLoopRecord:
    plan_record = parse_measured_loop_plan(
        plan.payload if isinstance(plan, MeasuredLoopRecord) else plan
    ).payload
    if cancellation_record is not None:
        cancellation = parse_cancellation_record(cancellation_record).payload
        if cancellation["run_id"] == plan_record["run_id"]:
            raise MeasuredLoopError("cancelled measured loop cannot accept a new iteration")
    previous = validate_iteration_chain(plan_record, previous_iterations)
    if previous and previous[-1].payload["decision"] in {"accept", "revert"}:
        raise MeasuredLoopError("terminal measured loop cannot continue")
    started, start_time = _timestamp(started_at, "iteration started at")
    ended, end_time = _timestamp(ended_at, "iteration ended at")
    _, plan_time = _timestamp(plan_record["created_at"], "plan created at")
    if start_time < plan_time or end_time < start_time:
        raise MeasuredLoopError("iteration time is outside the plan timeline")
    if (end_time - plan_time).total_seconds() > int(plan_record["budget"]["max_wall_time_seconds"]):
        raise MeasuredLoopError("iteration exceeds the wall-time budget")
    prior_values = {}
    if previous:
        prior_values = {
            str(item["metric_id"]): int(item["value"])
            for item in previous[-1].payload["metrics"]
        }
    observations = _metric_observations(plan_record, metric_values, prior_values)
    normalized_usage = _iteration_usage(usage)
    if decision not in ITERATION_DECISIONS or not isinstance(verification_passed, bool):
        raise MeasuredLoopError("iteration decision or verification is invalid")
    if decision in {"accept", "continue"} and not verification_passed:
        raise MeasuredLoopError("accepted or continuing iteration requires verification")
    if decision == "accept" and not all(bool(item["target_met"]) for item in observations):
        raise MeasuredLoopError("accepted iteration has unmet targets")
    body: dict[str, object] = {
        "schema_ref": "schemas/measured-loop-iteration.schema.json",
        "schema_version": 1,
        "run_id": plan_record["run_id"],
        "plan_digest": plan_record["plan_digest"],
        "iteration_number": len(previous) + 1,
        "previous_iteration_digest": (
            previous[-1].payload["iteration_digest"] if previous else None
        ),
        "started_at": started,
        "ended_at": ended,
        "duration_ms": int((end_time - start_time).total_seconds() * 1000),
        "worker_execution_identity_id": plan_record["worker_execution_identity"][
            "execution_identity_id"
        ],
        "verifier_execution_identity_id": plan_record["verifier_execution_identity"][
            "execution_identity_id"
        ],
        "metrics": observations,
        "improvement_observed": any(
            bool(item["minimum_delta_met"]) for item in observations
        ),
        "usage": normalized_usage,
        "decision": decision,
        "verification_passed": verification_passed,
        "evidence_digest": _digest_value(evidence_digest, "evidence digest"),
        "checkpoint_digest": _digest_value(checkpoint_digest, "checkpoint digest"),
        "verifier_evidence_digest": _digest_value(
            verifier_evidence_digest, "verifier evidence digest"
        ),
        "grants_authority": False,
    }
    body["iteration_digest"] = _digest(body)
    candidate = [record.as_dict() for record in previous] + [body]
    validate_iteration_chain(plan_record, candidate)
    return MeasuredLoopRecord(body)


def create_cancellation_record(
    plan: Mapping[str, object] | MeasuredLoopRecord,
    *,
    requested_at: str,
    requester_digest: str,
    reason_code: str,
) -> MeasuredLoopRecord:
    plan_record = parse_measured_loop_plan(
        plan.payload if isinstance(plan, MeasuredLoopRecord) else plan
    ).payload
    requested, requested_time = _timestamp(requested_at, "cancellation requested at")
    _, created_time = _timestamp(plan_record["created_at"], "plan created at")
    if requested_time < created_time:
        raise MeasuredLoopError("cancellation predates the plan")
    body: dict[str, object] = {
        "schema_ref": "schemas/measured-loop-cancellation.schema.json",
        "schema_version": 1,
        "run_id": plan_record["run_id"],
        "plan_digest": plan_record["plan_digest"],
        "requested_at": requested,
        "requester_digest": _digest_value(requester_digest, "requester digest"),
        "reason_code": _identifier(reason_code, "cancellation reason"),
        "record_only": True,
        "process_signal_sent": False,
        "process_termination_claimed": False,
        "grants_authority": False,
    }
    body["cancellation_digest"] = _digest(body)
    return MeasuredLoopRecord(body)


def parse_cancellation_record(payload: object) -> MeasuredLoopRecord:
    expected = {
        "schema_ref", "schema_version", "run_id", "plan_digest", "requested_at",
        "requester_digest", "reason_code", "record_only", "process_signal_sent",
        "process_termination_claimed", "grants_authority", "cancellation_digest",
    }
    if not isinstance(payload, Mapping):
        raise MeasuredLoopError("cancellation record must be an object")
    _exact(payload, expected, "cancellation record")
    if (
        payload.get("schema_ref") != "schemas/measured-loop-cancellation.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("record_only") is not True
        or payload.get("process_signal_sent") is not False
        or payload.get("process_termination_claimed") is not False
        or payload.get("grants_authority") is not False
    ):
        raise MeasuredLoopError("cancellation record contract is invalid")
    _identifier(payload.get("run_id"), "run id")
    for key in ("plan_digest", "requester_digest"):
        _digest_value(payload.get(key), key)
    _identifier(payload.get("reason_code"), "cancellation reason")
    _timestamp(payload.get("requested_at"), "cancellation requested at")
    claimed = _digest_value(payload.get("cancellation_digest"), "cancellation digest")
    if claimed != _digest({key: value for key, value in payload.items() if key != "cancellation_digest"}):
        raise MeasuredLoopError("cancellation digest is invalid")
    return MeasuredLoopRecord(dict(payload))


def _aggregate_usage(iterations: Sequence[MeasuredLoopRecord]) -> dict[str, int]:
    totals = {
        "rounds": len(iterations),
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_microunits": 0,
        "attempts": 0,
        "peak_concurrency": 0,
    }
    for record in iterations:
        usage = record.payload["usage"]
        for key in ("input_tokens", "output_tokens", "cost_microunits", "attempts"):
            totals[key] += int(usage[key])
        totals["peak_concurrency"] = max(totals["peak_concurrency"], int(usage["peak_concurrency"]))
    return totals


def _budget_stop_codes(
    usage: Mapping[str, object],
    budget: Mapping[str, object],
    *,
    elapsed_seconds: int,
) -> tuple[str, ...]:
    counters = (
        ("rounds", "max_rounds", "round-budget"),
        ("input_tokens", "max_input_tokens", "input-token-budget"),
        ("output_tokens", "max_output_tokens", "output-token-budget"),
        ("cost_microunits", "max_cost_microunits", "cost-budget"),
        ("attempts", "max_attempts", "attempt-budget"),
    )
    reasons = [
        reason
        for usage_key, budget_key, reason in counters
        if int(usage[usage_key]) >= int(budget[budget_key])
    ]
    if elapsed_seconds >= int(budget["max_wall_time_seconds"]):
        reasons.append("wall-time-budget")
    return tuple(sorted(reasons))


def build_measured_loop_status(
    policy: MeasuredLoopPolicy,
    plan: Mapping[str, object] | MeasuredLoopRecord,
    iterations: Sequence[Mapping[str, object]],
    *,
    observed_at: str,
    cancellation_record: Mapping[str, object] | None = None,
) -> MeasuredLoopRecord:
    plan_record = parse_measured_loop_plan(
        plan.payload if isinstance(plan, MeasuredLoopRecord) else plan, policy
    ).payload
    chain = validate_iteration_chain(plan_record, iterations)
    observed, observed_time = _timestamp(observed_at, "status observed at")
    _, created_time = _timestamp(plan_record["created_at"], "plan created at")
    if observed_time < created_time:
        raise MeasuredLoopError("status predates the plan")
    if chain:
        _, latest_end = _timestamp(chain[-1].payload["ended_at"], "latest iteration ended at")
        if observed_time < latest_end:
            raise MeasuredLoopError("status predates the latest verified iteration")
    cancellation = None
    if cancellation_record is not None:
        cancellation = parse_cancellation_record(cancellation_record).payload
        if (
            cancellation["run_id"] != plan_record["run_id"]
            or cancellation["plan_digest"] != plan_record["plan_digest"]
        ):
            raise MeasuredLoopError("cancellation does not match the measured loop")
        _, cancellation_time = _timestamp(cancellation["requested_at"], "cancellation requested at")
        if cancellation_time > observed_time:
            raise MeasuredLoopError("status predates the cancellation record")
    totals = _aggregate_usage(chain)
    budget = plan_record["budget"]
    latest = chain[-1].payload if chain else None
    elapsed = int((observed_time - created_time).total_seconds())
    budget_reached = bool(
        _budget_stop_codes(totals, budget, elapsed_seconds=elapsed)
    )
    plateau_rounds = int(policy.payload["plateau_rounds"])
    plateau = len(chain) >= plateau_rounds and not any(
        bool(record.payload["improvement_observed"])
        for record in chain[-plateau_rounds:]
    )
    activity_time = created_time
    if latest is not None:
        _, activity_time = _timestamp(latest["ended_at"], "latest iteration ended at")
    zombie = (
        observed_time - activity_time
    ).total_seconds() >= int(policy.payload["zombie_after_seconds"])
    if cancellation is not None:
        state, stop_reason = "cancelled", "cancel"
    elif latest is not None and latest["decision"] == "accept":
        state, stop_reason = "completed", "accept"
    elif latest is not None and latest["decision"] == "revert":
        state, stop_reason = "stopped", "revert"
    elif budget_reached:
        state, stop_reason = "stopped", "budget"
    elif plateau:
        state, stop_reason = "stopped", "plateau"
    elif zombie:
        state, stop_reason = "recovery-required", "zombie"
    elif chain:
        state, stop_reason = "running", "continue"
    else:
        state, stop_reason = "planned", "continue"
    metric_summary = []
    latest_values = {
        str(item["metric_id"]): item for item in latest["metrics"]
    } if latest else {}
    for metric in plan_record["metrics"]:
        observed_value = latest_values.get(str(metric["metric_id"]))
        metric_summary.append(
            {
                "metric_id": metric["metric_id"],
                "direction": metric["direction"],
                "unit": metric["unit"],
                "baseline": metric["baseline"],
                "target": metric["target"],
                "current": observed_value["value"] if observed_value else metric["baseline"],
                "target_met": bool(observed_value["target_met"]) if observed_value else False,
            }
        )
    ended_at = observed if state in TERMINAL_STATES else None
    body: dict[str, object] = {
        "schema_ref": "schemas/measured-loop-status.schema.json",
        "schema_version": 1,
        "run_id": plan_record["run_id"],
        "project_id": plan_record["project_id"],
        "work_item_id": plan_record["work_item_id"],
        "plan_digest": plan_record["plan_digest"],
        "state": state,
        "stop_reason": stop_reason,
        "terminal": state in TERMINAL_STATES,
        "resume_allowed": state in {"planned", "running"},
        "resume_requires_existing_authority": True,
        "started_at": plan_record["created_at"],
        "observed_at": observed,
        "ended_at": ended_at,
        "latest_iteration_digest": latest["iteration_digest"] if latest else None,
        "cancellation_digest": cancellation["cancellation_digest"] if cancellation else None,
        "verifier_execution_identity_id": plan_record["verifier_execution_identity"][
            "execution_identity_id"
        ],
        "usage": totals,
        "budget": dict(budget),
        "metrics": metric_summary,
        "grants_authority": False,
        "contains_prompts": False,
        "contains_outputs": False,
        "contains_physical_paths": False,
        "contains_secrets": False,
    }
    body["status_digest"] = _digest(body)
    return MeasuredLoopRecord(body)


def parse_measured_loop_status(payload: object) -> MeasuredLoopRecord:
    expected = {
        "schema_ref", "schema_version", "run_id", "project_id", "work_item_id",
        "plan_digest", "state", "stop_reason", "terminal", "resume_allowed",
        "resume_requires_existing_authority", "started_at", "observed_at", "ended_at",
        "latest_iteration_digest", "cancellation_digest", "verifier_execution_identity_id",
        "usage", "budget", "metrics", "grants_authority", "contains_prompts",
        "contains_outputs", "contains_physical_paths", "contains_secrets", "status_digest",
    }
    if not isinstance(payload, Mapping):
        raise MeasuredLoopError("measured loop status must be an object")
    _exact(payload, expected, "measured loop status")
    if (
        payload.get("schema_ref") != "schemas/measured-loop-status.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("grants_authority") is not False
        or any(payload.get(key) is not False for key in (
            "contains_prompts", "contains_outputs", "contains_physical_paths", "contains_secrets"
        ))
        or payload.get("resume_requires_existing_authority") is not True
    ):
        raise MeasuredLoopError("measured loop status contract is invalid")
    for key in ("run_id", "project_id", "work_item_id"):
        _identifier(payload.get(key), key)
    for key in ("plan_digest", "verifier_execution_identity_id"):
        _digest_value(payload.get(key), key)
    for key in ("latest_iteration_digest", "cancellation_digest"):
        if payload.get(key) is not None:
            _digest_value(payload.get(key), key)
    state, reason = payload.get("state"), payload.get("stop_reason")
    if state not in STATES or reason not in STOP_REASONS:
        raise MeasuredLoopError("measured loop state or stop reason is invalid")
    terminal = state in TERMINAL_STATES
    if payload.get("terminal") is not terminal or payload.get("resume_allowed") is not (not terminal):
        raise MeasuredLoopError("measured loop terminal flags are invalid")
    valid_pairs = {
        "planned": {"continue"},
        "running": {"continue"},
        "completed": {"accept"},
        "cancelled": {"cancel"},
        "recovery-required": {"zombie"},
        "stopped": {"budget", "plateau", "revert"},
    }
    if reason not in valid_pairs[str(state)]:
        raise MeasuredLoopError("measured loop state and stop reason are inconsistent")
    if (reason == "cancel") is not (payload.get("cancellation_digest") is not None):
        raise MeasuredLoopError("cancellation digest does not match status")
    _, started = _timestamp(payload.get("started_at"), "status started at")
    _, observed = _timestamp(payload.get("observed_at"), "status observed at")
    if observed < started:
        raise MeasuredLoopError("status predates the run")
    ended = payload.get("ended_at")
    if terminal:
        _, ended_time = _timestamp(ended, "status ended at")
        if ended_time < started or ended_time > observed:
            raise MeasuredLoopError("status ended at is invalid")
    elif ended is not None:
        raise MeasuredLoopError("nonterminal status must not have ended_at")
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        raise MeasuredLoopError("status usage must be an object")
    _exact(usage, {"rounds", "input_tokens", "output_tokens", "cost_microunits", "attempts", "peak_concurrency"}, "status usage")
    for key, value in usage.items():
        _integer(value, f"status {key}")
    budget = _bounded_budget(payload.get("budget"))
    metrics = payload.get("metrics")
    if isinstance(metrics, (str, bytes)) or not isinstance(metrics, Sequence) or not metrics:
        raise MeasuredLoopError("status metrics must be a non-empty list")
    metric_ids: list[str] = []
    for metric in metrics:
        if not isinstance(metric, Mapping):
            raise MeasuredLoopError("status metric must be an object")
        _exact(
            metric,
            {"metric_id", "direction", "unit", "baseline", "target", "current", "target_met"},
            "status metric",
        )
        metric_ids.append(_identifier(metric.get("metric_id"), "status metric id"))
        if metric.get("direction") not in DIRECTIONS:
            raise MeasuredLoopError("status metric direction is invalid")
        _identifier(metric.get("unit"), "status metric unit")
        for key in ("baseline", "target", "current"):
            _integer(metric.get(key), f"status metric {key}", minimum=-10**15)
        if not isinstance(metric.get("target_met"), bool):
            raise MeasuredLoopError("status target flag must be boolean")
    if metric_ids != sorted(set(metric_ids)):
        raise MeasuredLoopError("status metrics must be unique and canonically ordered")
    counter_limits = (
        ("rounds", "max_rounds"),
        ("input_tokens", "max_input_tokens"),
        ("output_tokens", "max_output_tokens"),
        ("cost_microunits", "max_cost_microunits"),
        ("attempts", "max_attempts"),
    )
    if any(int(usage[key]) > int(budget[limit]) for key, limit in counter_limits):
        raise MeasuredLoopError("status usage exceeds its immutable budget")
    if int(usage["peak_concurrency"]) > int(budget["max_concurrency"]):
        raise MeasuredLoopError("status peak concurrency exceeds its immutable budget")
    elapsed = int((observed - started).total_seconds())
    exhausted = _budget_stop_codes(usage, budget, elapsed_seconds=elapsed)
    if exhausted and not terminal:
        raise MeasuredLoopError("nonterminal status has an exhausted immutable budget")
    if reason == "budget" and not exhausted:
        raise MeasuredLoopError("budget status has no exhausted immutable budget")
    claimed = _digest_value(payload.get("status_digest"), "status digest")
    if claimed != _digest({key: value for key, value in payload.items() if key != "status_digest"}):
        raise MeasuredLoopError("measured loop status digest is invalid")
    return MeasuredLoopRecord(dict(payload))


def resume_measured_loop(
    policy: MeasuredLoopPolicy,
    plan: Mapping[str, object] | MeasuredLoopRecord,
    iterations: Sequence[Mapping[str, object]],
    persisted_status: Mapping[str, object],
    *,
    observed_at: str,
    cancellation_record: Mapping[str, object] | None = None,
) -> MeasuredLoopRecord:
    persisted = parse_measured_loop_status(persisted_status).payload
    plan_record = parse_measured_loop_plan(
        plan.payload if isinstance(plan, MeasuredLoopRecord) else plan, policy
    ).payload
    chain = validate_iteration_chain(plan_record, iterations)
    _, requested_observation = _timestamp(observed_at, "resume observed at")
    _, persisted_observation = _timestamp(
        persisted["observed_at"], "persisted status observed at"
    )
    if requested_observation < persisted_observation:
        raise MeasuredLoopError("resume observation predates persisted status")
    latest = chain[-1].payload["iteration_digest"] if chain else None
    if (
        persisted["run_id"] != plan_record["run_id"]
        or persisted["plan_digest"] != plan_record["plan_digest"]
        or persisted["latest_iteration_digest"] != latest
    ):
        raise MeasuredLoopError("persisted status does not match verified resume records")
    if persisted["terminal"]:
        return MeasuredLoopRecord(persisted)
    return build_measured_loop_status(
        policy,
        plan_record,
        [record.as_dict() for record in chain],
        observed_at=observed_at,
        cancellation_record=cancellation_record,
    )


def decide_admission(
    policy: MeasuredLoopPolicy,
    plan: Mapping[str, object] | MeasuredLoopRecord,
    status: Mapping[str, object],
    *,
    observed_at: str,
    requested_claims: int,
    active_claims: int,
    cpu_pressure_basis_points: int,
    ram_pressure_basis_points: int,
    provider_required: bool,
    provider_quota_remaining_basis_points: int | None,
    cost_headroom_microunits: int,
    failure_pressure_basis_points: int,
) -> MeasuredLoopRecord:
    plan_record = parse_measured_loop_plan(
        plan.payload if isinstance(plan, MeasuredLoopRecord) else plan, policy
    ).payload
    status_record = parse_measured_loop_status(status).payload
    if status_record["run_id"] != plan_record["run_id"] or status_record["plan_digest"] != plan_record["plan_digest"]:
        raise MeasuredLoopError("admission status does not match the measured loop")
    observed, observation_time = _timestamp(observed_at, "admission observed at")
    _, plan_time = _timestamp(plan_record["created_at"], "plan created at")
    _, status_started = _timestamp(status_record["started_at"], "status started at")
    _, status_observed = _timestamp(status_record["observed_at"], "status observed at")
    if status_started != plan_time or status_observed < plan_time:
        raise MeasuredLoopError("admission status timeline does not match the plan")
    if observation_time < status_observed:
        raise MeasuredLoopError("admission observation predates status")
    deadline = plan_time + timedelta(
        seconds=int(plan_record["budget"]["max_wall_time_seconds"])
    )
    if status_observed >= deadline and status_record["stop_reason"] != "budget":
        raise MeasuredLoopError("admission status does not reflect the wall-time budget")
    requested = _integer(requested_claims, "requested claims", minimum=1)
    active = _integer(active_claims, "active claims")
    cpu = _integer(cpu_pressure_basis_points, "CPU pressure", maximum=10_000)
    ram = _integer(ram_pressure_basis_points, "RAM pressure", maximum=10_000)
    failure = _integer(failure_pressure_basis_points, "failure pressure", maximum=10_000)
    cost = _integer(cost_headroom_microunits, "cost headroom")
    if not isinstance(provider_required, bool):
        raise MeasuredLoopError("provider required must be boolean")
    quota = None
    if provider_quota_remaining_basis_points is not None:
        quota = _integer(provider_quota_remaining_basis_points, "provider quota", maximum=10_000)
    if provider_required and quota is None:
        raise MeasuredLoopError("provider quota evidence is required")
    ceiling = min(
        int(policy.payload["max_concurrency_ceiling"]),
        int(plan_record["budget"]["max_concurrency"]),
    )
    reasons = []
    if status_record["terminal"]:
        reasons.append("run-terminal")
    if observation_time >= deadline:
        reasons.append("wall-time-budget")
    if (
        observation_time - status_observed
    ).total_seconds() >= int(policy.payload["zombie_after_seconds"]):
        reasons.append("status-stale")
    reasons.extend(
        _budget_stop_codes(
            status_record["usage"],
            status_record["budget"],
            elapsed_seconds=int((observation_time - plan_time).total_seconds()),
        )
    )
    if active >= ceiling:
        reasons.append("concurrency-ceiling")
    if cpu >= int(policy.payload["max_cpu_pressure_basis_points"]):
        reasons.append("cpu-pressure")
    if ram >= int(policy.payload["max_ram_pressure_basis_points"]):
        reasons.append("ram-pressure")
    if provider_required and quota is not None and quota < int(policy.payload["min_provider_quota_basis_points"]):
        reasons.append("provider-quota-pressure")
    if cost < int(policy.payload["min_cost_headroom_microunits"]):
        reasons.append("cost-pressure")
    if failure >= int(policy.payload["max_failure_pressure_basis_points"]):
        reasons.append("failure-pressure")
    available = max(0, ceiling - active)
    admitted = 0 if reasons else min(requested, available)
    if admitted == 0 and not reasons:
        reasons.append("concurrency-ceiling")
    body: dict[str, object] = {
        "schema_ref": "schemas/measured-loop-admission.schema.json",
        "schema_version": 1,
        "run_id": plan_record["run_id"],
        "plan_digest": plan_record["plan_digest"],
        "status_digest": status_record["status_digest"],
        "observed_at": observed,
        "decision": "admit" if admitted else "defer",
        "requested_claims": requested,
        "active_claims": active,
        "admitted_claims": admitted,
        "concurrency_ceiling": ceiling,
        "reason_codes": sorted(set(reasons)),
        "pressure": {
            "cpu_basis_points": cpu,
            "ram_basis_points": ram,
            "provider_required": provider_required,
            "provider_quota_remaining_basis_points": quota,
            "cost_headroom_microunits": cost,
            "failure_basis_points": failure,
        },
        "active_work_action": "preserve",
        "kill_requested": False,
        "grants_authority": False,
    }
    body["admission_digest"] = _digest(body)
    return MeasuredLoopRecord(body)


def parse_admission_decision(payload: object) -> MeasuredLoopRecord:
    expected = {
        "schema_ref", "schema_version", "run_id", "plan_digest", "status_digest",
        "observed_at", "decision", "requested_claims", "active_claims", "admitted_claims",
        "concurrency_ceiling", "reason_codes", "pressure", "active_work_action",
        "kill_requested", "grants_authority", "admission_digest",
    }
    if not isinstance(payload, Mapping):
        raise MeasuredLoopError("admission decision must be an object")
    _exact(payload, expected, "admission decision")
    if (
        payload.get("schema_ref") != "schemas/measured-loop-admission.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("decision") not in {"admit", "defer"}
        or payload.get("active_work_action") != "preserve"
        or payload.get("kill_requested") is not False
        or payload.get("grants_authority") is not False
    ):
        raise MeasuredLoopError("admission decision contract is invalid")
    _identifier(payload.get("run_id"), "run id")
    for key in ("plan_digest", "status_digest"):
        _digest_value(payload.get(key), key)
    _timestamp(payload.get("observed_at"), "admission observed at")
    for key in ("requested_claims", "active_claims", "admitted_claims", "concurrency_ceiling"):
        _integer(payload.get(key), key)
    reasons = payload.get("reason_codes")
    if not isinstance(reasons, list) or reasons != sorted(set(reasons)):
        raise MeasuredLoopError("admission reasons are invalid")
    for reason in reasons:
        _identifier(reason, "admission reason")
    if payload["decision"] == "admit" and int(payload["admitted_claims"]) < 1:
        raise MeasuredLoopError("admit decision must admit work")
    if payload["decision"] == "defer" and int(payload["admitted_claims"]) != 0:
        raise MeasuredLoopError("defer decision cannot admit work")
    if int(payload["admitted_claims"]) > int(payload["requested_claims"]):
        raise MeasuredLoopError("admission exceeds requested claims")
    if int(payload["active_claims"]) + int(payload["admitted_claims"]) > int(payload["concurrency_ceiling"]):
        raise MeasuredLoopError("admission exceeds the concurrency ceiling")
    if payload["decision"] == "admit" and reasons:
        raise MeasuredLoopError("admit decision cannot contain defer reasons")
    if payload["decision"] == "defer" and not reasons:
        raise MeasuredLoopError("defer decision requires a reason")
    pressure = payload.get("pressure")
    if not isinstance(pressure, Mapping):
        raise MeasuredLoopError("admission pressure is invalid")
    _exact(
        pressure,
        {"cpu_basis_points", "ram_basis_points", "provider_required", "provider_quota_remaining_basis_points", "cost_headroom_microunits", "failure_basis_points"},
        "admission pressure",
    )
    _integer(pressure.get("cpu_basis_points"), "CPU pressure", maximum=10_000)
    _integer(pressure.get("ram_basis_points"), "RAM pressure", maximum=10_000)
    _integer(pressure.get("cost_headroom_microunits"), "cost headroom")
    _integer(pressure.get("failure_basis_points"), "failure pressure", maximum=10_000)
    if not isinstance(pressure.get("provider_required"), bool):
        raise MeasuredLoopError("provider required must be boolean")
    quota = pressure.get("provider_quota_remaining_basis_points")
    if quota is not None:
        _integer(quota, "provider quota", maximum=10_000)
    if pressure.get("provider_required") is True and quota is None:
        raise MeasuredLoopError("provider quota evidence is required")
    claimed = _digest_value(payload.get("admission_digest"), "admission digest")
    if claimed != _digest({key: value for key, value in payload.items() if key != "admission_digest"}):
        raise MeasuredLoopError("admission digest is invalid")
    return MeasuredLoopRecord(dict(payload))


def build_morning_digest(status: Mapping[str, object], *, generated_at: str) -> MeasuredLoopRecord:
    current = parse_measured_loop_status(status).payload
    generated, generated_time = _timestamp(generated_at, "morning digest generated at")
    _, observed_time = _timestamp(current["observed_at"], "status observed at")
    if generated_time < observed_time:
        raise MeasuredLoopError("morning digest predates status")
    next_actions = {
        "accept": "review-accepted-evidence",
        "revert": "review-revert-evidence",
        "continue": "resume-verified-run",
        "plateau": "review-objective-or-metrics",
        "budget": "request-new-exact-plan",
        "cancel": "confirm-cancellation-record",
        "zombie": "recover-runtime-before-new-run",
    }
    body: dict[str, object] = {
        "schema_ref": "schemas/measured-loop-morning-digest.schema.json",
        "schema_version": 1,
        "run_id": current["run_id"],
        "project_id": current["project_id"],
        "work_item_id": current["work_item_id"],
        "state": current["state"],
        "stop_reason": current["stop_reason"],
        "generated_at": generated,
        "status_digest": current["status_digest"],
        "latest_iteration_digest": current["latest_iteration_digest"],
        "rounds": current["usage"]["rounds"],
        "usage": {
            "input_tokens": current["usage"]["input_tokens"],
            "output_tokens": current["usage"]["output_tokens"],
            "cost_microunits": current["usage"]["cost_microunits"],
            "attempts": current["usage"]["attempts"],
            "peak_concurrency": current["usage"]["peak_concurrency"],
        },
        "metrics": [
            {
                "metric_id": metric["metric_id"],
                "value": metric["current"],
                "target": metric["target"],
                "target_met": metric["target_met"],
            }
            for metric in current["metrics"]
        ],
        "next_safe_action": next_actions[str(current["stop_reason"])],
        "verifier_execution_identity_id": current["verifier_execution_identity_id"],
        "grants_authority": False,
        "contains_prompts": False,
        "contains_outputs": False,
        "contains_physical_paths": False,
        "contains_secrets": False,
    }
    body["morning_digest"] = _digest(body)
    return MeasuredLoopRecord(body)


def parse_morning_digest(payload: object) -> MeasuredLoopRecord:
    expected = {
        "schema_ref", "schema_version", "run_id", "project_id", "work_item_id", "state",
        "stop_reason", "generated_at", "status_digest", "latest_iteration_digest", "rounds",
        "usage", "metrics", "next_safe_action", "verifier_execution_identity_id",
        "grants_authority", "contains_prompts", "contains_outputs", "contains_physical_paths",
        "contains_secrets", "morning_digest",
    }
    if not isinstance(payload, Mapping):
        raise MeasuredLoopError("morning digest must be an object")
    _exact(payload, expected, "morning digest")
    if (
        payload.get("schema_ref") != "schemas/measured-loop-morning-digest.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("grants_authority") is not False
        or any(payload.get(key) is not False for key in (
            "contains_prompts", "contains_outputs", "contains_physical_paths", "contains_secrets"
        ))
    ):
        raise MeasuredLoopError("morning digest contract is invalid")
    for key in ("run_id", "project_id", "work_item_id", "next_safe_action"):
        _identifier(payload.get(key), key)
    if payload.get("state") not in STATES or payload.get("stop_reason") not in STOP_REASONS:
        raise MeasuredLoopError("morning state is invalid")
    for key in ("status_digest", "verifier_execution_identity_id"):
        _digest_value(payload.get(key), key)
    if payload.get("latest_iteration_digest") is not None:
        _digest_value(payload.get("latest_iteration_digest"), "latest iteration digest")
    _timestamp(payload.get("generated_at"), "morning digest generated at")
    _integer(payload.get("rounds"), "rounds")
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        raise MeasuredLoopError("morning usage must be an object")
    _exact(
        usage,
        {"input_tokens", "output_tokens", "cost_microunits", "attempts", "peak_concurrency"},
        "morning usage",
    )
    for key in usage:
        _integer(usage.get(key), f"morning {key}")
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        raise MeasuredLoopError("morning metrics must be a list")
    metric_ids: list[str] = []
    for metric in metrics:
        if not isinstance(metric, Mapping):
            raise MeasuredLoopError("morning metric must be an object")
        _exact(metric, {"metric_id", "value", "target", "target_met"}, "morning metric")
        metric_ids.append(_identifier(metric.get("metric_id"), "morning metric id"))
        _integer(metric.get("value"), "morning metric value", minimum=-10**15)
        _integer(metric.get("target"), "morning metric target", minimum=-10**15)
        if not isinstance(metric.get("target_met"), bool):
            raise MeasuredLoopError("morning target flag must be boolean")
    if metric_ids != sorted(set(metric_ids)):
        raise MeasuredLoopError("morning metrics must be unique and canonically ordered")
    claimed = _digest_value(payload.get("morning_digest"), "morning digest")
    if claimed != _digest({key: value for key, value in payload.items() if key != "morning_digest"}):
        raise MeasuredLoopError("morning digest hash is invalid")
    return MeasuredLoopRecord(dict(payload))
