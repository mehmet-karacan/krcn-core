from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.policies import (  # noqa: E402
    UserPolicyError,
    evaluate_policies,
    parse_user_policy,
)


def policy_payload(policy_id: str = "database-read-only") -> dict:
    return {
        "schema_version": 1,
        "policy_id": policy_id,
        "scope": {"kind": "integration", "ref": "reporting-database"},
        "revision": 1,
        "rules": [
            {
                "rule_id": "allow-select",
                "resource_type": "database",
                "operations": ["select"],
                "effect": "allow",
                "provenance": {"kind": "explicit-user"},
                "active": True,
            },
            {
                "rule_id": "deny-mutation",
                "resource_type": "database",
                "operations": ["insert", "update", "delete", "ddl"],
                "effect": "deny",
                "provenance": {"kind": "explicit-user"},
                "active": True,
            },
        ],
    }


class PolicyEngineTests(unittest.TestCase):
    def test_select_only_policy_allows_select_and_denies_delete(self) -> None:
        policy = parse_user_policy(policy_payload())
        scope = {"integration": "reporting-database"}
        select = evaluate_policies(
            [policy], resource_type="database", operation="select", scope_refs=scope
        )
        delete = evaluate_policies(
            [policy], resource_type="database", operation="delete", scope_refs=scope
        )
        self.assertEqual("allow", select.effect)
        self.assertEqual("deny", delete.effect)

    def test_deny_cannot_be_overridden_by_another_allow(self) -> None:
        restrictive = parse_user_policy(policy_payload())
        permissive_payload = policy_payload("later-allow")
        permissive_payload["rules"] = [
            {
                "rule_id": "allow-delete",
                "resource_type": "database",
                "operations": ["delete"],
                "effect": "allow",
                "provenance": {"kind": "approved-import"},
                "active": True,
            }
        ]
        permissive = parse_user_policy(permissive_payload)
        decision = evaluate_policies(
            [restrictive, permissive],
            resource_type="database",
            operation="delete",
            scope_refs={"integration": "reporting-database"},
        )
        self.assertEqual("deny", decision.effect)
        self.assertEqual(
            {"allow-delete", "deny-mutation"}, set(decision.matched_rule_ids)
        )

    def test_policy_does_not_apply_outside_its_scope(self) -> None:
        policy = parse_user_policy(policy_payload())
        decision = evaluate_policies(
            [policy],
            resource_type="database",
            operation="select",
            scope_refs={"integration": "another-database"},
        )
        self.assertEqual("not-applicable", decision.effect)

    def test_inferred_provenance_is_rejected(self) -> None:
        payload = policy_payload()
        payload["rules"][0]["provenance"]["kind"] = "inferred"
        with self.assertRaisesRegex(UserPolicyError, "provenance kind"):
            parse_user_policy(payload)

    def test_global_scope_cannot_hide_a_machine_specific_ref(self) -> None:
        payload = policy_payload()
        payload["scope"] = {"kind": "global", "ref": "unexpected"}
        with self.assertRaisesRegex(UserPolicyError, "must not contain ref"):
            parse_user_policy(payload)


if __name__ == "__main__":
    unittest.main()
