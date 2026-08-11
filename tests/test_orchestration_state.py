from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.orchestration_state import (  # noqa: E402
    OrchestrationStateError,
    OrchestrationStateStore,
    transition_state,
)
from krcn_core.orchestration_verifier import VerifierHandlerResult  # noqa: E402
import test_orchestration_authorization as authorization_fixtures  # noqa: E402
import test_orchestration_verifier as verifier_fixtures  # noqa: E402


class OrchestrationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        local = LocalWorkspaceStore(
            Path(self.temporary.name),
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.local = local
        self.store = OrchestrationStateStore(local)
        fixture = verifier_fixtures.OrchestrationVerifierTests(
            methodName="test_all_constraints_criteria_and_requirements_need_passing_evidence"
        )
        fixture.setUp()
        self.fixture = fixture
        self.intent = fixture.intent
        self.plan = fixture.plan
        self.authorization = fixture.authorization
        self.execution = fixture.execution

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def passing_verification(self):
        return self.fixture.verify(self.fixture.evidence_for_all)

    def test_state_events_checkpoint_handoff_and_resume_complete_flow(self) -> None:
        state = self.store.initialize(
            self.plan,
            "synthetic-session",
            self.authorization,
        )
        self.assertEqual("authorized", state.status)
        state = self.store.transition(
            state,
            self.plan,
            to_status="running",
            event_type="worker-started",
            subject_digest=self.execution.checkpoint.idempotency_key,
            current_step_id="inspect-policy",
        )
        self.store.save_execution(self.execution)
        state = self.store.transition(
            state,
            self.plan,
            to_status="verifying",
            event_type="workers-completed",
            subject_digest=self.execution.checkpoint.checkpoint_id,
            completed_step_ids=("inspect-policy",),
        )
        verification = self.passing_verification()
        state = self.store.transition(
            state,
            self.plan,
            to_status="completed",
            event_type="task-verified",
            subject_digest=verification.verification_id,
            verification=verification,
            completed_step_ids=("inspect-policy",),
        )
        handoff = self.store.save_handoff(
            state,
            self.plan,
            verification=verification,
        )
        resumed = self.store.resume(
            self.plan.task_id,
            self.plan,
            self.authorization,
        )
        self.assertEqual("completed", resumed.state.status)
        self.assertEqual(4, resumed.event_count)
        self.assertEqual((), resumed.next_step_ids)
        self.assertEqual(handoff.resume_token, resumed.handoff.resume_token)
        self.assertEqual(1, len(resumed.executions))

    def test_interrupted_task_resumes_without_chat_history(self) -> None:
        state = self.store.initialize(
            self.plan,
            "synthetic-session",
            self.authorization,
        )
        state = self.store.transition(
            state,
            self.plan,
            to_status="running",
            event_type="worker-started",
            subject_digest=self.authorization.authorization_id,
            current_step_id="inspect-policy",
        )
        state = self.store.transition(
            state,
            self.plan,
            to_status="interrupted",
            event_type="execution-interrupted",
            subject_digest="a" * 64,
            current_step_id="inspect-policy",
        )
        handoff = self.store.save_handoff(state, self.plan)
        serialized = json.dumps(handoff.as_dict(), ensure_ascii=False)
        self.assertNotIn("chat", serialized.casefold())
        self.assertNotIn(self.intent.goal.value, serialized)
        resumed = self.store.resume(
            self.plan.task_id,
            self.plan,
            self.authorization,
        )
        self.assertEqual(("inspect-policy",), resumed.next_step_ids)
        self.assertEqual(3, resumed.event_count)

    def test_completion_requires_passing_verification(self) -> None:
        state = self.store.initialize(
            self.plan,
            "synthetic-session",
            self.authorization,
        )
        state = self.store.transition(
            state,
            self.plan,
            to_status="running",
            event_type="worker-started",
            subject_digest=self.authorization.authorization_id,
        )
        state = self.store.transition(
            state,
            self.plan,
            to_status="verifying",
            event_type="workers-completed",
            subject_digest=self.execution.checkpoint.checkpoint_id,
            completed_step_ids=("inspect-policy",),
        )
        failed = self.fixture.verify(lambda context: VerifierHandlerResult(()))
        with self.assertRaisesRegex(OrchestrationStateError, "passing"):
            self.store.transition(
                state,
                self.plan,
                to_status="completed",
                event_type="task-verified",
                subject_digest=failed.verification_id,
                verification=failed,
                completed_step_ids=("inspect-policy",),
            )

    def test_approval_waiting_state_preserves_exact_plan_triggers(self) -> None:
        fixture = authorization_fixtures.OrchestrationAuthorizationTests(
            methodName="test_write_requires_exact_task_and_mutation_approval"
        )
        fixture.setUp()
        plan, _, _ = fixture.write_fixture()
        state = self.store.initialize(plan, "synthetic-session")
        self.assertEqual("awaiting-approval", state.status)
        handoff = self.store.save_handoff(state, plan)
        self.assertEqual(plan.approval_triggers, handoff.approval_triggers)
        resumed = self.store.resume(plan.task_id, plan)
        self.assertEqual(plan.approval_triggers, resumed.approval_triggers)

    def test_runtime_ownership_and_event_tampering_are_enforced(self) -> None:
        state = self.store.initialize(
            self.plan,
            "synthetic-session",
            self.authorization,
        )
        next_state, _ = transition_state(
            state,
            self.plan,
            to_status="running",
            event_type="worker-started",
            subject_digest=self.authorization.authorization_id,
        )
        write = self.local.prepare_put(
            "orchestration-states",
            state.state_id,
            next_state.as_dict(),
            expected_revision=1,
        )
        self.assertEqual("runtime", write.mutation.ownership)
        self.assertFalse(write.mutation.approval_required)

        event_record = self.local.list_records("orchestration-events")[0]
        event_path = (
            Path(self.temporary.name)
            / "events"
            / "orchestration"
            / f"{event_record.record_id}.json"
        )
        envelope = json.loads(event_path.read_text(encoding="utf-8"))
        envelope["payload"]["subject_digest"] = "f" * 64
        event_path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.resume(
                self.plan.task_id,
                self.plan,
                self.authorization,
            )

    def test_orchestration_schemas_are_versioned(self) -> None:
        expected = {
            "orchestration-state.schema.json": "urn:krcn:schemas:orchestration-state:1",
            "orchestration-event.schema.json": "urn:krcn:schemas:orchestration-event:1",
            "orchestration-checkpoint.schema.json": "urn:krcn:schemas:orchestration-checkpoint:1",
            "orchestration-handoff.schema.json": "urn:krcn:schemas:orchestration-handoff:1",
        }
        for name, schema_id in expected.items():
            with self.subTest(name=name):
                payload = json.loads(
                    (REPO_ROOT / "schemas" / name).read_text(encoding="utf-8")
                )
                self.assertEqual(schema_id, payload["$id"])


if __name__ == "__main__":
    unittest.main()
