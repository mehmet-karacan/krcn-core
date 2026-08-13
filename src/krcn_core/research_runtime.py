"""Research DAG execution over the project-scoped agent runtime queue."""

from __future__ import annotations

import hashlib
import hmac
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Mapping

from .agent_runtime import AgentRuntimeQueue
from .json_documents import canonical_json_bytes
from .mutation_gate import MutationAuthorization, MutationPlan, OwnershipResolver, plan_mutation
from .research_execution import validate_research_execution_result


RESEARCH_DAG = {
    "researcher": (),
    "architecture-reviewer": (),
    "critic": ("researcher", "architecture-reviewer"),
    "synthesizer": ("critic",),
    "citation-verifier": ("synthesizer",),
}
TRUST_ROLES = {
    "researcher": "worker",
    "architecture-reviewer": "worker",
    "critic": "verifier",
    "synthesizer": "worker",
    "citation-verifier": "verifier",
}


class ResearchRuntimeError(ValueError):
    """Raised when native research execution cannot be trusted."""


@dataclass(frozen=True)
class ResearchWorkUnit:
    research_id: str
    role: str
    trust_role: str
    dependencies: tuple[str, ...]
    prompt: str
    dependency_results: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True)
class ResearchRuntimePlan:
    project_id: str
    work_item_id: str
    work_item_revision: int
    work_item_digest: str
    research_id: str
    task_plan_id: str
    prompts: Mapping[str, str]
    prompt_digests: Mapping[str, str]
    execution_assignments_digest: str
    max_concurrency: int
    queue_state_digest: str
    plan_id: str
    mutation: MutationPlan

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/research-runtime-plan.schema.json",
            "schema_version": 1,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "work_item_id": self.work_item_id,
            "research_id": self.research_id,
            "roles": [
                {
                    "role": role,
                    "trust_role": TRUST_ROLES[role],
                    "depends_on": list(RESEARCH_DAG[role]),
                    "prompt_sha256": self.prompt_digests[role],
                }
                for role in RESEARCH_DAG
            ],
            "max_concurrency": self.max_concurrency,
            "execution_assignments_sha256": self.execution_assignments_digest,
            "queue_state_sha256": self.queue_state_digest,
            "native_execution_required": True,
            "operator_mediated_completion_allowed": False,
            "mutation": self.mutation.as_dict(),
        }


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _validate_result(role: str, result: Mapping[str, object]) -> dict[str, object]:
    expected = {
        "execution_mode", "worker_id", "agent_result", "research_result",
        "execution",
    }
    if set(result) != expected or result.get("execution_mode") != "native":
        raise ResearchRuntimeError("manual research result is not native completion")
    worker_id = result.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ResearchRuntimeError("research worker identity is invalid")
    agent_result = result.get("agent_result")
    required_agent = {"status", "summary", "evidence", "changes", "preserved_areas"}
    optional_agent = {"issues"}
    if (
        not isinstance(agent_result, Mapping)
        or not required_agent.issubset(agent_result)
        or set(agent_result) - required_agent - optional_agent
        or agent_result.get("status") != "completed"
        or not isinstance(agent_result.get("summary"), str)
        or not str(agent_result["summary"]).strip()
    ):
        raise ResearchRuntimeError("research agent result did not complete")
    evidence = agent_result.get("evidence")
    if not isinstance(evidence, list) or any(
        not isinstance(item, Mapping)
        or set(item) - {"kind", "reference", "digest"}
        or not isinstance(item.get("kind"), str)
        or not item.get("kind")
        or not isinstance(item.get("reference"), str)
        or not item.get("reference")
        for item in evidence
    ):
        raise ResearchRuntimeError("research agent evidence is invalid")
    for field in ("changes", "preserved_areas", "issues"):
        value = agent_result.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ResearchRuntimeError("research agent result list is invalid")
    research_result = result.get("research_result")
    if not isinstance(research_result, Mapping) or set(research_result) != {"response_markdown", "findings"}:
        raise ResearchRuntimeError("research result contract is invalid")
    response = research_result.get("response_markdown")
    findings = research_result.get("findings")
    if not isinstance(response, str) or not response.strip() or not isinstance(findings, Mapping):
        raise ResearchRuntimeError("research result content is invalid")
    if set(findings) != {"sources", "claims", "conflicts"} or any(
        not isinstance(findings[name], list)
        or any(not isinstance(item, Mapping) for item in findings[name])
        for name in ("sources", "claims", "conflicts")
    ):
        raise ResearchRuntimeError("research findings contract is invalid")
    execution = result.get("execution")
    execution_fields = {
        "schema_ref", "schema_version", "status", "client_id", "provider",
        "provider_request_id", "session_id", "model_ref", "response_markdown",
        "response_sha256", "stderr_sha256", "exit_code", "duration_ms",
        "stdout_truncated", "stderr_truncated", "executable_ref_sha256",
        "cwd_sha256", "output_contract", "provider_authority_granted",
        "physical_paths_included", "credential_values_included",
    }
    if (
        not isinstance(execution, Mapping)
        or set(execution) != execution_fields
        or execution.get("schema_ref") != "schemas/research-execution-result.schema.json"
        or execution.get("schema_version") != 1
        or execution.get("status") != "completed"
        or execution.get("provider_authority_granted") is not False
        or execution.get("physical_paths_included") is not False
        or execution.get("credential_values_included") is not False
    ):
        raise ResearchRuntimeError("research native execution evidence is invalid")
    try:
        validate_research_execution_result(dict(execution))
    except ValueError as exc:
        raise ResearchRuntimeError("research native execution evidence is invalid") from exc
    if execution.get("response_markdown") != response:
        raise ResearchRuntimeError("research execution response does not match research result")
    for field in ("response_sha256", "stderr_sha256", "executable_ref_sha256", "cwd_sha256"):
        digest = execution.get(field)
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ResearchRuntimeError("research execution digest is invalid")
    if hashlib.sha256(response.encode("utf-8")).hexdigest() != execution["response_sha256"]:
        raise ResearchRuntimeError("research execution response digest is invalid")
    normalized = dict(result)
    normalized["role"] = role
    normalized["result_sha256"] = _digest(result)
    return normalized


