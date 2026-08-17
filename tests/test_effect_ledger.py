from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_execution_identity import create_agent_execution_identity  # noqa: E402
from krcn_core.effect_ledger import (  # noqa: E402
    EffectLedgerError,
    build_effect_claim,
    build_effect_receipt,
    build_effect_reconciliation,
    parse_effect_claim,
    parse_effect_receipt,
    parse_effect_reconciliation,
)
from krcn_core.validation_gate import build_validation_gate  # noqa: E402


def sha(character: str) -> str:
    return character * 64


def gate(*, effect_type: str = "write"):
    verifier = create_agent_execution_identity(
        task_id="task-one", plan_id=sha("a"), step_id="verify-effect", role="verifier",
        actor_digest=sha("8"), session_digest=sha("9"), assignment_digest=sha("7"),
        runtime_kind="isolated-role",
    )
    return build_validation_gate(
        project_id="project-one", work_item_id="work-one", task_id="task-one",
        task_plan_id=sha("a"), worker_step_id="apply-change", effect_id="write-change",
        effect_type=effect_type, effect_digest=sha("b"), effect_authorization_id=sha("c"),
        worker_execution_identity_id=sha("d"), worker_actor_digest=sha("e"),
        verifier_execution_identity=verifier,
        subjects=[{"subject_kind": "acceptance-criterion", "subject_digest": sha("1")}],
        checks=[{"check_id": "state-check", "actor_kind": "verifier", "method": "state-check",
                 "expected_result": "passed", "evidence_required": ["state-observation"],
                 "subject_digests": [sha("1")]}],
        policy_revision=sha("f"), source_revision_digest=sha("0"),
        created_at="2026-08-17T15:00:00.000Z",
        mutation_plan_id=sha("3") if effect_type == "write" else None,
        provider_request_id=sha("4") if effect_type == "network" else None,
    )


def claim(**overrides):
    values = {
        "project_id": "project-one", "work_item_id": "work-one", "task_id": "task-one",
        "task_plan_id": sha("a"), "step_id": "apply-change", "queue_id": "queue-one",
        "attempt_id": "attempt-one", "attempt_number": 1,
        "execution_identity_id": sha("d"), "lease_id": "lease-one", "fencing_token": 2,
        "effect_id": "write-change", "effect_type": "write", "effect_digest": sha("b"),
        "idempotency_key": sha("5"), "effect_authorization_id": sha("c"),
        "validation_gate": gate(), "host_digest": sha("6"),
        "claimed_at": "2026-08-17T15:01:00.000Z", "mutation_plan_id": sha("3"),
        "provider_request_id": None,
    }
    values.update(overrides)
    return build_effect_claim(**values)


