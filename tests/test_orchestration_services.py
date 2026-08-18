from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.cli.app import main as cli_main  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.work_graph import apply_work_item, prepare_work_item  # noqa: E402
from krcn_core.orchestration_verifier import (  # noqa: E402
    VerifierHandlerRegistry,
    VerifierHandlerResult,
    VerifierHandlerSpec,
    create_verification_evidence,
)
from krcn_core.orchestration_state import OrchestrationStateStore  # noqa: E402
from krcn_core.orchestration_worker import (  # noqa: E402
    WorkerEffect,
    WorkerHandlerRegistry,
    WorkerHandlerResult,
    WorkerHandlerSpec,
)
import test_orchestration_verifier as verifier_fixtures  # noqa: E402
from test_policy_engine import policy_payload  # noqa: E402
from agent_identity_fixtures import digest, execution_identity  # noqa: E402


class OrchestrationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name)
        policy_root = self.data_root / "policies"
        policy_root.mkdir()
        (policy_root / "database-read-only.json").write_text(
            json.dumps(policy_payload(), ensure_ascii=False),
            encoding="utf-8",
        )
        fixture = verifier_fixtures.OrchestrationVerifierTests(
            methodName="test_all_constraints_criteria_and_requirements_need_passing_evidence"
        )
        fixture.setUp()
        self.intent = fixture.intent
        self.selection = fixture.selection
        self.plan = fixture.plan
        step_payloads = []
        for step in self.plan.steps:
            payload = step.as_dict()
            payload.pop("step_digest")
            step_payloads.append(payload)
        self.planning = {
            "intent": self.intent.as_dict(),
            "capability_record_refs": [
                item.record_id for item in self.selection.selected
            ],
            "required_capabilities": list(self.selection.required_capabilities),
            "steps": step_payloads,
        }
        self.context = {
            "planning": self.planning,
            "session_id": "synthetic-session",
            "operations": [
                {
                    "step_id": "inspect-policy",
                    "resource_type": "database",
                    "operation": "select",
                    "scope_refs": {"integration": "reporting-database"},
                    "require_policy_match": True,
                    "approval_trigger": None,
                }
            ],
            "mutations": [],
            "providers": [],
            "approval": None,
        }
        workers = WorkerHandlerRegistry()
        workers.register(
            WorkerHandlerSpec(
                "inspect-handler",
                ("plan.execute", "record.read"),
                ("execute", "read"),
                lambda context, payload: WorkerHandlerResult(
                    {"rows": 1},
                    (
                        WorkerEffect(
                            "policy-read",
                            "read",
                            None,
                            None,
                            ("a" * 64,),
                        ),
                    ),
                ),
                identity_actor_digest=digest("worker-inspect-policy-actor"),
                runtime_kind="local-handler",
            )
        )
        verifiers = VerifierHandlerRegistry()

        def verify(context):
            return VerifierHandlerResult(
                tuple(
                    create_verification_evidence(
                        evidence_id=f"service-evidence-{index}",
                        evidence_type="policy-decision",
                        subject_kind=subject.kind,
                        subject_digest=subject.subject_digest,
                        verifier_step_id=context.verifier_step_id,
                        verifier_execution_identity_id=(
                            context.verifier_execution_identity.execution_identity_id
                        ),
                        covered_worker_step_ids=("inspect-policy",),
                        observed_digests=("a" * 64,),
                        passed=True,
                    )
                    for index, subject in enumerate(context.subjects, start=1)
                )
            )

        verifiers.register(
            VerifierHandlerSpec(
                "policy-verifier",
                ("evidence.verify",),
                ("execute", "read"),
                verify,
                identity_actor_digest=digest("verifier-verify-policy-actor"),
                runtime_kind="local-handler",
            )
        )
        store = LocalWorkspaceStore(
            self.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(
            REPO_ROOT,
            store,
            orchestration_worker_handlers=workers,
            orchestration_verifier_handlers=verifiers,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_clients_receive_the_same_task_plan(self) -> None:
        plans = []
        for client_kind in (
            "cli",
            "sdk",
            "mcp",
            "plugin",
            "codex",
            "claude",
            "future-client",
        ):
            response = self.service.execute(
                ServiceRequest(
                    client_kind,
                    "orchestrator.plan",
                    self.planning,
                )
            )
            plans.append(response.data["plan"])
        self.assertTrue(all(item == plans[0] for item in plans))
        self.assertFalse(plans[0]["grants_execution"])

    def test_shared_service_runs_authorized_checkpointed_verified_flow(self) -> None:
        authorized = self.service.execute(
            ServiceRequest(
                "sdk",
                "orchestrator.authorize",
                {"context": self.context},
            )
        )
        authorization_id = authorized.data["authorization"]["authorization_id"]
        started = self.service.execute(
            ServiceRequest(
                "plugin",
                "orchestrator.start",
                {"context": self.context},
                apply=True,
                expected_plan_id=self.plan.plan_id,
            )
        )
        self.assertEqual("authorized", started.data["state"]["status"])
        executed = self.service.execute(
            ServiceRequest(
                "codex",
                "orchestrator.execute",
                {
                    "context": self.context,
                    "step_id": "inspect-policy",
                    "handler_id": "inspect-handler",
                    "input": {"query": "synthetic-select"},
                    "execution_identity": execution_identity(
                        self.plan, "inspect-policy", "worker"
                    ).as_dict(),
                },
                apply=True,
                expected_plan_id=self.plan.plan_id,
            )
        )
        self.assertEqual("verifying", executed.data["state"]["status"])
        verified = self.service.execute(
            ServiceRequest(
                "claude",
                "orchestrator.verify",
                {
                    "context": self.context,
                    "verifier_requests": [
                        {
                            "step_id": "verify-policy",
                            "handler_id": "policy-verifier",
                            "execution_identity": execution_identity(
                                self.plan, "verify-policy", "verifier"
                            ).as_dict(),
                        }
                    ],
                },
                apply=True,
                expected_plan_id=self.plan.plan_id,
            )
        )
        self.assertEqual("completed", verified.data["state"]["status"])
        resumed = self.service.execute(
            ServiceRequest(
                "mcp",
                "orchestrator.resume",
                {"context": self.context},
            )
        )
        self.assertEqual("completed", resumed.data["resume"]["status"])
        self.assertEqual(authorization_id, verified.data["state"]["authorization_id"])
        status = self.service.execute(
            ServiceRequest(
                "cli",
                "orchestrator.status",
                {"context": self.context},
            )
        )
        timeline = status.data["timeline"]
        self.assertEqual(
            ["task-initialized", "worker-started", "worker-completed", "task-verified"],
            [item["event_type"] for item in timeline["events"]],
        )
        self.assertFalse(timeline["payload_disclosed"])
        self.assertNotIn("synthetic-select", json.dumps(timeline))

    def test_intent_service_does_not_retain_raw_request(self) -> None:
        request = "Veritabanında delete istemiyorum, sadece select kullan."
        response = self.service.execute(
            ServiceRequest(
                "agent",
                "orchestrator.intent",
                {
                    "request": request,
                    "extraction": verifier_fixtures.extraction(),
                },
            )
        )
        self.assertNotIn(request, json.dumps(response.as_dict(), ensure_ascii=False))

    def test_layout_v2_orchestration_is_scoped_to_project_work_item(self) -> None:
        (self.data_root / "layout.json").write_bytes(user_home_layout_bytes())
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        store = self.service._store

        def apply_record(plan):
            store.apply_put(
                plan,
                authorize_mutation(
                    plan.mutation,
                    dry_run=DryRunEvidence(plan.mutation.plan_id, True),
                    approval=ApprovalEvidence(
                        plan.mutation.plan_id,
                        "test-approval",
                        True,
                    ),
                ),
            )

        project = {
            "schema_version": 1,
            "project_id": "sample",
            "name": "Sample",
            "description": "Scoped orchestration",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        apply_record(store.prepare_put(
            "projects", "sample", project,
            expected_revision=0, project_id="sample",
        ))
        work_plan = prepare_work_item(
            store,
            ownership,
            {
                "work_item_id": "task-scoped",
                "project_id": "sample",
                "work_type": "task",
                "title": "Scoped task",
                "description": "Persist runtime inside the project capsule",
                "status": "active",
                "acceptance_criteria": [
                    item.value for item in self.intent.acceptance_criteria
                ],
                "relations": [],
                "evidence": [],
                "provenance": {"source_kind": "user", "source_ref": "test"},
            },
        )
        apply_work_item(
            store,
            work_plan,
            {
                effect.plan_id: authorize_mutation(
                    effect,
                    dry_run=DryRunEvidence(effect.plan_id, True),
                    approval=(
                        ApprovalEvidence(effect.plan_id, "test-approval", True)
                        if effect.approval_required
                        else None
                    ),
                )
                for effect in work_plan.effect_plans
            },
        )
        arguments = {
            "context": self.context,
            "project_id": "sample",
            "work_item_id": "task-scoped",
        }
        started = self.service.execute(ServiceRequest(
            "plugin",
            "orchestrator.start",
            arguments,
            apply=True,
            expected_plan_id=self.plan.plan_id,
        ))
        self.assertEqual("authorized", started.data["state"]["status"])
        runtime = self.data_root / "projects" / "sample" / "runtime"
        self.assertTrue((runtime / "orchestration-states" / f"{self.plan.task_id}.json").is_file())
        self.assertTrue((runtime / "orchestration-plans" / f"{self.plan.task_id}.json").is_file())
        handoff = store.read("orchestration-handoffs", f"{self.plan.task_id}-handoff")
        self.assertIn("project:sample", handoff.payload["context_refs"])
        self.assertIn("work-item:task-scoped", handoff.payload["context_refs"])

        progress = OrchestrationStateStore(store).project_progress("sample")
        self.assertEqual(1, len(progress))
        self.assertEqual("task-scoped", progress[0]["work_item_id"])
        self.assertEqual(1, progress[0]["total_step_count"])
        self.assertEqual(0, progress[0]["completed_step_count"])
        self.assertEqual("inspect-policy", progress[0]["next_steps"][0]["step_id"])
        self.assertFalse(progress[0]["grants_authority"])
        resumed_project = self.service.execute(ServiceRequest(
            "opencode",
            "project.resume",
            {
                "working_directory": str(self.data_root),
                "project_ref": "sample",
            },
        ))
        active_progress = resumed_project.data["resume"]["work"]["active_progress"]
        self.assertEqual("task-scoped", active_progress[0]["work_item_id"])
        self.assertEqual(0, active_progress[0]["completed_step_count"])

        executed = self.service.execute(ServiceRequest(
            "codex",
            "orchestrator.execute",
            {
                **arguments,
                "step_id": "inspect-policy",
                "handler_id": "inspect-handler",
                "input": {"query": "synthetic-select"},
                "execution_identity": execution_identity(
                    self.plan, "inspect-policy", "worker"
                ).as_dict(),
            },
            apply=True,
            expected_plan_id=self.plan.plan_id,
        ))
        self.assertEqual("verifying", executed.data["state"]["status"])
        progress = OrchestrationStateStore(store).project_progress("sample")
        self.assertEqual(1, progress[0]["completed_step_count"])
        self.assertEqual(0, progress[0]["pending_step_count"])
        self.assertEqual([], progress[0]["next_steps"])
        self.assertTrue(progress[0]["verification_required"])
        self.assertEqual("verify-task", progress[0]["next_action"])

        verify_request = ServiceRequest(
            "claude",
            "orchestrator.verify",
            {
                **arguments,
                "verifier_requests": [{
                    "step_id": "verify-policy",
                    "handler_id": "policy-verifier",
                    "execution_identity": execution_identity(
                        self.plan, "verify-policy", "verifier"
                    ).as_dict(),
                }],
            },
            apply=True,
            expected_plan_id=self.plan.plan_id,
        )
        state_store = self.service._orchestration._states
        original_transition = state_store.transition

        def interrupt_terminal_transition(current, plan, **kwargs):
            if kwargs.get("event_type") == "task-verified":
                raise RuntimeError("injected terminal transition interruption")
            return original_transition(current, plan, **kwargs)

        state_store.transition = interrupt_terminal_transition
        try:
            with self.assertRaisesRegex(RuntimeError, "injected terminal"):
                self.service.execute(verify_request)
        finally:
            state_store.transition = original_transition
        interrupted_state = store.read("orchestration-states", self.plan.task_id)
        self.assertEqual("verifying", interrupted_state.payload["status"])
        self.assertEqual(
            "completed", store.read("work-items", "task-scoped").payload["status"]
        )

        verified = self.service.execute(verify_request)
        self.assertEqual("completed", verified.data["state"]["status"])
        completion = verified.data["work_completion"]
        self.assertTrue(completion["completed"])
        self.assertFalse(completion["second_approval_required"])
        completed_item = store.read("work-items", "task-scoped")
        self.assertEqual("completed", completed_item.payload["status"])
        self.assertEqual(2, completed_item.revision)
        self.assertIsNotNone(store.read("work-events", "task-scoped-r2"))
        attestation_id = f"{self.plan.task_id}-work-completion"
        self.assertIsNotNone(
            store.read("work-completion-attestations", attestation_id)
        )
        repeated = self.service.execute(verify_request)
        self.assertEqual("ok", repeated.status)
        self.assertTrue(repeated.data["no_op"])
        self.assertTrue(repeated.data["work_completion"]["completed"])
        self.assertEqual(2, store.read("work-items", "task-scoped").revision)

    def test_cli_uses_the_same_plan_service_contract(self) -> None:
        request_path = self.data_root / "orchestrator-plan.json"
        request_path.write_text(
            json.dumps(self.planning, ensure_ascii=False),
            encoding="utf-8",
        )
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = cli_main(
                [
                    "orchestrator",
                    "plan",
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(self.data_root),
                    "--request-file",
                    str(request_path),
                ]
            )
        self.assertEqual(0, result, error.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual(self.plan.plan_id, payload["data"]["plan"]["plan_id"])


if __name__ == "__main__":
    unittest.main()
