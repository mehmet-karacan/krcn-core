"""Transport-neutral orchestration facade used by every client adapter."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Sequence

from .agent_execution_identity import parse_agent_execution_identity
from .capability_registry import load_capability_registry, select_capability_records
from .local_store import LocalWorkspaceStore
from .mutation_gate import DryRunEvidence, MutationPlan, OwnershipResolver, plan_mutation
from .orchestration_authorization import (
    TaskApproval,
    TaskMutationRequest,
    TaskProviderRequest,
    authorize_task_plan,
    create_operation_request,
)
from .orchestration_intent import create_task_intent, parse_task_intent
from .orchestration_plan import create_task_plan
from .orchestration_state import OrchestrationStateStore
from .orchestration_verifier import (
    VerifierHandlerRegistry,
    VerifierRequest,
    verify_task,
)
from .orchestration_worker import (
    WorkerHandlerRegistry,
    create_work_request,
    execute_worker_step,
)
from .policies import load_user_policies
from .provider_gate import create_provider_request
from .work_completion import (
    WorkCompletionError,
    apply_verified_work_completion,
    build_work_completion_attestation,
    persist_work_completion_attestation,
    parse_work_completion_attestation,
    prepare_verified_work_completion,
    reconcile_applied_work_completion,
)


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ORCHESTRATION_OPERATIONS = {
    "orchestrator.intent",
    "orchestrator.plan",
    "orchestrator.authorize",
    "orchestrator.start",
    "orchestrator.execute",
    "orchestrator.verify",
    "orchestrator.status",
    "orchestrator.timeline",
    "orchestrator.resume",
}


class OrchestrationServiceError(ValueError):
    """Raised when a shared orchestration service request is invalid."""


def _fields(
    payload: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    allowed = required | (optional or set())
    if set(payload) != allowed and (
        required - set(payload) or set(payload) - allowed
    ):
        raise OrchestrationServiceError(f"{label} fields are invalid")


def _object(payload: Mapping[str, object], name: str) -> dict[str, object]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise OrchestrationServiceError(f"{name} must be an object")
    return dict(value)


def _list(payload: Mapping[str, object], name: str) -> list[object]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise OrchestrationServiceError(f"{name} must be a list")
    return value


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise OrchestrationServiceError(f"{name} must be a non-empty string")
    return value


class OrchestrationApplicationService:
    """Keep orchestration policy in one service shared by all transports."""

    def __init__(
        self,
        repo_root: Path,
        store: LocalWorkspaceStore,
        *,
        worker_handlers: WorkerHandlerRegistry | None = None,
        verifier_handlers: VerifierHandlerRegistry | None = None,
    ) -> None:
        self._repo_root = repo_root.resolve()
        self._store = store
        self._ownership = OwnershipResolver.from_repository(self._repo_root)
        self._states = OrchestrationStateStore(store)
        self._worker_handlers = worker_handlers or WorkerHandlerRegistry()
        self._verifier_handlers = verifier_handlers or VerifierHandlerRegistry()

    def _planning_context(self, payload: Mapping[str, object]):
        _fields(
            payload,
            required={
                "intent",
                "capability_record_refs",
                "required_capabilities",
                "steps",
            },
            label="orchestration planning context",
        )
        intent = parse_task_intent(_object(payload, "intent"))
        refs = _list(payload, "capability_record_refs")
        capabilities = _list(payload, "required_capabilities")
        if any(not isinstance(item, str) for item in (*refs, *capabilities)):
            raise OrchestrationServiceError("capability selections must be strings")
        selection = select_capability_records(
            load_capability_registry(self._repo_root),
            refs,
            capabilities,
        )
        raw_steps = _list(payload, "steps")
        if any(not isinstance(item, dict) for item in raw_steps):
            raise OrchestrationServiceError("task steps must be objects")
        plan = create_task_plan(intent, selection, raw_steps)
        return intent, selection, plan

    def _mutation_requests(self, payloads: Sequence[object]):
        bindings = []
        for item in payloads:
            if not isinstance(item, dict):
                raise OrchestrationServiceError("mutation binding must be an object")
            _fields(
                item,
                required={"step_id", "mutation", "dry_run_verified"},
                label="mutation binding",
            )
            mutation_payload = _object(item, "mutation")
            expected = {
                "schema_version", "plan_id", "operation", "target_ref", "ownership",
                "change_digest", "dry_run_required", "approval_required", "reversible",
            }
            if set(mutation_payload) != expected:
                raise OrchestrationServiceError("mutation plan fields are invalid")
            rebuilt = plan_mutation(
                self._ownership,
                operation=mutation_payload["operation"],
                target_ref=mutation_payload["target_ref"],
                expected_ownership=mutation_payload["ownership"],
                change_digest=mutation_payload["change_digest"],
                reversible=mutation_payload["reversible"],
            )
            if rebuilt.as_dict() != mutation_payload:
                raise OrchestrationServiceError("mutation plan does not match repository ownership")
            if item.get("dry_run_verified") is not True:
                raise OrchestrationServiceError("verified mutation dry-run is required")
            bindings.append(
                TaskMutationRequest(
                    _string(item, "step_id"),
                    rebuilt,
                    DryRunEvidence(rebuilt.plan_id, True),
                )
            )
        return tuple(bindings)

    @staticmethod
    def _provider_requests(payloads: Sequence[object]):
        bindings = []
        for item in payloads:
            if not isinstance(item, dict):
                raise OrchestrationServiceError("provider binding must be an object")
            _fields(
                item,
                required={
                    "step_id", "provider", "endpoint", "data_categories",
                    "operation_scope", "retention_assumptions", "session_id", "remote",
                },
                label="provider binding",
            )
            categories = _list(item, "data_categories")
            if any(not isinstance(value, str) for value in categories) or not isinstance(item.get("remote"), bool):
                raise OrchestrationServiceError("provider disclosure fields are invalid")
            request = create_provider_request(
                provider=_string(item, "provider"),
                endpoint=_string(item, "endpoint"),
                data_categories=tuple(categories),
                operation_scope=_string(item, "operation_scope"),
                retention_assumptions=_string(item, "retention_assumptions"),
                session_id=_string(item, "session_id"),
                remote=bool(item["remote"]),
            )
            bindings.append(TaskProviderRequest(_string(item, "step_id"), request))
        return tuple(bindings)

    @staticmethod
    def _task_approval(payload: object) -> TaskApproval | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise OrchestrationServiceError("task approval must be an object")
        expected = {
            "plan_id", "task_id", "session_id", "approval_id", "approved",
            "approved_triggers", "mutation_plan_ids", "provider_request_ids",
        }
        if set(payload) != expected:
            raise OrchestrationServiceError("task approval fields are invalid")
        arrays = []
        for name in ("approved_triggers", "mutation_plan_ids", "provider_request_ids"):
            value = payload.get(name)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise OrchestrationServiceError("task approval scope is invalid")
            arrays.append(tuple(value))
        if not isinstance(payload.get("approved"), bool):
            raise OrchestrationServiceError("task approval decision is invalid")
        return TaskApproval(
            _string(payload, "plan_id"),
            _string(payload, "task_id"),
            _string(payload, "session_id"),
            _string(payload, "approval_id"),
            bool(payload["approved"]),
            arrays[0],
            arrays[1],
            arrays[2],
        )

    def _authorization_context(self, payload: Mapping[str, object]):
        _fields(
            payload,
            required={
                "planning", "session_id", "operations", "mutations", "providers",
                "approval",
            },
            label="orchestration authorization context",
        )
        intent, selection, plan = self._planning_context(_object(payload, "planning"))
        operations = []
        for item in _list(payload, "operations"):
            if not isinstance(item, dict):
                raise OrchestrationServiceError("operation binding must be an object")
            _fields(
                item,
                required={
                    "step_id", "resource_type", "operation", "scope_refs",
                    "require_policy_match", "approval_trigger",
                },
                label="operation binding",
            )
            scope_refs = _object(item, "scope_refs")
            approval_trigger = item.get("approval_trigger")
            if approval_trigger is not None and not isinstance(approval_trigger, str):
                raise OrchestrationServiceError("operation approval trigger is invalid")
            operations.append(
                create_operation_request(
                    step_id=_string(item, "step_id"),
                    resource_type=_string(item, "resource_type"),
                    operation=_string(item, "operation"),
                    scope_refs=scope_refs,
                    require_policy_match=item.get("require_policy_match"),
                    approval_trigger=approval_trigger,
                )
            )
        session_id = _string(payload, "session_id")
        authorization = authorize_task_plan(
            self._repo_root,
            intent=intent,
            selection=selection,
            plan=plan,
            session_id=session_id,
            policies=load_user_policies(self._store.data_root / "policies"),
            operations=operations,
            mutations=self._mutation_requests(_list(payload, "mutations")),
            providers=self._provider_requests(_list(payload, "providers")),
            approval=self._task_approval(payload.get("approval")),
        )
        return intent, selection, plan, authorization

    @staticmethod
    def _require_apply_plan(apply: bool, expected_plan_id: str | None, plan_id: str) -> None:
        if not apply:
            raise OrchestrationServiceError("orchestration state change requires apply")
        if expected_plan_id != plan_id:
            raise OrchestrationServiceError("apply requires the exact task plan id")

    def execute(
        self,
        operation: str,
        arguments: Mapping[str, object],
        *,
        apply: bool,
        expected_plan_id: str | None,
    ) -> tuple[str, Mapping[str, object]]:
        if operation == "orchestrator.intent":
            _fields(arguments, required={"request", "extraction"}, label="intent request")
            if apply:
                raise OrchestrationServiceError("intent normalization cannot be applied")
            intent = create_task_intent(
                _string(arguments, "request"),
                _object(arguments, "extraction"),
            )
            return "ok", {"intent": intent.as_dict()}
        if operation == "orchestrator.plan":
            if apply:
                raise OrchestrationServiceError("task planning cannot be applied")
            intent, selection, plan = self._planning_context(arguments)
            return "planned", {
                "intent": intent.as_dict(),
                "selection": selection.as_dict(),
                "plan": plan.as_dict(),
            }

        operation_required = {"context"}
        optional = {
            "step_id", "handler_id", "input", "verifier_requests",
            "execution_identity", "project_id", "work_item_id",
        }
        _fields(arguments, required=operation_required, optional=optional, label="orchestration request")
        context = _object(arguments, "context")
        intent, _, plan, authorization = self._authorization_context(context)
        project_id = arguments.get("project_id")
        work_item_id = arguments.get("work_item_id")
        if project_id is not None:
            if not isinstance(project_id, str) or not IDENTIFIER.fullmatch(project_id):
                raise OrchestrationServiceError("orchestration project id is invalid")
            if self._store.read("projects", project_id) is None:
                raise OrchestrationServiceError("orchestration project is not registered")
        if work_item_id is not None:
            if project_id is None or not isinstance(work_item_id, str) or not IDENTIFIER.fullmatch(work_item_id):
                raise OrchestrationServiceError("orchestration work item id is invalid")
            work = self._store.read("work-items", work_item_id)
            if work is None or work.payload.get("project_id") != project_id:
                raise OrchestrationServiceError("orchestration work item is not in the project")
        if self._store.layout_version >= 2 and operation not in {
            "orchestrator.authorize",
        } and (project_id is None or work_item_id is None):
            raise OrchestrationServiceError(
                "layout v2 orchestration requires project_id and work_item_id"
            )
        if operation == "orchestrator.authorize":
            if apply:
                raise OrchestrationServiceError("authorization validation cannot be applied")
            return "ok", {"authorization": authorization.as_dict()}
        if operation == "orchestrator.start":
            self._require_apply_plan(apply, expected_plan_id, plan.plan_id)
            state = self._states.initialize(
                plan,
                authorization.session_id,
                authorization,
                project_id,
                work_item_id,
            )
            handoff = self._states.save_handoff(
                state, plan, project_id=project_id, work_item_id=work_item_id
            )
            return "applied", {"state": state.as_dict(), "handoff": handoff.as_dict()}
        if operation in {
            "orchestrator.status",
            "orchestrator.timeline",
            "orchestrator.resume",
        }:
            if apply:
                raise OrchestrationServiceError(
                    "resume, status, and timeline are read operations"
                )
            if operation == "orchestrator.timeline":
                return "ok", {"timeline": self._states.timeline(plan.task_id)}
            resumed = self._states.resume(plan.task_id, plan, authorization)
            data = {"resume": resumed.public_summary()}
            if operation == "orchestrator.status":
                data["timeline"] = self._states.timeline(plan.task_id)
            return "ok", data
        if operation == "orchestrator.execute":
            self._require_apply_plan(apply, expected_plan_id, plan.plan_id)
            step_id = _string(arguments, "step_id")
            handler_id = _string(arguments, "handler_id")
            input_payload = _object(arguments, "input")
            try:
                execution_identity = parse_agent_execution_identity(
                    _object(arguments, "execution_identity")
                )
            except ValueError as exc:
                raise OrchestrationServiceError(
                    "worker execution identity is invalid"
                ) from exc
            resumed = self._states.resume(plan.task_id, plan, authorization)
            state = resumed.state
            if state.status in {"authorized", "failed", "interrupted"}:
                state = self._states.transition(
                    state,
                    plan,
                    to_status="running",
                    event_type="worker-started",
                    subject_digest=authorization.authorization_id,
                    current_step_id=step_id,
                    project_id=project_id,
                )
            elif state.status != "running":
                raise OrchestrationServiceError("orchestration state is not worker-executable")
            request = create_work_request(
                plan,
                authorization,
                step_id=step_id,
                handler_id=handler_id,
                input_payload=input_payload,
                execution_identity=execution_identity,
            )
            execution = execute_worker_step(
                plan,
                authorization,
                request,
                self._worker_handlers,
                history=resumed.executions,
            )
            self._states.save_execution(execution, project_id)
            all_executions = (*resumed.executions, execution)
            completed = {
                item.checkpoint.step_id
                for item in all_executions
                if item.checkpoint.status == "completed"
            }
            failed = {
                item.checkpoint.step_id
                for item in all_executions
                if item.checkpoint.status == "failed" and item.checkpoint.step_id not in completed
            }
            worker_ids = {item.step_id for item in plan.steps if item.role == "worker"}
            target_status = "failed" if execution.checkpoint.status == "failed" else (
                "verifying" if completed == worker_ids else "running"
            )
            state = self._states.transition(
                state,
                plan,
                to_status=target_status,
                event_type="worker-failed" if target_status == "failed" else "worker-completed",
                subject_digest=execution.checkpoint.checkpoint_id,
                completed_step_ids=completed,
                failed_step_ids=failed,
                current_step_id=None if target_status == "verifying" else step_id,
                project_id=project_id,
            )
            handoff = self._states.save_handoff(
                state, plan, project_id=project_id, work_item_id=work_item_id
            )
            return "applied", {
                "execution": execution.as_dict(),
                "state": state.as_dict(),
                "handoff": handoff.as_dict(),
            }
        if operation == "orchestrator.verify":
            requests_payload = _list(arguments, "verifier_requests")
            requests = []
            for item in requests_payload:
                if not isinstance(item, dict) or set(item) != {
                    "step_id",
                    "handler_id",
                    "execution_identity",
                }:
                    raise OrchestrationServiceError("verifier request fields are invalid")
                try:
                    execution_identity = parse_agent_execution_identity(
                        _object(item, "execution_identity")
                    )
                except ValueError as exc:
                    raise OrchestrationServiceError(
                        "verifier execution identity is invalid"
                    ) from exc
                requests.append(
                    VerifierRequest(
                        _string(item, "step_id"),
                        _string(item, "handler_id"),
                        execution_identity,
                    )
                )
            resumed = self._states.resume(plan.task_id, plan, authorization)
            if resumed.state.status == "completed":
                if not isinstance(project_id, str) or not isinstance(work_item_id, str):
                    raise OrchestrationServiceError(
                        "completed orchestration has no Work Graph binding"
                    )
                stored_attestation = self._store.read(
                    "work-completion-attestations",
                    f"{plan.task_id}-work-completion",
                )
                stored_work = self._store.read("work-items", work_item_id)
                if stored_attestation is None or stored_work is None:
                    raise OrchestrationServiceError(
                        "completed orchestration lacks completion attestation"
                    )
                try:
                    attestation = parse_work_completion_attestation(
                        stored_attestation.payload
                    )
                except ValueError as exc:
                    raise OrchestrationServiceError(
                        "stored completion attestation is invalid"
                    ) from exc
                if (
                    attestation.project_id != project_id
                    or attestation.work_item_id != work_item_id
                    or attestation.task_plan_id != plan.plan_id
                    or attestation.authorization_id != authorization.authorization_id
                    or attestation.verification_id != resumed.state.verification_id
                    or stored_work.payload.get("status") != "completed"
                ):
                    raise OrchestrationServiceError(
                        "completed orchestration binding changed"
                    )
                if apply:
                    self._require_apply_plan(apply, expected_plan_id, plan.plan_id)
                return "ok", {
                    "verification": {
                        "verification_id": attestation.verification_id,
                        "status": "verified",
                        "completion_allowed": True,
                        "persisted_attestation": True,
                    },
                    "state": resumed.state.as_dict(),
                    "handoff": (
                        resumed.handoff.as_dict() if resumed.handoff else None
                    ),
                    "work_completion": {
                        "status": "completed",
                        "completed": True,
                        "work_item_id": work_item_id,
                        "attestation_id": attestation.attestation_id,
                        "second_approval_required": False,
                        "reopen_supported": True,
                    },
                    "no_op": True,
                }
            if resumed.state.status != "verifying":
                raise OrchestrationServiceError("orchestration state is not ready for verification")
            verification = verify_task(
                intent,
                plan,
                authorization,
                resumed.executions,
                requests,
                self._verifier_handlers,
            )
            if not apply:
                return "ok", {"verification": verification.as_dict()}
            self._require_apply_plan(apply, expected_plan_id, plan.plan_id)
            target_status = "completed" if verification.completion_allowed else "failed"
            work_completion: dict[str, object] = {
                "status": "not-requested",
                "completed": False,
                "second_approval_required": False,
            }
            if (
                target_status == "completed"
                and isinstance(project_id, str)
                and isinstance(work_item_id, str)
            ):
                try:
                    attestation_record = self._store.read(
                        "work-completion-attestations",
                        f"{plan.task_id}-work-completion",
                    )
                    if attestation_record is None:
                        attestation = build_work_completion_attestation(
                            self._store,
                            project_id=project_id,
                            work_item_id=work_item_id,
                            plan=plan,
                            verification=verification,
                        )
                        # Preparing before any write makes proof and concurrency
                        # failures leave the orchestration in verifying state.
                        completion_plan = prepare_verified_work_completion(
                            self._repo_root,
                            self._store,
                            attestation,
                        )
                        persist_work_completion_attestation(self._store, attestation)
                        completion_result = apply_verified_work_completion(
                            self._store,
                            self._ownership,
                            completion_plan,
                        )
                    else:
                        attestation = parse_work_completion_attestation(
                            attestation_record.payload
                        )
                        if (
                            attestation.project_id != project_id
                            or attestation.work_item_id != work_item_id
                            or attestation.task_id != plan.task_id
                            or attestation.task_plan_id != plan.plan_id
                            or attestation.authorization_id
                            != authorization.authorization_id
                            or attestation.verification_id
                            != verification.verification_id
                        ):
                            raise WorkCompletionError(
                                "stored completion attestation binding changed"
                            )
                        stored_target = self._store.read("work-items", work_item_id)
                        if (
                            stored_target is not None
                            and stored_target.payload.get("status") == "completed"
                        ):
                            completion_result = reconcile_applied_work_completion(
                                self._repo_root,
                                self._store,
                                self._ownership,
                                attestation,
                            )
                        else:
                            completion_plan = prepare_verified_work_completion(
                                self._repo_root,
                                self._store,
                                attestation,
                            )
                            completion_result = apply_verified_work_completion(
                                self._store,
                                self._ownership,
                                completion_plan,
                            )
                    work_completion = {
                        "status": "completed",
                        "completed": True,
                        **completion_result,
                    }
                except WorkCompletionError as exc:
                    raise OrchestrationServiceError(
                        f"verified Work Graph completion failed: {exc}"
                    ) from exc
            state = self._states.transition(
                resumed.state,
                plan,
                to_status=target_status,
                event_type="task-verified" if target_status == "completed" else "verification-failed",
                subject_digest=verification.verification_id,
                verification=verification if target_status == "completed" else None,
                completed_step_ids=resumed.state.completed_step_ids,
                project_id=project_id,
            )
            handoff = self._states.save_handoff(
                state,
                plan,
                verification=verification,
                project_id=project_id,
                work_item_id=work_item_id,
            )
            return "applied", {
                "verification": verification.as_dict(),
                "state": state.as_dict(),
                "handoff": handoff.as_dict(),
                "work_completion": work_completion,
            }
        raise OrchestrationServiceError("orchestration operation is invalid")
