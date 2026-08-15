"""Authorized, checkpointed, and idempotent worker execution."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .agent_execution_identity import (
    AgentExecutionIdentity,
    RUNTIME_KINDS,
    parse_agent_execution_identity,
)
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
    identity_actor_digest: str | None = None
    runtime_kind: str | None = None


@dataclass(frozen=True)
class TaskWorkRequest:
    task_id: str
    plan_id: str
    authorization_id: str
    execution_identity: AgentExecutionIdentity | None
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
    execution_identity: AgentExecutionIdentity
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
    execution_identity_id: str | None
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
            **(
                {"execution_identity_id": self.execution_identity_id}
                if self.execution_identity_id is not None
                else {}
            ),
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
    execution_identity_id: str | None
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
            **(
                {"execution_identity_id": self.execution_identity_id}
                if self.execution_identity_id is not None
                else {}
            ),
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
    execution_identity: AgentExecutionIdentity | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/worker-execution.schema.json",
            "schema_version": 2 if self.execution_identity is not None else 1,
            "checkpoint": self.checkpoint.as_dict(),
            "journal": self.journal.as_dict(),
            "replayed": self.replayed,
            **(
                {"execution_identity": self.execution_identity.as_dict()}
                if self.execution_identity is not None
                else {}
            ),
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
        if (
            not isinstance(spec.identity_actor_digest, str)
            or not SHA256.fullmatch(spec.identity_actor_digest)
            or spec.runtime_kind not in RUNTIME_KINDS
        ):
            raise WorkerExecutionError("worker handler execution identity is invalid")
        self._handlers[spec.handler_id] = spec

    def get(self, handler_id: str) -> WorkerHandlerSpec | None:
        return self._handlers.get(handler_id)


def parse_worker_execution(payload: object) -> WorkerExecution:
    """Parse persisted worker records; plan-bound validation remains separate."""

    base_fields = {
        "schema_ref",
        "schema_version",
        "checkpoint",
        "journal",
        "replayed",
    }
    if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
        raise WorkerExecutionError("worker execution fields are invalid")
    version = int(payload["schema_version"])
    expected_fields = base_fields | ({"execution_identity"} if version == 2 else set())
    if set(payload) != expected_fields:
        raise WorkerExecutionError("worker execution fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/worker-execution.schema.json"
        or not isinstance(payload.get("replayed"), bool)
    ):
        raise WorkerExecutionError("worker execution header is invalid")
    execution_identity = None
    if version == 2:
        try:
            execution_identity = parse_agent_execution_identity(
                payload.get("execution_identity")
            )
        except ValueError as exc:
            raise WorkerExecutionError("worker execution identity is invalid") from exc
    checkpoint_payload = payload.get("checkpoint")
    journal_payload = payload.get("journal")
    checkpoint_fields = {
        "checkpoint_id",
        "task_id",
        "plan_id",
        "authorization_id",
        "step_id",
        "step_digest",
        "idempotency_key",
        "status",
        "result_digest",
        "failure_digest",
    }
    if version == 2:
        checkpoint_fields.add("execution_identity_id")
    journal_fields = {
        "journal_id",
        "task_id",
        "plan_id",
        "authorization_id",
        "step_id",
        "handler_id",
        "input_digest",
        "idempotency_key",
        "status",
        "effects",
        "result_digest",
        "failure_digest",
    }
    if version == 2:
        journal_fields.add("execution_identity_id")
    if not isinstance(checkpoint_payload, dict) or set(checkpoint_payload) != checkpoint_fields:
        raise WorkerExecutionError("worker checkpoint fields are invalid")
    if not isinstance(journal_payload, dict) or set(journal_payload) != journal_fields:
        raise WorkerExecutionError("worker journal fields are invalid")
    digest_fields = {
        "checkpoint_id",
        "plan_id",
        "authorization_id",
        "step_digest",
        "idempotency_key",
    }
    if any(not SHA256.fullmatch(str(checkpoint_payload.get(item, ""))) for item in digest_fields):
        raise WorkerExecutionError("worker checkpoint digest is invalid")
    for item in ("task_id", "step_id"):
        if not IDENTIFIER.fullmatch(str(checkpoint_payload.get(item, ""))):
            raise WorkerExecutionError("worker checkpoint identifier is invalid")
    effects_payload = journal_payload.get("effects")
    if not isinstance(effects_payload, list):
        raise WorkerExecutionError("worker effects are invalid")
    journal_digest_fields = {
        "journal_id",
        "plan_id",
        "authorization_id",
        "input_digest",
        "idempotency_key",
    }
    if any(not SHA256.fullmatch(str(journal_payload.get(item, ""))) for item in journal_digest_fields):
        raise WorkerExecutionError("worker journal digest is invalid")
    for item in ("task_id", "step_id", "handler_id"):
        if not IDENTIFIER.fullmatch(str(journal_payload.get(item, ""))):
            raise WorkerExecutionError("worker journal identifier is invalid")
    for record in (checkpoint_payload, journal_payload):
        for item in ("result_digest", "failure_digest"):
            value = record.get(item)
            if value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)):
                raise WorkerExecutionError("worker result or failure digest is invalid")
    effects = []
    effect_fields = {
        "effect_id",
        "effect_type",
        "mutation_plan_id",
        "provider_request_id",
        "evidence_digests",
    }
    for item in effects_payload:
        if not isinstance(item, dict) or set(item) != effect_fields:
            raise WorkerExecutionError("worker effect fields are invalid")
        evidence = item.get("evidence_digests")
        if (
            not isinstance(evidence, list)
            or len(set(evidence)) != len(evidence)
            or any(not SHA256.fullmatch(str(value)) for value in evidence)
        ):
            raise WorkerExecutionError("worker effect evidence is invalid")
        if (
            not IDENTIFIER.fullmatch(str(item.get("effect_id", "")))
            or item.get("effect_type") not in {"read", "write", "execute", "network"}
        ):
            raise WorkerExecutionError("worker effect identity is invalid")
        for field in ("mutation_plan_id", "provider_request_id"):
            value = item.get(field)
            if value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)):
                raise WorkerExecutionError("worker effect authorization digest is invalid")
        effects.append(
            WorkerEffect(
                str(item.get("effect_id")),
                str(item.get("effect_type")),
                item.get("mutation_plan_id") if isinstance(item.get("mutation_plan_id"), str) else None,
                item.get("provider_request_id") if isinstance(item.get("provider_request_id"), str) else None,
                tuple(evidence),
            )
        )
    checkpoint = WorkerCheckpoint(
        str(checkpoint_payload["checkpoint_id"]),
        str(checkpoint_payload["task_id"]),
        str(checkpoint_payload["plan_id"]),
        str(checkpoint_payload["authorization_id"]),
        str(checkpoint_payload["step_id"]),
        str(checkpoint_payload["step_digest"]),
        str(checkpoint_payload["idempotency_key"]),
        str(checkpoint_payload["execution_identity_id"])
        if version == 2
        else None,
        str(checkpoint_payload["status"]),
        checkpoint_payload["result_digest"] if isinstance(checkpoint_payload["result_digest"], str) else None,
        checkpoint_payload["failure_digest"] if isinstance(checkpoint_payload["failure_digest"], str) else None,
    )
    journal = WorkerEffectJournal(
        str(journal_payload["journal_id"]),
        str(journal_payload["task_id"]),
        str(journal_payload["plan_id"]),
        str(journal_payload["authorization_id"]),
        str(journal_payload["step_id"]),
        str(journal_payload["handler_id"]),
        str(journal_payload["input_digest"]),
        str(journal_payload["idempotency_key"]),
        str(journal_payload["execution_identity_id"])
        if version == 2
        else None,
        str(journal_payload["status"]),
        tuple(effects),
        journal_payload["result_digest"] if isinstance(journal_payload["result_digest"], str) else None,
        journal_payload["failure_digest"] if isinstance(journal_payload["failure_digest"], str) else None,
    )
    if version == 2 and (
        execution_identity is None
        or checkpoint.execution_identity_id
        != execution_identity.execution_identity_id
        or journal.execution_identity_id != execution_identity.execution_identity_id
    ):
        raise WorkerExecutionError("worker execution identity binding is invalid")
    return WorkerExecution(
        checkpoint,
        journal,
        bool(payload["replayed"]),
        execution_identity,
    )


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
    execution_identity: AgentExecutionIdentity,
) -> TaskWorkRequest:
    """Bind handler input to one exact authorized step and idempotency key."""

    if not IDENTIFIER.fullmatch(step_id) or not IDENTIFIER.fullmatch(handler_id):
        raise WorkerExecutionError("worker request identifiers are invalid")
    if not isinstance(input_payload, Mapping):
        raise WorkerExecutionError("worker input must be an object")
    try:
        checked_identity = parse_agent_execution_identity(execution_identity.as_dict())
    except (AttributeError, ValueError) as exc:
        raise WorkerExecutionError("worker execution identity is invalid") from exc
    if (
        checked_identity.task_id != plan.task_id
        or checked_identity.plan_id != plan.plan_id
        or checked_identity.step_id != step_id
        or checked_identity.role != "worker"
    ):
        raise WorkerExecutionError("worker execution identity does not match the step")
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
        "execution_identity_id": checked_identity.execution_identity_id,
        "step_id": step_id,
        "handler_id": handler_id,
        "input_digest": input_digest,
    }
    return TaskWorkRequest(
        plan.task_id,
        plan.plan_id,
        authorization.authorization_id,
        checked_identity,
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
        or request.execution_identity is None
        or request.execution_identity.task_id != plan.task_id
        or request.execution_identity.plan_id != plan.plan_id
        or request.execution_identity.step_id != request.step_id
        or request.execution_identity.role != "worker"
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
        "execution_identity_id": request.execution_identity.execution_identity_id,
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
        "execution_identity_id": request.execution_identity.execution_identity_id,
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
        request.execution_identity.execution_identity_id,
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
        request.execution_identity.execution_identity_id,
        status,
        effects,
        result_digest,
        failure_digest,
    )
    return WorkerExecution(checkpoint, journal, False, request.execution_identity)


def validate_worker_execution(
    plan: TaskPlan,
    authorization: TaskAuthorization,
    execution: WorkerExecution,
) -> None:
    """Validate persisted worker records before they are trusted as evidence."""

    checkpoint = execution.checkpoint
    journal = execution.journal
    if execution.execution_identity is not None:
        try:
            checked_identity = parse_agent_execution_identity(
                execution.execution_identity.as_dict()
            )
        except (AttributeError, ValueError) as exc:
            raise WorkerExecutionError("worker execution identity is invalid") from exc
        if checked_identity.execution_identity_id != checkpoint.execution_identity_id:
            raise WorkerExecutionError("worker execution identity binding is invalid")
    request = TaskWorkRequest(
        checkpoint.task_id,
        checkpoint.plan_id,
        checkpoint.authorization_id,
        execution.execution_identity,
        checkpoint.step_id,
        journal.handler_id,
        {},
        journal.input_digest,
        checkpoint.idempotency_key,
    )
    step, step_auth = _step_authorization(plan, authorization, request)
    if (
        journal.task_id != checkpoint.task_id
        or journal.plan_id != checkpoint.plan_id
        or journal.authorization_id != checkpoint.authorization_id
        or journal.step_id != checkpoint.step_id
        or journal.idempotency_key != checkpoint.idempotency_key
        or journal.execution_identity_id != checkpoint.execution_identity_id
        or journal.status != checkpoint.status
        or journal.result_digest != checkpoint.result_digest
        or journal.failure_digest != checkpoint.failure_digest
        or checkpoint.step_digest != step.step_digest
        or (
            execution.execution_identity is not None
            and checkpoint.execution_identity_id
            != execution.execution_identity.execution_identity_id
        )
    ):
        raise WorkerExecutionError("worker checkpoint and journal do not match")
    if checkpoint.status not in {"completed", "failed"}:
        raise WorkerExecutionError("worker checkpoint status is invalid")
    if checkpoint.status == "completed":
        if not checkpoint.result_digest or checkpoint.failure_digest is not None:
            raise WorkerExecutionError("completed worker checkpoint is invalid")
        _validate_effects(
            step,
            step_auth,
            WorkerHandlerResult({}, journal.effects),
        )
    elif (
        checkpoint.result_digest is not None
        or not checkpoint.failure_digest
        or journal.effects
    ):
        raise WorkerExecutionError("failed worker checkpoint is invalid")
    journal_identity = journal.as_dict()
    journal_identity.pop("journal_id")
    if hashlib.sha256(canonical_json(journal_identity)).hexdigest() != journal.journal_id:
        raise WorkerExecutionError("worker journal digest does not match")
    checkpoint_identity = checkpoint.as_dict()
    checkpoint_identity.pop("checkpoint_id")
    checkpoint_identity["journal_id"] = journal.journal_id
    if (
        hashlib.sha256(canonical_json(checkpoint_identity)).hexdigest()
        != checkpoint.checkpoint_id
    ):
        raise WorkerExecutionError("worker checkpoint digest does not match")


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
            return WorkerExecution(
                previous.checkpoint,
                previous.journal,
                True,
                previous.execution_identity,
            )
    _validate_dependencies(plan, step, history)
    handler = handlers.get(request.handler_id)
    if handler is None:
        raise WorkerExecutionError("worker handler is not explicitly registered")
    if not set(step.required_capabilities).issubset(handler.capabilities):
        raise WorkerExecutionError("worker handler lacks required capabilities")
    if not set(handler.side_effects).issubset(step.side_effects):
        raise WorkerExecutionError("worker handler side effects exceed the task step")
    if (
        request.execution_identity.actor_digest != handler.identity_actor_digest
        or request.execution_identity.runtime_kind != handler.runtime_kind
    ):
        raise WorkerExecutionError(
            "worker execution identity does not match the registered handler"
        )
    context = WorkerContext(
        request.task_id,
        request.plan_id,
        request.authorization_id,
        request.execution_identity,
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
