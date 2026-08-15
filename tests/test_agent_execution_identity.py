from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_execution_identity import (  # noqa: E402
    AgentExecutionIdentityError,
    create_agent_execution_identity,
    parse_agent_execution_identity,
)


class AgentExecutionIdentityTests(unittest.TestCase):
    def identity(self):
        return create_agent_execution_identity(
            task_id="sample-task",
            plan_id="a" * 64,
            step_id="inspect-source",
            role="worker",
            actor_digest="b" * 64,
            session_digest="c" * 64,
            assignment_digest="d" * 64,
            runtime_kind="native-subagent",
        )

    def test_identity_is_digest_bound_schema_valid_and_authority_free(self) -> None:
        identity = self.identity()
        payload = identity.as_dict()
        schema = json.loads(
            (
                REPO_ROOT / "schemas" / "agent-execution-identity.schema.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))
        self.assertFalse(payload["grants_authority"])
        self.assertEqual(
            identity.execution_identity_id,
            parse_agent_execution_identity(payload).execution_identity_id,
        )

    def test_tampered_actor_or_extra_locator_is_rejected(self) -> None:
        payload = self.identity().as_dict()
        payload["actor_digest"] = "e" * 64
        with self.assertRaisesRegex(AgentExecutionIdentityError, "digest"):
            parse_agent_execution_identity(payload)

        payload = self.identity().as_dict()
        payload["working_directory"] = "source-root"
        with self.assertRaisesRegex(AgentExecutionIdentityError, "fields"):
            parse_agent_execution_identity(payload)

    def test_invalid_role_runtime_or_boolean_digest_fails_closed(self) -> None:
        for overrides in (
            {"role": "planner"},
            {"runtime_kind": "unknown"},
            {"actor_digest": True},
        ):
            values = {
                "task_id": "sample-task",
                "plan_id": "a" * 64,
                "step_id": "inspect-source",
                "role": "worker",
                "actor_digest": "b" * 64,
                "session_digest": "c" * 64,
                "assignment_digest": "d" * 64,
                "runtime_kind": "native-subagent",
            }
            values.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises(AgentExecutionIdentityError):
                    create_agent_execution_identity(**values)


if __name__ == "__main__":
    unittest.main()