def _batches() -> tuple[tuple[str, ...], ...]:
    return (
        ("researcher", "architecture-reviewer"),
        ("critic",),
        ("synthesizer",),
        ("citation-verifier",),
    )


def prepare_research_runtime_dispatch(
    queue: AgentRuntimeQueue,
    ownership: OwnershipResolver,
    *,
    project_id: str,
    work_item_id: str,
    work_item_revision: int,
    work_item_digest: str,
    research_id: str,
    task_plan_id: str,
    prompts: Mapping[str, str],
    execution_assignments_digest: str,
    max_concurrency: int = 2,
) -> ResearchRuntimePlan:
    if project_id != queue.project_id:
        raise ResearchRuntimeError("research runtime project does not match its queue")
    identifiers = (project_id, work_item_id, research_id)
    if any(not isinstance(value, str) or not value or not value.replace("-", "a").isalnum() for value in identifiers):
        raise ResearchRuntimeError("research runtime identity is invalid")
    if not isinstance(work_item_revision, int) or isinstance(work_item_revision, bool) or work_item_revision < 1:
        raise ResearchRuntimeError("research work revision is invalid")
    for digest in (work_item_digest, task_plan_id, execution_assignments_digest):
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ResearchRuntimeError("research runtime digest is invalid")
    if set(prompts) != set(RESEARCH_DAG) or any(
        not isinstance(value, str) or not value.strip() for value in prompts.values()
    ):
        raise ResearchRuntimeError("research prompts must cover every runtime role")
    if not 1 <= max_concurrency <= 8:
        raise ResearchRuntimeError("research concurrency must be between 1 and 8")
    prompt_digests = {
        role: hashlib.sha256(prompts[role].encode("utf-8")).hexdigest()
        for role in RESEARCH_DAG
    }
    identity = {
        "project_id": project_id,
        "work_item_id": work_item_id,
        "work_item_revision": work_item_revision,
        "work_item_digest": work_item_digest,
        "research_id": research_id,
        "task_plan_id": task_plan_id,
        "prompt_digests": prompt_digests,
        "execution_assignments_digest": execution_assignments_digest,
        "max_concurrency": max_concurrency,
        "dag": {role: list(dependencies) for role, dependencies in RESEARCH_DAG.items()},
        "trust_roles": TRUST_ROLES,
        "queue_state_digest": queue.state_digest(),
    }
    change_digest = _digest(identity)
    target_ref = ".krcn/" + queue.path.relative_to(queue.data_root).as_posix()
    mutation = plan_mutation(
        ownership,
        operation="update" if queue.path.exists() else "create",
        target_ref=target_ref,
        expected_ownership="runtime",
        change_digest=change_digest,
        reversible=True,
    )
    runtime_plan_id = _digest({"identity": identity, "mutation": mutation.as_dict()})
    return ResearchRuntimePlan(
        project_id, work_item_id, work_item_revision, work_item_digest,
        research_id, task_plan_id, dict(prompts), prompt_digests,
        execution_assignments_digest,
        max_concurrency, str(identity["queue_state_digest"]), runtime_plan_id, mutation,
    )


