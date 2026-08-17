from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_runtime import (  # noqa: E402
    AgentRuntimeError,
    apply_runtime_queue_action,
    prepare_runtime_queue_action,
)
from krcn_core.agent_execution_identity import create_agent_execution_identity  # noqa: E402
from krcn_core.effect_ledger import build_effect_claim, build_effect_receipt  # noqa: E402
from krcn_core.effect_ledger_store import EffectLedgerStore, effect_ledger_path  # noqa: E402
from krcn_core.validation_gate import build_validation_gate, parse_validation_gate  # noqa: E402
from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.work_graph import apply_work_item, prepare_work_item  # noqa: E402


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def authorization(plan):
    return authorize_mutation(
        plan,
        dry_run=DryRunEvidence(plan.plan_id, verified=True),
        approval=(
            ApprovalEvidence(plan.plan_id, "test-approval", approved=True)
            if plan.approval_required
            else None
        ),
    )


def runtime_gate(work_id: str, effect_type: str):
    verifier = create_agent_execution_identity(
        task_id=f"run-{work_id}", plan_id="a" * 64, step_id="verify-effect",
        role="verifier", actor_digest="8" * 64, session_digest="9" * 64,
        assignment_digest="7" * 64, runtime_kind="isolated-role",
    )
    return build_validation_gate(
        project_id="sample", work_item_id=work_id, task_id=f"run-{work_id}",
        task_plan_id="a" * 64, worker_step_id="implement", effect_id=f"{effect_type}-change",
        effect_type=effect_type, effect_digest="b" * 64, effect_authorization_id="c" * 64,
        worker_execution_identity_id="d" * 64, worker_actor_digest="e" * 64,
        verifier_execution_identity=verifier,
        subjects=[{"subject_kind": "acceptance-criterion", "subject_digest": "1" * 64}],
        checks=[{"check_id": "state-check", "actor_kind": "verifier", "method": "state-check",
                 "expected_result": "passed", "evidence_required": ["state-observation"],
                 "subject_digests": ["1" * 64]}],
        policy_revision="f" * 64, source_revision_digest="0" * 64,
        created_at="2026-08-17T15:00:00.000Z",
        mutation_plan_id="3" * 64 if effect_type == "write" else None,
        provider_request_id="4" * 64 if effect_type == "network" else None,
    )


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        project = {
            "schema_version": 1,
            "project_id": "sample",
            "name": "Sample",
            "description": "Agent runtime test",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        project_plan = self.store.prepare_put(
            "projects", "sample", project,
            expected_revision=0, project_id="sample",
        )
        self.store.apply_put(project_plan, authorization(project_plan.mutation))
        self.clock = FakeClock()
        self.add_work("task-one")
        self.add_work("task-two")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def add_work(self, work_id: str) -> None:
        arguments = {
            "work_item_id": work_id,
            "project_id": "sample",
            "work_type": "task",
            "title": work_id,
            "description": "Runtime work",
            "status": "active",
            "acceptance_criteria": ["Runtime completes"],
            "relations": [],
            "evidence": [],
            "provenance": {"source_kind": "user", "source_ref": "test"},
        }
        plan = prepare_work_item(self.store, self.ownership, arguments)
        apply_work_item(
            self.store,
            plan,
            {effect.plan_id: authorization(effect) for effect in plan.effect_plans},
        )

    def complete_work(self, work_id: str) -> None:
        arguments = {
            "work_item_id": work_id,
            "project_id": "sample",
            "work_type": "task",
            "title": work_id,
            "description": "Runtime work",
            "status": "completed",
            "acceptance_criteria": ["Runtime completes"],
            "relations": [],
            "evidence": [{
                "evidence_type": "test",
                "reference": f"runtime:{work_id}",
                "digest": "e" * 64,
                "label": "Verified runtime completion",
            }],
            "provenance": {"source_kind": "orchestrator", "source_ref": "runtime-test"},
        }
        plan = prepare_work_item(self.store, self.ownership, arguments)
        apply_work_item(
            self.store,
            plan,
            {effect.plan_id: authorization(effect) for effect in plan.effect_plans},
        )

    def prepare(self, action: str, arguments: dict[str, object]):
        return prepare_runtime_queue_action(
            REPO_ROOT,
            self.store,
            self.ownership,
            action,
            arguments,
            clock=self.clock,
        )

    def apply(self, action: str, arguments: dict[str, object]):
        queue, plan = self.prepare(action, arguments)
        result = apply_runtime_queue_action(queue, plan, authorization(plan.mutation))
        return queue, plan, result

    @staticmethod
    def enqueue_args(work_id: str, *, effects=None, resources=None, role="worker") -> dict[str, object]:
        selected_effects = effects or ["read"]
        result = {
            "project_id": "sample",
            "work_item_id": work_id,
            "task_id": f"run-{work_id}",
            "plan_id": "a" * 64,
            "step_id": "implement",
            "required_role": role,
            "required_capabilities": ["project-read"],
            "side_effects": selected_effects,
            "resource_refs": resources or [f"task:sample:{work_id}"],
        }
        non_read = next((item for item in selected_effects if item != "read"), None)
        if non_read is not None:
            result["validation_gate"] = runtime_gate(work_id, non_read).as_dict()
        return result

    @staticmethod
    def claim_args(owner: str = "owner-token-0000001") -> dict[str, object]:
        return {
            "project_id": "sample",
            "owner_token": owner,
            "worker_role": "worker",
            "capability_refs": ["project-read"],
            "lease_seconds": 60,
        }

    def test_enqueue_is_idempotent_and_only_one_worker_claims(self) -> None:
        _, _, first = self.apply("enqueue", self.enqueue_args("task-one"))
        _, _, second = self.apply("enqueue", self.enqueue_args("task-one"))
        self.assertEqual(first["queue_id"], second["queue_id"])
        self.assertTrue(second["idempotent_reuse"])
        queue, _, claim = self.apply("claim", self.claim_args())
        self.assertTrue(claim["claimed"])
        _, _, other = self.apply("claim", self.claim_args("owner-token-0000002"))
        self.assertFalse(other["claimed"])
        self.assertEqual(1, queue.status()["active_lease_count"])

    def test_heartbeat_and_completion_reject_stale_fencing(self) -> None:
        self.apply("enqueue", self.enqueue_args("task-one"))
        _, _, claim = self.apply("claim", self.claim_args())
        lease = {
            "project_id": "sample",
            "queue_id": claim["queue_id"],
            "lease_id": claim["lease_id"],
            "owner_token": "owner-token-0000001",
            "fencing_token": claim["fencing_token"],
        }
        _, _, heartbeat = self.apply("heartbeat", {**lease, "lease_seconds": 60})
        self.assertGreater(heartbeat["expires_at"], self.clock())
        with self.assertRaises(AgentRuntimeError):
            self.apply("complete", {
                **lease,
                "fencing_token": claim["fencing_token"] + 1,
                "evidence_digest": "b" * 64,
            })
        queue, _, completed = self.apply("complete", {**lease, "evidence_digest": "b" * 64})
        self.assertEqual("completed", completed["status"])
        self.assertTrue(completed["projection_job_created"])
        self.assertEqual(1, queue.status()["pending_projection_count"])
        _, _, blocked = self.apply("reconcile", {"project_id": "sample"})
        self.assertEqual(1, blocked["blocked_count"])
        self.complete_work("task-one")
        queue, _, reconciled = self.apply("reconcile", {"project_id": "sample"})
        self.assertEqual(1, reconciled["completed_count"])
        self.assertEqual(0, queue.status()["pending_projection_count"])
        self.assertEqual(1, queue.status()["completed_projection_count"])

    def test_expired_read_is_requeued_with_new_fence_and_old_worker_is_rejected(self) -> None:
        self.apply("enqueue", self.enqueue_args("task-one"))
        _, _, first = self.apply("claim", self.claim_args())
        old_lease = {
            "project_id": "sample",
            "queue_id": first["queue_id"],
            "lease_id": first["lease_id"],
            "owner_token": "owner-token-0000001",
            "fencing_token": first["fencing_token"],
        }
        self.clock.advance(61)
        _, _, recovered = self.apply("recover", {"project_id": "sample"})
        self.assertEqual("queued", recovered["items"][0]["status"])
        _, _, second = self.apply("claim", self.claim_args("owner-token-0000002"))
        self.assertGreater(second["fencing_token"], first["fencing_token"])
        with self.assertRaises(AgentRuntimeError):
            self.apply("complete", {**old_lease, "evidence_digest": "c" * 64})

    def test_expired_write_requires_recovery_and_releases_resource_lock(self) -> None:
        resource = "path:sample:src/service.py"
        self.apply("enqueue", self.enqueue_args("task-one", effects=["write"], resources=[resource]))
        self.apply("enqueue", self.enqueue_args("task-two", effects=["write"], resources=["path:sample:src"]))
        _, _, first = self.apply("claim", self.claim_args())
        self.assertTrue(first["claimed"])
        _, _, blocked = self.apply("claim", self.claim_args("owner-token-0000002"))
        self.assertFalse(blocked["claimed"])
        self.clock.advance(61)
        _, _, recovered = self.apply("recover", {"project_id": "sample"})
        self.assertEqual("recovery-required", recovered["items"][0]["status"])
        _, _, second = self.apply("claim", self.claim_args("owner-token-0000002"))
        self.assertTrue(second["claimed"])

    def test_failed_read_replays_but_verifier_write_is_rejected(self) -> None:
        self.apply("enqueue", self.enqueue_args("task-one"))
        _, _, claim = self.apply("claim", self.claim_args())
        _, _, failed = self.apply("fail", {
            "project_id": "sample",
            "queue_id": claim["queue_id"],
            "lease_id": claim["lease_id"],
            "owner_token": "owner-token-0000001",
            "fencing_token": claim["fencing_token"],
            "evidence_digest": "d" * 64,
            "replay_safe": True,
        })
        self.assertEqual("queued", failed["status"])
        with self.assertRaises(AgentRuntimeError):
            self.prepare(
                "enqueue",
                self.enqueue_args("task-two", effects=["write"], role="verifier"),
            )
        _, execute_plan = self.prepare(
            "enqueue",
            self.enqueue_args("task-two", effects=["execute"], role="verifier"),
        )
        self.assertEqual("enqueue", execute_plan.action)

    def test_v2_effect_binding_is_additive_and_blocks_early_completion(self) -> None:
        missing_gate = self.enqueue_args("task-one", effects=["write"])
        missing_gate.pop("validation_gate")
        with self.assertRaisesRegex(AgentRuntimeError, "pre-execution validation gate"):
            self.prepare("enqueue", missing_gate)
        arguments = self.enqueue_args("task-one", effects=["write"])
        validation_gate = parse_validation_gate(arguments["validation_gate"])
        self.apply("enqueue", arguments)
        queue, _, claim = self.apply("claim", self.claim_args())
        self.assertTrue(claim["ledger_required"])
        self.assertFalse(claim["handler_execution_allowed"])
        self.assertEqual(validation_gate.validation_gate_id, claim["validation_gate_id"])
        lease = {
            "project_id": "sample", "queue_id": claim["queue_id"],
            "lease_id": claim["lease_id"], "owner_token": "owner-token-0000001",
            "fencing_token": claim["fencing_token"],
        }
        with self.assertRaisesRegex(AgentRuntimeError, "receipt is required"):
            self.apply("complete", {**lease, "evidence_digest": "2" * 64})
        effect_claim = build_effect_claim(
            project_id="sample", work_item_id="task-one", task_id="run-task-one",
            task_plan_id="a" * 64, step_id="implement", queue_id=claim["queue_id"],
            attempt_id=claim["attempt_id"], attempt_number=1,
            execution_identity_id="d" * 64, lease_id=claim["lease_id"],
            fencing_token=claim["fencing_token"], effect_id="write-change",
            effect_type="write", effect_digest="b" * 64, idempotency_key="5" * 64,
            effect_authorization_id="c" * 64, validation_gate=validation_gate,
            host_digest="6" * 64, claimed_at="2026-08-17T15:01:00.000Z",
            mutation_plan_id="3" * 64,
        )
        ledger = EffectLedgerStore(effect_ledger_path(self.store.data_root, "sample"))
        ledger.record_claim(effect_claim, validation_gate=validation_gate)
        _, _, bound_claim = self.apply(
            "bind_effect_claim", {**lease, "effect_claim": effect_claim.as_dict()}
        )
        self.assertTrue(bound_claim["handler_execution_allowed"])
        effect_receipt = build_effect_receipt(
            claim=effect_claim, outcome="completed", retry_safety="non-replayable",
            result_digest="4" * 64, finished_at="2026-08-17T15:02:00.000Z",
            observed_fencing_token=claim["fencing_token"],
        )
        ledger.record_receipt(effect_receipt)
        self.apply("bind_effect_receipt", {**lease, "effect_receipt": effect_receipt.as_dict()})
        queue, _, completed = self.apply(
            "complete", {**lease, "evidence_digest": "5" * 64}
        )
        self.assertEqual("completed", completed["status"])
        item = queue.status()["items"][0]
        self.assertEqual(effect_claim.claim_id, item["effect_claim_id"])
        self.assertEqual(effect_receipt.receipt_id, item["effect_receipt_id"])
        self.assertEqual(0, queue.status()["effect_ledger"]["unattended_recovery_count"])

    def test_v1_queue_metadata_is_migrated_additively(self) -> None:
        queue, _, _ = self.apply("enqueue", self.enqueue_args("task-one"))
        import sqlite3

        connection = sqlite3.connect(queue.path)
        try:
            connection.execute("UPDATE metadata SET value='1' WHERE key='schema_version'")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(AgentRuntimeError, "explicit additive migration"):
            self.apply("claim", self.claim_args())
        reopened, _, migrated = self.apply("migrate_v2", {"project_id": "sample"})
        self.assertTrue(migrated["migrated"])
        self.assertTrue(migrated["migration_id"].startswith("queue-v1-to-v2-"))
        connection = reopened._connect(create=False)
        self.assertIsNotNone(connection)
        try:
            self.assertEqual("2", connection.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0])
            columns = {row[1] for row in connection.execute("PRAGMA table_info(queue_items)")}
            self.assertTrue({"validation_gate_id", "effect_claim_id", "effect_receipt_id"}.issubset(columns))
            journal = connection.execute(
                "SELECT from_version,to_version,status FROM queue_schema_migrations"
            ).fetchone()
            self.assertEqual((1, 2, "completed"), tuple(journal))
        finally:
            connection.close()

    def test_nonportable_resource_refs_and_owner_tokens_are_rejected(self) -> None:
        with self.assertRaises(AgentRuntimeError):
            self.prepare(
                "enqueue",
                self.enqueue_args("task-one", resources=["path:sample:../secret"]),
            )
        self.apply("enqueue", self.enqueue_args("task-one"))
        with self.assertRaises(AgentRuntimeError):
            self.prepare("claim", self.claim_args("short"))

    def test_shared_application_service_preserves_exact_plan(self) -> None:
        service = create_application_service(REPO_ROOT, self.home)
        arguments = self.enqueue_args("task-one")
        planned = service.execute(ServiceRequest(
            client_kind="test-client",
            operation="runtime.queue.enqueue",
            arguments=arguments,
        ))
        self.assertEqual("planned", planned.status)
        applied = service.execute(ServiceRequest(
            client_kind="test-client",
            operation="runtime.queue.enqueue",
            arguments=arguments,
            apply=True,
            expected_plan_id=planned.data["plan"]["plan_id"],
        ))
        self.assertEqual("applied", applied.status)
        status = service.execute(ServiceRequest(
            client_kind="test-client",
            operation="runtime.queue.status",
            arguments={"project_id": "sample"},
        ))
        self.assertEqual(1, status.data["result"]["counts"]["queued"])
        resume = service.execute(ServiceRequest(
            client_kind="test-client",
            operation="project.resume",
            arguments={
                "working_directory": str(self.home),
                "project_ref": "sample",
            },
        ))
        self.assertEqual(
            1,
            resume.data["resume"]["work"]["runtime_queue"]["counts"]["queued"],
        )
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT, self.home)}
        self.assertTrue(checks["runtime-home"].passed)


if __name__ == "__main__":
    unittest.main()
