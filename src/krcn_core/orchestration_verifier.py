"""Independent, evidence-bound verification for orchestrated tasks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Sequence

from .agent_execution_identity import (
    AgentExecutionIdentity,
    RUNTIME_KINDS,
    parse_agent_execution_identity,
)
from .information_records import canonical_json
from .orchestration_authorization import TaskAuthorization
from .orchestration_intent import TaskIntent
from .orchestration_plan import TaskPlan, TaskPlanStep
from .orchestration_worker import WorkerExecution, validate_worker_execution


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SUBJECT_KINDS = {
    "acceptance-criterion",
    "constraint",
    "verification-requirement",
}
EVIDENCE_TYPES = {
    "artifact-digest",
    "policy-decision",
    "preservation-check",
    "state-observation",
    "test-result",
}


class TaskVerificationError(ValueError):
    """Raised when verification inputs are invalid or evidence is untrusted."""


@dataclass(frozen=True)
class VerificationSubject:
    kind: str
    value: str
    subject_digest: str


@dataclass(frozen=True)
class VerificationEvidence:
    evidence_id: str
    evidence_type: str
    subject_kind: str
    subject_digest: str
    verifier_step_id: str
    verifier_execution_identity_id: str
    covered_worker_step_ids: tuple[str, ...]
    observed_digests: tuple[str, ...]
    passed: bool
    evidence_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "subject_kind": self.subject_kind,
            "subject_digest": self.subject_digest,
            "verifier_step_id": self.verifier_step_id,
            "verifier_execution_identity_id": self.verifier_execution_identity_id,
            "covered_worker_step_ids": list(self.covered_worker_step_ids),
            "observed_digests": list(self.observed_digests),
            "passed": self.passed,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class VerifierHandlerResult:
    evidence: tuple[VerificationEvidence, ...]


@dataclass(frozen=True)
class VerifierContext:
    task_id: str
    plan_id: str
    authorization_id: str
    verifier_step_id: str
    verifier_execution_identity: AgentExecutionIdentity
    subjects: tuple[VerificationSubject, ...]
    worker_executions: tuple[WorkerExecution, ...]
    allowed_evidence_digests: tuple[str, ...]


@dataclass(frozen=True)
class VerifierHandlerSpec:
    handler_id: str
    capabilities: tuple[str, ...]
    side_effects: tuple[str, ...]
    callback: Callable[[VerifierContext], VerifierHandlerResult]
    identity_actor_digest: str | None = None
    runtime_kind: str | None = None


@dataclass(frozen=True)
class VerifierRequest:
    step_id: str
    handler_id: str
    execution_identity: AgentExecutionIdentity


@dataclass(frozen=True)
class SubjectVerification:
    kind: str
    subject_digest: str
    evidence_ids: tuple[str, ...]
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "subject_digest": self.subject_digest,
            "evidence_ids": list(self.evidence_ids),
            "passed": self.passed,
        }


@dataclass(frozen=True)
class TaskVerification:
    task_id: str
    plan_id: str
    authorization_id: str
    worker_checkpoint_ids: tuple[str, ...]
    worker_execution_identity_ids: tuple[str, ...]
    verifier_execution_identities: tuple[AgentExecutionIdentity, ...]
    evidence: tuple[VerificationEvidence, ...]
    subjects: tuple[SubjectVerification, ...]
    failure_codes: tuple[str, ...]
    status: str
    completion_allowed: bool
    verification_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/task-verification.schema.json",
            "schema_version": 2,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "authorization_id": self.authorization_id,
            "worker_checkpoint_ids": list(self.worker_checkpoint_ids),
            "worker_execution_identity_ids": list(
                self.worker_execution_identity_ids
            ),
            "verifier_execution_identities": [
                item.as_dict() for item in self.verifier_execution_identities
            ],
            "evidence": [item.as_dict() for item in self.evidence],
            "subjects": [item.as_dict() for item in self.subjects],
            "failure_codes": list(self.failure_codes),
            "status": self.status,
            "completion_allowed": self.completion_allowed,
            "verification_id": self.verification_id,
        }


class VerifierHandlerRegistry:
    """Explicit verifier registry; verifier selection never scans the host."""

    def __init__(self) -> None:
        self._handlers: dict[str, VerifierHandlerSpec] = {}

    def register(self, spec: VerifierHandlerSpec) -> None:
        if not IDENTIFIER.fullmatch(spec.handler_id):
            raise TaskVerificationError("verifier handler id is invalid")
        if spec.handler_id in self._handlers:
            raise TaskVerificationError("verifier handler is already registered")
        if not spec.capabilities or len(set(spec.capabilities)) != len(spec.capabilities):
            raise TaskVerificationError("verifier capabilities are invalid")
        if not set(spec.side_effects).issubset({"read", "execute"}):
            raise TaskVerificationError("verifier handlers may only read and execute")
        if len(set(spec.side_effects)) != len(spec.side_effects):
            raise TaskVerificationError("verifier side effects must be unique")
        if not callable(spec.callback):
            raise TaskVerificationError("verifier callback is invalid")
        if (
            not isinstance(spec.identity_actor_digest, str)
            or not SHA256.fullmatch(spec.identity_actor_digest)
            or spec.runtime_kind not in RUNTIME_KINDS
        ):
            raise TaskVerificationError("verifier handler execution identity is invalid")
        self._handlers[spec.handler_id] = spec

    def get(self, handler_id: str) -> VerifierHandlerSpec | None:
        return self._handlers.get(handler_id)


def verification_subject_digest(kind: str, value: str) -> str:
    if kind not in SUBJECT_KINDS or not isinstance(value, str) or not value.strip():
        raise TaskVerificationError("verification subject is invalid")
    return hashlib.sha256(canonical_json({"kind": kind, "value": value})).hexdigest()


def create_verification_evidence(
    *,
    evidence_id: str,
    evidence_type: str,
    subject_kind: str,
    subject_digest: str,
    verifier_step_id: str,
    verifier_execution_identity_id: str,
    covered_worker_step_ids: Sequence[str],
    observed_digests: Sequence[str],
    passed: bool,
) -> VerificationEvidence:
    """Create digest-bound evidence without retaining raw observed data."""

    if not IDENTIFIER.fullmatch(evidence_id):
        raise TaskVerificationError("evidence id is invalid")
    if evidence_type not in EVIDENCE_TYPES or subject_kind not in SUBJECT_KINDS:
        raise TaskVerificationError("evidence classification is invalid")
    if (
        not isinstance(subject_digest, str)
        or not SHA256.fullmatch(subject_digest)
        or not IDENTIFIER.fullmatch(verifier_step_id)
        or not isinstance(verifier_execution_identity_id, str)
        or not SHA256.fullmatch(verifier_execution_identity_id)
    ):
        raise TaskVerificationError("evidence subject or verifier is invalid")
    workers = tuple(sorted(set(covered_worker_step_ids)))
    observed = tuple(sorted(set(observed_digests)))
    if (
        not workers
        or len(workers) != len(tuple(covered_worker_step_ids))
        or any(not IDENTIFIER.fullmatch(item) for item in workers)
    ):
        raise TaskVerificationError("evidence worker coverage is invalid")
    if (
        not observed
        or len(observed) != len(tuple(observed_digests))
        or any(not SHA256.fullmatch(item) for item in observed)
    ):
        raise TaskVerificationError("observed evidence digests are invalid")
    if not isinstance(passed, bool):
        raise TaskVerificationError("evidence passed must be boolean")
    identity = {
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "subject_kind": subject_kind,
        "subject_digest": subject_digest,
        "verifier_step_id": verifier_step_id,
        "verifier_execution_identity_id": verifier_execution_identity_id,
        "covered_worker_step_ids": list(workers),
        "observed_digests": list(observed),
        "passed": passed,
    }
    return VerificationEvidence(
        evidence_id,
        evidence_type,
        subject_kind,
        subject_digest,
        verifier_step_id,
        verifier_execution_identity_id,
        workers,
        observed,
        passed,
        hashlib.sha256(canonical_json(identity)).hexdigest(),
    )


def _subjects(intent: TaskIntent) -> tuple[VerificationSubject, ...]:
    values = [
        *(VerificationSubject(
            "acceptance-criterion",
            item.value,
            verification_subject_digest("acceptance-criterion", item.value),
        ) for item in intent.acceptance_criteria),
        *(VerificationSubject(
            "constraint",
            item.value,
            verification_subject_digest("constraint", item.value),
        ) for item in intent.constraints),
        *(VerificationSubject(
            "verification-requirement",
            item.value,
            verification_subject_digest("verification-requirement", item.value),
        ) for item in intent.verification_requirements),
    ]
    return tuple(sorted(values, key=lambda item: (item.kind, item.subject_digest)))


def _ancestors(step_id: str, steps: dict[str, TaskPlanStep]) -> set[str]:
    found: set[str] = set()
    pending = list(steps[step_id].depends_on)
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(steps[current].depends_on)
    return found


def _evidence_digest(evidence: VerificationEvidence) -> str:
    payload = evidence.as_dict()
    payload.pop("evidence_digest")
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _allowed_digests(execution: WorkerExecution) -> set[str]:
    values = {
        execution.checkpoint.checkpoint_id,
        execution.journal.journal_id,
    }
    if execution.checkpoint.result_digest:
        values.add(execution.checkpoint.result_digest)
    values.update(
        digest
        for effect in execution.journal.effects
        for digest in effect.evidence_digests
    )
    return values


def verify_task(
    intent: TaskIntent,
    plan: TaskPlan,
    authorization: TaskAuthorization,
    executions: Sequence[WorkerExecution],
    requests: Sequence[VerifierRequest],
    handlers: VerifierHandlerRegistry,
) -> TaskVerification:
    """Verify every worker, constraint, criterion, and requirement before completion."""

    authorization_payload = authorization.as_dict()
    authorization_payload.pop("schema_ref")
    authorization_payload.pop("schema_version")
    authorization_payload.pop("authorization_id")
    if (
        intent.task_id != plan.task_id
        or intent.intent_digest != plan.intent_digest
        or authorization.task_id != plan.task_id
        or authorization.plan_id != plan.plan_id
        or authorization.intent_digest != intent.intent_digest
        or hashlib.sha256(canonical_json(authorization_payload)).hexdigest()
        != authorization.authorization_id
    ):
        raise TaskVerificationError("verification context does not match the exact task plan")
    steps = {step.step_id: step for step in plan.steps}
    worker_ids = {step.step_id for step in plan.steps if step.role == "worker"}
    verifier_ids = {step.step_id for step in plan.steps if step.role == "verifier"}
    completed: dict[str, WorkerExecution] = {}
    failure_codes: set[str] = set()
    for execution in executions:
        if execution.execution_identity is None:
            raise TaskVerificationError(
                "worker execution identity is required for independent verification"
            )
        try:
            validate_worker_execution(plan, authorization, execution)
        except ValueError as exc:
            raise TaskVerificationError("worker evidence is invalid") from exc
        if execution.checkpoint.status == "completed":
            previous = completed.get(execution.checkpoint.step_id)
            if previous and previous.checkpoint.checkpoint_id != execution.checkpoint.checkpoint_id:
                raise TaskVerificationError("worker has conflicting completed checkpoints")
            completed[execution.checkpoint.step_id] = execution
    if set(completed) != worker_ids:
        failure_codes.add("worker-checkpoint-incomplete")
    worker_identities = tuple(
        sorted(
            (item.execution_identity for item in completed.values()),
            key=lambda item: item.execution_identity_id,
        )
    )

    request_by_step: dict[str, VerifierRequest] = {}
    for request in requests:
        try:
            identity = parse_agent_execution_identity(
                request.execution_identity.as_dict()
            )
        except (AttributeError, ValueError) as exc:
            raise TaskVerificationError("verifier execution identity is invalid") from exc
        if (
            request.step_id not in verifier_ids
            or not IDENTIFIER.fullmatch(request.handler_id)
            or identity.task_id != plan.task_id
            or identity.plan_id != plan.plan_id
            or identity.step_id != request.step_id
            or identity.role != "verifier"
        ):
            raise TaskVerificationError("verifier request is invalid")
        if request.step_id in request_by_step:
            raise TaskVerificationError("verifier request is duplicated")
        request_by_step[request.step_id] = request
    if set(request_by_step) != verifier_ids:
        raise TaskVerificationError("every verifier step requires an explicit handler")
    verifier_identities = tuple(
        request_by_step[step_id].execution_identity
        for step_id in sorted(request_by_step)
    )
    if len({item.execution_identity_id for item in verifier_identities}) != len(
        verifier_identities
    ):
        raise TaskVerificationError("verifier execution identities must be unique")
    worker_actor_digests = {item.actor_digest for item in worker_identities}
    worker_assignment_digests = {item.assignment_digest for item in worker_identities}
    if any(
        item.actor_digest in worker_actor_digests
        or item.assignment_digest in worker_assignment_digests
        for item in verifier_identities
    ):
        raise TaskVerificationError(
            "verifier execution identity must be independent from every worker"
        )

    subjects = _subjects(intent)
    subject_map = {(item.kind, item.subject_digest): item for item in subjects}
    all_evidence: list[VerificationEvidence] = []
    for step_id in sorted(verifier_ids):
        step = steps[step_id]
        request = request_by_step[step_id]
        handler = handlers.get(request.handler_id)
        if handler is None:
            raise TaskVerificationError("verifier handler is not explicitly registered")
        if not set(step.required_capabilities).issubset(handler.capabilities):
            raise TaskVerificationError("verifier handler lacks required capabilities")
        if not set(handler.side_effects).issubset(step.side_effects):
            raise TaskVerificationError("verifier handler side effects exceed the task step")
        if (
            request.execution_identity.actor_digest != handler.identity_actor_digest
            or request.execution_identity.runtime_kind != handler.runtime_kind
        ):
            raise TaskVerificationError(
                "verifier execution identity does not match the registered handler"
            )
        covered_workers = worker_ids & _ancestors(step_id, steps)
        available = tuple(
            sorted(
                (completed[item] for item in covered_workers if item in completed),
                key=lambda item: item.checkpoint.step_id,
            )
        )
        allowed = tuple(sorted({digest for item in available for digest in _allowed_digests(item)}))
        context = VerifierContext(
            plan.task_id,
            plan.plan_id,
            authorization.authorization_id,
            step_id,
            request.execution_identity,
            subjects,
            available,
            allowed,
        )
        try:
            result = handler.callback(context)
        except Exception:
            failure_codes.add("verifier-handler-failed")
            continue
        if not isinstance(result, VerifierHandlerResult):
            raise TaskVerificationError("verifier handler result is invalid")
        allowed_set = set(allowed)
        for evidence in result.evidence:
            if evidence.evidence_digest != _evidence_digest(evidence):
                raise TaskVerificationError("verification evidence digest does not match")
            if evidence.verifier_step_id != step_id:
                raise TaskVerificationError("verification evidence is bound to another step")
            if (
                evidence.verifier_execution_identity_id
                != request.execution_identity.execution_identity_id
            ):
                raise TaskVerificationError(
                    "verification evidence is bound to another execution identity"
                )
            subject = subject_map.get((evidence.subject_kind, evidence.subject_digest))
            if subject is None:
                raise TaskVerificationError("verification evidence subject is not planned")
            if (
                subject.kind == "acceptance-criterion"
                and subject.value not in step.acceptance_criteria
            ) or (
                subject.kind == "verification-requirement"
                and subject.value not in step.verification_requirements
            ):
                raise TaskVerificationError("verification evidence exceeds verifier step scope")
            if not set(evidence.covered_worker_step_ids).issubset(covered_workers):
                raise TaskVerificationError("verification evidence exceeds worker coverage")
            if not set(evidence.observed_digests).issubset(allowed_set):
                raise TaskVerificationError("verification evidence is not backed by worker output")
            all_evidence.append(evidence)

    ordered_evidence = tuple(sorted(all_evidence, key=lambda item: item.evidence_id))
    if len({item.evidence_id for item in ordered_evidence}) != len(ordered_evidence):
        raise TaskVerificationError("verification evidence ids must be unique")
    covered_worker_ids = {
        worker
        for evidence in ordered_evidence
        for worker in evidence.covered_worker_step_ids
        if evidence.passed
    }
    if covered_worker_ids != worker_ids:
        failure_codes.add("worker-evidence-incomplete")

    subject_results = []
    for subject in subjects:
        matching = tuple(
            item
            for item in ordered_evidence
            if item.subject_kind == subject.kind
            and item.subject_digest == subject.subject_digest
        )
        passed = bool(matching) and all(item.passed for item in matching)
        if not matching:
            failure_codes.add("subject-evidence-missing")
        elif not passed:
            failure_codes.add("subject-verification-failed")
        subject_results.append(
            SubjectVerification(
                subject.kind,
                subject.subject_digest,
                tuple(item.evidence_id for item in matching),
                passed,
            )
        )
    failures = tuple(sorted(failure_codes))
    completion_allowed = not failures and all(item.passed for item in subject_results)
    identity = {
        "task_id": plan.task_id,
        "plan_id": plan.plan_id,
        "authorization_id": authorization.authorization_id,
        "worker_checkpoint_ids": sorted(
            item.checkpoint.checkpoint_id for item in completed.values()
        ),
        "worker_execution_identity_ids": sorted(
            item.execution_identity_id for item in worker_identities
        ),
        "verifier_execution_identities": [
            item.as_dict() for item in verifier_identities
        ],
        "evidence": [item.as_dict() for item in ordered_evidence],
        "subjects": [item.as_dict() for item in subject_results],
        "failure_codes": list(failures),
        "status": "verified" if completion_allowed else "failed",
        "completion_allowed": completion_allowed,
    }
    verification_id = hashlib.sha256(canonical_json(identity)).hexdigest()
    return TaskVerification(
        plan.task_id,
        plan.plan_id,
        authorization.authorization_id,
        tuple(identity["worker_checkpoint_ids"]),
        tuple(identity["worker_execution_identity_ids"]),
        verifier_identities,
        ordered_evidence,
        tuple(subject_results),
        failures,
        str(identity["status"]),
        completion_allowed,
        verification_id,
    )
