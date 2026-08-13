from __future__ import annotations

import sys
import tempfile
import threading
import hashlib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_runtime import (  # noqa: E402
    AgentRuntimeError,
    AgentRuntimeQueue,
    SchedulerPolicy,
    load_scheduler_policy,
)
from krcn_core.research_runtime import (  # noqa: E402
    RESEARCH_DAG,
    ResearchRuntimeError,
    dispatch_research_runtime,
    get_research_runtime_status,
    prepare_research_runtime_dispatch,
)
from krcn_core.mutation_gate import DryRunEvidence, OwnershipResolver, authorize_mutation  # noqa: E402


class ResearchRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name)
        self.queue = AgentRuntimeQueue(
            self.data_root,
            "sample",
            load_scheduler_policy(REPO_ROOT),
        )
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.prompts = {role: f"Prompt for {role}" for role in RESEARCH_DAG}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def adapter(unit):
        response = f"# {unit.role}\n"
        return {
            "execution_mode": "native",
            "worker_id": f"worker-{unit.role}",
            "agent_result": {
                "status": "completed",
                "summary": f"Completed {unit.role}",
                "evidence": [{"kind": "test", "reference": unit.role}],
                "changes": [],
                "preserved_areas": ["project-source"],
            },
            "research_result": {
                "response_markdown": response,
                "findings": {"sources": [], "claims": [], "conflicts": []},
            },
            "execution": {
                "schema_ref": "schemas/research-execution-result.schema.json",
                "schema_version": 1,
                "status": "completed",
                "client_id": "codex-cli",
                "provider": "local-test",
                "provider_request_id": "9" * 64,
                "session_id": "test-session",
                "model_ref": "test-model",
                "response_markdown": response,
                "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                "stderr_sha256": "0" * 64,
                "exit_code": 0,
                "duration_ms": 1,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "executable_ref_sha256": "1" * 64,
                "cwd_sha256": "2" * 64,
                "output_contract": "research-agent-result-v1",
                "provider_authority_granted": False,
                "physical_paths_included": False,
                "credential_values_included": False,
            },
        }

    def dispatch(self, adapter=None):
        plan = prepare_research_runtime_dispatch(
            self.queue,
            self.ownership,
            project_id="sample",
            work_item_id="research-task",
            work_item_revision=1,
            work_item_digest="a" * 64,
            research_id="runtime-pilot",
            task_plan_id="b" * 64,
            prompts=self.prompts,
            execution_assignments_digest="f" * 64,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        return dispatch_research_runtime(
            self.queue,
            plan,
            authorization,
            adapters={role: adapter or self.adapter for role in RESEARCH_DAG},
            owner_tokens={
                role: f"owner-token-{index:08d}"
                for index, role in enumerate(RESEARCH_DAG, start=1)
            },
            expected_plan_id=plan.plan_id,
        )

    def test_dispatch_uses_queue_and_completes_the_dependency_order(self) -> None:
        observed = []
        initial_barrier = threading.Barrier(2, timeout=2)

        def adapter(unit):
            observed.append((unit.role, unit.dependencies, unit.trust_role))
            if not unit.dependencies:
                initial_barrier.wait()
            return self.adapter(unit)

        result = self.dispatch(adapter)
        self.assertEqual("completed", result["status"])
        observed_by_role = {item[0]: item for item in observed}
        self.assertEqual(set(RESEARCH_DAG), set(observed_by_role))
        self.assertEqual("verifier", observed_by_role["critic"][2])
        self.assertEqual("verifier", observed_by_role["citation-verifier"][2])
        status = get_research_runtime_status(self.queue, "runtime-pilot")
        self.assertTrue(status["native_completion"])
        self.assertEqual({"completed": 5}, status["counts"])
        self.assertFalse(any("prompt" in key or "token" in key or "path" in key for key in status))

    def test_duplicate_dispatch_is_idempotent(self) -> None:
        first = self.dispatch()
        self.assertEqual("completed", first["status"])
        plan = prepare_research_runtime_dispatch(
            self.queue,
            self.ownership,
            project_id="sample",
            work_item_id="research-task",
            work_item_revision=1,
            work_item_digest="a" * 64,
            research_id="runtime-pilot",
            task_plan_id="b" * 64,
            prompts=self.prompts,
            execution_assignments_digest="f" * 64,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        repeated = dispatch_research_runtime(
            self.queue,
            plan,
            authorization,
            adapters={role: self.adapter for role in RESEARCH_DAG},
            owner_tokens={role: f"second-owner-token-{index:08d}" for index, role in enumerate(RESEARCH_DAG)},
            expected_plan_id=plan.plan_id,
        )
        self.assertEqual("already-completed", repeated["status"])
        self.assertEqual(5, len(self.queue.status()["items"]))

    def test_stale_queue_state_is_rejected(self) -> None:
        plan = prepare_research_runtime_dispatch(
            self.queue,
            self.ownership,
            project_id="sample",
            work_item_id="research-task",
            work_item_revision=1,
            work_item_digest="a" * 64,
            research_id="runtime-pilot",
            task_plan_id="b" * 64,
            prompts=self.prompts,
            execution_assignments_digest="f" * 64,
        )
        self.queue.apply(
            "enqueue",
            {
                "project_id": "sample", "work_item_id": "other-task", "work_item_revision": 1,
                "work_item_digest": "c" * 64, "task_id": "other-run", "parent_task_id": None,
                "plan_id": "d" * 64, "step_id": "other", "required_role": "worker",
                "required_capabilities": ["research-execution"], "side_effects": ["read"],
                "resource_refs": ["task:sample:other-task"], "idempotency_key": "e" * 64,
                "queue_id": "queue-" + "e" * 24, "max_attempts": 3,
            },
            self.queue.state_digest(),
        )
        authorization = authorize_mutation(plan.mutation, dry_run=DryRunEvidence(plan.mutation.plan_id, True))
        with self.assertRaisesRegex(ResearchRuntimeError, "changed after planning"):
            dispatch_research_runtime(
                self.queue, plan, authorization,
                adapters={role: self.adapter for role in RESEARCH_DAG},
                owner_tokens={role: f"stale-owner-token-{index:08d}" for index, role in enumerate(RESEARCH_DAG)},
                expected_plan_id=plan.plan_id,
            )

    def test_cancellation_is_fail_closed(self) -> None:
        called = 0

        def cancelled():
            nonlocal called
            called += 1
            return called > 3

        plan = prepare_research_runtime_dispatch(
            self.queue, self.ownership, project_id="sample", work_item_id="research-task",
            work_item_revision=1, work_item_digest="a" * 64, research_id="runtime-pilot",
            task_plan_id="b" * 64, prompts=self.prompts,
            execution_assignments_digest="f" * 64,
        )
        authorization = authorize_mutation(plan.mutation, dry_run=DryRunEvidence(plan.mutation.plan_id, True))
        with self.assertRaisesRegex(ResearchRuntimeError, "cancelled"):
            dispatch_research_runtime(
                self.queue, plan, authorization,
                adapters={role: self.adapter for role in RESEARCH_DAG},
                owner_tokens={role: f"cancel-owner-token-{index:08d}" for index, role in enumerate(RESEARCH_DAG)},
                expected_plan_id=plan.plan_id, cancellation=cancelled,
            )
        self.assertFalse(get_research_runtime_status(self.queue, "runtime-pilot")["native_completion"])

    def test_verifier_cannot_reuse_dependency_worker_identity(self) -> None:
        def adapter(unit):
            result = self.adapter(unit)
            if unit.role == "critic":
                result["worker_id"] = "worker-researcher"
            return result

        with self.assertRaisesRegex(ResearchRuntimeError, "verify its own work"):
            self.dispatch(adapter)
        status = get_research_runtime_status(self.queue, "runtime-pilot")
        critic = next(item for item in status["items"] if item["step_id"] == "critic")
        self.assertEqual("recovery-required", critic["status"])

    def test_execution_result_tamper_is_rejected(self) -> None:
        def adapter(unit):
            result = self.adapter(unit)
            result["execution"]["physical_paths_included"] = True
            return result

        with self.assertRaisesRegex(ResearchRuntimeError, "execution evidence"):
            self.dispatch(adapter)

    def test_queue_rejects_wrong_owner_and_fencing_evidence(self) -> None:
        identity = {
            "project_id": "sample", "work_item_id": "research-task", "work_item_revision": 1,
            "work_item_digest": "a" * 64, "task_id": "runtime-pilot", "parent_task_id": None,
            "plan_id": "b" * 64, "step_id": "researcher", "required_role": "worker",
            "required_capabilities": ["research-execution"], "side_effects": ["read"],
            "resource_refs": ["task:sample:research-task"], "idempotency_key": "c" * 64,
            "queue_id": "queue-" + "c" * 24, "max_attempts": 3,
        }
        self.queue.apply("enqueue", identity, self.queue.state_digest())
        owner_digest = hashlib.sha256(b"owner-token-0000001").hexdigest()
        claim = self.queue.apply(
            "claim",
            {
                "project_id": "sample", "owner_digest": owner_digest, "worker_role": "worker",
                "capability_refs": ["research-execution"], "lease_seconds": 60,
            },
            self.queue.state_digest(),
        )
        lease = {
            "project_id": "sample", "queue_id": claim["queue_id"], "lease_id": claim["lease_id"],
            "owner_digest": hashlib.sha256(b"different-owner-token").hexdigest(),
            "fencing_token": claim["fencing_token"], "evidence_digest": "d" * 64,
        }
        with self.assertRaisesRegex(AgentRuntimeError, "ownership or fencing"):
            self.queue.apply("complete", lease, self.queue.state_digest())
        lease["owner_digest"] = owner_digest
        lease["fencing_token"] = int(claim["fencing_token"]) + 1
        with self.assertRaisesRegex(AgentRuntimeError, "ownership or fencing"):
            self.queue.apply("complete", lease, self.queue.state_digest())

    def test_exact_plan_and_independent_owner_tokens_are_required(self) -> None:
        plan = prepare_research_runtime_dispatch(
            self.queue,
            self.ownership,
            project_id="sample",
            work_item_id="research-task",
            work_item_revision=1,
            work_item_digest="a" * 64,
            research_id="runtime-pilot",
            task_plan_id="b" * 64,
            prompts=self.prompts,
            execution_assignments_digest="f" * 64,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
        )
        with self.assertRaisesRegex(ResearchRuntimeError, "exact plan"):
            dispatch_research_runtime(
                self.queue,
                plan,
                authorization,
                adapters={role: self.adapter for role in RESEARCH_DAG},
                owner_tokens={role: f"owner-token-{index:08d}" for index, role in enumerate(RESEARCH_DAG)},
                expected_plan_id="c" * 64,
            )
        with self.assertRaisesRegex(ResearchRuntimeError, "independent"):
            dispatch_research_runtime(
                self.queue,
                plan,
                authorization,
                adapters={role: self.adapter for role in RESEARCH_DAG},
                owner_tokens={role: "same-owner-token-0001" for role in RESEARCH_DAG},
                expected_plan_id=plan.plan_id,
            )

    def test_manual_operator_result_fails_closed_and_is_not_completed(self) -> None:
        def adapter(unit):
            result = self.adapter(unit)
            result["execution_mode"] = "external-manual"
            return result

        with self.assertRaisesRegex(ResearchRuntimeError, "not native completion"):
            self.dispatch(adapter)
        status = get_research_runtime_status(self.queue, "runtime-pilot")
        self.assertFalse(status["native_completion"])
        self.assertNotIn("completed", status["counts"])

    def test_adapter_failure_releases_lease_and_fails_closed(self) -> None:
        def adapter(_unit):
            raise RuntimeError("provider failure")

        with self.assertRaisesRegex(ResearchRuntimeError, "adapter failed"):
            self.dispatch(adapter)
        status = get_research_runtime_status(self.queue, "runtime-pilot")
        self.assertEqual(0, status["active_lease_count"])
        self.assertEqual({"recovery-required": 2}, status["counts"])
        plan = prepare_research_runtime_dispatch(
            self.queue, self.ownership, project_id="sample", work_item_id="research-task",
            work_item_revision=1, work_item_digest="a" * 64, research_id="runtime-pilot",
            task_plan_id="b" * 64, prompts=self.prompts,
            execution_assignments_digest="f" * 64,
        )
        authorization = authorize_mutation(
            plan.mutation, dry_run=DryRunEvidence(plan.mutation.plan_id, True)
        )
        with self.assertRaisesRegex(ResearchRuntimeError, "new research id"):
            dispatch_research_runtime(
                self.queue, plan, authorization,
                adapters={role: self.adapter for role in RESEARCH_DAG},
                owner_tokens={role: f"retry-owner-{index:08d}" for index, role in enumerate(RESEARCH_DAG)},
                expected_plan_id=plan.plan_id,
            )

    def test_partial_canonical_role_set_is_never_native_completion(self) -> None:
        identity = {
            "project_id": "sample", "work_item_id": "research-task", "work_item_revision": 1,
            "work_item_digest": "a" * 64, "task_id": "partial-research", "parent_task_id": None,
            "plan_id": "b" * 64, "step_id": "researcher", "required_role": "worker",
            "required_capabilities": ["research-execution", "research-role-researcher"],
            "side_effects": ["read"], "resource_refs": ["task:sample:research-researcher"],
            "idempotency_key": "c" * 64, "queue_id": "queue-" + "c" * 24,
            "max_attempts": 3,
        }
        self.queue.apply("enqueue", identity, self.queue.state_digest())
        status = get_research_runtime_status(self.queue, "partial-research")
        self.assertFalse(status["native_completion"])

    def test_long_execution_renews_lease_with_periodic_heartbeat(self) -> None:
        now = [1000.0]
        heartbeat_seen = threading.Event()
        heartbeat_count = [0]
        base = load_scheduler_policy(REPO_ROOT)
        queue = AgentRuntimeQueue(
            self.data_root,
            "sample",
            SchedulerPolicy(
                2, 1, 10, 1, base.default_max_attempts,
                base.maximum_attempts, base.claim_busy_timeout_ms,
            ),
            clock=lambda: now[0],
        )
        self.queue = queue

        def heartbeat_wait(signal, seconds):
            now[0] += seconds
            heartbeat_count[0] += 1
            if heartbeat_count[0] >= 3:
                heartbeat_seen.set()
            return signal.wait(0.001)

        def adapter(unit):
            self.assertTrue(heartbeat_seen.wait(1))
            return self.adapter(unit)

        plan = prepare_research_runtime_dispatch(
            queue, self.ownership, project_id="sample", work_item_id="research-task",
            work_item_revision=1, work_item_digest="a" * 64, research_id="runtime-pilot",
            task_plan_id="b" * 64, prompts=self.prompts,
            execution_assignments_digest="f" * 64, max_concurrency=1,
        )
        authorization = authorize_mutation(
            plan.mutation, dry_run=DryRunEvidence(plan.mutation.plan_id, True)
        )
        result = dispatch_research_runtime(
            queue, plan, authorization,
            adapters={role: adapter for role in RESEARCH_DAG},
            owner_tokens={role: f"heartbeat-owner-{index:08d}" for index, role in enumerate(RESEARCH_DAG)},
            expected_plan_id=plan.plan_id,
            heartbeat_wait=heartbeat_wait,
        )
        self.assertEqual("completed", result["status"])
        self.assertGreaterEqual(heartbeat_count[0], 3)


if __name__ == "__main__":
    unittest.main()
