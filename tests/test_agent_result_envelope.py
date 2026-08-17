from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_result_envelope import (  # noqa: E402
    AgentResultEnvelopeError,
    build_agent_result_envelope,
    parse_agent_result_envelope,
)
from krcn_core.workflow_step_receipt import (  # noqa: E402
    WorkflowStepReceiptError,
    aggregate_step_receipts,
    build_workflow_step_receipt,
    parse_workflow_step_receipt,
)


def sha(character: str) -> str:
    return character * 64


def envelope(**overrides):
    values = {
        "correlation_id": "correlation-one",
        "project_id": "project-one",
        "work_item_id": "work-one",
        "task_id": "task-one",
        "task_plan_id": sha("a"),
        "step_id": "worker-one",
        "queue_id": "queue-one",
        "execution_identity_id": sha("b"),
        "role": "worker",
        "route_decision_id": sha("c"),
        "delegation_decision_id": sha("d"),
        "model_assignment_id": "model-one",
        "admission_decision_id": None,
        "status": "completed",
        "headline": "Reviewed analysis completed",
        "findings": [
            {"code": "SOURCE_CONFIRMED", "statement": "Reviewed evidence is current"}
        ],
        "artifacts": [
            {
                "artifact_id": "report-one",
                "artifact_type": "report",
                "artifact_digest": sha("e"),
            }
        ],
        "evidence": [
            {
                "evidence_id": "evidence-one",
                "evidence_type": "state-observation",
                "evidence_digest": sha("f"),
            }
        ],
        "effects": [
            {
                "effect_id": "source-read",
                "effect_type": "read",
                "claim_id": None,
                "receipt_id": None,
                "result_digest": sha("1"),
            }
        ],
        "risks": [],
        "recommended_action_code": "VERIFY_RESULT",
        "recommended_action_statement": "Run independent verification",
        "recommended_action_role": "verifier",
        "verification_required": True,
    }
    values.update(overrides)
    return build_agent_result_envelope(**values)


def receipt(**overrides):
    values = {
        "correlation_id": "correlation-one",
        "project_id": "project-one",
        "work_item_id": "work-one",
        "task_id": "task-one",
        "task_plan_id": sha("a"),
        "step_id": "worker-one",
        "queue_id": "queue-one",
        "attempt_id": "attempt-one",
        "sequence": 1,
        "attempt_number": 1,
        "actor_kind": "agent",
        "role": "worker",
        "execution_identity_id": sha("b"),
        "model_assignment_id": "model-one",
        "client_id": "codex",
        "status": "completed",
        "input_digest": sha("c"),
        "output_digest": sha("d"),
        "context_snapshot_digest": sha("e"),
        "route_decision_id": sha("f"),
        "started_at": "2026-08-17T12:00:00.000Z",
        "finished_at": "2026-08-17T12:00:01.500Z",
        "harness_revision": "runtime-v1",
        "policy_revision": "policy-v1",
        "input_tokens": 100,
        "output_tokens": 40,
        "cache_read_tokens": 10,
        "cache_write_tokens": 5,
        "cost_microunits": 250,
        "currency": "USD",
    }
    values.update(overrides)
    return build_workflow_step_receipt(**values)


