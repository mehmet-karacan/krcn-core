"""Digest-bound worker and verifier execution identities."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .information_records import canonical_json


IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ROLES = {"worker", "verifier"}
RUNTIME_KINDS = {
    "client-cli",
    "isolated-role",
    "local-handler",
    "native-subagent",
}


class AgentExecutionIdentityError(ValueError):
    """Raised when an execution identity is incomplete or tampered."""


@dataclass(frozen=True)
class AgentExecutionIdentity:
    execution_identity_id: str
    task_id: str
    plan_id: str
    step_id: str
    role: str
    actor_digest: str
    session_digest: str
    assignment_digest: str
    runtime_kind: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_ref": "schemas/agent-execution-identity.schema.json",
            "schema_version": 1,
            "execution_identity_id": self.execution_identity_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "role": self.role,
            "actor_digest": self.actor_digest,
            "session_digest": self.session_digest,
            "assignment_digest": self.assignment_digest,
            "runtime_kind": self.runtime_kind,
            "grants_authority": False,
        }


def _identity_body(
    *,
    task_id: str,
    plan_id: str,
    step_id: str,
    role: str,
    actor_digest: str,
    session_digest: str,
    assignment_digest: str,
    runtime_kind: str,
) -> dict[str, object]:
    if (
        not IDENTIFIER.fullmatch(task_id)
        or not IDENTIFIER.fullmatch(step_id)
        or role not in ROLES
        or runtime_kind not in RUNTIME_KINDS
        or any(
            not isinstance(value, str) or not SHA256.fullmatch(value)
            for value in (
                plan_id,
                actor_digest,
                session_digest,
                assignment_digest,
            )
        )
    ):
        raise AgentExecutionIdentityError("agent execution identity values are invalid")
    return {
        "task_id": task_id,
        "plan_id": plan_id,
        "step_id": step_id,
        "role": role,
        "actor_digest": actor_digest,
        "session_digest": session_digest,
        "assignment_digest": assignment_digest,
        "runtime_kind": runtime_kind,
    }


def create_agent_execution_identity(
    *,
    task_id: str,
    plan_id: str,
    step_id: str,
    role: str,
    actor_digest: str,
    session_digest: str,
    assignment_digest: str,
    runtime_kind: str,
) -> AgentExecutionIdentity:
    body = _identity_body(
        task_id=task_id,
        plan_id=plan_id,
        step_id=step_id,
        role=role,
        actor_digest=actor_digest,
        session_digest=session_digest,
        assignment_digest=assignment_digest,
        runtime_kind=runtime_kind,
    )
    return AgentExecutionIdentity(
        hashlib.sha256(canonical_json(body)).hexdigest(),
        task_id,
        plan_id,
        step_id,
        role,
        actor_digest,
        session_digest,
        assignment_digest,
        runtime_kind,
    )


def parse_agent_execution_identity(payload: object) -> AgentExecutionIdentity:
    expected = {
        "schema_ref",
        "schema_version",
        "execution_identity_id",
        "task_id",
        "plan_id",
        "step_id",
        "role",
        "actor_digest",
        "session_digest",
        "assignment_digest",
        "runtime_kind",
        "grants_authority",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise AgentExecutionIdentityError("agent execution identity fields are invalid")
    if (
        payload.get("schema_ref") != "schemas/agent-execution-identity.schema.json"
        or payload.get("schema_version") != 1
        or payload.get("grants_authority") is not False
    ):
        raise AgentExecutionIdentityError("agent execution identity contract is invalid")
    body = _identity_body(
        task_id=str(payload.get("task_id", "")),
        plan_id=str(payload.get("plan_id", "")),
        step_id=str(payload.get("step_id", "")),
        role=str(payload.get("role", "")),
        actor_digest=str(payload.get("actor_digest", "")),
        session_digest=str(payload.get("session_digest", "")),
        assignment_digest=str(payload.get("assignment_digest", "")),
        runtime_kind=str(payload.get("runtime_kind", "")),
    )
    expected_id = hashlib.sha256(canonical_json(body)).hexdigest()
    if payload.get("execution_identity_id") != expected_id:
        raise AgentExecutionIdentityError("agent execution identity digest is invalid")
    return AgentExecutionIdentity(
        expected_id,
        str(body["task_id"]),
        str(body["plan_id"]),
        str(body["step_id"]),
        str(body["role"]),
        str(body["actor_digest"]),
        str(body["session_digest"]),
        str(body["assignment_digest"]),
        str(body["runtime_kind"]),
    )
