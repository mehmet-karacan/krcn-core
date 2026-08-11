from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.information_records import parse_information_record, payload_digest  # noqa: E402
from krcn_core.local_store import LocalStoreError, LocalWorkspaceStore  # noqa: E402
from krcn_core.memory_gate import (  # noqa: E402
    MemoryGateError,
    apply_memory_lifecycle,
    apply_memory_persistence,
    memory_action_digest,
    memory_candidate_digest,
    memory_review_digest,
    parse_memory_action,
    parse_memory_candidate,
    parse_memory_review,
    prepare_memory_lifecycle,
    prepare_memory_persistence,
    prepare_policy_promotion,
)
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.policies import parse_user_policy  # noqa: E402


def proposed_memory(*, revision: int = 1, provenance_kind: str = "source-derived"):
    content = {
        "memory_type": "preference",
        "title": "Database access preference",
        "text": "Use read-only database access",
        "scope_ref": "project:sample-project",
        "retention_purpose": "Preserve an explicit operating preference",
        "sensitivity": "non-sensitive",
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": "database-access-memory",
            "information_class": "memory",
            "ownership": "user-data",
            "subject_ref": "memory:database-access-memory",
            "revision": revision,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": provenance_kind,
                "evidence": [
                    {
                        "source_ref": "source:sample-project",
                        "revision_id": "rev-1",
                        "digest": "a" * 64,
                        "relation": "supports",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )


def memory_candidate(*, origin: str = "conversation-summary", conflicts=()):
    proposed = proposed_memory()
    conflict_refs = tuple(sorted(conflicts))
    digest = memory_candidate_digest(
        "database-access-candidate",
        origin,
        proposed,
        conflict_refs,
        False,
    )
    return parse_memory_candidate(
        {
            "schema_ref": "schemas/memory-candidate.schema.json",
            "schema_version": 1,
            "candidate_id": "database-access-candidate",
            "origin": origin,
            "proposed_memory": proposed.as_payload(),
            "conflict_refs": list(conflict_refs),
            "policy_promotion": False,
            "candidate_digest": digest,
        }
    )


def memory_review(
    candidate,
    *,
    outcome: str = "approved",
    reviewed_by: str = "user",
    conflicts=None,
):
    acknowledged = tuple(
        sorted(candidate.conflict_refs if conflicts is None else conflicts)
    )
    approval_id = "synthetic-memory-approval" if outcome == "approved" else None
    digest = memory_review_digest(
        "database-access-review",
        candidate.candidate_id,
        candidate.candidate_digest,
        outcome,
        reviewed_by,
        "memory-session-1",
        approval_id,
        acknowledged,
    )
    return parse_memory_review(
        {
            "schema_ref": "schemas/memory-review.schema.json",
            "schema_version": 1,
            "review_id": "database-access-review",
            "candidate_id": candidate.candidate_id,
            "candidate_digest": candidate.candidate_digest,
            "outcome": outcome,
            "reviewed_by": reviewed_by,
            "session_id": "memory-session-1",
            "approval_id": approval_id,
            "acknowledged_conflict_refs": list(acknowledged),
            "review_digest": digest,
        }
    )


def memory_action(record, *, action: str, replacement_ref: str | None = None):
    digest = memory_action_digest(
        "database-access-action",
        action,
        record.record_id,
        record.revision,
        record.content_digest,
        replacement_ref,
        "memory-session-2",
        "synthetic-action-approval",
        True,
    )
    return parse_memory_action(
        {
            "schema_ref": "schemas/memory-action.schema.json",
            "schema_version": 1,
            "action_id": "database-access-action",
            "action": action,
            "memory_id": record.record_id,
            "expected_revision": record.revision,
            "expected_content_digest": record.content_digest,
            "replacement_ref": replacement_ref,
            "session_id": "memory-session-2",
            "approval_id": "synthetic-action-approval",
            "approved": True,
            "action_digest": digest,
        }
    )


def database_policy(*, revision: int, delete_effect: str, provenance: str, evidence_ref=None):
    def rule(rule_id, operation, effect):
        provenance_payload = {"kind": provenance}
        if evidence_ref is not None:
            provenance_payload["evidence_ref"] = evidence_ref
        return {
            "rule_id": rule_id,
            "resource_type": "database",
            "operations": [operation],
            "effect": effect,
            "constraints": {},
            "provenance": provenance_payload,
            "active": True,
        }

    return {
        "schema_version": 1,
        "policy_id": "database-read-only",
        "scope": {"kind": "integration", "ref": "sample-database"},
        "revision": revision,
        "rules": [
            rule("allow-select", "select", "allow"),
            rule("control-delete", "delete", delete_effect),
        ],
    }


class MemoryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(Path(self.temporary.name), self.ownership)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def authorize(write_plan):
        mutation = write_plan.mutation
        return authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                mutation.plan_id,
                "synthetic-mutation-approval",
                approved=True,
            ),
        )

    def persist(self):
        candidate = memory_candidate()
        review = memory_review(candidate)
        plan = prepare_memory_persistence(
            self.store,
            candidate,
            review,
            expected_revision=0,
        )
        stored = apply_memory_persistence(
            self.store,
            plan,
            candidate,
            review,
            self.authorize(plan.write_plan),
        )
        return plan.memory_record, stored

    def test_conversation_summary_cannot_persist_without_user_approval(self) -> None:
        candidate = memory_candidate(origin="conversation-summary")
        review = memory_review(
            candidate,
            outcome="needs-changes",
            reviewed_by="delegate",
        )
        with self.assertRaisesRegex(MemoryGateError, "not approved"):
            prepare_memory_persistence(
                self.store,
                candidate,
                review,
                expected_revision=0,
            )

    def test_approved_candidate_still_uses_exact_user_data_mutation_gate(self) -> None:
        candidate = memory_candidate()
        review = memory_review(candidate)
        plan = prepare_memory_persistence(
            self.store,
            candidate,
            review,
            expected_revision=0,
        )
        self.assertEqual("user-data", plan.write_plan.mutation.ownership)
        self.assertTrue(plan.write_plan.mutation.approval_required)
        stored = apply_memory_persistence(
            self.store,
            plan,
            candidate,
            review,
            self.authorize(plan.write_plan),
        )
        parsed = parse_information_record(dict(stored.payload))
        self.assertEqual("approved-memory", parsed.provenance.kind)
        self.assertEqual("current", parsed.lifecycle)

    def test_rejected_candidate_and_unreviewed_conflict_cannot_persist(self) -> None:
        candidate = memory_candidate(conflicts=("source:sample-project",))
        rejected = memory_review(candidate, outcome="rejected")
        with self.assertRaisesRegex(MemoryGateError, "not approved"):
            prepare_memory_persistence(
                self.store,
                candidate,
                rejected,
                expected_revision=0,
            )
        mismatch = memory_review(candidate, conflicts=())
        with self.assertRaisesRegex(MemoryGateError, "not reviewed exactly"):
            prepare_memory_persistence(
                self.store,
                candidate,
                mismatch,
                expected_revision=0,
            )

    def test_memory_cannot_override_active_policy_even_after_review(self) -> None:
        candidate = memory_candidate(conflicts=("policy:database-read-only",))
        review = memory_review(candidate)
        with self.assertRaisesRegex(MemoryGateError, "cannot override"):
            prepare_memory_persistence(
                self.store,
                candidate,
                review,
                expected_revision=0,
            )

    def test_candidate_and_review_digest_tampering_is_rejected(self) -> None:
        candidate_payload = memory_candidate().as_payload()
        candidate_payload["origin"] = "inference"
        with self.assertRaisesRegex(MemoryGateError, "does not match"):
            parse_memory_candidate(candidate_payload)
        candidate = memory_candidate()
        review_payload = memory_review(candidate).as_payload()
        review_payload["session_id"] = "another-session"
        with self.assertRaisesRegex(MemoryGateError, "does not match"):
            parse_memory_review(review_payload)

    def test_revoke_is_a_separate_approved_lifecycle_update(self) -> None:
        current, _ = self.persist()
        revoke = memory_action(current, action="revoke")
        revoke_plan = prepare_memory_lifecycle(self.store, revoke)
        revoked = apply_memory_lifecycle(
            self.store,
            revoke_plan,
            revoke,
            self.authorize(revoke_plan.write_plan),
        )
        self.assertEqual("archived", revoked.payload["lifecycle"])
        self.assertEqual(2, revoked.revision)

    def test_supersede_preserves_the_replacement_reference_as_evidence(self) -> None:
        current, _ = self.persist()
        action = memory_action(
            current,
            action="supersede",
            replacement_ref="memory:replacement-memory",
        )
        plan = prepare_memory_lifecycle(self.store, action)
        superseded = apply_memory_lifecycle(
            self.store,
            plan,
            action,
            self.authorize(plan.write_plan),
        )
        record = parse_information_record(dict(superseded.payload))
        self.assertEqual("superseded", record.lifecycle)
        self.assertIn(
            "memory:replacement-memory",
            [item.source_ref for item in record.provenance.evidence],
        )

    def test_stale_or_malformed_lifecycle_action_is_rejected(self) -> None:
        current, _ = self.persist()
        stale_payload = memory_action(current, action="revoke").as_payload()
        stale_payload["expected_revision"] = 2
        stale_payload["action_digest"] = memory_action_digest(
            stale_payload["action_id"],
            stale_payload["action"],
            stale_payload["memory_id"],
            2,
            stale_payload["expected_content_digest"],
            None,
            stale_payload["session_id"],
            stale_payload["approval_id"],
            True,
        )
        stale = parse_memory_action(stale_payload)
        with self.assertRaisesRegex(MemoryGateError, "stale revision"):
            prepare_memory_lifecycle(self.store, stale)

        invalid = memory_action(current, action="supersede", replacement_ref="memory:new")
        invalid_payload = invalid.as_payload()
        invalid_payload["approved"] = False
        with self.assertRaisesRegex(MemoryGateError, "explicit approval"):
            parse_memory_action(invalid_payload)

    def test_direct_store_cannot_bypass_memory_payload_validation(self) -> None:
        record = proposed_memory()
        payload = record.as_payload()
        content = dict(payload["payload"])
        content["unexpected"] = "value"
        payload["payload"] = content
        payload["content_digest"] = payload_digest(content)
        with self.assertRaisesRegex(LocalStoreError, "memory payload fields"):
            self.store.prepare_put(
                "memory",
                record.record_id,
                payload,
                expected_revision=0,
            )

    def test_policy_promotion_is_separate_and_cannot_weaken_delete_deny(self) -> None:
        memory, _ = self.persist()
        existing = parse_user_policy(
            database_policy(
                revision=1,
                delete_effect="deny",
                provenance="explicit-user",
            )
        )
        unsafe = database_policy(
            revision=2,
            delete_effect="allow",
            provenance="approved-memory",
            evidence_ref="memory:database-access-memory",
        )
        with self.assertRaisesRegex(MemoryGateError, "weaken"):
            prepare_policy_promotion(
                memory,
                unsafe,
                self.ownership,
                existing_policy=existing,
            )

        safe = database_policy(
            revision=2,
            delete_effect="deny",
            provenance="approved-memory",
            evidence_ref="memory:database-access-memory",
        )
        plan = prepare_policy_promotion(
            memory,
            safe,
            self.ownership,
            existing_policy=existing,
        )
        self.assertEqual("user-data", plan.mutation.ownership)
        self.assertTrue(plan.mutation.approval_required)
        self.assertEqual(
            ".krcn/policies/database-read-only.json",
            plan.mutation.target_ref,
        )
        self.assertEqual(
            "schemas/policy-promotion-plan.schema.json",
            plan.public_summary()["schema_ref"],
        )


if __name__ == "__main__":
    unittest.main()
