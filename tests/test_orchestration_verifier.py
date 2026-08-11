from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.capability_registry import (  # noqa: E402
    load_capability_registry,
    select_capability_records,
)
from krcn_core.orchestration_authorization import (  # noqa: E402
    authorize_task_plan,
    create_operation_request,
)
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import create_task_plan  # noqa: E402
from krcn_core.orchestration_verifier import (  # noqa: E402
    TaskVerificationError,
    VerifierHandlerRegistry,
    VerifierHandlerResult,
    VerifierHandlerSpec,
    VerifierRequest,
    create_verification_evidence,
    verify_task,
)
from krcn_core.orchestration_worker import (  # noqa: E402
    WorkerEffect,
    WorkerExecution,
    WorkerHandlerRegistry,
    WorkerHandlerResult,
    WorkerHandlerSpec,
    create_work_request,
    execute_worker_step,
)
from test_database_policy import select_only_policy  # noqa: E402
from test_orchestration_intent import extraction  # noqa: E402
from test_orchestration_plan import read_only_steps  # noqa: E402


class OrchestrationVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = create_task_intent(
            "Veritabanında delete istemiyorum, sadece select kullan.",
            extraction(),
        )
        registry = load_capability_registry(REPO_ROOT)
        self.selection = select_capability_records(
            registry,
            ["worker-agent", "verifier-agent", "local-store-reader-tool"],
            ["plan.execute", "record.read", "evidence.verify"],
        )
        self.plan = create_task_plan(self.intent, self.selection, read_only_steps())
        operation = create_operation_request(
            step_id="inspect-policy",
            resource_type="database",
            operation="select",
            scope_refs={"integration": "reporting-database"},
            require_policy_match=True,
        )
        self.authorization = authorize_task_plan(
            REPO_ROOT,
            intent=self.intent,
            selection=self.selection,
            plan=self.plan,
            session_id="synthetic-session",
            policies=[select_only_policy()],
            operations=[operation],
        )
        worker_handlers = WorkerHandlerRegistry()
        worker_handlers.register(
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
        request = create_work_request(
            self.plan,
            self.authorization,
            step_id="inspect-policy",
            handler_id="inspect-handler",
            input_payload={"query": "synthetic-select"},
        )
        self.execution = execute_worker_step(
            self.plan,
            self.authorization,
            request,
            worker_handlers,
        )

    def verifier_registry(self, callback):
        registry = VerifierHandlerRegistry()
        registry.register(
            VerifierHandlerSpec(
                "policy-verifier",
                ("evidence.verify",),
                ("execute", "read"),
                callback,
            )
        )
        return registry

    def evidence_for_all(self, context, *, passed=True, observed="a" * 64):
        return VerifierHandlerResult(
            tuple(
                create_verification_evidence(
                    evidence_id=f"evidence-{index}",
                    evidence_type="policy-decision"
                    if subject.kind != "verification-requirement"
                    else "test-result",
                    subject_kind=subject.kind,
                    subject_digest=subject.subject_digest,
                    verifier_step_id=context.verifier_step_id,
                    covered_worker_step_ids=("inspect-policy",),
                    observed_digests=(observed,),
                    passed=passed,
                )
                for index, subject in enumerate(context.subjects, start=1)
            )
        )

    def verify(self, callback, *, executions=None):
        return verify_task(
            self.intent,
            self.plan,
            self.authorization,
            [self.execution] if executions is None else executions,
            [VerifierRequest("verify-policy", "policy-verifier")],
            self.verifier_registry(callback),
        )

    def test_all_constraints_criteria_and_requirements_need_passing_evidence(self) -> None:
        result = self.verify(self.evidence_for_all)
        self.assertTrue(result.completion_allowed)
        self.assertEqual("verified", result.status)
        self.assertEqual(3, len(result.subjects))
        self.assertTrue(all(item.passed for item in result.subjects))
        self.assertEqual((), result.failure_codes)

    def test_missing_or_failed_evidence_blocks_completion(self) -> None:
        missing = self.verify(lambda context: VerifierHandlerResult(()))
        self.assertFalse(missing.completion_allowed)
        self.assertIn("subject-evidence-missing", missing.failure_codes)
        self.assertIn("worker-evidence-incomplete", missing.failure_codes)

        failed = self.verify(
            lambda context: self.evidence_for_all(context, passed=False)
        )
        self.assertFalse(failed.completion_allowed)
        self.assertIn("subject-verification-failed", failed.failure_codes)

    def test_missing_worker_checkpoint_blocks_completion(self) -> None:
        result = self.verify(lambda context: VerifierHandlerResult(()), executions=[])
        self.assertFalse(result.completion_allowed)
        self.assertIn("worker-checkpoint-incomplete", result.failure_codes)

    def test_tampered_worker_or_unbacked_evidence_is_rejected(self) -> None:
        tampered_checkpoint = replace(
            self.execution.checkpoint,
            result_digest="f" * 64,
        )
        tampered = WorkerExecution(
            tampered_checkpoint,
            self.execution.journal,
            False,
        )
        with self.assertRaisesRegex(TaskVerificationError, "worker evidence"):
            self.verify(self.evidence_for_all, executions=[tampered])

        with self.assertRaisesRegex(TaskVerificationError, "not backed"):
            self.verify(
                lambda context: self.evidence_for_all(
                    context,
                    observed="f" * 64,
                )
            )

    def test_verifier_cannot_write_and_schema_is_versioned(self) -> None:
        registry = VerifierHandlerRegistry()
        with self.assertRaisesRegex(TaskVerificationError, "only read and execute"):
            registry.register(
                VerifierHandlerSpec(
                    "unsafe-verifier",
                    ("evidence.verify",),
                    ("write",),
                    lambda context: VerifierHandlerResult(()),
                )
            )
        schema = json.loads(
            (REPO_ROOT / "schemas" / "task-verification.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("urn:krcn:schemas:task-verification:1", schema["$id"])


if __name__ == "__main__":
    unittest.main()
