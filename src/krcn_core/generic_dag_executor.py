"""Generic TaskPlan DAG execution over the fenced project runtime queue."""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .agent_execution_identity import (
    AgentExecutionIdentity,
    parse_agent_execution_identity,
)
from .agent_runtime import (
    AgentRuntimeQueue,
    runtime_resource_refs_conflict,
    validate_runtime_resource_ref,
)
from .information_records import canonical_json
from .mutation_gate import (
    MutationAuthorization,
    MutationPlan,
    OwnershipResolver,
    plan_mutation,
)
from .orchestration_authorization import TaskAuthorization
from .orchestration_plan import TaskPlan, TaskPlanStep, parse_task_plan


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class GenericDagExecutionError(ValueError):
    """Raised when a generic DAG cannot be scheduled or trusted."""


@dataclass(frozen=True)
class DagStepAssignment:
    step_id: str
    handler_id: str
    execution_identity: AgentExecutionIdentity
    resource_refs: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "handler_id": self.handler_id,
            "execution_identity": self.execution_identity.as_dict(),
            "resource_refs": list(self.resource_refs),
        }


@dataclass(frozen=True)
class DagAdapterSpec:
    handler_id: str
    actor_digest: str
    runtime_kind: str
    callback: Callable[["DagWorkUnit"], Mapping[str, object]]


@dataclass(frozen=True)
class DagWorkUnit:
    project_id: str
    work_item_id: str
    task_id: str
    plan_id: str
    step: TaskPlanStep
    assignment: DagStepAssignment
    dependency_evidence: Mapping[str, str]


@dataclass(frozen=True)
class GenericDagExecutionPlan:
    project_id: str
    work_item_id: str
    work_item_revision: int
    work_item_digest: str
    task_plan: TaskPlan
    authorization_id: str
    assignments: tuple[DagStepAssignment, ...]
    max_concurrency: int
    queue_state_digest: str
    plan_id: str
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/generic-dag-execution-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "task_id": self.task_plan.task_id,
            "task_plan_id": self.task_plan.plan_id,
            "authorization_id": self.authorization_id,
            "assignments": [item.as_dict() for item in self.assignments],
            "max_concurrency": self.max_concurrency,
            "queue_state_sha256": self.queue_state_digest,
            "queue_control_serial": True,
            "handler_execution_parallel": True,
            "grants_authority": False,
            "mutation": self.mutation.as_dict(),
        }


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _validate_authorization(plan: TaskPlan, authorization: TaskAuthorization) -> None:
    plan_steps = {step.step_id: step for step in plan.steps}
    authorized = {step.step_id: step for step in authorization.steps}
    if (
        authorization.task_id != plan.task_id
        or authorization.plan_id != plan.plan_id
        or authorization.intent_digest != plan.intent_digest
        or authorization.selection_digest != plan.selection_digest
        or not SHA256.fullmatch(authorization.authorization_id)
        or set(authorized) != set(plan_steps)
        or any(
            authorized[step_id].step_digest != plan_steps[step_id].step_digest
            for step_id in plan_steps
        )
    ):
        raise GenericDagExecutionError(
            "generic DAG authorization does not match the exact task plan"
        )


def _ancestors(step_id: str, steps: Mapping[str, TaskPlanStep]) -> set[str]:
    found: set[str] = set()
    pending = list(steps[step_id].depends_on)
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(steps[current].depends_on)
    return found