class AgentResultEnvelopeTests(unittest.TestCase):
    def test_worker_envelope_is_bounded_digest_bound_and_schema_valid(self) -> None:
        result = envelope()
        payload = result.as_dict()
        schema = json.loads(
            (REPO_ROOT / "schemas/agent-result-envelope.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))
        self.assertEqual("completed", result.status)
        self.assertEqual("worker", result.role)
        self.assertFalse(payload["safety"]["grants_authority"])
        self.assertEqual(result, parse_agent_result_envelope(payload))

    def test_explorer_cannot_report_mutation_effect(self) -> None:
        with self.assertRaisesRegex(AgentResultEnvelopeError, "explorer"):
            envelope(
                role="explorer",
                effects=[
                    {
                        "effect_id": "write-one",
                        "effect_type": "write",
                        "claim_id": sha("1"),
                        "receipt_id": sha("2"),
                        "result_digest": sha("3"),
                    }
                ],
            )

    def test_completed_worker_mutation_requires_claim_receipt_and_result(self) -> None:
        with self.assertRaisesRegex(AgentResultEnvelopeError, "claim evidence"):
            envelope(
                effects=[
                    {
                        "effect_id": "write-one",
                        "effect_type": "write",
                        "claim_id": None,
                        "receipt_id": None,
                        "result_digest": None,
                    }
                ]
            )

    def test_verifier_requires_coverage_verdict_and_nonproduct_artifacts(self) -> None:
        verified = envelope(
            role="verifier",
            step_id="verify-one",
            artifacts=[
                {
                    "artifact_id": "test-one",
                    "artifact_type": "test-result",
                    "artifact_digest": sha("e"),
                }
            ],
            effects=[],
            covered_worker_step_ids=["worker-one"],
            verdict="passed",
            verification_id=sha("9"),
        )
        self.assertEqual("passed", verified.as_dict()["result"]["verification"]["verdict"])
        with self.assertRaisesRegex(AgentResultEnvelopeError, "verifier"):
            envelope(role="verifier", step_id="verify-one", effects=[])

    def test_failure_and_partial_shapes_are_explicit(self) -> None:
        failed = envelope(
            status="failed",
            failure={
                "category": "TOOL_TIMEOUT",
                "retry_safety": "reconciliation-required",
                "failure_digest": sha("9"),
                "last_verified_checkpoint_id": None,
            },
            recommended_action_code="RECONCILE_EFFECT",
            recommended_action_statement="Reconcile the pending effect",
            recommended_action_role="coordinator",
        )
        self.assertEqual("failed", failed.status)
        partial = envelope(
            status="partial",
            missing_step_ids=["worker-two"],
            recommended_action_code="RUN_MISSING_STEP",
        )
        self.assertEqual(["worker-two"], partial.as_dict()["result"]["missing_step_ids"])
        with self.assertRaisesRegex(AgentResultEnvelopeError, "missing-step"):
            envelope(status="partial")

    def test_unsafe_text_unknown_fields_and_digest_tamper_fail_closed(self) -> None:
        with self.assertRaisesRegex(AgentResultEnvelopeError, "unsafe"):
            envelope(headline="Inspect " + "C:" + "\\private\\result.txt")
        with self.assertRaisesRegex(AgentResultEnvelopeError, "unsafe"):
            envelope(headline="api" + "_key=example-value")
        payload = envelope().as_dict()
        payload["unexpected"] = True
        with self.assertRaisesRegex(AgentResultEnvelopeError, "fields"):
            parse_agent_result_envelope(payload)
        payload = envelope().as_dict()
        payload["result"]["summary"]["headline"] = "Changed"
        with self.assertRaisesRegex(AgentResultEnvelopeError, "digest"):
            parse_agent_result_envelope(payload)


class WorkflowStepReceiptTests(unittest.TestCase):
    def test_receipt_validates_schema_time_usage_and_digest(self) -> None:
        result = receipt()
        payload = result.as_dict()
        schema = json.loads(
            (REPO_ROOT / "schemas/workflow-step-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))
        self.assertEqual(1500, payload["usage"]["duration_ms"])
        self.assertEqual(payload["identity"]["receipt_id"], payload["receipt_digest"])
        self.assertEqual(result, parse_workflow_step_receipt(payload))

    def test_failure_receipt_requires_failure_evidence(self) -> None:
        failed = receipt(
            status="timed-out",
            output_digest=None,
            failure_category="TOOL_TIMEOUT",
            failure_digest=sha("8"),
            cost_microunits=0,
            currency=None,
        )
        self.assertEqual("timed-out", failed.status)
        with self.assertRaisesRegex(WorkflowStepReceiptError, "incomplete"):
            receipt(status="failed", output_digest=None, cost_microunits=0, currency=None)

    def test_duration_currency_boolean_and_tamper_fail_closed(self) -> None:
        with self.assertRaisesRegex(WorkflowStepReceiptError, "duration"):
            receipt(duration_ms=4)
        with self.assertRaisesRegex(WorkflowStepReceiptError, "currency"):
            receipt(cost_microunits=1, currency=None)
        with self.assertRaisesRegex(WorkflowStepReceiptError, "sequence"):
            receipt(sequence=True)
        payload = receipt().as_dict()
        payload["usage"]["input_tokens"] = 999
        with self.assertRaisesRegex(WorkflowStepReceiptError, "digest"):
            parse_workflow_step_receipt(payload)

    def test_receipt_aggregation_is_reproducible_and_scope_bound(self) -> None:
        first = receipt()
        second = receipt(
            step_id="worker-two",
            attempt_id="attempt-two",
            sequence=2,
            input_tokens=50,
            output_tokens=10,
            cache_read_tokens=0,
            cache_write_tokens=0,
            cost_microunits=100,
        )
        aggregate = aggregate_step_receipts([second, first])
        self.assertEqual(2, aggregate["receipt_count"])
        self.assertEqual(150, aggregate["usage"]["input_tokens"])
        self.assertEqual(350, aggregate["usage"]["cost_microunits"])
        self.assertFalse(aggregate["grants_authority"])
        with self.assertRaisesRegex(WorkflowStepReceiptError, "scope"):
            aggregate_step_receipts(
                [first, receipt(correlation_id="correlation-two", attempt_id="attempt-two")]
            )
        with self.assertRaisesRegex(WorkflowStepReceiptError, "duplicates"):
            aggregate_step_receipts([first, first])


if __name__ == "__main__":
    unittest.main()
