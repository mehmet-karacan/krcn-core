from __future__ import annotations
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from krcn_core.foundation import load_json
from krcn_core.route_enforcement import decide_route_enforcement, load_route_enforcement_policy

ROOT = Path(__file__).resolve().parents[1]

class RouteEnforcementTests(unittest.TestCase):
    def test_measured_adjacent_promotion_and_rollback(self):
        policy = load_route_enforcement_policy(ROOT)
        promoted = decide_route_enforcement(policy, current_stage="shadow", requested_stage="advisory", observation_count=1000, mismatch_count=1, project_opt_in=False)
        self.assertTrue(promoted.payload["allowed"]); self.assertFalse(promoted.payload["mutation_allowed"])
        rollback = decide_route_enforcement(policy, current_stage="advisory", requested_stage="shadow", observation_count=0, mismatch_count=0, project_opt_in=False)
        self.assertTrue(rollback.payload["allowed"]); self.assertTrue(rollback.payload["rollback_available"])
        schema = load_json(ROOT / "schemas" / "route-enforcement-decision.schema.json")
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(promoted.as_dict())))

    def test_skips_mismatch_and_missing_opt_in_block(self):
        policy = load_route_enforcement_policy(ROOT)
        for kwargs, reason in ((dict(current_stage="shadow", requested_stage="project-opt-in", observation_count=1000, mismatch_count=0, project_opt_in=True), "adjacent-stage-required"), (dict(current_stage="advisory", requested_stage="project-opt-in", observation_count=1000, mismatch_count=100, project_opt_in=True), "mismatch-threshold"), (dict(current_stage="advisory", requested_stage="project-opt-in", observation_count=1000, mismatch_count=0, project_opt_in=False), "project-opt-in-required")):
            decision = decide_route_enforcement(policy, **kwargs)
            self.assertFalse(decision.payload["allowed"]); self.assertIn(reason, decision.payload["reason_codes"])

if __name__ == "__main__": unittest.main()
