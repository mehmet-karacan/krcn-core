from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.model_capability_gate import (  # noqa: E402
    ModelCapabilityGateError,
    evaluate_model_capability,
    load_model_capability_golden_set,
    load_model_capability_policy,
    parse_model_capability_evaluation,
    parse_model_capability_golden_set,
    parse_model_capability_policy,
)


def measurement(
    token: str,
    *,
    success: bool = True,
    verifier: bool = True,
    score: int = 9000,
    input_tokens: int = 100,
    output_tokens: int = 50,
    latency_ms: int = 1000,
    agent_calls: int = 1,
    human_interventions: int = 0,
    violations: list[str] | None = None,
) -> dict[str, object]:
    return {
        "execution_digest": token * 64,
        "task_success": success,
        "verifier_pass": verifier,
        "score_basis_points": score,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "agent_call_count": agent_calls,
        "human_intervention_count": human_interventions,
        "hard_constraint_violations": violations or [],
    }


class ModelCapabilityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy_payload = json.loads(
            (REPO_ROOT / "config" / "model-capability-preservation.json").read_text(
                encoding="utf-8"
            )
        )
        self.golden_payload = json.loads(
            (REPO_ROOT / "config" / "model-capability-golden-set.json").read_text(
                encoding="utf-8"
            )
        )
        self.policy = load_model_capability_policy(REPO_ROOT)
        self.golden = load_model_capability_golden_set(REPO_ROOT, self.policy)
        self.baseline = {
            case.case_id: measurement(token)
            for case, token in zip(self.golden.cases, "12345")
        }
        self.enabled = {
            case.case_id: measurement(token)
            for case, token in zip(self.golden.cases, "abcde")
        }

    def enabled_token(self, case_id: str) -> str:
        return str(self.enabled[case_id]["execution_digest"])[0]

    def test_policy_and_golden_set_match_their_public_schemas(self) -> None:
        pairs = (
            (
                "model-capability-preservation-policy.schema.json",
                self.policy_payload,
            ),
            ("model-capability-golden-set.schema.json", self.golden_payload),
        )
        for schema_name, payload in pairs:
            with self.subTest(schema=schema_name):
                schema = json.loads(
                    (REPO_ROOT / "schemas" / schema_name).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    [],
                    list(Draft202012Validator(schema).iter_errors(payload)),
                )

    def test_policy_freezes_hard_and_soft_boundaries(self) -> None:
        self.assertIn("authority-boundary", self.policy.hard_constraints)
        self.assertIn("solution-method", self.policy.soft_guidance)
        self.assertEqual(
            200,
            self.policy.thresholds[
                "maximum_general_success_regression_basis_points"
            ],
        )

        weakened = copy.deepcopy(self.policy_payload)
        weakened["hard_constraints"].remove("authority-boundary")
        with self.assertRaisesRegex(ModelCapabilityGateError, "coverage"):
            parse_model_capability_policy(weakened)

        relaxed = copy.deepcopy(self.policy_payload)
        relaxed["thresholds"][
            "maximum_general_success_regression_basis_points"
        ] = 201
        with self.assertRaisesRegex(ModelCapabilityGateError, "weaken"):
            parse_model_capability_policy(relaxed)

    def test_golden_set_has_full_rule_coverage_without_prompt_content(self) -> None:
        hard = set().union(*(set(case.hard_constraint_refs) for case in self.golden.cases))
        soft = set().union(*(set(case.soft_guidance_refs) for case in self.golden.cases))
        self.assertEqual(set(self.policy.hard_constraints), hard)
        self.assertEqual(set(self.policy.soft_guidance), soft)

        tampered = copy.deepcopy(self.golden_payload)
        tampered["cases"][0]["prompt"] = "raw task prompt"
        with self.assertRaisesRegex(ModelCapabilityGateError, "fields"):
            parse_model_capability_golden_set(tampered, self.policy)

    def test_equal_capability_passes_and_round_trips(self) -> None:
        evaluation = evaluate_model_capability(
            self.policy,
            self.golden,
            self.baseline,
            self.enabled,
        )
        payload = evaluation.as_dict()

        self.assertEqual("passed", evaluation.status)
        self.assertEqual([], payload["blocking_reasons"])
        self.assertFalse(payload["invariants"]["raw_prompt_included"])
        self.assertFalse(payload["invariants"]["private_chain_of_thought_included"])
        schema = json.loads(
            (
                REPO_ROOT / "schemas" / "model-capability-evaluation.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [],
            list(Draft202012Validator(schema).iter_errors(payload)),
        )
        parsed = parse_model_capability_evaluation(
            payload, self.policy, self.golden
        )
        self.assertEqual(evaluation.evaluation_id, parsed.evaluation_id)

    def test_general_success_regression_over_two_points_blocks(self) -> None:
        case_id = next(case.case_id for case in self.golden.cases if not case.critical)
        self.enabled[case_id] = measurement(
            self.enabled_token(case_id), success=False
        )
        evaluation = evaluate_model_capability(
            self.policy, self.golden, self.baseline, self.enabled
        )

        self.assertEqual("blocked", evaluation.status)
        self.assertIn("general-success-regression", evaluation.blocking_reasons)
        self.assertEqual(-2000, evaluation.aggregate["success_delta_basis_points"])

    def test_any_critical_score_regression_blocks(self) -> None:
        case_id = next(case.case_id for case in self.golden.cases if case.critical)
        self.enabled[case_id] = measurement(
            self.enabled_token(case_id), score=8999
        )
        evaluation = evaluate_model_capability(
            self.policy, self.golden, self.baseline, self.enabled
        )

        self.assertEqual("blocked", evaluation.status)
        self.assertIn("critical-regression", evaluation.blocking_reasons)
        self.assertEqual(1, evaluation.aggregate["critical_regression_count"])

    def test_hard_constraint_violation_always_blocks(self) -> None:
        case = next(
            item
            for item in self.golden.cases
            if "authority-boundary" in item.hard_constraint_refs
        )
        self.enabled[case.case_id] = measurement(
            self.enabled_token(case.case_id), violations=["authority-boundary"]
        )
        evaluation = evaluate_model_capability(
            self.policy, self.golden, self.baseline, self.enabled
        )

        self.assertEqual("blocked", evaluation.status)
        self.assertIn("hard-constraint-violation", evaluation.blocking_reasons)
        self.assertEqual(1, evaluation.aggregate["hard_constraint_violation_count"])

    def test_cost_overhead_is_visible_but_does_not_weaken_capability_gate(self) -> None:
        self.enabled = {
            case.case_id: measurement(
                token,
                input_tokens=300,
                output_tokens=150,
                latency_ms=2000,
                agent_calls=3,
                human_interventions=1,
            )
            for case, token in zip(self.golden.cases, "abcde")
        }
        evaluation = evaluate_model_capability(
            self.policy, self.golden, self.baseline, self.enabled
        )

        self.assertEqual("passed", evaluation.status)
        self.assertEqual(
            (
                "agent-call-overhead",
                "human-intervention-overhead",
                "latency-overhead",
                "token-overhead",
            ),
            evaluation.advisories,
        )

    def test_missing_case_invalid_measurement_and_unknown_violation_fail_closed(self) -> None:
        self.enabled.pop(next(iter(self.enabled)))
        with self.assertRaisesRegex(ModelCapabilityGateError, "exact golden set"):
            evaluate_model_capability(
                self.policy, self.golden, self.baseline, self.enabled
            )

        self.enabled = {
            case.case_id: measurement(token)
            for case, token in zip(self.golden.cases, "abcde")
        }
        first = self.golden.cases[0]
        self.enabled[first.case_id]["score_basis_points"] = True
        with self.assertRaisesRegex(ModelCapabilityGateError, "score"):
            evaluate_model_capability(
                self.policy, self.golden, self.baseline, self.enabled
            )

        self.enabled[first.case_id] = measurement(
            self.enabled_token(first.case_id), violations=["authority-boundary"]
        )
        with self.assertRaisesRegex(ModelCapabilityGateError, "outside"):
            evaluate_model_capability(
                self.policy, self.golden, self.baseline, self.enabled
            )

    def test_tampered_aggregate_or_raw_field_is_rejected(self) -> None:
        payload = evaluate_model_capability(
            self.policy, self.golden, self.baseline, self.enabled
        ).as_dict()
        payload["aggregate"]["enabled_success_count"] = 0
        with self.assertRaisesRegex(ModelCapabilityGateError, "digest"):
            parse_model_capability_evaluation(payload, self.policy, self.golden)

        payload = evaluate_model_capability(
            self.policy, self.golden, self.baseline, self.enabled
        ).as_dict()
        payload["raw_output"] = "not allowed"
        with self.assertRaisesRegex(ModelCapabilityGateError, "fields"):
            parse_model_capability_evaluation(payload, self.policy, self.golden)

    def test_reused_execution_evidence_cannot_stand_in_for_an_ab_run(self) -> None:
        first, second = self.golden.cases[:2]
        self.enabled[second.case_id]["execution_digest"] = self.enabled[
            first.case_id
        ]["execution_digest"]
        with self.assertRaisesRegex(ModelCapabilityGateError, "distinct"):
            evaluate_model_capability(
                self.policy, self.golden, self.baseline, self.enabled
            )


if __name__ == "__main__":
    unittest.main()
