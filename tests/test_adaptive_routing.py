from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.adaptive_routing import (  # noqa: E402
    AdaptiveRoutingError,
    compare_shadow_route,
    create_route_request,
    decide_route,
    load_adaptive_routing_policy,
    parse_route_decision,
    parse_route_request,
    parse_shadow_route_comparison,
)


def digest(character: str) -> str:
    return character * 64


class AdaptiveRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_adaptive_routing_policy(REPO_ROOT)

    def request(self, **overrides):
        values = {
            "request_id": "request-one",
            "correlation_id": "correlation-one",
            "client_id": "codex-desktop",
            "project_id": "project-one",
            "work_item_id": "work-one",
            "source_revision_digest": digest("a"),
            "intent_digest": digest("b"),
            "context_digest": digest("c"),
            "task_type": "analysis",
            "risk_level": "low",
            "mutation_level": "none",
            "data_classification": "internal",
            "estimated_work_units": 2,
            "context_size_tokens": 8000,
            "context_pressure_millis": 10,
            "independent_subproblem_count": 1,
            "dependency_depth": 0,
            "required_capabilities": ["source-read"],
            "available_capabilities": ["source-read"],
            "deterministic_validator_available": True,
            "verifier_available": True,
            "sandbox_available": True,
            "resources": [
                {
                    "node_id": "analysis-step",
                    "resource_ref": "path:project-one/src",
                    "access": "read",
                }
            ],
            "approval_required": False,
            "approval_verified": False,
            "pending_claim_without_receipt": False,
            "input_tokens": 12000,
            "output_tokens": 4000,
            "cost_microunits": 1000,
            "latency_seconds": 120,
            "maximum_concurrency": 2,
            "remote_required": False,
            "provider_assurance_available": False,
            "source_revision_current": True,
            "authoritative_context_required": True,
        }
        values.update(overrides)
        return create_route_request(self.policy, **values)

    def route(self, **overrides):
        return decide_route(self.policy, self.request(**overrides))

    def assert_schema(self, name: str, payload: dict[str, object]) -> None:
        schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(payload))
        self.assertEqual([], errors)

    def test_policy_request_and_decision_are_deterministic_and_authority_free(self) -> None:
        first_request = self.request()
        second_request = self.request()
        self.assertEqual(first_request.request_digest, second_request.request_digest)
        first = decide_route(self.policy, first_request)
        second = decide_route(self.policy, second_request)
        self.assertEqual(first.decision_digest, second.decision_digest)
        self.assertEqual("single-worker", first.route_mode)
        self.assertFalse(first.payload["grants_authority"])
        self.assertFalse(first.payload["enforcement_applied"])
        self.assertIsNone(first.payload["delegation_decision_id"])
        self.assertEqual([], first.payload["model_assignment_ids"])
        self.assertIsNone(first.payload["admission_decision_id"])
        self.assert_schema("route-request.schema.json", first_request.as_dict())
        self.assert_schema("route-decision.schema.json", first.as_dict())

    def test_coordinator_and_direct_read_routes_are_distinct(self) -> None:
        status = self.route(task_type="status", estimated_work_units=0, context_size_tokens=0)
        self.assertEqual("coordinator-response", status.route_mode)
        direct = self.route(
            estimated_work_units=1,
            context_size_tokens=3000,
            authoritative_context_required=False,
            project_id=None,
            work_item_id=None,
            source_revision_digest=None,
        )
        self.assertEqual("direct-read", direct.route_mode)

    def test_independent_disjoint_work_routes_parallel(self) -> None:
        route = self.route(
            estimated_work_units=4,
            independent_subproblem_count=2,
            maximum_concurrency=4,
            resources=[
                {
                    "node_id": "inspect-code",
                    "resource_ref": "path:project-one/src",
                    "access": "read",
                },
                {
                    "node_id": "inspect-tests",
                    "resource_ref": "path:project-one/tests",
                    "access": "read",
                },
            ],
        )
        self.assertEqual("parallel-dag", route.route_mode)
        self.assertEqual(2, route.payload["selected"]["maximum_concurrency"])

    def test_resource_conflict_or_dependency_routes_sequential(self) -> None:
        conflict = self.route(
            mutation_level="core",
            approval_required=True,
            approval_verified=True,
            independent_subproblem_count=2,
            resources=[
                {
                    "node_id": "worker-one",
                    "resource_ref": "path:project-one/src/module.py",
                    "access": "write",
                },
                {
                    "node_id": "worker-two",
                    "resource_ref": "path:project-one/src/module.py",
                    "access": "read",
                },
            ],
        )
        self.assertEqual("sequential-dag", conflict.route_mode)
        self.assertTrue(conflict.payload["resource_conflict_observed"])
        parent_child = self.route(
            mutation_level="core",
            approval_required=True,
            approval_verified=True,
            independent_subproblem_count=2,
            resources=[
                {
                    "node_id": "worker-one",
                    "resource_ref": "path:project-one/src",
                    "access": "write",
                },
                {
                    "node_id": "worker-two",
                    "resource_ref": "path:project-one/src/module.py",
                    "access": "read",
                },
            ],
        )
        self.assertEqual("sequential-dag", parent_child.route_mode)
        dependency = self.route(dependency_depth=2, independent_subproblem_count=3)
        self.assertEqual("sequential-dag", dependency.route_mode)

    def test_recovery_classification_and_nondeterministic_read_do_not_route_direct(self) -> None:
        recovery = self.route(task_type="recovery")
        self.assertEqual("recovery-required", recovery.route_mode)
        nondeterministic = self.route(
            estimated_work_units=1,
            context_size_tokens=3000,
            deterministic_validator_available=False,
        )
        self.assertEqual("single-worker", nondeterministic.route_mode)

    def test_approval_is_review_only_and_never_authority(self) -> None:
        route = self.route(
            mutation_level="core",
            approval_required=True,
            approval_verified=False,
        )
        self.assertEqual("review-only", route.route_mode)
        self.assertEqual(["approval-required"], route.payload["reason_codes"])
        self.assertFalse(route.payload["grants_authority"])

    def test_pending_claim_requires_reconciliation(self) -> None:
        route = self.route(pending_claim_without_receipt=True)
        self.assertEqual("recovery-required", route.route_mode)
        self.assertEqual(
            ["effect-reconciliation-required"], route.payload["reason_codes"]
        )

    def test_capability_secret_provider_and_budget_gates_fail_closed(self) -> None:
        missing = self.route(available_capabilities=[])
        self.assertEqual("blocked", missing.route_mode)
        self.assertEqual(["capability-missing"], missing.payload["reason_codes"])
        secret = self.route(
            data_classification="secret",
            remote_required=True,
            provider_assurance_available=True,
        )
        self.assertEqual(["secret-remote-denied"], secret.payload["reason_codes"])
        assurance = self.route(remote_required=True, provider_assurance_available=False)
        self.assertEqual(
            ["provider-assurance-required"], assurance.payload["reason_codes"]
        )
        exhausted = self.route(cost_microunits=0)
        self.assertEqual(["budget-exhausted"], exhausted.payload["reason_codes"])

    def test_mutation_sandbox_high_risk_verifier_context_and_stale_gates(self) -> None:
        sandbox = self.route(
            mutation_level="core",
            approval_required=True,
            approval_verified=True,
            sandbox_available=False,
        )
        self.assertEqual(["sandbox-required"], sandbox.payload["reason_codes"])
        verifier = self.route(risk_level="high", verifier_available=False)
        self.assertEqual(
            ["independent-verifier-required"], verifier.payload["reason_codes"]
        )
        context = self.route(project_id=None, work_item_id=None)
        self.assertEqual(["work-context-required"], context.payload["reason_codes"])
        stale = self.route(source_revision_current=False)
        self.assertEqual(["source-revision-stale"], stale.payload["reason_codes"])

    def test_shadow_comparison_never_changes_observed_behavior(self) -> None:
        decision = self.route(independent_subproblem_count=2)
        matched = compare_shadow_route(
            self.policy, decision, observed_route="delegated-dag"
        )
        self.assertEqual("matched", matched.payload["comparison_status"])
        self.assertFalse(matched.payload["behavior_changed"])
        mismatch = compare_shadow_route(
            self.policy, decision, observed_route="coordinator-response"
        )
        self.assertEqual("mismatch", mismatch.payload["comparison_status"])
        self.assertFalse(mismatch.payload["grants_authority"])
        self.assert_schema("route-shadow-comparison.schema.json", matched.as_dict())

    def test_tampering_unknown_fields_and_noncanonical_inputs_are_rejected(self) -> None:
        request = self.request()
        unknown = request.as_dict()
        unknown["raw_prompt"] = "do work"
        with self.assertRaisesRegex(AdaptiveRoutingError, "fields"):
            parse_route_request(unknown, self.policy)
        tampered = decide_route(self.policy, request).as_dict()
        tampered["selected"]["route_mode"] = "parallel-dag"
        with self.assertRaises(AdaptiveRoutingError):
            parse_route_decision(tampered, self.policy, request=request)
        comparison = compare_shadow_route(
            self.policy, decide_route(self.policy, request), observed_route="delegated-dag"
        ).as_dict()
        comparison["behavior_changed"] = True
        with self.assertRaisesRegex(AdaptiveRoutingError, "invalid"):
            parse_shadow_route_comparison(comparison)
        noncanonical = request.as_dict()
        noncanonical["capabilities"]["available"] = ["source-read", "aaa"]
        noncanonical["request_digest"] = digest("d")
        with self.assertRaises(AdaptiveRoutingError):
            parse_route_request(noncanonical, self.policy)

    def test_policy_tampering_is_rejected(self) -> None:
        unsafe = copy.deepcopy(self.policy.as_dict())
        unsafe["invariants"]["enforcement_enabled"] = True
        from krcn_core.adaptive_routing import parse_adaptive_routing_policy

        with self.assertRaisesRegex(AdaptiveRoutingError, "unsafe"):
            parse_adaptive_routing_policy(unsafe)

    def test_golden_route_set_is_schema_valid_and_matches_policy(self) -> None:
        golden = json.loads(
            (REPO_ROOT / "config" / "adaptive-routing-golden-set.json").read_text(
                encoding="utf-8"
            )
        )
        self.assert_schema("adaptive-routing-golden-set.schema.json", golden)
        self.assertEqual(self.policy.payload["revision"], golden["policy_revision"])
        observed: set[str] = set()
        for case in golden["cases"]:
            with self.subTest(case=case["case_id"]):
                decision = self.route(**case["overrides"])
                self.assertEqual(case["expected_route"], decision.route_mode)
                self.assertIn(case["expected_reason"], decision.payload["reason_codes"])
                observed.add(case["case_id"])
        self.assertEqual(len(golden["cases"]), len(observed))


if __name__ == "__main__":
    unittest.main()