def _validate_assignments(
    project_id: str,
    plan: TaskPlan,
    assignments: Mapping[str, DagStepAssignment],
) -> tuple[DagStepAssignment, ...]:
    steps = {step.step_id: step for step in plan.steps}
    if any(step.role == "planner" for step in plan.steps):
        raise GenericDagExecutionError(
            "planner steps are coordinator work and cannot enter the runtime queue"
        )
    if set(assignments) != set(steps):
        raise GenericDagExecutionError(
            "generic DAG assignments must cover every executable step"
        )
    checked: list[DagStepAssignment] = []
    for step_id in sorted(assignments):
        assignment = assignments[step_id]
        if (
            assignment.step_id != step_id
            or not IDENTIFIER.fullmatch(assignment.handler_id)
        ):
            raise GenericDagExecutionError("generic DAG assignment is invalid")
        try:
            identity = parse_agent_execution_identity(
                assignment.execution_identity.as_dict()
            )
        except (AttributeError, ValueError) as exc:
            raise GenericDagExecutionError(
                "generic DAG execution identity is invalid"
            ) from exc
        step = steps[step_id]
        if (
            identity.task_id != plan.task_id
            or identity.plan_id != plan.plan_id
            or identity.step_id != step_id
            or identity.role != step.role
        ):
            raise GenericDagExecutionError(
                "generic DAG execution identity does not match its task step"
            )
        if not assignment.resource_refs:
            raise GenericDagExecutionError(
                "generic DAG step requires a logical resource reference"
            )
        try:
            resources = tuple(
                sorted(
                    {
                        validate_runtime_resource_ref(value, project_id)
                        for value in assignment.resource_refs
                    }
                )
            )
        except ValueError as exc:
            raise GenericDagExecutionError(
                "generic DAG resource reference is invalid"
            ) from exc
        checked.append(
            DagStepAssignment(step_id, assignment.handler_id, identity, resources)
        )
    if len({item.execution_identity.execution_identity_id for item in checked}) != len(
        checked
    ):
        raise GenericDagExecutionError(
            "generic DAG execution identities must be unique"
        )
    by_step = {item.step_id: item for item in checked}
    for verifier in (step for step in plan.steps if step.role == "verifier"):
        workers = {
            ancestor
            for ancestor in _ancestors(verifier.step_id, steps)
            if steps[ancestor].role == "worker"
        }
        verifier_identity = by_step[verifier.step_id].execution_identity
        if any(
            verifier_identity.actor_digest
            == by_step[worker].execution_identity.actor_digest
            or verifier_identity.assignment_digest
            == by_step[worker].execution_identity.assignment_digest
            for worker in workers
        ):
            raise GenericDagExecutionError(
                "generic DAG verifier identity is not independent"
            )
    return tuple(checked)


def prepare_generic_dag_execution(
    queue: AgentRuntimeQueue,
    ownership: OwnershipResolver,
    *,
    project_id: str,
    work_item_id: str,
    work_item_revision: int,
    work_item_digest: str,
    task_plan: TaskPlan,
    task_authorization: TaskAuthorization,
    assignments: Mapping[str, DagStepAssignment],
    max_concurrency: int = 2,
) -> GenericDagExecutionPlan:
    """Prepare one exact runtime mutation for a generic TaskPlan DAG."""

    if project_id != queue.project_id:
        raise GenericDagExecutionError(
            "generic DAG project does not match its runtime queue"
        )
    if (
        not isinstance(work_item_id, str)
        or not work_item_id
        or not isinstance(work_item_revision, int)
        or isinstance(work_item_revision, bool)
        or work_item_revision < 1
        or not isinstance(work_item_digest, str)
        or not SHA256.fullmatch(work_item_digest)
        or not IDENTIFIER.fullmatch(work_item_id)
    ):
        raise GenericDagExecutionError("generic DAG work identity is invalid")
    try:
        checked_plan = parse_task_plan(task_plan.as_dict())
    except (AttributeError, ValueError) as exc:
        raise GenericDagExecutionError("generic DAG task plan is invalid") from exc
    _validate_authorization(checked_plan, task_authorization)
    checked_assignments = _validate_assignments(
        project_id,
        checked_plan,
        assignments,
    )
    if (
        not isinstance(max_concurrency, int)
        or isinstance(max_concurrency, bool)
        or not 1 <= max_concurrency <= 32
    ):
        raise GenericDagExecutionError(
            "generic DAG concurrency must be between 1 and 32"
        )
    queue_state = queue.state_digest()
    identity = {
        "project_id": project_id,
        "work_item_id": work_item_id,
        "work_item_revision": work_item_revision,
        "work_item_digest": work_item_digest,
        "task_plan_id": checked_plan.plan_id,
        "authorization_id": task_authorization.authorization_id,
        "assignments": [item.as_dict() for item in checked_assignments],
        "max_concurrency": max_concurrency,
        "queue_state_digest": queue_state,
    }
    target_ref = ".krcn/" + queue.path.relative_to(queue.data_root).as_posix()
    mutation = plan_mutation(
        ownership,
        operation="update" if queue.path.exists() else "create",
        target_ref=target_ref,
        expected_ownership="runtime",
        change_digest=_digest(identity),
        reversible=True,
    )
    execution_plan_id = _digest(
        {"identity": identity, "mutation": mutation.as_dict()}
    )
    return GenericDagExecutionPlan(
        project_id,
        work_item_id,
        work_item_revision,
        work_item_digest,
        checked_plan,
        task_authorization.authorization_id,
        checked_assignments,
        max_concurrency,
        queue_state,
        execution_plan_id,
        mutation,
    )


