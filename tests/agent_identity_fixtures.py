from __future__ import annotations

import hashlib

from krcn_core.agent_execution_identity import create_agent_execution_identity


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def execution_identity(
    plan,
    step_id: str,
    role: str,
    *,
    actor: str | None = None,
    assignment: str | None = None,
    session: str = "synthetic-session",
):
    return create_agent_execution_identity(
        task_id=plan.task_id,
        plan_id=plan.plan_id,
        step_id=step_id,
        role=role,
        actor_digest=digest(actor or f"{role}-{step_id}-actor"),
        session_digest=digest(session),
        assignment_digest=digest(assignment or f"{role}-{step_id}-assignment"),
        runtime_kind="local-handler",
    )