class EffectLedgerTests(unittest.TestCase):
    def assert_schema_valid(self, name: str, payload: dict[str, object]) -> None:
        schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))

    def test_claim_is_deterministic_and_exactly_bound_to_gate(self) -> None:
        first = claim()
        self.assertEqual(first.claim_id, claim().claim_id)
        self.assertEqual(first.as_dict(), parse_effect_claim(first.as_dict(), validation_gate=gate()).as_dict())
        self.assert_schema_valid("effect-claim.schema.json", first.as_dict())
        with self.assertRaisesRegex(EffectLedgerError, "validation gate"):
            claim(effect_digest=sha("9"))

    def test_claim_authorization_and_fence_are_strict(self) -> None:
        with self.assertRaisesRegex(EffectLedgerError, "mutation plan"):
            claim(mutation_plan_id=None)
        with self.assertRaisesRegex(EffectLedgerError, "fencing token"):
            claim(fencing_token=0)
        network_gate = gate(effect_type="network")
        network = claim(effect_type="network", validation_gate=network_gate, mutation_plan_id=None,
                        provider_request_id=sha("4"))
        self.assertEqual("network", network.payload["effect"]["effect_type"])

    def test_completed_receipt_is_terminal_and_non_replayable(self) -> None:
        checked = claim()
        receipt = build_effect_receipt(
            claim=checked, outcome="completed", retry_safety="non-replayable",
            result_digest=sha("7"), finished_at="2026-08-17T15:02:00.000Z",
            observed_fencing_token=2,
        )
        self.assertEqual(receipt.as_dict(), parse_effect_receipt(receipt.as_dict(), claim=checked).as_dict())
        self.assert_schema_valid("effect-receipt.schema.json", receipt.as_dict())
        with self.assertRaisesRegex(EffectLedgerError, "completed"):
            build_effect_receipt(claim=checked, outcome="completed", retry_safety="replay-safe",
                                 result_digest=sha("7"), finished_at="2026-08-17T15:02:00.000Z",
                                 observed_fencing_token=2)

    def test_failure_and_uncertain_receipts_require_sanitized_failure(self) -> None:
        checked = claim()
        failure = build_effect_receipt(
            claim=checked, outcome="failed", retry_safety="replay-safe",
            failure_category="adapter-failure", failure_digest=sha("8"),
            finished_at="2026-08-17T15:02:00.000Z", observed_fencing_token=2,
        )
        self.assertEqual("failed", failure.payload["outcome"]["status"])
        with self.assertRaisesRegex(EffectLedgerError, "reconciliation"):
            build_effect_receipt(
                claim=checked, outcome="uncertain", retry_safety="replay-safe",
                failure_category="host-timeout", failure_digest=sha("9"),
                finished_at="2026-08-17T15:02:00.000Z", observed_fencing_token=2,
            )

    def test_receipt_rejects_stale_fence_and_reversed_time(self) -> None:
        with self.assertRaisesRegex(EffectLedgerError, "stale"):
            build_effect_receipt(
                claim=claim(), outcome="failed", retry_safety="replay-safe",
                failure_category="adapter-failure", failure_digest=sha("8"),
                finished_at="2026-08-17T15:02:00.000Z", observed_fencing_token=1,
            )
        with self.assertRaisesRegex(EffectLedgerError, "predates"):
            build_effect_receipt(
                claim=claim(), outcome="failed", retry_safety="replay-safe",
                failure_category="adapter-failure", failure_digest=sha("8"),
                finished_at="2026-08-17T15:00:00.000Z", observed_fencing_token=2,
            )

    def test_uncertain_receipt_can_be_reconciled_without_granting_replay(self) -> None:
        checked = claim()
        receipt = build_effect_receipt(
            claim=checked, outcome="uncertain", retry_safety="reconciliation-required",
            failure_category="host-timeout", failure_digest=sha("9"),
            finished_at="2026-08-17T15:02:00.000Z", observed_fencing_token=2,
        )
        record = build_effect_reconciliation(
            claim=checked, receipt=receipt, outcome="effect-state-unknown",
            evidence=[{"evidence_type": "state-observation", "evidence_digest": sha("0")}],
            reconciler_execution_identity_id=sha("2"), observed_at="2026-08-17T15:03:00.000Z",
        )
        self.assertEqual(record.as_dict(), parse_effect_reconciliation(record.as_dict(), claim=checked, receipt=receipt).as_dict())
        self.assert_schema_valid("effect-reconciliation.schema.json", record.as_dict())
        self.assertFalse(record.payload["safety"]["permits_implicit_replay"])

    def test_completed_receipt_cannot_be_reconciled(self) -> None:
        checked = claim()
        receipt = build_effect_receipt(
            claim=checked, outcome="completed", retry_safety="non-replayable",
            result_digest=sha("7"), finished_at="2026-08-17T15:02:00.000Z",
            observed_fencing_token=2,
        )
        with self.assertRaisesRegex(EffectLedgerError, "successful"):
            build_effect_reconciliation(
                claim=checked, receipt=receipt, outcome="effect-confirmed",
                evidence=[{"evidence_type": "state-observation", "evidence_digest": sha("0")}],
                reconciler_execution_identity_id=sha("2"), observed_at="2026-08-17T15:03:00.000Z",
            )

    def test_tamper_and_unknown_fields_fail_closed(self) -> None:
        payload = claim().as_dict()
        payload["effect"]["effect_digest"] = sha("9")
        with self.assertRaisesRegex(EffectLedgerError, "digest"):
            parse_effect_claim(payload)
        receipt = build_effect_receipt(
            claim=claim(), outcome="failed", retry_safety="replay-safe",
            failure_category="adapter-failure", failure_digest=sha("8"),
            finished_at="2026-08-17T15:02:00.000Z", observed_fencing_token=2,
        ).as_dict()
        receipt["raw_output"] = "forbidden"
        with self.assertRaisesRegex(EffectLedgerError, "fields"):
            parse_effect_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
