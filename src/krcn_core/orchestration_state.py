"""Persistent orchestration state, event history, resume, and handoff records."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence

from .information_records import canonical_json
from .mutation_gate import DryRunEvidence, authorize_mutation
from .orchestration_authorization import TaskAuthorization
from .orchestration_plan import TaskPlan
from .orchestration_verifier import TaskVerification
from .orchestration_worker import (
    WorkerExecution,
    parse_worker_execution,
    validate_worker_execution,
)

if TYPE_CHECKING:
    from .local_store import LocalWorkspaceStore, StoredRecord


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
STATUSES = {
    "planned",
    "awaiting-approval",
    "authorized",
    "running",
    "verifying",
    "completed",
    "failed",
    "interrupted",
    "blocked",
}
TRANSITIONS = {
    "planned": {"authorized", "blocked"},
    "awaiting-approval": {"authorized", "blocked"},
    "authorized": {"running", "blocked"},
    "running": {"running", "verifying", "failed", "interrupted", "blocked"},
    "verifying": {"completed", "failed", "interrupted", "blocked"},
    "failed": {"running", "blocked"},
    "interrupted": {"running", "verifying", "failed", "blocked"},
    "completed": set(),
    "blocked": {"authorized"},
}


class OrchestrationStateError(ValueError):
    """Raised when orchestration history cannot be persisted or resumed safely."""


@dataclass(frozen=True)
class OrchestrationState:
    state_id: str
    task_id: str
    session_id: str
    plan_id: str
    authorization_id: str | None
    verification_id: str | None
    status: str
    current_step_id: str | None
    completed_step_ids: tuple[str, ...]
    failed_step_ids: tuple[str, ...]
    event_head_digest: str
    revision: int
    state_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/orchestration-state.schema.json",
            "schema_version": 1,
            "state_id": self.state_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "plan_id": self.plan_id,
            "authorization_id": self.authorization_id,
            "verification_id": self.verification_id,
            "status": self.status,
            "current_step_id": self.current_step_id,
            "completed_step_ids": list(self.completed_step_ids),
            "failed_step_ids": list(self.failed_step_ids),
            "event_head_digest": self.event_head_digest,
            "revision": self.revision,
            "state_digest": self.state_digest,
        }


@dataclass(frozen=True)
class OrchestrationEvent:
    event_id: str
    task_id: str
    plan_id: str
    sequence: int
    event_type: str
    from_status: str | None
    to_status: str
    subject_digest: str
    prior_event_digest: str | None
    state_revision: int
    revision: int
    event_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/orchestration-event.schema.json",
            "schema_version": 1,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "subject_digest": self.subject_digest,
            "prior_event_digest": self.prior_event_digest,
            "state_revision": self.state_revision,
            "revision": self.revision,
            "event_digest": self.event_digest,
        }


@dataclass(frozen=True)
class OrchestrationHandoff:
    handoff_id: str
    task_id: str
    plan_id: str
    authorization_id: str | None
    state_digest: str
    event_head_digest: str
    status: str
    completed_step_ids: tuple[str, ...]
    pending_step_ids: tuple[str, ...]
    approval_triggers: tuple[str, ...]
    failure_codes: tuple[str, ...]
    context_refs: tuple[str, ...]
    resume_token: str
    revision: int
    handoff_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/orchestration-handoff.schema.json",
            "schema_version": 1,
            "handoff_id": self.handoff_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "authorization_id": self.authorization_id,
            "state_digest": self.state_digest,
            "event_head_digest": self.event_head_digest,
            "status": self.status,
            "completed_step_ids": list(self.completed_step_ids),
            "pending_step_ids": list(self.pending_step_ids),
            "approval_triggers": list(self.approval_triggers),
            "failure_codes": list(self.failure_codes),
            "context_refs": list(self.context_refs),
            "resume_token": self.resume_token,
            "revision": self.revision,
            "handoff_digest": self.handoff_digest,
        }


@dataclass(frozen=True)
class ResumePackage:
    state: OrchestrationState
    executions: tuple[WorkerExecution, ...]
    event_count: int
    next_step_ids: tuple[str, ...]
    approval_triggers: tuple[str, ...]
    handoff: OrchestrationHandoff | None

    def public_summary(self) -> dict[str, object]:
        return {
            "task_id": self.state.task_id,
            "plan_id": self.state.plan_id,
            "status": self.state.status,
            "state_revision": self.state.revision,
            "event_count": self.event_count,
            "completed_step_ids": list(self.state.completed_step_ids),
            "next_step_ids": list(self.next_step_ids),
            "approval_triggers": list(self.approval_triggers),
            "resume_token": self.handoff.resume_token if self.handoff else None,
        }


def _digest(payload: Mapping[str, object], digest_field: str) -> str:
    identity = dict(payload)
    identity.pop(digest_field, None)
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def _validate_ids(values: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(values, list)
        or len(set(values)) != len(values)
        or any(not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in values)
    ):
        raise OrchestrationStateError(f"{label} is invalid")
    return tuple(sorted(values))


def parse_orchestration_state(payload: object) -> OrchestrationState:
    expected = {
        "schema_ref", "schema_version", "state_id", "task_id", "session_id",
        "plan_id", "authorization_id", "verification_id", "status",
        "current_step_id", "completed_step_ids", "failed_step_ids",
        "event_head_digest", "revision", "state_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise OrchestrationStateError("orchestration state fields are invalid")
    if payload.get("schema_ref") != "schemas/orchestration-state.schema.json" or payload.get("schema_version") != 1:
        raise OrchestrationStateError("orchestration state header is invalid")
    for field in ("state_id", "task_id"):
        if not IDENTIFIER.fullmatch(str(payload.get(field, ""))):
            raise OrchestrationStateError("orchestration state identity is invalid")
    if payload["state_id"] != payload["task_id"] or not str(payload.get("session_id", "")).strip():
        raise OrchestrationStateError("orchestration state scope is invalid")
    for field in ("plan_id", "event_head_digest", "state_digest"):
        if not SHA256.fullmatch(str(payload.get(field, ""))):
            raise OrchestrationStateError("orchestration state digest is invalid")
    for field in ("authorization_id", "verification_id"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not SHA256.fullmatch(value)):
            raise OrchestrationStateError("orchestration state optional digest is invalid")
    status = payload.get("status")
    current_step = payload.get("current_step_id")
    if status not in STATUSES or (current_step is not None and not IDENTIFIER.fullmatch(str(current_step))):
        raise OrchestrationStateError("orchestration state status is invalid")
    completed = _validate_ids(payload.get("completed_step_ids"), "completed steps")
    failed = _validate_ids(payload.get("failed_step_ids"), "failed steps")
    if set(completed) & set(failed):
        raise OrchestrationStateError("completed and failed steps overlap")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise OrchestrationStateError("orchestration state revision is invalid")
    if payload["state_digest"] != _digest(payload, "state_digest"):
        raise OrchestrationStateError("orchestration state digest does not match")
    return OrchestrationState(
        str(payload["state_id"]), str(payload["task_id"]), str(payload["session_id"]),
        str(payload["plan_id"]), payload["authorization_id"], payload["verification_id"],
        str(status), current_step, completed, failed, str(payload["event_head_digest"]),
        revision, str(payload["state_digest"]),
    )


def parse_orchestration_event(payload: object) -> OrchestrationEvent:
    expected = {
        "schema_ref", "schema_version", "event_id", "task_id", "plan_id",
        "sequence", "event_type", "from_status", "to_status", "subject_digest",
        "prior_event_digest", "state_revision", "revision", "event_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise OrchestrationStateError("orchestration event fields are invalid")
    if payload.get("schema_ref") != "schemas/orchestration-event.schema.json" or payload.get("schema_version") != 1:
        raise OrchestrationStateError("orchestration event header is invalid")
    for field in ("event_id", "task_id", "event_type"):
        if not IDENTIFIER.fullmatch(str(payload.get(field, ""))):
            raise OrchestrationStateError("orchestration event identity is invalid")
    if not SHA256.fullmatch(str(payload.get("plan_id", ""))) or not SHA256.fullmatch(str(payload.get("subject_digest", ""))):
        raise OrchestrationStateError("orchestration event digest is invalid")
    prior = payload.get("prior_event_digest")
    if prior is not None and (not isinstance(prior, str) or not SHA256.fullmatch(prior)):
        raise OrchestrationStateError("orchestration prior event digest is invalid")
    if payload.get("from_status") is not None and payload.get("from_status") not in STATUSES:
        raise OrchestrationStateError("orchestration event source status is invalid")
    if payload.get("to_status") not in STATUSES:
        raise OrchestrationStateError("orchestration event target status is invalid")
    if payload.get("revision") != 1:
        raise OrchestrationStateError("orchestration event revision must be 1")
    sequence = payload.get("sequence")
    state_revision = payload.get("state_revision")
    if not isinstance(sequence, int) or sequence < 1 or sequence != state_revision:
        raise OrchestrationStateError("orchestration event sequence is invalid")
    if payload.get("event_digest") != _digest(payload, "event_digest"):
        raise OrchestrationStateError("orchestration event digest does not match")
    return OrchestrationEvent(
        str(payload["event_id"]), str(payload["task_id"]), str(payload["plan_id"]),
        sequence, str(payload["event_type"]), payload["from_status"], str(payload["to_status"]),
        str(payload["subject_digest"]), prior, state_revision, 1, str(payload["event_digest"]),
    )


def parse_orchestration_checkpoint(payload: object) -> tuple[int, WorkerExecution]:
    expected = {
        "schema_ref", "schema_version", "checkpoint_record_id", "task_id",
        "plan_id", "authorization_id", "step_id", "execution", "revision",
        "record_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise OrchestrationStateError("orchestration checkpoint fields are invalid")
    if payload.get("schema_ref") != "schemas/orchestration-checkpoint.schema.json" or payload.get("schema_version") != 1:
        raise OrchestrationStateError("orchestration checkpoint header is invalid")
    for field in ("checkpoint_record_id", "task_id", "step_id"):
        if not IDENTIFIER.fullmatch(str(payload.get(field, ""))):
            raise OrchestrationStateError("orchestration checkpoint identity is invalid")
    for field in ("plan_id", "authorization_id", "record_digest"):
        if not SHA256.fullmatch(str(payload.get(field, ""))):
            raise OrchestrationStateError("orchestration checkpoint digest is invalid")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise OrchestrationStateError("orchestration checkpoint revision is invalid")
    try:
        execution = parse_worker_execution(payload.get("execution"))
    except ValueError as exc:
        raise OrchestrationStateError("persisted worker execution is invalid") from exc
    if (
        execution.checkpoint.task_id != payload["task_id"]
        or execution.checkpoint.plan_id != payload["plan_id"]
        or execution.checkpoint.authorization_id != payload["authorization_id"]
        or execution.checkpoint.step_id != payload["step_id"]
        or payload["record_digest"] != _digest(payload, "record_digest")
    ):
        raise OrchestrationStateError("orchestration checkpoint binding is invalid")
    return revision, execution


def parse_orchestration_handoff(payload: object) -> OrchestrationHandoff:
    expected = {
        "schema_ref", "schema_version", "handoff_id", "task_id", "plan_id",
        "authorization_id", "state_digest", "event_head_digest", "status",
        "completed_step_ids", "pending_step_ids", "approval_triggers",
        "failure_codes", "context_refs", "resume_token", "revision", "handoff_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise OrchestrationStateError("orchestration handoff fields are invalid")
    if payload.get("schema_ref") != "schemas/orchestration-handoff.schema.json" or payload.get("schema_version") != 1:
        raise OrchestrationStateError("orchestration handoff header is invalid")
    for field in ("handoff_id", "task_id"):
        if not IDENTIFIER.fullmatch(str(payload.get(field, ""))):
            raise OrchestrationStateError("orchestration handoff identity is invalid")
    for field in ("plan_id", "state_digest", "event_head_digest", "resume_token", "handoff_digest"):
        if not SHA256.fullmatch(str(payload.get(field, ""))):
            raise OrchestrationStateError("orchestration handoff digest is invalid")
    authorization_id = payload.get("authorization_id")
    if authorization_id is not None and not SHA256.fullmatch(str(authorization_id)):
        raise OrchestrationStateError("orchestration handoff authorization is invalid")
    completed = _validate_ids(payload.get("completed_step_ids"), "handoff completed steps")
    pending = _validate_ids(payload.get("pending_step_ids"), "handoff pending steps")
    if set(completed) & set(pending):
        raise OrchestrationStateError("handoff completed and pending steps overlap")
    approvals = _validate_ids(payload.get("approval_triggers"), "handoff approvals")
    failures = _validate_ids(payload.get("failure_codes"), "handoff failures")
    refs = payload.get("context_refs")
    if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs) or any(not isinstance(item, str) or not item.strip() for item in refs):
        raise OrchestrationStateError("handoff context refs are invalid")
    revision = payload.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise OrchestrationStateError("orchestration handoff revision is invalid")
    if payload.get("status") not in STATUSES or payload["handoff_digest"] != _digest(payload, "handoff_digest"):
        raise OrchestrationStateError("orchestration handoff status or digest is invalid")
    return OrchestrationHandoff(
        str(payload["handoff_id"]), str(payload["task_id"]), str(payload["plan_id"]),
        authorization_id, str(payload["state_digest"]), str(payload["event_head_digest"]),
        str(payload["status"]), completed, pending, approvals, failures, tuple(refs),
        str(payload["resume_token"]), revision, str(payload["handoff_digest"]),
    )


def _event(
    *,
    task_id: str,
    plan_id: str,
    sequence: int,
    event_type: str,
    from_status: str | None,
    to_status: str,
    subject_digest: str,
    prior_event_digest: str | None,
) -> OrchestrationEvent:
    base = {
        "task_id": task_id,
        "plan_id": plan_id,
        "sequence": sequence,
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "subject_digest": subject_digest,
        "prior_event_digest": prior_event_digest,
        "state_revision": sequence,
    }
    event_id = "event-" + hashlib.sha256(canonical_json(base)).hexdigest()[:24]
    payload = {
        "schema_ref": "schemas/orchestration-event.schema.json",
        "schema_version": 1,
        "event_id": event_id,
        **base,
        "revision": 1,
    }
    payload["event_digest"] = _digest(payload, "event_digest")
    return parse_orchestration_event(payload)


def _state_payload(
    *,
    task_id: str,
    session_id: str,
    plan_id: str,
    authorization_id: str | None,
    verification_id: str | None,
    status: str,
    current_step_id: str | None,
    completed_step_ids: Sequence[str],
    failed_step_ids: Sequence[str],
    event_head_digest: str,
    revision: int,
) -> OrchestrationState:
    payload = {
        "schema_ref": "schemas/orchestration-state.schema.json",
        "schema_version": 1,
        "state_id": task_id,
        "task_id": task_id,
        "session_id": session_id,
        "plan_id": plan_id,
        "authorization_id": authorization_id,
        "verification_id": verification_id,
        "status": status,
        "current_step_id": current_step_id,
        "completed_step_ids": sorted(set(completed_step_ids)),
        "failed_step_ids": sorted(set(failed_step_ids)),
        "event_head_digest": event_head_digest,
        "revision": revision,
    }
    payload["state_digest"] = _digest(payload, "state_digest")
    return parse_orchestration_state(payload)


def create_initial_state(
    plan: TaskPlan,
    session_id: str,
    authorization: TaskAuthorization | None = None,
) -> tuple[OrchestrationState, OrchestrationEvent]:
    if not session_id.strip():
        raise OrchestrationStateError("session id is required")
    if authorization and (authorization.plan_id != plan.plan_id or authorization.task_id != plan.task_id):
        raise OrchestrationStateError("initial authorization does not match task plan")
    status = "authorized" if authorization else ("awaiting-approval" if plan.requires_approval else "planned")
    event = _event(
        task_id=plan.task_id,
        plan_id=plan.plan_id,
        sequence=1,
        event_type="task-initialized",
        from_status=None,
        to_status=status,
        subject_digest=authorization.authorization_id if authorization else plan.plan_id,
        prior_event_digest=None,
    )
    state = _state_payload(
        task_id=plan.task_id,
        session_id=session_id,
        plan_id=plan.plan_id,
        authorization_id=authorization.authorization_id if authorization else None,
        verification_id=None,
        status=status,
        current_step_id=None,
        completed_step_ids=(),
        failed_step_ids=(),
        event_head_digest=event.event_digest,
        revision=1,
    )
    return state, event


def transition_state(
    current: OrchestrationState,
    plan: TaskPlan,
    *,
    to_status: str,
    event_type: str,
    subject_digest: str,
    authorization: TaskAuthorization | None = None,
    verification: TaskVerification | None = None,
    completed_step_ids: Sequence[str] | None = None,
    failed_step_ids: Sequence[str] | None = None,
    current_step_id: str | None = None,
) -> tuple[OrchestrationState, OrchestrationEvent]:
    if current.plan_id != plan.plan_id or current.task_id != plan.task_id:
        raise OrchestrationStateError("state does not match task plan")
    if to_status not in TRANSITIONS[current.status]:
        raise OrchestrationStateError("orchestration state transition is invalid")
    if not IDENTIFIER.fullmatch(event_type) or not SHA256.fullmatch(subject_digest):
        raise OrchestrationStateError("orchestration transition evidence is invalid")
    authorization_id = current.authorization_id
    if authorization is not None:
        if authorization.plan_id != plan.plan_id or authorization.task_id != plan.task_id:
            raise OrchestrationStateError("transition authorization does not match")
        authorization_id = authorization.authorization_id
    if to_status in {"authorized", "running", "verifying", "completed"} and authorization_id is None:
        raise OrchestrationStateError("authorized state requires task authorization")
    completed = tuple(sorted(set(completed_step_ids if completed_step_ids is not None else current.completed_step_ids)))
    failed = tuple(sorted(set(failed_step_ids if failed_step_ids is not None else current.failed_step_ids)))
    worker_ids = {step.step_id for step in plan.steps if step.role == "worker"}
    if not set(current.completed_step_ids).issubset(completed) or not set(completed).issubset(worker_ids) or not set(failed).issubset(worker_ids) or set(completed) & set(failed):
        raise OrchestrationStateError("transition worker state is invalid")
    if current_step_id is not None and current_step_id not in worker_ids:
        raise OrchestrationStateError("transition current step is invalid")
    verification_id = current.verification_id
    if to_status == "verifying" and set(completed) != worker_ids:
        raise OrchestrationStateError("verification requires every worker checkpoint")
    if to_status == "completed":
        if not (
            verification
            and verification.plan_id == plan.plan_id
            and verification.authorization_id == authorization_id
            and verification.completion_allowed
            and verification.status == "verified"
            and set(completed) == worker_ids
        ):
            raise OrchestrationStateError("completion requires passing task verification")
        verification_id = verification.verification_id
    event = _event(
        task_id=plan.task_id,
        plan_id=plan.plan_id,
        sequence=current.revision + 1,
        event_type=event_type,
        from_status=current.status,
        to_status=to_status,
        subject_digest=subject_digest,
        prior_event_digest=current.event_head_digest,
    )
    state = _state_payload(
        task_id=current.task_id,
        session_id=current.session_id,
        plan_id=current.plan_id,
        authorization_id=authorization_id,
        verification_id=verification_id,
        status=to_status,
        current_step_id=current_step_id,
        completed_step_ids=completed,
        failed_step_ids=failed,
        event_head_digest=event.event_digest,
        revision=current.revision + 1,
    )
    return state, event


def create_handoff(
    state: OrchestrationState,
    plan: TaskPlan,
    *,
    revision: int,
    verification: TaskVerification | None = None,
) -> OrchestrationHandoff:
    if state.task_id != plan.task_id or state.plan_id != plan.plan_id:
        raise OrchestrationStateError("handoff state does not match task plan")
    worker_ids = {step.step_id for step in plan.steps if step.role == "worker"}
    pending = tuple(sorted(worker_ids - set(state.completed_step_ids)))
    approval_triggers = plan.approval_triggers if state.status == "awaiting-approval" else ()
    failure_codes = verification.failure_codes if verification and not verification.completion_allowed else ()
    handoff_id = f"{state.task_id}-handoff"
    context_refs = (
        ".ai/repository-context.json",
        "schemas/orchestration-state.schema.json",
        "schemas/task-plan.schema.json",
        f"orchestration-state:{state.state_id}",
    )
    resume_identity = {
        "task_id": state.task_id,
        "plan_id": state.plan_id,
        "state_digest": state.state_digest,
        "event_head_digest": state.event_head_digest,
    }
    payload = {
        "schema_ref": "schemas/orchestration-handoff.schema.json",
        "schema_version": 1,
        "handoff_id": handoff_id,
        "task_id": state.task_id,
        "plan_id": state.plan_id,
        "authorization_id": state.authorization_id,
        "state_digest": state.state_digest,
        "event_head_digest": state.event_head_digest,
        "status": state.status,
        "completed_step_ids": list(state.completed_step_ids),
        "pending_step_ids": list(pending),
        "approval_triggers": list(approval_triggers),
        "failure_codes": list(failure_codes),
        "context_refs": list(context_refs),
        "resume_token": hashlib.sha256(canonical_json(resume_identity)).hexdigest(),
        "revision": revision,
    }
    payload["handoff_digest"] = _digest(payload, "handoff_digest")
    return parse_orchestration_handoff(payload)


class OrchestrationStateStore:
    """Persist orchestration records in runtime-owned local storage."""

    def __init__(self, store: "LocalWorkspaceStore") -> None:
        self._store = store

    @staticmethod
    def _authorize(write_plan):
        return authorize_mutation(
            write_plan.mutation,
            dry_run=DryRunEvidence(write_plan.mutation.plan_id, True),
        )

    def _put(self, record_type: str, record_id: str, payload: Mapping[str, object]):
        current = self._store.read(record_type, record_id)
        expected_revision = current.revision if current else 0
        plan = self._store.prepare_put(
            record_type,
            record_id,
            payload,
            expected_revision=expected_revision,
        )
        if plan.mutation.ownership != "runtime" or plan.mutation.approval_required:
            raise OrchestrationStateError("orchestration records must stay in runtime ownership")
        return self._store.apply_put(plan, self._authorize(plan))

    def initialize(
        self,
        plan: TaskPlan,
        session_id: str,
        authorization: TaskAuthorization | None = None,
    ) -> OrchestrationState:
        if self._store.read("orchestration-states", plan.task_id) is not None:
            raise OrchestrationStateError("orchestration state already exists")
        state, event = create_initial_state(plan, session_id, authorization)
        self._put("orchestration-events", event.event_id, event.as_dict())
        self._put("orchestration-states", state.state_id, state.as_dict())
        return state

    def transition(
        self,
        current: OrchestrationState,
        plan: TaskPlan,
        **kwargs,
    ) -> OrchestrationState:
        stored = self._store.read("orchestration-states", current.state_id)
        if stored is None or stored.revision != current.revision or stored.payload_sha256 != hashlib.sha256((canonical_json(current.as_dict()) + b"\n")).hexdigest():
            raise OrchestrationStateError("orchestration state changed before transition")
        state, event = transition_state(current, plan, **kwargs)
        self._put("orchestration-events", event.event_id, event.as_dict())
        self._put("orchestration-states", state.state_id, state.as_dict())
        return state

    def save_execution(self, execution: WorkerExecution) -> None:
        checkpoint = execution.checkpoint
        record_id = f"{checkpoint.task_id}-{checkpoint.step_id}"
        current = self._store.read("orchestration-checkpoints", record_id)
        revision = current.revision + 1 if current else 1
        payload = {
            "schema_ref": "schemas/orchestration-checkpoint.schema.json",
            "schema_version": 1,
            "checkpoint_record_id": record_id,
            "task_id": checkpoint.task_id,
            "plan_id": checkpoint.plan_id,
            "authorization_id": checkpoint.authorization_id,
            "step_id": checkpoint.step_id,
            "execution": execution.as_dict(),
            "revision": revision,
        }
        payload["record_digest"] = _digest(payload, "record_digest")
        self._put("orchestration-checkpoints", record_id, payload)

    def save_handoff(
        self,
        state: OrchestrationState,
        plan: TaskPlan,
        *,
        verification: TaskVerification | None = None,
    ) -> OrchestrationHandoff:
        record_id = f"{state.task_id}-handoff"
        current = self._store.read("orchestration-handoffs", record_id)
        handoff = create_handoff(
            state,
            plan,
            revision=current.revision + 1 if current else 1,
            verification=verification,
        )
        self._put("orchestration-handoffs", record_id, handoff.as_dict())
        return handoff

    def resume(
        self,
        task_id: str,
        plan: TaskPlan,
        authorization: TaskAuthorization | None = None,
    ) -> ResumePackage:
        stored_state = self._store.read("orchestration-states", task_id)
        if stored_state is None:
            raise OrchestrationStateError("orchestration state was not found")
        state = parse_orchestration_state(stored_state.payload)
        if state.plan_id != plan.plan_id or state.task_id != plan.task_id:
            raise OrchestrationStateError("persisted state does not match task plan")
        if state.authorization_id is not None:
            if authorization is None or authorization.authorization_id != state.authorization_id:
                raise OrchestrationStateError("resume requires matching task authorization")
        events = []
        for record in self._store.list_records("orchestration-events"):
            event = parse_orchestration_event(record.payload)
            if event.task_id == task_id and event.state_revision <= state.revision:
                events.append(event)
        by_digest = {event.event_digest: event for event in events}
        chain = []
        digest: str | None = state.event_head_digest
        while digest is not None:
            event = by_digest.get(digest)
            if event is None:
                raise OrchestrationStateError("orchestration event chain is incomplete")
            chain.append(event)
            digest = event.prior_event_digest
        if len(chain) != state.revision or [item.sequence for item in reversed(chain)] != list(range(1, state.revision + 1)):
            raise OrchestrationStateError("orchestration event chain is invalid")
        executions = []
        for record in self._store.list_records("orchestration-checkpoints"):
            _, execution = parse_orchestration_checkpoint(record.payload)
            if execution.checkpoint.task_id != task_id:
                continue
            if authorization is None:
                raise OrchestrationStateError("checkpoint resume requires authorization")
            validate_worker_execution(plan, authorization, execution)
            executions.append(execution)
        completed = {
            item.checkpoint.step_id
            for item in executions
            if item.checkpoint.status == "completed"
        }
        worker_steps = {step.step_id: step for step in plan.steps if step.role == "worker"}
        next_steps = tuple(
            sorted(
                step_id
                for step_id, step in worker_steps.items()
                if step_id not in completed
                and (set(step.depends_on) & set(worker_steps)).issubset(completed)
            )
        ) if state.status != "completed" else ()
        handoff_record = self._store.read("orchestration-handoffs", f"{task_id}-handoff")
        handoff = parse_orchestration_handoff(handoff_record.payload) if handoff_record else None
        if handoff and (handoff.state_digest != state.state_digest or handoff.plan_id != plan.plan_id):
            handoff = None
        return ResumePackage(
            state,
            tuple(sorted(executions, key=lambda item: item.checkpoint.step_id)),
            len(chain),
            next_steps,
            plan.approval_triggers if state.status == "awaiting-approval" else (),
            handoff,
        )
