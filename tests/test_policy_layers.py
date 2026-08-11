from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class UserPolicyContractTests(unittest.TestCase):
    def test_user_policy_schema_defines_enforcement_outcomes(self) -> None:
        schema = load_json(REPO_ROOT / "schemas" / "user-policy.schema.json")
        self.assertEqual("urn:krcn:schemas:user-policy:1", schema["$id"])
        rule_properties = schema["properties"]["rules"]["items"]["properties"]
        self.assertEqual(
            ["allow", "deny", "require-approval"],
            rule_properties["effect"]["enum"],
        )
        provenance = rule_properties["provenance"]["properties"]["kind"]["enum"]
        self.assertEqual(
            ["explicit-user", "approved-memory", "approved-import"],
            provenance,
        )

    def test_user_policies_are_owned_as_preserved_user_data(self) -> None:
        manifest = load_json(REPO_ROOT / "config" / "ownership-manifest.json")
        classes = {item["id"]: item for item in manifest["classes"]}
        self.assertIn(".krcn/policies/**", classes["user-data"]["paths"])
        self.assertNotIn(".krcn/policies/**", classes["core"]["paths"])
        self.assertEqual("preserve", classes["user-data"]["merge_strategy"])

    def test_shared_context_requires_policy_preservation(self) -> None:
        instructions = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        orientation = (REPO_ROOT / "AI-CONTEXT.md").read_text(encoding="utf-8")
        self.assertIn("must never weaken, replace, or delete", instructions)
        self.assertIn("must not silently weaken or overwrite", orientation)

    def test_policy_spec_makes_deny_stronger_than_allow(self) -> None:
        specification = (
            REPO_ROOT / "docs" / "specifications" / "POLICY-LAYERS.md"
        ).read_text(encoding="utf-8")
        self.assertIn("A deny result wins over allow.", specification)
        self.assertIn("explicit policy change", specification)


if __name__ == "__main__":
    unittest.main()