def _queue_identity(
    plan: GenericDagExecutionPlan,
    step: TaskPlanStep,
    assignment: DagStepAssignment,
) -> dict[str, object]:
    plan_capability = "dag-plan-" + plan.task_plan.plan_id[:16]
    identity: dict[str, object] = {
        "project_id": plan.project_id,
        "work_item_id": plan.work_item_id,
        "work_item_revision": plan.work_item_revision,
        "work_item_digest": plan.work_item_digest,
        "task_id": plan.task_plan.task_id,
        "parent_task_id": plan.task_plan.task_id if step.depends_on else None,
        "plan_id": plan.task_plan.plan_id,
        "step_id": step.step_id,
        "required_role": step.role,
        "required_capabilities": [
            "dag-execution",
            plan_capability,
            "dag-step-" + step.step_id,
        ],
        "side_effects": list(step.side_effects),
        "resource_refs": list(assignment.resource_refs),
    }
    identity["idempotency_key"] = _digest(identity)
    identity["queue_id"] = "queue-" + str(identity["idempotency_key"])[:24]
    return identity


def _validate_adapter_result(
    unit: DagWorkUnit,
    payload: object,
) -> dict[str, object]:
    expected = {
        "schema_ref",
        "schema_version",
        "status",
        "task_id",
        "plan_id",
        "step_id",
        "execution_identity_id",
        "evidence_digest",
        "grants_authority",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise GenericDagExecutionError("generic DAG step result fields are invalid")
    if (
        payload.get("schema_ref")
        != "schemas/generic-dag-execution-result.schema.json#/$defs/adapterResult"
        or payload.get("schema_version") != 1
        or payload.get("status") != "completed"
        or payload.get("task_id") != unit.task_id
        or payload.get("plan_id") != unit.plan_id
        or payload.get("step_id") != unit.step.step_id
        or payload.get("execution_identity_id")
        != unit.assignment.execution_identity.execution_identity_id
        or payload.get("grants_authority") is not False
    ):
        raise GenericDagExecutionError("generic DAG step result binding is invalid")
    evidence = payload.get("evidence_digest")
    if (
        not isinstance(evidence, str)
        or len(evidence) != 64
        or any(character not in "0123456789abcdef" for character in evidence)
    ):
        raise GenericDagExecutionError("generic DAG step evidence is invalid")
    return dict(payload)


def create_generic_dag_step_result(
    unit: DagWorkUnit,
    *,
    evidence_digest: str,
) -> dict[str, object]:
    """Build the only result shape accepted by the generic scheduler."""

    payload = {
        "schema_ref": (
            "schemas/generic-dag-execution-result.schema.json#/$defs/adapterResult"
        ),
        "schema_version": 1,
        "status": "completed",
        "task_id": unit.task_id,
        "plan_id": unit.plan_id,
        "step_id": unit.step.step_id,
        "execution_identity_id": (
            unit.assignment.execution_identity.execution_identity_id
        ),
        "evidence_digest": evidence_digest,
        "grants_authority": False,
    }
    return _validate_adapter_result(unit, payload)


def _resources_overlap(
    left: DagStepAssignment,
    right: DagStepAssignment,
) -> bool:
    return any(
        runtime_resource_refs_conflict(first, second)
        for first in left.resource_refs
        for second in right.resource_refs
    )


def _select_parallel_batch(
    ready: Sequence[str],
    assignments: Mapping[str, DagStepAssignment],
    maximum: int,
) -> tuple[str, ...]:
    selected: list[str] = []
    for step_id in sorted(ready):
        if any(
            _resources_overlap(assignments[step_id], assignments[existing])
            for existing in selected
        ):
            continue
        selected.append(step_id)
        if len(selected) == maximum:
            break
    return tuple(selected)


def dispatch_generic_dag_execution(
    queue: AgentRuntimeQueue,
    plan: GenericDagExecutionPlan,
    authorization: MutationAuthorization,
    *,
    adapters: Mapping[str, DagAdapterSpec],
    owner_tokens: Mapping[str, str],
    expected_plan_id: str,
    cancellation: Callable[[], bool] | None = None,
    heartbeat_wait: Callable[[threading.Event, float], bool] | None = None,
) -> dict[str, object]:
    """Run ready non-conflicting steps concurrently and checkpoint every result."""

    if not hmac.compare_digest(plan.plan_id, expected_plan_id):
        raise GenericDagExecutionError(
            "generic DAG approval does not match the exact execution plan"
        )
    if (
        authorization.plan.plan_id != plan.mutation.plan_id
        or not authorization.dry_run_verified
    ):
        raise GenericDagExecutionError("generic DAG runtime mutation is not authorized")
    if queue.project_id != plan.project_id:
        raise GenericDagExecutionError("generic DAG runtime queue is misbound")
    if queue.state_digest() != plan.queue_state_digest:
        raise GenericDagExecutionError("generic DAG queue changed after planning")
    steps = {step.step_id: step for step in plan.task_plan.steps}
    assignments = {item.step_id: item for item in plan.assignments}
    if set(adapters) != set(steps) or set(owner_tokens) != set(steps):
        raise GenericDagExecutionError(
            "generic DAG adapters and owner tokens must cover every step"
        )
    if (
        any(not isinstance(token, str) or len(token) < 16 for token in owner_tokens.values())
        or len(set(owner_tokens.values())) != len(owner_tokens)
    ):
        raise GenericDagExecutionError(
            "generic DAG owner tokens must be valid and independent"
        )
    owner_digests = {
        step_id: hashlib.sha256(token.encode("utf-8")).hexdigest()
        for step_id, token in owner_tokens.items()
    }
    for step_id, adapter in adapters.items():
        assignment = assignments[step_id]
        identity = assignment.execution_identity
        if (
            adapter.handler_id != assignment.handler_id
            or adapter.actor_digest != identity.actor_digest
            or adapter.runtime_kind != identity.runtime_kind
            or owner_digests[step_id] != identity.session_digest
            or not callable(adapter.callback)
        ):
            raise GenericDagExecutionError(
                "generic DAG adapter does not match its trusted execution identity"
            )
    planned_queue = {
        step_id: _queue_identity(plan, steps[step_id], assignments[step_id])
        for step_id in steps
    }
    queue_control = threading.Lock()

    def queue_apply(action: str, arguments: Mapping[str, object]) -> dict[str, object]:
        with queue_control:
            return queue.apply(action, arguments, queue.state_digest())

    def current_items() -> dict[str, Mapping[str, object]]:
        status = queue.status()
        selected = {
            str(item["queue_id"]): item
            for item in status["items"]
            if str(item["queue_id"])
            in {str(value["queue_id"]) for value in planned_queue.values()}
        }
        for step_id, identity in planned_queue.items():
            item = selected.get(str(identity["queue_id"]))
            if item is None:
                continue
            if (
                item.get("work_item_id") != plan.work_item_id
                or item.get("work_item_revision") != plan.work_item_revision
                or item.get("work_item_digest") != plan.work_item_digest
                or item.get("task_id") != plan.task_plan.task_id
                or item.get("plan_id") != plan.task_plan.plan_id
                or item.get("step_id") != step_id
                or item.get("required_role") != steps[step_id].role
            ):
                raise GenericDagExecutionError(
                    "generic DAG queue checkpoint identity is invalid"
                )
        return selected

    def completed_evidence(item: Mapping[str, object]) -> str:
        evidence = item.get("result_digest")
        if not isinstance(evidence, str) or not SHA256.fullmatch(evidence):
            raise GenericDagExecutionError(
                "generic DAG completed checkpoint evidence is invalid"
            )
        return evidence

    existing_at_start = current_items()
    completed: dict[str, str] = {
        step_id: completed_evidence(
            existing_at_start[str(identity["queue_id"])]
        )
        for step_id, identity in planned_queue.items()
        if existing_at_start.get(str(identity["queue_id"]), {}).get("status")
        == "completed"
    }
    executed: list[str] = []

    def enqueue(step_id: str) -> Mapping[str, object]:
        identity = dict(planned_queue[step_id])
        identity["max_attempts"] = queue.policy.default_max_attempts
        return queue_apply("enqueue", identity)

    def execute(step_id: str, queued: Mapping[str, object]) -> tuple[str, str]:
        if cancellation is not None and cancellation():
            raise GenericDagExecutionError("generic DAG execution was cancelled")
        step = steps[step_id]
        assignment = assignments[step_id]
        capabilities = list(planned_queue[step_id]["required_capabilities"])
        claim = queue_apply(
            "claim",
            {
                "project_id": plan.project_id,
                "owner_digest": owner_digests[step_id],
                "worker_role": step.role,
                "capability_refs": capabilities,
                "lease_seconds": queue.policy.default_lease_seconds,
            },
        )
        if not claim.get("claimed") or claim.get("queue_id") != queued["queue_id"]:
            raise GenericDagExecutionError(
                "generic DAG queue item could not be claimed"
            )
        lease = {
            "project_id": plan.project_id,
            "queue_id": claim["queue_id"],
            "lease_id": claim["lease_id"],
            "owner_digest": owner_digests[step_id],
            "fencing_token": claim["fencing_token"],
        }
        queue_apply(
            "heartbeat",
            {**lease, "lease_seconds": queue.policy.default_lease_seconds},
        )
        stop = threading.Event()
        heartbeat_errors: list[BaseException] = []

        def maintain_lease() -> None:
            wait = heartbeat_wait or (lambda signal, seconds: signal.wait(seconds))
            try:
                while not wait(stop, float(queue.policy.heartbeat_interval_seconds)):
                    queue_apply(
                        "heartbeat",
                        {**lease, "lease_seconds": queue.policy.default_lease_seconds},
                    )
            except BaseException as exc:
                heartbeat_errors.append(exc)
                stop.set()

        heartbeat = threading.Thread(
            target=maintain_lease,
            name=f"krcn-dag-heartbeat-{step_id}",
            daemon=True,
        )
        heartbeat.start()
        unit = DagWorkUnit(
            plan.project_id,
            plan.work_item_id,
            plan.task_plan.task_id,
            plan.task_plan.plan_id,
            step,
            assignment,
            {dependency: completed[dependency] for dependency in step.depends_on},
        )
        try:
            result = _validate_adapter_result(
                unit,
                adapters[step_id].callback(unit),
            )
            if cancellation is not None and cancellation():
                raise GenericDagExecutionError("generic DAG execution was cancelled")
            stop.set()
            heartbeat.join()
            if heartbeat_errors:
                raise GenericDagExecutionError(
                    "generic DAG lease heartbeat failed"
                ) from heartbeat_errors[0]
            evidence = str(result["evidence_digest"])
            queue_apply("complete", {**lease, "evidence_digest": evidence})
            return step_id, evidence
        except Exception as exc:
            stop.set()
            heartbeat.join()
            replay_safe = set(step.side_effects).issubset({"read"})
            try:
                queue_apply(
                    "fail",
                    {
                        **lease,
                        "evidence_digest": _digest(
                            {"step_id": step_id, "error": type(exc).__name__}
                        ),
                        "replay_safe": replay_safe,
                    },
                )
            except Exception as fail_exc:
                raise GenericDagExecutionError(
                    "generic DAG failure could not release its lease"
                ) from fail_exc
            if isinstance(exc, GenericDagExecutionError):
                raise
            raise GenericDagExecutionError("generic DAG adapter failed") from exc

    while len(completed) < len(steps):
        if cancellation is not None and cancellation():
            raise GenericDagExecutionError("generic DAG execution was cancelled")
        by_queue_id = current_items()
        for step_id, identity in planned_queue.items():
            item = by_queue_id.get(str(identity["queue_id"]))
            if item is None:
                continue
            status = item.get("status")
            if status == "completed":
                completed[step_id] = completed_evidence(item)
            elif status in {"leased", "blocked", "recovery-required"}:
                raise GenericDagExecutionError(
                    f"generic DAG step {step_id} requires recovery before dispatch"
                )
        ready = [
            step_id
            for step_id, step in steps.items()
            if step_id not in completed
            and set(step.depends_on).issubset(completed)
            and by_queue_id.get(
                str(planned_queue[step_id]["queue_id"]), {"status": "absent"}
            ).get("status")
            in {"absent", "queued"}
        ]
        batch = _select_parallel_batch(
            ready,
            assignments,
            plan.max_concurrency,
        )
        if not batch:
            raise GenericDagExecutionError(
                "generic DAG has no schedulable ready step"
            )
        queued = {
            step_id: (
                enqueue(step_id)
                if str(planned_queue[step_id]["queue_id"]) not in by_queue_id
                else {
                    "queue_id": str(planned_queue[step_id]["queue_id"]),
                    "status": "queued",
                }
            )
            for step_id in batch
        }
        failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = {
                executor.submit(execute, step_id, queued[step_id]): step_id
                for step_id in batch
            }
            for future in as_completed(futures):
                try:
                    step_id, evidence = future.result()
                    completed[step_id] = evidence
                    executed.append(step_id)
                except Exception as exc:
                    failures.append(exc)
        if failures:
            failure = failures[0]
            if isinstance(failure, GenericDagExecutionError):
                raise failure
            raise GenericDagExecutionError("generic DAG execution failed") from failure
    ordered_results = [
        {
            "step_id": step.step_id,
            "execution_identity_id": (
                assignments[step.step_id].execution_identity.execution_identity_id
            ),
            "evidence_digest": completed[step.step_id],
            "status": "completed",
        }
        for step in plan.task_plan.steps
    ]
    return {
        "schema_ref": "schemas/generic-dag-execution-result.schema.json",
        "schema_version": 1,
        "status": "already-completed" if not executed else "completed",
        "project_id": plan.project_id,
        "work_item_id": plan.work_item_id,
        "task_id": plan.task_plan.task_id,
        "task_plan_id": plan.task_plan.plan_id,
        "execution_plan_id": plan.plan_id,
        "step_results": ordered_results,
        "executed_step_ids": [
            step.step_id for step in plan.task_plan.steps if step.step_id in set(executed)
        ],
        "resumed": bool(existing_at_start),
        "max_concurrency": plan.max_concurrency,
        "queue_control_serial": True,
        "handler_execution_parallel": True,
        "runtime_completion": True,
        "grants_authority": False,
    }