def dispatch_research_runtime(
    queue: AgentRuntimeQueue,
    plan: ResearchRuntimePlan,
    authorization: MutationAuthorization,
    *,
    adapters: Mapping[str, Callable[[ResearchWorkUnit], Mapping[str, object]]],
    owner_tokens: Mapping[str, str],
    expected_plan_id: str,
    cancellation: Callable[[], bool] | None = None,
    heartbeat_wait: Callable[[threading.Event, float], bool] | None = None,
) -> dict[str, object]:
    """Execute the research DAG using real queue leases and fencing tokens."""

    if not hmac.compare_digest(plan.plan_id, expected_plan_id):
        raise ResearchRuntimeError("research runtime approval does not match the exact plan")
    if authorization.plan.plan_id != plan.mutation.plan_id or not authorization.dry_run_verified:
        raise ResearchRuntimeError("research runtime mutation is not authorized")
    project_id = plan.project_id
    work_item_id = plan.work_item_id
    work_item_revision = plan.work_item_revision
    work_item_digest = plan.work_item_digest
    research_id = plan.research_id
    task_plan_id = plan.task_plan_id
    prompts = plan.prompts
    max_concurrency = plan.max_concurrency
    planned_queue_ids = {
        role: "queue-" + _digest({
            "project_id": project_id,
            "work_item_id": work_item_id,
            "work_item_revision": work_item_revision,
            "work_item_digest": work_item_digest,
            "task_id": research_id,
            "parent_task_id": research_id if RESEARCH_DAG[role] else None,
            "plan_id": task_plan_id,
            "step_id": role,
            "required_role": TRUST_ROLES[role],
            "required_capabilities": ["research-execution", f"research-role-{role}"],
            "side_effects": ["read"],
            "resource_refs": [f"task:{project_id}:research-{role}"],
        })[:24]
        for role in RESEARCH_DAG
    }
    current_status = queue.status()
    current_by_id = {str(item["queue_id"]): item for item in current_status["items"]}
    if all(current_by_id.get(queue_id, {}).get("status") == "completed" for queue_id in planned_queue_ids.values()):
        return {
            "schema_ref": "schemas/research-runtime-result.schema.json",
            "schema_version": 1,
            "status": "already-completed",
            "research_id": research_id,
            "queue_ids": planned_queue_ids,
            "roles": list(RESEARCH_DAG),
            "results": {},
            "native_completion": True,
            "max_concurrency": max_concurrency,
        }
    existing = [current_by_id[queue_id] for queue_id in planned_queue_ids.values() if queue_id in current_by_id]
    if existing:
        raise ResearchRuntimeError(
            "an incomplete research id cannot be resumed; use a new research id"
        )
    if queue.state_digest() != plan.queue_state_digest:
        raise ResearchRuntimeError("research runtime queue changed after planning")
    if set(adapters) != set(RESEARCH_DAG) or set(owner_tokens) != set(RESEARCH_DAG):
        raise ResearchRuntimeError("research execution binding must cover every role")
    if any(not isinstance(value, str) or len(value) < 16 for value in owner_tokens.values()):
        raise ResearchRuntimeError("research owner token is invalid")
    if len(set(owner_tokens.values())) != len(owner_tokens):
        raise ResearchRuntimeError("research verifier and worker owners must be independent")
    completed: dict[str, Mapping[str, object]] = {}
    queue_ids: dict[str, str] = {}
    owner_digests = {
        role: hashlib.sha256(token.encode("utf-8")).hexdigest()
        for role, token in owner_tokens.items()
    }
    queue_control = threading.Lock()

    def queue_apply(action: str, arguments: Mapping[str, object]) -> dict[str, object]:
        with queue_control:
            return queue.apply(action, arguments, queue.state_digest())

    def enqueue(role: str) -> dict[str, object]:
        dependencies = RESEARCH_DAG[role]
        identity: dict[str, object] = {
            "project_id": project_id,
            "work_item_id": work_item_id,
            "work_item_revision": work_item_revision,
            "work_item_digest": work_item_digest,
            "task_id": research_id,
            "parent_task_id": research_id if dependencies else None,
            "plan_id": task_plan_id,
            "step_id": role,
            "required_role": TRUST_ROLES[role],
            "required_capabilities": ["research-execution", f"research-role-{role}"],
            "side_effects": ["read"],
            "resource_refs": [f"task:{project_id}:research-{role}"],
        }
        identity["idempotency_key"] = _digest(identity)
        identity["queue_id"] = "queue-" + identity["idempotency_key"][:24]
        identity["max_attempts"] = queue.policy.default_max_attempts
        enqueued = queue_apply("enqueue", identity)
        queue_ids[role] = str(enqueued["queue_id"])
        return enqueued

    def execute(role: str, enqueued: Mapping[str, object]) -> tuple[str, dict[str, object]]:
        if cancellation is not None and cancellation():
            raise ResearchRuntimeError("research execution was cancelled")
        claim = queue_apply(
            "claim",
            {
                "project_id": project_id,
                "owner_digest": owner_digests[role],
                "worker_role": TRUST_ROLES[role],
                "capability_refs": ["research-execution", f"research-role-{role}"],
                "lease_seconds": queue.policy.default_lease_seconds,
            },
        )
        if not claim.get("claimed") or claim.get("queue_id") != enqueued["queue_id"]:
            raise ResearchRuntimeError("research queue item could not be claimed")
        lease = {
            "project_id": project_id,
            "queue_id": claim["queue_id"],
            "lease_id": claim["lease_id"],
            "owner_digest": owner_digests[role],
            "fencing_token": claim["fencing_token"],
        }
        queue_apply(
            "heartbeat",
            {**lease, "lease_seconds": queue.policy.default_lease_seconds},
        )
        unit = ResearchWorkUnit(
            research_id, role, TRUST_ROLES[role], RESEARCH_DAG[role], prompts[role],
            {dependency: completed[dependency] for dependency in RESEARCH_DAG[role]},
        )
        heartbeat_stop = threading.Event()
        heartbeat_errors: list[BaseException] = []

        def maintain_lease() -> None:
            wait = heartbeat_wait or (lambda signal, seconds: signal.wait(seconds))
            try:
                while not wait(
                    heartbeat_stop,
                    float(queue.policy.heartbeat_interval_seconds),
                ):
                    queue_apply(
                        "heartbeat",
                        {**lease, "lease_seconds": queue.policy.default_lease_seconds},
                    )
            except BaseException as exc:
                heartbeat_errors.append(exc)
                heartbeat_stop.set()

        heartbeat_thread = threading.Thread(
            target=maintain_lease,
            name=f"krcn-research-heartbeat-{role}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = _validate_result(role, dict(adapters[role](unit)))
            if role in {"critic", "citation-verifier"}:
                dependency_workers = {
                    str(completed[dependency]["worker_id"])
                    for dependency in RESEARCH_DAG[role]
                }
                if str(result["worker_id"]) in dependency_workers:
                    raise ResearchRuntimeError("research verifier may not verify its own work")
            if cancellation is not None and cancellation():
                raise ResearchRuntimeError("research execution was cancelled")
            heartbeat_stop.set()
            heartbeat_thread.join()
            if heartbeat_errors:
                raise ResearchRuntimeError("research execution lease heartbeat failed") from heartbeat_errors[0]
            evidence = str(result["result_sha256"])
            queue_apply("complete", {**lease, "evidence_digest": evidence})
            return role, result
        except Exception as exc:
            heartbeat_stop.set()
            heartbeat_thread.join()
            try:
                queue_apply(
                    "fail",
                    {**lease, "evidence_digest": _digest({"role": role, "error": type(exc).__name__}), "replay_safe": False},
                )
            except Exception as fail_exc:
                raise ResearchRuntimeError(
                    "research execution failed and lease recovery could not be recorded"
                ) from fail_exc
            if isinstance(exc, ResearchRuntimeError):
                raise
            raise ResearchRuntimeError("research execution adapter failed") from exc
    for batch in _batches():
        if cancellation is not None and cancellation():
            raise ResearchRuntimeError("research execution was cancelled")
        if any(not set(RESEARCH_DAG[role]).issubset(completed) for role in batch):
            raise ResearchRuntimeError("research dependency is not completed")
        enqueued = {role: enqueue(role) for role in batch}
        failures: list[Exception] = []
        with ThreadPoolExecutor(max_workers=min(max_concurrency, len(batch))) as executor:
            futures = {executor.submit(execute, role, enqueued[role]): role for role in batch}
            for future in as_completed(futures):
                try:
                    role, result = future.result()
                    completed[role] = result
                except Exception as exc:
                    failures.append(exc)
        if failures:
            failure = failures[0]
            if isinstance(failure, ResearchRuntimeError):
                raise failure
            raise ResearchRuntimeError("research execution failed") from failure
    return {
        "schema_ref": "schemas/research-runtime-result.schema.json",
        "schema_version": 1,
        "status": "completed",
        "research_id": research_id,
        "queue_ids": queue_ids,
        "roles": list(completed),
        "results": completed,
        "native_completion": True,
        "max_concurrency": max_concurrency,
    }


def get_research_runtime_status(queue: AgentRuntimeQueue, research_id: str) -> dict[str, object]:
    status = queue.status()
    items = [item for item in status["items"] if item.get("task_id") == research_id]
    role_set = {str(item.get("step_id")) for item in items}
    canonical_roles = role_set == set(RESEARCH_DAG) and len(items) == len(RESEARCH_DAG)
    return {
        "research_id": research_id,
        "items": items,
        "counts": {state: sum(item["status"] == state for item in items) for state in sorted({item["status"] for item in items})},
        "active_lease_count": status["active_lease_count"],
        "native_completion": canonical_roles and all(item["status"] == "completed" for item in items),
    }
