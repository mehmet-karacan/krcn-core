"""Authorized, checkpointed, and idempotent worker execution."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .information_records import canonical_json
from .orchestration_authorization import (
    OperationAuthorization,
    StepAuthorization,
    TaskAuthorization,
)
from .orchestration_plan import TaskPlan, TaskPlanStep


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SENSITIVE_TEXT = re.compile(
    rb"(?i)(?:password|passwd|token|api[_-]?key|secret)\s*[:=]|"
    rb"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+"
)
SENSITIVE_KEY = re.compile(r"(?i)(?:password|passwd|token|api[_-]?key|secret)")


class WorkerExecutionError(ValueError):
    """Raised before a handler runs when execution scope is invalid."""


@dataclass(frozen=True)
class WorkerEffect:
    effect_id: str
    effect_type: str
    mutation_plan_id: str | None
    provider_request_id: str | None
    evidence_digests: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "effect_type": self.effect_type,
            "mutation_plan_id": self.mutation_plan_id,
            "provider_request_id": self.provider_request_id,
            "evidence_digests": list(self.evidence_digests),
        }


@dataclass(frozen=True)
class WorkerHandlerResult:
    summary: Mapping[str, object]
    effects: tuple[WorkerEffect, ...]


@dataclass(frozen=True)
class WorkerHandlerSpec:
    handler_id: str
    capabilities: tuple[str, ...]
    side_effects: tuple[str, ...]
    callback: Callable[["WorkerContext", Mapping[str, object]], WorkerHandlerResult]


@dataclass(frozen=True)
class TaskWorkRequest:
    task_id: str
    plan_id: str
    authorization_id: str
    step_id: str
    handler_id: str
    input_payload: Mapping[str, object]
    input_digest: str
    idempotency_key: str


@dataclass(frozen=True)
class WorkerContext:
    task_id: str
    plan_id: str
    authorization_id: str
    step_id: str
    idempotency_key: str
    operations: tuple[OperationAuthorization, ...]
    mutation_plan_ids: tuple[str, ...]
    provider_request_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkerCheckpoint:
    checkpoint_id: str
    task_id: str
    plan_id: str
    authorization_id: str
    step_id: str
    step_digest: str
    idempotency_key: str
    status: str
    result_digest: str | None
    failure_digest: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "authorization_id": self.authorization_id,
            "step_id": self.step_id,
            "step_digest": self.step_digest,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "result_digest": self.result_digest,
            "failure_digest": self.failure_digest,
        }


@dataclass(frozen=True)
class WorkerEffectJournal:
    journal_id: str
    task_id: str
    plan_id: str
    authorization_id: str
    step_id: str
    handler_id: str
    input_digest: str
    idempotency_key: str
    status: str
    effects: tuple[WorkerEffect, ...]
    result_digest: str | None
    failure_digest: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "journal_id": self.journal_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "authorization_id": self.authorization_id,
            "step_id": self.step_id,
            "handler_id": self.handler_id,
            "input_digest": self.input_digest,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "effects": [effect.as_dict() for effect in self.effects],
            "result_digest": self.result_digest,
            "failure_digest": self.failure_digest,
        }


@dataclass(frozen=True)
class WorkerExecution:
    checkpoint: WorkerCheckpoint
    journal: WorkerEffectJournal
    replayed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/worker-execution.schema.json",
            "schema_version": 1,
            "checkpoint": self.checkpoint.as_dict(),
            "journal": self.journal.as_dict(),
            "replayed": self.replayed,
        }


class WorkerHandlerRegistry:
    """Explicit worker handler registry with no host or module discovery."""

    def __init__(self) -> None:
        self._handlers: dict[str, WorkerHandlerSpec] = {}

    def register(self, spec: WorkerHandlerSpec) -> None:
        if not IDENTIFIER.fullmatch(spec.handler_id):
            raise WorkerExecutionError("worker handler id is invalid")
        if spec.handler_id in self._handlers:
            raise WorkerExecutionError("worker handler is already registered")
        if not spec.capabilities or len(set(spec.capabilities)) != len(spec.capabilities):
            raise WorkerExecutionError("worker handler capabilities are invalid")
        if not set(spec.side_effects).issubset({"read", "write", "execute", "network"}):
            raise WorkerExecutionError("worker handler side effects are invalid")
        if len(set(spec.side_effects)) != len(spec.side_effects):
            raise WorkerExecutionError("worker handler side effects must be unique")
        if not callable(spec.callback):
            raise WorkerExecutionError("worker handler callback is invalid")
        self._handlers[spec.handler_id] = spec

    def get(self, handler_id: str) -> WorkerHandlerSpec | None:
        return self._handlers.get(handler_id)


def _contains_sensitive_value(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            SENSITIVE_KEY.search(str(key)) or _contains_sensitive_value(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_value(item) for item in value)
    if isinstance(value, str):
        return bool(SENSITIVE_TEXT.search(value.encode("utf-8")))
    return False


def create_work_request(
    plan: TaskPlan,
    authorization: TaskAuthorization,
    *,
    step_id: str,
    handler_id: str,
    input_payload: Mapping[str, object],
) -> TaskWorkRequest:
    """Bind handler input to one exact authorized step and idempotency key."""

    if not IDENTIFIER.fullmatch(step_id) or not IDENTIFIER.fullmatch(handler_id):
        raise WorkerExecutionError("worker request identifiers are invalid")
    if not isinstance(input_payload, Mapping):
        raise WorkerExecutionError("worker input must be an object")
    try:
        encoded = canonical_json(dict(input_payload))
    except (TypeError, ValueError) as exc:
        raise WorkerExecutionError("worker input must be canonical JSON") from exc
    if len(encoded) > 1024 * 1024 or _contains_sensitive_value(input_payload):
        raise WorkerExecutionError("worker input is too large or contains sensitive text")
    input_digest = hashlib.sha256(encoded).hexdigest()
    identity = {
        "task_id": plan.task_id,
        "plan_id": plan.plan_id,
        "authorization_id": authorization.authorization_id,
        "step_id": step_id,
        "handler_id": handler_id,
        "input_digest": input_digest,
    }
    return TaskWorkRequest(
        plan.task_id,
        plan.plan_id,
        authorization.authorization_id,
        step_id,
        handler_id,
        dict(input_payload),
        input_digest,
        hashlib.sha256(canonical_json(identity)).hexdigest(),
    )


def _authorization_digest(authorization: TaskAuthorization) -> str:
    payload = authorization.as_dict()
    payload.pop("schema_ref")
    payload.pop("schema_version")
    payload.pop("authorization_id")
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _step_authorization(
    plan: TaskPlan,
    authorization: TaskAuthorization,
    request: TaskWorkRequest,
) -> tuple[TaskPlanStep, StepAuthorization]:
    if (
        authorization.authorization_id != _authorization_digest(authorization)
        or authorization.task_id != plan.task_id
        or authorization.plan_id != plan.plan_id
        or authorization.intent_digest != plan.intent_digest
        or authorization.selection_digest != plan.selection_digest
        or request.task_id != plan.task_id
        or request.plan_id != plan.plan_id
        or request.authorization_id != authorization.authorization_id
    ):
        raise WorkerExecutionError("worker authorization does not match the exact task plan")
    step = next((item for item in plan.steps if item.step_id == request.step_id), None)
    step_auth = next(
        (item for item in authorization.steps if item.step_id == request.step_id),
        None,
    )
    if (
        step is None
        or step.role != "worker"
        or step_auth is None
        or step_auth.step_digest != step.step_digest
    ):
        raise WorkerExecutionError("worker step lacks matching authorization")
    return step, step_auth


def _validate_dependencies(
    plan: TaskPlan,
    step: TaskPlanStep,
    history: Sequence[WorkerExecution],
) -> None:
    worker_ids = {item.step_id for item in plan.steps if item.role == "worker"}
    required = set(step.depends_on) & worker_ids
    completed = {
        item.checkpoint.step_id
        for item in history
        if item.checkpoint.plan_id == plan.plan_id
        and item.checkpoint.status == "completed"
    }
    if not required.issubset(completed):
        raise WorkerExecutionError("worker dependencies are not completed")


def _validate_effects(
    step: TaskPlanStep,
    step_auth: StepAuthorization,
    result: WorkerHandlerResult,
) -> tuple[WorkerEffect, ...]:
    if not isinstance(result, WorkerHandlerResult):
        raise WorkerExecutionError("worker handler result is invalid")
    encoded = canonical_json(dict(result.summary))
    if len(encoded) > 1024 * 1024 or _contains_sensitive_value(result.summary):
        raise WorkerExecutionError("worker result is too large or contains sensitive text")
    effects = tuple(sorted(result.effects, key=lambda item: item.effect_id))
    if len({item.effect_id for item in effects}) != len(effects):
        raise WorkerExecutionError("worker effect ids must be unique")
    for effect in effects:
        if not IDENTIFIER.fullmatch(effect.effect_id):
            raise WorkerExecutionError("worker effect id is invalid")
        if effect.effect_type not in step.side_effects:
            raise WorkerExecutionError("worker effect exceeds the task step")
        if any(not SHA256.fullmatch(item) for item in effect.evidence_digests):
            raise WorkerExecutionError("worker evidence digest is invalid")
        if effect.effect_type == "write":
            if effect.mutation_plan_id not in step_auth.mutation_plan_ids:
                raise WorkerExecutionError("worker write lacks authorized mutation plan")
        elif effect.mutation_plan_id is not None:
            raise WorkerExecutionError("non-write effect cannot claim a mutation plan")
        if effect.effect_type == "network":
            if effect.provider_request_id not in step_auth.provider_request_ids:
                raise WorkerExecutionError("worker network effect lacks provider authorization")
        elif effect.provider_request_id is not None:
            raise WorkerExecutionError("non-network effect cannot claim a provider request")
    used_mutations = {
        item.mutation_plan_id for item in effects if item.mutation_plan_id is not None
    }
    used_providers = {
        item.provider_request_id for item in effects if item.provider_request_id is not None
    }
    if used_mutations != set(step_auth.mutation_plan_ids):
        raise WorkerExecutionError("worker did not report every authorized mutation")
    if used_providers != set(step_auth.provider_request_ids):
        raise WorkerExecutionError("worker did not report every authorized provider request")
    return effects


def _execution_records(
    request: TaskWorkRequest,
    step: TaskPlanStep,
    *,
    status: str,
    effects: tuple[WorkerEffect, ...],
    result_digest: str | None,
    failure_digest: str | None,
) -> WorkerExecution:
    journal_identity = {
        "task_id": request.task_id,
        "plan_id": request.plan_id,
        "authorization_id": request.authorization_id,
        "step_id": request.step_id,
        "handler_id": request.handler_id,
        "input_digest": request.input_digest,
        "idempotency_key": request.idempotency_key,
        "status": status,
        "effects": [item.as_dict() for item in effects],
        "result_digest": result_digest,
        "failure_digest": failure_digest,
    }
    journal_id = hashlib.sha256(canonical_json(journal_identity)).hexdigest()
    checkpoint_identity = {
        "task_id": request.task_id,
        "plan_id": request.plan_id,
        "authorization_id": request.authorization_id,
        "step_id": request.step_id,
        "step_digest": step.step_digest,
        "idempotency_key": request.idempotency_key,
        "status": status,
        "result_digest": result_digest,
        "failure_digest": failure_digest,
        "journal_id": journal_id,
    }
    checkpoint_id = hashlib.sha256(canonical_json(checkpoint_identity)).hexdigest()
    checkpoint = WorkerCheckpoint(
        checkpoint_id,
        request.task_id,
        request.plan_id,
        request.authorization_id,
        request.step_id,
        step.step_digest,
        request.idempotency_key,
        status,
        result_digest,
        failure_digest,
    )
    journal = WorkerEffectJournal(
        journal_id,
        request.task_id,
        request.plan_id,
        request.authorization_id,
        request.step_id,
        request.handler_id,
        request.input_digest,
        request.idempotency_key,
        status,
        effects,
        result_digest,
        failure_digest,
    )
    return WorkerExecution(checkpoint, journal, False)


def execute_worker_step(
    plan: TaskPlan,
    authorization: TaskAuthorization,
    request: TaskWorkRequest,
    handlers: WorkerHandlerRegistry,
    *,
    history: Sequence[WorkerExecution] = (),
) -> WorkerExecution:
    """Execute one exact worker step or replay its completed checkpoint."""

    step, step_auth = _step_authorization(plan, authorization, request)
    for previous in history:
        if (
            previous.checkpoint.plan_id == plan.plan_id
            and previous.checkpoint.step_id == step.step_id
            and previous.checkpoint.status == "completed"
        ):
            if previous.checkpoint.idempotency_key != request.idempotency_key:
                raise WorkerExecutionError("completed worker step cannot be rebound to new input")
            return WorkerExecution(previous.checkpoint, previous.journal, True)
    _validate_dependencies(plan, step, history)
    handler = handlers.get(request.handler_id)
    if handler is None:
        raise WorkerExecutionError("worker handler is not explicitly registered")
    if not set(step.required_capabilities).issubset(handler.capabilities):
        raise WorkerExecutionError("worker handler lacks required capabilities")
    if not set(handler.side_effects).issubset(step.side_effects):
        raise WorkerExecutionError("worker handler side effects exceed the task step")
    context = WorkerContext(
        request.task_id,
        request.plan_id,
        request.authorization_id,
        request.step_id,
        request.idempotency_key,
        step_auth.operations,
        step_auth.mutation_plan_ids,
        step_auth.provider_request_ids,
    )
    try:
        result = handler.callback(context, request.input_payload)
        effects = _validate_effects(step, step_auth, result)
        result_digest = hashlib.sha256(canonical_json(dict(result.summary))).hexdigest()
        return _execution_records(
            request,
            step,
            status="completed",
            effects=effects,
            result_digest=result_digest,
            failure_digest=None,
        )
    except Exception as exc:
        failure_identity = {
            "exception_type": type(exc).__name__,
            "message_digest": hashlib.sha256(str(exc).encode("utf-8")).hexdigest(),
        }
        return _execution_records(
            request,
            step,
            status="failed",
            effects=(),
            result_digest=None,
            failure_digest=hashlib.sha256(canonical_json(failure_identity)).hexdigest(),
        )
