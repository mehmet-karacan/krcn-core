from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_execution_identity import create_agent_execution_identity  # noqa: E402
from krcn_core.effect_ledger import (  # noqa: E402
    build_effect_claim,
    build_effect_receipt,
    build_effect_reconciliation,
)
from krcn_core.effect_ledger_store import EffectLedgerStore, EffectLedgerStoreError  # noqa: E402
from krcn_core.validation_gate import build_validation_gate  # noqa: E402


def sha(character: str) -> str:
    return character * 64


def make_gate():
    verifier = create_agent_execution_identity(
        task_id="task-one", plan_id=sha("a"), step_id="verify-effect", role="verifier",
        actor_digest=sha("8"), session_digest=sha("9"), assignment_digest=sha("7"), runtime_kind="isolated-role",
    )
    return build_validation_gate(
        project_id="project-one", work_item_id="work-one", task_id="task-one", task_plan_id=sha("a"),
        worker_step_id="apply-change", effect_id="write-change", effect_type="write",
        effect_digest=sha("b"), effect_authorization_id=sha("c"), worker_execution_identity_id=sha("d"),
        worker_actor_digest=sha("e"), verifier_execution_identity=verifier,
        subjects=[{"subject_kind": "acceptance-criterion", "subject_digest": sha("1")}],
        checks=[{"check_id": "state-check", "actor_kind": "verifier", "method": "state-check",
                 "expected_result": "passed", "evidence_required": ["state-observation"], "subject_digests": [sha("1")]}],
        policy_revision=sha("f"), source_revision_digest=sha("0"), created_at="2026-08-17T15:00:00.000Z",
        mutation_plan_id=sha("3"),
    )


def make_claim(*, idempotency_key: str = sha("5"), effect_digest: str = sha("b")):
    gate = make_gate()
    return gate, build_effect_claim(
        project_id="project-one", work_item_id="work-one", task_id="task-one", task_plan_id=sha("a"),
        step_id="apply-change", queue_id="queue-one", attempt_id="attempt-one", attempt_number=1,
        execution_identity_id=sha("d"), lease_id="lease-one", fencing_token=2,
        effect_id="write-change", effect_type="write", effect_digest=effect_digest,
        idempotency_key=idempotency_key, effect_authorization_id=sha("c"), validation_gate=gate,
        host_digest=sha("6"), claimed_at="2026-08-17T15:01:00.000Z", mutation_plan_id=sha("3"),
    )


class EffectLedgerStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "effect-ledger.sqlite"
        self.store = EffectLedgerStore(self.path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_claim_is_durable_and_replay_does_not_execute_again(self) -> None:
        gate, claim = make_claim()
        first = self.store.record_claim(claim, validation_gate=gate)
        replay = self.store.record_claim(claim, validation_gate=gate)
        self.assertEqual(("claimed", True), (first["status"], first["execution_allowed"]))
        self.assertEqual(("current", False), (replay["status"], replay["execution_allowed"]))
        reopened = EffectLedgerStore(self.path)
        self.assertTrue(reopened.claim_status(claim.claim_id)["recovery_required"])
        self.assertEqual((claim.claim_id,), reopened.recovery_required_claims())
        report = reopened.doctor_report()
        self.assertTrue(report["integrity_verified"])
        self.assertEqual(1, report["recovery_required_count"])

    def test_same_idempotency_key_conflicting_claim_is_rejected(self) -> None:
        gate, claim = make_claim()
        self.store.record_claim(claim, validation_gate=gate)
        other_gate = make_gate()
        payload = claim.as_dict()
        payload["bindings"]["attempt_number"] = 2
        # A conflicting claim cannot be forged through the parser, so use a
        # separately valid gate/claim with the same key and different attempt.
        other = build_effect_claim(
            project_id="project-one", work_item_id="work-one", task_id="task-one", task_plan_id=sha("a"),
            step_id="apply-change", queue_id="queue-one", attempt_id="attempt-two", attempt_number=2,
            execution_identity_id=sha("d"), lease_id="lease-two", fencing_token=3,
            effect_id="write-change", effect_type="write", effect_digest=sha("b"),
            idempotency_key=sha("5"), effect_authorization_id=sha("c"), validation_gate=other_gate,
            host_digest=sha("6"), claimed_at="2026-08-17T15:01:01.000Z", mutation_plan_id=sha("3"),
        )
        with self.assertRaisesRegex(EffectLedgerStoreError, "conflicting claim"):
            self.store.record_claim(other, validation_gate=other_gate)

    def test_single_terminal_receipt_and_idempotent_replay(self) -> None:
        gate, claim = make_claim()
        self.store.record_claim(claim, validation_gate=gate)
        receipt = build_effect_receipt(
            claim=claim, outcome="completed", retry_safety="non-replayable", result_digest=sha("7"),
            finished_at="2026-08-17T15:02:00.000Z", observed_fencing_token=2,
        )
        self.assertEqual("recorded", self.store.record_receipt(receipt)["status"])
        self.assertEqual("current", self.store.record_receipt(receipt)["status"])
        status = self.store.claim_status(claim.claim_id)
        self.assertFalse(status["recovery_required"])
        self.assertEqual("completed", status["receipt_status"])
        self.assertEqual(0, self.store.doctor_report()["recovery_required_count"])
        conflict = build_effect_receipt(
            claim=claim, outcome="failed", retry_safety="replay-safe", failure_category="adapter-failure",
            failure_digest=sha("8"), finished_at="2026-08-17T15:02:01.000Z", observed_fencing_token=2,
        )
        with self.assertRaisesRegex(EffectLedgerStoreError, "conflicting terminal"):
            self.store.record_receipt(conflict)

    def test_receipt_without_claim_is_rejected(self) -> None:
        _, claim = make_claim()
        receipt = build_effect_receipt(
            claim=claim, outcome="failed", retry_safety="replay-safe", failure_category="adapter-failure",
            failure_digest=sha("8"), finished_at="2026-08-17T15:02:00.000Z", observed_fencing_token=2,
        )
        with self.assertRaisesRegex(EffectLedgerStoreError, "not recorded"):
            self.store.record_receipt(receipt)

    def test_missing_or_uncertain_receipt_reconciliation_is_durable(self) -> None:
        gate, claim = make_claim()
        self.store.record_claim(claim, validation_gate=gate)
        reconciliation = build_effect_reconciliation(
            claim=claim, receipt=None, outcome="effect-state-unknown",
            evidence=[{"evidence_type": "state-observation", "evidence_digest": sha("0")}],
            reconciler_execution_identity_id=sha("2"), observed_at="2026-08-17T15:03:00.000Z",
        )
        self.assertEqual("recorded", self.store.record_reconciliation(reconciliation)["status"])
        self.assertEqual("current", self.store.record_reconciliation(reconciliation)["status"])
        status = self.store.claim_status(claim.claim_id)
        self.assertFalse(status["recovery_required"])
        self.assertEqual("effect-state-unknown", status["reconciliation_outcome"])
        receipt = build_effect_receipt(
            claim=claim, outcome="failed", retry_safety="replay-safe", failure_category="late-result",
            failure_digest=sha("8"), finished_at="2026-08-17T15:04:00.000Z", observed_fencing_token=2,
        )
        with self.assertRaisesRegex(EffectLedgerStoreError, "late receipt"):
            self.store.record_receipt(receipt)

    def test_database_integrity_and_symlink_guard(self) -> None:
        self.assertTrue(self.store.integrity_check())
        link = Path(self.temporary.name) / "linked.sqlite"
        try:
            link.symlink_to(self.path)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(EffectLedgerStoreError, "symlink"):
            EffectLedgerStore(link)


if __name__ == "__main__":
    unittest.main()
