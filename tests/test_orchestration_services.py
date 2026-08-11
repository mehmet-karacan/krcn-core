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
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.orchestration_verifier import (  # noqa: E402
    VerifierHandlerRegistry,
    VerifierHandlerResult,
    VerifierHandlerSpec,
    create_verification_evidence,
)
from krcn_core.orchestration_worker import (  # noqa: E402
    WorkerEffect,
    WorkerHandlerRegistry,
    WorkerHandlerResult,
    WorkerHandlerSpec,
)
import test_orchestration_verifier as verifier_fixtures  # noqa: E402
from test_policy_engine import policy_payload  # noqa: E402


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
