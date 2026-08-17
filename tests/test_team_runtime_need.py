from __future__ import annotations
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from krcn_core.foundation import load_json
from krcn_core.team_runtime_need import assess_team_runtime_need, load_team_runtime_need_policy

ROOT = Path(__file__).resolve().parents[1]

class TeamRuntimeNeedTests(unittest.TestCase):
    def test_current_local_first_profile_is_explicitly_deferred(self):
        policy = load_team_runtime_need_policy(ROOT)
        result = assess_team_runtime_need(policy, machine_count=1, concurrent_worker_count=4, cross_machine_claim_required=False, enterprise_needs=(), migration_owner_assigned=False, rollback_owner_assigned=False, operating_budget_approved=False)
        self.assertEqual("deferred", result.payload["decision"]); self.assertFalse(result.payload["postgresql_required"]); self.assertEqual(0, result.payload["provider_calls"])
        schema = load_json(ROOT / "schemas" / "team-runtime-assessment.schema.json")
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(result.as_dict())))

    def test_real_team_need_only_opens_a_separate_plan_without_authority(self):
        policy = load_team_runtime_need_policy(ROOT)
        result = assess_team_runtime_need(policy, machine_count=3, concurrent_worker_count=12, cross_machine_claim_required=True, enterprise_needs=("high-availability",), migration_owner_assigned=True, rollback_owner_assigned=True, operating_budget_approved=True)
        self.assertEqual("eligible-for-separate-plan", result.payload["decision"]); self.assertTrue(result.payload["postgresql_required"]); self.assertFalse(result.payload["migration_allowed"]); self.assertFalse(result.payload["authority_granted"])

if __name__ == "__main__": unittest.main()
