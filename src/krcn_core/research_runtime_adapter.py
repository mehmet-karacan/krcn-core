"""Bind approved CLI execution plans to strict research runtime work units."""

from __future__ import annotations

import json
import shutil
from typing import Callable, Mapping

from .provider_gate import ProviderAuthorization
from .research_execution import (
    CancellationSignal,
    ExecutableResolver,
    ProcessRunner,
    ResearchExecutionPlan,
    execute_research_execution,
    validate_research_agent_output,
    validate_research_execution_result,
)
from .research_runtime import ResearchRuntimeError, ResearchWorkUnit


def bind_research_runtime_adapter(
    adapter: Callable[[ResearchWorkUnit], Mapping[str, object]],
    plan: ResearchExecutionPlan,
    *,
    worker_id: str,
) -> Callable[[ResearchWorkUnit], Mapping[str, object]]:
    """Bind any host override to the same exact execution assignment."""

    def execute(unit: ResearchWorkUnit) -> Mapping[str, object]:
        result = dict(adapter(unit))
        execution = result.get("execution")
        if (
            result.get("worker_id") != worker_id
            or not isinstance(execution, Mapping)
            or execution.get("client_id") != plan.client_id
            or execution.get("provider") != plan.provider
            or execution.get("provider_request_id") != plan.provider_request_id
            or execution.get("session_id") != plan.session_id
            or execution.get("model_ref") != plan.model_ref
            or execution.get("output_contract") != plan.output_contract
        ):
            raise ResearchRuntimeError(
                "research adapter result does not match its exact execution assignment"
            )
        validate_research_agent_output(
            {
                "schema_ref": "schemas/research-agent-output.schema.json",
                "schema_version": 1,
                "agent_result": result.get("agent_result"),
                "research_result": result.get("research_result"),
            }
        )
        validate_research_execution_result(dict(execution))
        return result

    return execute


def _dependency_projection(unit: ResearchWorkUnit) -> list[dict[str, object]]:
    projection = []
    for role in unit.dependencies:
        source = unit.dependency_results.get(role)
        if not isinstance(source, Mapping):
            raise ResearchRuntimeError("research dependency result is unavailable")
        agent = source.get("agent_result")
        research = source.get("research_result")
        result_digest = source.get("result_sha256")
        if not isinstance(agent, Mapping) or not isinstance(research, Mapping):
            raise ResearchRuntimeError("research dependency result is invalid")
        if not isinstance(result_digest, str) or len(result_digest) != 64:
            raise ResearchRuntimeError("research dependency digest is invalid")
        projection.append(
            {
                "role": role,
                "agent_summary": agent.get("summary"),
                "agent_evidence": agent.get("evidence"),
                "research_response_markdown": research.get("response_markdown"),
                "research_findings": research.get("findings"),
                "result_sha256": result_digest,
            }
        )
    return projection


def _structured_prompt(unit: ResearchWorkUnit, *, maximum_bytes: int) -> str:
    dependencies = ", ".join(unit.dependencies) or "none"
    contract = {
        "schema_ref": "schemas/research-agent-output.schema.json",
        "schema_version": 1,
        "agent_result": {
            "status": "completed",
            "summary": "non-empty summary",
            "evidence": [{"kind": "source", "reference": "portable reference"}],
            "changes": [],
            "preserved_areas": ["project-source"],
        },
        "research_result": {
            "response_markdown": "non-empty Markdown",
            "findings": {"sources": [], "claims": [], "conflicts": []},
        },
    }
    dependency_context = _dependency_projection(unit)
    prompt = (
        unit.prompt.rstrip()
        + "\n\n## Native execution contract\n\n"
        + f"Runtime role: `{unit.role}`. Trust role: `{unit.trust_role}`. "
        + f"Completed dependencies: `{dependencies}`.\n\n"
        + "## Verified dependency context\n\n"
        + json.dumps(dependency_context, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n\n"
        + "Return exactly one JSON object. Do not use Markdown fences or add prose outside JSON. "
        + "A free-text answer is rejected and cannot complete this work unit. Use this exact shape:\n\n"
        + json.dumps(contract, ensure_ascii=False, indent=2)
        + "\n"
    )
    if len(prompt.encode("utf-8")) > maximum_bytes:
        raise ResearchRuntimeError(
            "research dependency context exceeds the explicit prompt budget"
        )
    return prompt


def create_research_runtime_adapter(
    plan: ResearchExecutionPlan,
    provider_authorization: ProviderAuthorization,
    *,
    worker_id: str,
    runner: ProcessRunner | None = None,
    cancellation: CancellationSignal | None = None,
    executable_resolver: ExecutableResolver = shutil.which,
) -> Callable[[ResearchWorkUnit], Mapping[str, object]]:
    """Create one explicit role adapter without discovering a host or provider."""

    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ResearchRuntimeError("research runtime worker identity is invalid")

    def execute(unit: ResearchWorkUnit) -> Mapping[str, object]:
        result = execute_research_execution(
            plan,
            _structured_prompt(unit, maximum_bytes=plan.max_prompt_bytes),
            provider_authorization=provider_authorization,
            runner=runner,
            cancellation=cancellation,
            executable_resolver=executable_resolver,
        )
        if result.status != "completed" or result.structured_output is None:
            raise ResearchRuntimeError(
                f"research CLI execution did not complete with structured output: {result.status}"
            )
        structured = dict(result.structured_output)
        agent_result = structured.get("agent_result")
        research_result = structured.get("research_result")
        if not isinstance(agent_result, Mapping) or not isinstance(research_result, Mapping):
            raise ResearchRuntimeError("research CLI structured output is incomplete")
        return {
            "execution_mode": "native",
            "worker_id": worker_id,
            "agent_result": dict(agent_result),
            "research_result": dict(research_result),
            "execution": result.as_dict(),
        }

    return bind_research_runtime_adapter(execute, plan, worker_id=worker_id)
