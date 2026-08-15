from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_execution_identity import create_agent_execution_identity  # noqa: E402
from krcn_core.execution_governance import (  # noqa: E402
    ExecutionGovernanceError,
    authorize_environment_transition,
    build_environment_promotion_plan,
    build_environment_rollback_plan,
    create_governance_plan,
    create_register_entry,
    load_execution_governance_policy,
    parse_environment_transition_plan,
    parse_governance_plan,
    parse_register_entry,
    parse_transition_authorization,
    validate_register,
)
from krcn_core.mutation_gate import ApprovalEvidence, DryRunEvidence, OwnershipResolver  # noqa: E402


def digest(character: str) -> str:
    return character * 64


class ExecutionGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_execution_governance_policy(REPO_ROOT)
        self.resolver = OwnershipResolver.from_repository(REPO_ROOT)
        self.worker = create_agent_execution_identity(
            task_id="task-one", plan_id=digest("a"), step_id="execute",
            role="worker", actor_digest=digest("b"), session_digest=digest("c"),
            assignment_digest=digest("d"), runtime_kind="native-subagent",
        )
        self.verifier = create_agent_execution_identity(
            task_id="task-one", plan_id=digest("a"), step_id="verify",
            role="verifier", actor_digest=digest("e"), session_digest=digest("f"),
            assignment_digest=digest("1"), runtime_kind="native-subagent",
        )
        self.plan = create_governance_plan(
            self.policy,
            governance_id="governance-one", project_id="project-one", task_id="task-one",
            task_plan_id=digest("a"), objective_ref="objective:quality",
            objective_digest=digest("2"), constraint_refs=["policy:bounded", "test:required"],
            created_at="2026-08-16T01:00:00Z",
        )
        self.known = self.entry(
            entry_id="known-one", kind="known", severity="low", disposition="resolved"
        )

    def entry(self, **overrides):
        values = {
            "entry_id": "entry-one", "kind": "unknown", "topic_ref": "topic:database",
            "statement_digest": digest("3"), "evidence_digest": digest("4"),
            "severity": "medium", "disposition": "open", "owner_ref": "role:analyst",
            "related_ref": "work:item-one", "recorded_at": "2026-08-16T01:01:00Z",
        }
        values.update(overrides)
        return create_register_entry(self.policy, self.plan, **values)

    def promotion(self, **overrides):
        values = {
            "transition_id": "promote-dev-test", "source_stage": "dev",
            "target_stage": "test", "source_environment_digest": digest("5"),
            "target_environment_digest": digest("6"), "artifact_digest": digest("7"),
            "test_digest": digest("8"), "verifier_evidence_digest": digest("9"),
            "rollback_digest": digest("a"),
            "worker_execution_identity": self.worker.as_dict(),
            "verifier_execution_identity": self.verifier.as_dict(),
            "provider_gate": {"required": False, "provider_ref": None,
                              "approval_ref": None, "authorization_digest": None},
            "register_entries": [self.known.as_dict()],
            "created_at": "2026-08-16T01:02:00Z",
        }
        values.update(overrides)
        return build_environment_promotion_plan(
            self.resolver, self.policy, self.plan, **values
        )

    def authorization(self, transition, *, at="2026-08-16T01:03:00Z", existing=None):
        mutation = transition.payload["mutation"]
        return authorize_environment_transition(
            self.policy, self.plan, transition, self.resolver,
            dry_run=DryRunEvidence(str(mutation["plan_id"]), True),
            approval=ApprovalEvidence(str(mutation["plan_id"]), "approval-one", True),
            observed_source_stage=str(transition.payload["source_stage"]),
            observed_source_environment_digest=str(transition.payload["source_environment_digest"]),
            authorized_at=at, existing_authorization=existing,
        )

    def assert_schema_valid(self, name: str, payload: dict) -> None:
        schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        registry = Registry()
        for dependency in ("agent-execution-identity.schema.json", "mutation-plan.schema.json"):
            resource = Resource.from_contents(
                json.loads((REPO_ROOT / "schemas" / dependency).read_text(encoding="utf-8"))
            )
            registry = registry.with_resource(str(resource.id()), resource)
        errors = list(Draft202012Validator(schema, registry=registry).iter_errors(payload))
        self.assertEqual([], errors)

    def test_policy_and_immutable_plan_are_digest_bound(self) -> None:
        self.assertFalse(self.policy.payload["grants_authority"])
        self.assertFalse(self.plan.payload["grants_authority"])
        tampered = copy.deepcopy(self.plan.as_dict())
        tampered["objective_digest"] = digest("b")
        with self.assertRaisesRegex(ExecutionGovernanceError, "digest"):
            parse_governance_plan(tampered, self.policy)
        stale_policy = copy.deepcopy(self.policy.as_dict())
        stale_policy["blocking_severities"] = ["critical"]
        with self.assertRaises(ExecutionGovernanceError):
            parse_governance_plan(self.plan.as_dict(), type(self.policy)(stale_policy))

    def test_all_register_kinds_are_contentless_and_evidence_bound(self) -> None:
        entries = [
            self.entry(entry_id="known-two", kind="known", disposition="accepted"),
            self.entry(entry_id="unknown-two", kind="unknown", disposition="open"),
            self.entry(entry_id="assumption-two", kind="assumption", disposition="accepted"),
            self.entry(entry_id="deviation-two", kind="deviation", disposition="mitigated"),
        ]
        self.assertEqual(4, len(validate_register(self.plan, [item.as_dict() for item in entries])))
        for entry in entries:
            parsed = parse_register_entry(entry.as_dict()).payload
            self.assertFalse(parsed["contains_raw_content"])
            self.assertFalse(parsed["contains_secrets"])
            self.assertFalse(parsed["contains_physical_paths"])
            self.assertNotIn("statement", parsed)
        with self.assertRaisesRegex(ExecutionGovernanceError, "disposition"):
            self.entry(entry_id="known-open", kind="known", disposition="open")
        tampered = copy.deepcopy(entries[0].as_dict())
        tampered["evidence_digest"] = digest("c")
        with self.assertRaisesRegex(ExecutionGovernanceError, "digest"):
            parse_register_entry(tampered)
        with self.assertRaisesRegex(ExecutionGovernanceError, "predate"):
            self.entry(entry_id="entry-before-plan", recorded_at="2026-08-16T00:58:00Z")

    def test_register_supersession_must_reference_an_earlier_immutable_entry(self) -> None:
        first = self.entry(entry_id="unknown-first")
        same_time = self.entry(
            entry_id="unknown-resolution", disposition="resolved",
            supersedes_entry_digest=str(first.payload["entry_digest"]),
        )
        with self.assertRaisesRegex(ExecutionGovernanceError, "forward"):
            validate_register(self.plan, [first.as_dict(), same_time.as_dict()])
        later = self.entry(
            entry_id="unknown-resolution-later", disposition="resolved",
            recorded_at="2026-08-16T01:02:00Z",
            supersedes_entry_digest=str(first.payload["entry_digest"]),
        )
        self.assertEqual(2, len(validate_register(self.plan, [first.as_dict(), later.as_dict()])))
        unrelated = self.entry(
            entry_id="unrelated-resolution", kind="known", topic_ref="topic:other",
            severity="low", disposition="resolved", owner_ref="role:other",
            recorded_at="2026-08-16T01:03:00Z",
            supersedes_entry_digest=str(first.payload["entry_digest"]),
        )
        with self.assertRaisesRegex(ExecutionGovernanceError, "lineage"):
            validate_register(self.plan, [first.as_dict(), unrelated.as_dict()])
        critical = self.entry(
            entry_id="critical-open", severity="critical", disposition="open"
        )
        downgraded = self.entry(
            entry_id="critical-downgraded", severity="low", disposition="open",
            recorded_at="2026-08-16T01:03:00Z",
            supersedes_entry_digest=str(critical.payload["entry_digest"]),
        )
        with self.assertRaisesRegex(ExecutionGovernanceError, "lower severity"):
            validate_register(self.plan, [critical.as_dict(), downgraded.as_dict()])

    def test_open_high_unknown_or_deviation_blocks_promotion(self) -> None:
        blocking = self.entry(
            entry_id="unknown-critical", kind="unknown", severity="critical",
            disposition="open",
        )
        with self.assertRaisesRegex(ExecutionGovernanceError, "block"):
            self.promotion(register_entries=[blocking.as_dict()])
        resolved = self.entry(
            entry_id="unknown-resolved", kind="unknown", severity="critical",
            disposition="resolved",
        )
        self.assertEqual("test", self.promotion(register_entries=[resolved.as_dict()]).payload["target_stage"])
        future_resolution = self.entry(
            entry_id="unknown-future-resolution", kind="unknown",
            severity="critical", disposition="resolved",
            recorded_at="2026-08-16T03:00:00Z",
        )
        with self.assertRaisesRegex(ExecutionGovernanceError, "future register"):
            self.promotion(register_entries=[future_resolution.as_dict()])

    def test_promotions_cannot_skip_stages_or_enter_production_directly(self) -> None:
        with self.assertRaisesRegex(ExecutionGovernanceError, "predate"):
            self.promotion(created_at="2026-08-16T00:59:00Z")
        with self.assertRaisesRegex(ExecutionGovernanceError, "adjacent"):
            self.promotion(target_stage="pilot")
        with self.assertRaisesRegex(ExecutionGovernanceError, "adjacent"):
            self.promotion(source_stage="dev", target_stage="production")
        with self.assertRaisesRegex(ExecutionGovernanceError, "digests"):
            self.promotion(target_environment_digest=digest("5"))
        with self.assertRaisesRegex(ExecutionGovernanceError, "predecessor"):
            self.promotion(
                transition_id="promote-pilot-production", source_stage="pilot",
                target_stage="production",
            )

    def test_worker_and_verifier_must_be_independent(self) -> None:
        nonindependent = create_agent_execution_identity(
            task_id="task-one", plan_id=digest("a"), step_id="verify",
            role="verifier", actor_digest=digest("b"), session_digest=digest("f"),
            assignment_digest=digest("d"), runtime_kind="native-subagent",
        )
        with self.assertRaisesRegex(ExecutionGovernanceError, "independent"):
            self.promotion(verifier_execution_identity=nonindependent.as_dict())

    def test_provider_use_requires_existing_logical_approval_binding(self) -> None:
        with self.assertRaisesRegex(ExecutionGovernanceError, "provider"):
            self.promotion(provider_gate={"required": True, "provider_ref": "provider:remote",
                "approval_ref": None, "authorization_digest": None})
        with self.assertRaisesRegex(ExecutionGovernanceError, "typed provider"):
            self.promotion(provider_gate={"required": True,
                "provider_ref": "provider:remote", "approval_ref": "approval:session-one",
                "authorization_digest": digest("b")})

    def test_exact_mutation_approval_and_fresh_source_are_required(self) -> None:
        transition = self.promotion()
        mutation = transition.payload["mutation"]
        with self.assertRaisesRegex(ExecutionGovernanceError, "authorization"):
            authorize_environment_transition(
                self.policy, self.plan, transition, self.resolver,
                dry_run=DryRunEvidence(str(mutation["plan_id"]), True), approval=None,
                observed_source_stage="dev", observed_source_environment_digest=digest("5"),
                authorized_at="2026-08-16T01:03:00Z",
            )
        with self.assertRaisesRegex(ExecutionGovernanceError, "stale"):
            authorize_environment_transition(
                self.policy, self.plan, transition, self.resolver,
                dry_run=DryRunEvidence(str(mutation["plan_id"]), True),
                approval=ApprovalEvidence(str(mutation["plan_id"]), "approval-one", True),
                observed_source_stage="dev", observed_source_environment_digest=digest("c"),
                authorized_at="2026-08-16T01:03:00Z",
            )
        authorized = self.authorization(transition)
        self.assertTrue(authorized.payload["does_not_execute"])
        self.assertFalse(authorized.payload["grants_implicit_authority"])
        with self.assertRaisesRegex(ExecutionGovernanceError, "predate"):
            self.authorization(transition, at="2026-08-16T00:00:00Z")

    def test_transition_and_authorization_tampering_fail_closed_and_replay_is_idempotent(self) -> None:
        transition = self.promotion()
        tampered = copy.deepcopy(transition.as_dict())
        tampered["artifact_digest"] = digest("c")
        with self.assertRaises(ExecutionGovernanceError):
            parse_environment_transition_plan(tampered, self.policy, self.plan, self.resolver)
        authorized = self.authorization(transition)
        replay = self.authorization(transition, existing=authorized.as_dict())
        self.assertEqual(authorized.as_dict(), replay.as_dict())
        with self.assertRaisesRegex(ExecutionGovernanceError, "idempotent"):
            self.authorization(
                transition, at="2026-08-16T01:04:00Z", existing=authorized.as_dict()
            )
        damaged = copy.deepcopy(authorized.as_dict())
        damaged["authorized_at"] = "2026-08-16T01:04:00Z"
        with self.assertRaisesRegex(ExecutionGovernanceError, "digest"):
            parse_transition_authorization(damaged)

    def test_rollback_is_adjacent_exact_and_bound_to_authorized_promotion(self) -> None:
        promotion = self.promotion()
        authorized = self.authorization(promotion)
        rollback = build_environment_rollback_plan(
            self.resolver, self.policy, self.plan, promotion, authorized,
            observed_environment_digest=digest("6"), transition_id="rollback-test-dev",
            artifact_digest=digest("7"), test_digest=digest("d"),
            verifier_evidence_digest=digest("e"), rollback_digest=digest("f"),
            worker_execution_identity=self.worker.as_dict(),
            verifier_execution_identity=self.verifier.as_dict(),
            provider_gate={"required": False, "provider_ref": None,
                           "approval_ref": None, "authorization_digest": None},
            register_entries=[self.known.as_dict()], created_at="2026-08-16T01:05:00Z",
        )
        self.assertEqual(("rollback", "test", "dev"),
                         (rollback.payload["transition_kind"], rollback.payload["source_stage"], rollback.payload["target_stage"]))
        self.assertEqual(promotion.payload["transition_digest"], rollback.payload["rollback_of_transition_digest"])
        with self.assertRaisesRegex(ExecutionGovernanceError, "stale"):
            build_environment_rollback_plan(
                self.resolver, self.policy, self.plan, promotion, authorized,
                observed_environment_digest=digest("c"), transition_id="rollback-stale",
                artifact_digest=digest("7"), test_digest=digest("d"),
                verifier_evidence_digest=digest("e"), rollback_digest=digest("f"),
                worker_execution_identity=self.worker.as_dict(),
                verifier_execution_identity=self.verifier.as_dict(),
                provider_gate={"required": False, "provider_ref": None,
                               "approval_ref": None, "authorization_digest": None},
                register_entries=[self.known.as_dict()], created_at="2026-08-16T01:05:00Z",
            )

    def test_public_records_are_strict_schema_valid(self) -> None:
        transition = self.promotion()
        authorization = self.authorization(transition)
        records = {
            "execution-governance-policy.schema.json": self.policy.as_dict(),
            "execution-governance-plan.schema.json": self.plan.as_dict(),
            "execution-governance-entry.schema.json": self.known.as_dict(),
            "execution-environment-transition-plan.schema.json": transition.as_dict(),
            "execution-environment-transition-authorization.schema.json": authorization.as_dict(),
        }
        for name, payload in records.items():
            with self.subTest(schema=name):
                self.assert_schema_valid(name, payload)


if __name__ == "__main__":
    unittest.main()
