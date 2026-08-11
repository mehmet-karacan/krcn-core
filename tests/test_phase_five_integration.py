from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.capability_registry import (  # noqa: E402
    CapabilitySelection,
    load_capability_registry,
    select_capability_records,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    DryRunEvidence,
    OwnershipResolver,
    plan_mutation,
)
from krcn_core.orchestration_authorization import (  # noqa: E402
    TaskAuthorizationError,
    TaskMutationRequest,
    TaskProviderRequest,
    authorize_task_plan,
    create_operation_request,
)
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import create_task_plan  # noqa: E402
from krcn_core.orchestration_verifier import (  # noqa: E402
    VerifierHandlerRegistry,
    VerifierHandlerResult,
    VerifierHandlerSpec,
    VerifierRequest,
    create_verification_evidence,
    verify_task,
)
from krcn_core.orchestration_worker import (  # noqa: E402
    WorkerEffect,
    WorkerHandlerRegistry,
    WorkerHandlerResult,
    WorkerHandlerSpec,
    create_work_request,
    execute_worker_step,
)
from krcn_core.provider_gate import create_provider_request  # noqa: E402
import test_orchestration_authorization as authorization_fixtures  # noqa: E402
from test_orchestration_intent import extraction, value  # noqa: E402
from test_orchestration_plan import read_only_steps  # noqa: E402
import test_orchestration_services as service_fixtures  # noqa: E402


class PhaseFiveIntegrationTests(unittest.TestCase):
    def test_controlled_core_effect_stays_exact_plan_bound(self) -> None:
        intent_payload = extraction()
        intent_payload["ownership_impact"] = ["core"]
        intent_payload["constraints"] = [value("Yalnız planlanan core hedefini değiştir")]
        intent_payload["acceptance_criteria"] = [value("Core etkisi exact mutation planına bağlıdır")]
        intent_payload["verification_requirements"] = [value("Worker kanıtı mutation kimliğini taşımalıdır")]
        intent = create_task_intent(
            "Kontrollü core değişikliğini planla ve kanıtla.",
            intent_payload,
        )
        registry = load_capability_registry(REPO_ROOT)
        selection = select_capability_records(
            registry,
            ["worker-agent", "verifier-agent"],
            ["plan.execute", "evidence.verify"],
        )
        steps = [
            {
                "step_id": "update-core",
                "title": "Apply the exact synthetic core effect",
                "role": "worker",
                "depends_on": [],
                "required_capabilities": ["plan.execute"],
                "capability_record_refs": ["worker-agent"],
                "side_effects": ["execute", "write"],
                "ownership_impacts": ["core"],
                "provider_mode": "none",
                "approval_triggers": [],
                "acceptance_criteria": [],
                "verification_requirements": [],
                "reversible": True,
                "rollback_strategy": "restore-checkpoint",
            },
            {
                "step_id": "verify-core",
                "title": "Verify the synthetic core effect",
                "role": "verifier",
                "depends_on": ["update-core"],
                "required_capabilities": ["evidence.verify"],
                "capability_record_refs": ["verifier-agent"],
                "side_effects": ["execute", "read"],
                "ownership_impacts": ["core"],
                "provider_mode": "none",
                "approval_triggers": [],
                "acceptance_criteria": ["Core etkisi exact mutation planına bağlıdır"],
                "verification_requirements": ["Worker kanıtı mutation kimliğini taşımalıdır"],
                "reversible": True,
                "rollback_strategy": "not-required",
            },
        ]
        plan = create_task_plan(intent, selection, steps)
        mutation = plan_mutation(
            OwnershipResolver.from_repository(REPO_ROOT),
            operation="update",
            target_ref="README.md",
            expected_ownership="core",
            change_digest="c" * 64,
            reversible=True,
        )
        authorization = authorize_task_plan(
            REPO_ROOT,
            intent=intent,
            selection=selection,
            plan=plan,
            session_id="synthetic-session",
            operations=[
                create_operation_request(
                    step_id="update-core",
                    resource_type="local-record",
                    operation="update",
                )
            ],
            mutations=[
                TaskMutationRequest(
                    "update-core",
                    mutation,
                    DryRunEvidence(mutation.plan_id, True),
                )
            ],
        )
        workers = WorkerHandlerRegistry()
        workers.register(
            WorkerHandlerSpec(
                "synthetic-core-handler",
                ("plan.execute",),
                ("execute", "write"),
                lambda context, payload: WorkerHandlerResult(
                    {"synthetic": True},
                    (
                        WorkerEffect(
                            "core-write",
                            "write",
                            mutation.plan_id,
                            None,
                            ("d" * 64,),
                        ),
                    ),
                ),
            )
        )
        execution = execute_worker_step(
            plan,
            authorization,
            create_work_request(
                plan,
                authorization,
                step_id="update-core",
                handler_id="synthetic-core-handler",
                input_payload={"fixture": "core-effect"},
            ),
            workers,
        )
        verifiers = VerifierHandlerRegistry()

        def verify(context):
            return VerifierHandlerResult(
                tuple(
                    create_verification_evidence(
                        evidence_id=f"core-evidence-{index}",
                        evidence_type="artifact-digest",
                        subject_kind=subject.kind,
                        subject_digest=subject.subject_digest,
                        verifier_step_id=context.verifier_step_id,
                        covered_worker_step_ids=("update-core",),
                        observed_digests=("d" * 64,),
                        passed=True,
                    )
                    for index, subject in enumerate(context.subjects, start=1)
                )
            )

        verifiers.register(
            VerifierHandlerSpec(
                "synthetic-core-verifier",
                ("evidence.verify",),
                ("execute", "read"),
                verify,
            )
        )
        result = verify_task(
            intent,
            plan,
            authorization,
            [execution],
            [VerifierRequest("verify-core", "synthetic-core-verifier")],
            verifiers,
        )
        self.assertTrue(result.completion_allowed)
        self.assertFalse(plan.requires_approval)
        self.assertEqual((mutation.plan_id,), authorization.steps[0].mutation_plan_ids)

    def test_policy_scope_and_provider_escalations_fail_closed(self) -> None:
        fixture = service_fixtures.OrchestrationServiceTests(
            methodName="test_all_clients_receive_the_same_task_plan"
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        denied_context = copy.deepcopy(fixture.context)
        denied_context["operations"][0]["operation"] = "delete"
        with self.assertRaisesRegex(TaskAuthorizationError, "policy denies"):
            fixture.service.execute(
                ServiceRequest(
                    "plugin",
                    "orchestrator.authorize",
                    {"context": denied_context},
                )
            )

        changed_planning = copy.deepcopy(fixture.planning)
        changed_planning["steps"][0]["title"] = "Expanded task scope"
        changed_context = copy.deepcopy(fixture.context)
        changed_context["planning"] = changed_planning
        with self.assertRaisesRegex(ValueError, "exact task plan"):
            fixture.service.execute(
                ServiceRequest(
                    "codex",
                    "orchestrator.start",
                    {"context": changed_context},
                    apply=True,
                    expected_plan_id=fixture.plan.plan_id,
                )
            )

        auth_fixture = authorization_fixtures.OrchestrationAuthorizationTests(
            methodName="test_remote_provider_requires_exact_disclosure_request_and_session"
        )
        auth_fixture.setUp()
        remote = authorization_fixtures.remote_record()
        selected = tuple(
            sorted(
                (*auth_fixture.selection.selected, remote),
                key=lambda item: (item.kind, item.record_id),
            )
        )
        selection = CapabilitySelection(
            selected,
            tuple(sorted((*auth_fixture.selection.required_capabilities, "provider.query"))),
            tuple(sorted({item for record in selected for item in record.approval_triggers})),
            auth_fixture.selection.registry_digest,
        )
        steps = read_only_steps()
        steps[0]["required_capabilities"].append("provider.query")
        steps[0]["capability_record_refs"].append("synthetic-remote-tool")
        steps[0]["side_effects"].append("network")
        steps[0]["provider_mode"] = "remote"
        steps[0]["approval_triggers"] = ["remote-provider-use"]
        remote_plan = create_task_plan(auth_fixture.intent, selection, steps)
        provider = create_provider_request(
            provider="approved-remote",
            endpoint="https://synthetic.invalid",
            data_categories=("synthetic-metadata",),
            operation_scope="task-read",
            retention_assumptions="Synthetic payload is not retained",
            session_id="synthetic-session",
            remote=True,
        )
        with self.assertRaisesRegex(TaskAuthorizationError, "exact-plan"):
            authorize_task_plan(
                REPO_ROOT,
                intent=auth_fixture.intent,
                selection=selection,
                plan=remote_plan,
                session_id="synthetic-session",
                operations=[
                    create_operation_request(
                        step_id="inspect-policy",
                        resource_type="local-record",
                        operation="read",
                    )
                ],
                providers=[TaskProviderRequest("inspect-policy", provider)],
            )

    def test_interrupted_service_resumes_in_a_new_service_instance(self) -> None:
        fixture = service_fixtures.OrchestrationServiceTests(
            methodName="test_shared_service_runs_authorized_checkpointed_verified_flow"
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        failing = WorkerHandlerRegistry()
        failing.register(
            WorkerHandlerSpec(
                "inspect-handler",
                ("plan.execute", "record.read"),
                ("execute", "read"),
                lambda context, payload: (_ for _ in ()).throw(
                    RuntimeError("synthetic interruption")
                ),
            )
        )
        store = LocalWorkspaceStore(
            fixture.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        first = KrcnApplicationService(
            REPO_ROOT,
            store,
            orchestration_worker_handlers=failing,
        )
        first.execute(
            ServiceRequest(
                "cli",
                "orchestrator.start",
                {"context": fixture.context},
                apply=True,
                expected_plan_id=fixture.plan.plan_id,
            )
        )
        failed = first.execute(
            ServiceRequest(
                "cli",
                "orchestrator.execute",
                {
                    "context": fixture.context,
                    "step_id": "inspect-policy",
                    "handler_id": "inspect-handler",
                    "input": {"query": "synthetic-select"},
                },
                apply=True,
                expected_plan_id=fixture.plan.plan_id,
            )
        )
        self.assertEqual("failed", failed.data["state"]["status"])

        succeeding = WorkerHandlerRegistry()
        succeeding.register(
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
            )
        )
        resumed_verifiers = VerifierHandlerRegistry()
        resumed_verifiers.register(
            VerifierHandlerSpec(
                "policy-verifier",
                ("evidence.verify",),
                ("execute", "read"),
                lambda context: VerifierHandlerResult(
                    tuple(
                        create_verification_evidence(
                            evidence_id=f"resume-evidence-{index}",
                            evidence_type="policy-decision",
                            subject_kind=subject.kind,
                            subject_digest=subject.subject_digest,
                            verifier_step_id=context.verifier_step_id,
                            covered_worker_step_ids=("inspect-policy",),
                            observed_digests=("a" * 64,),
                            passed=True,
                        )
                        for index, subject in enumerate(context.subjects, start=1)
                    )
                ),
            )
        )
        second = KrcnApplicationService(
            REPO_ROOT,
            LocalWorkspaceStore(
                fixture.data_root,
                OwnershipResolver.from_repository(REPO_ROOT),
            ),
            orchestration_worker_handlers=succeeding,
            orchestration_verifier_handlers=resumed_verifiers,
        )
        resumed = second.execute(
            ServiceRequest(
                "claude",
                "orchestrator.resume",
                {"context": fixture.context},
            )
        )
        self.assertEqual(("inspect-policy",), tuple(resumed.data["resume"]["next_step_ids"]))
        completed_worker = second.execute(
            ServiceRequest(
                "codex",
                "orchestrator.execute",
                {
                    "context": fixture.context,
                    "step_id": "inspect-policy",
                    "handler_id": "inspect-handler",
                    "input": {"query": "synthetic-select"},
                },
                apply=True,
                expected_plan_id=fixture.plan.plan_id,
            )
        )
        self.assertEqual("verifying", completed_worker.data["state"]["status"])
        completed = second.execute(
            ServiceRequest(
                "mcp",
                "orchestrator.verify",
                {
                    "context": fixture.context,
                    "verifier_requests": [
                        {"step_id": "verify-policy", "handler_id": "policy-verifier"}
                    ],
                },
                apply=True,
                expected_plan_id=fixture.plan.plan_id,
            )
        )
        self.assertEqual("completed", completed.data["state"]["status"])


if __name__ == "__main__":
    unittest.main()
