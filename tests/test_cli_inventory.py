from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / ".ai" / "legacy-cli-inventory.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class LegacyCliInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = load_json(INVENTORY_PATH)
        cls.commands = {
            command["id"]: command for command in cls.inventory["commands"]
        }

    def test_inventory_is_reference_only_without_source_code(self) -> None:
        self.assertEqual("reference-only", self.inventory["status"])
        self.assertFalse(self.inventory["source_code_imported"])
        self.assertEqual(
            "schemas/cli-command-inventory.schema.json",
            self.inventory["schema_ref"],
        )

    def test_external_staging_baseline_has_portable_fingerprint(self) -> None:
        fingerprint = self.inventory["source_fingerprint"]
        self.assertRegex(fingerprint["sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(3669, fingerprint["line_count"])
        self.assertEqual(163852, fingerprint["byte_count"])
        self.assertEqual("external-local", fingerprint["staging_location"])
        self.assertEqual(
            {"ip-address", "unicode-long-dash"},
            set(fingerprint["content_findings"]),
        )

    def test_all_legacy_commands_have_unique_identifiers(self) -> None:
        command_list = self.inventory["commands"]
        self.assertEqual(29, len(command_list))
        self.assertEqual(29, len(self.commands))
        self.assertEqual(
            1,
            sum(command["visibility"] == "internal" for command in command_list),
        )

    def test_mutating_commands_declare_write_ownership(self) -> None:
        for command in self.inventory["commands"]:
            with self.subTest(command=command["id"]):
                if command["behavior"] in {"write", "mixed"}:
                    self.assertTrue(command["writes"])

    def test_network_capable_commands_are_not_preserved_unchanged(self) -> None:
        for command in self.inventory["commands"]:
            with self.subTest(command=command["id"]):
                if command["network_effects"]:
                    self.assertNotEqual("preserve", command["disposition"])

    def test_database_build_waits_for_statement_policy_enforcement(self) -> None:
        command = self.commands["database-index-build"]
        self.assertEqual("defer", command["disposition"])
        self.assertIn("non-select-session-command", command["risk_codes"])
        self.assertIn("database-connection", command["network_effects"])

    def test_external_writes_and_lock_approval_are_explicit_risks(self) -> None:
        self.assertIn(
            "external-source-write",
            self.commands["project-onboard"]["risk_codes"],
        )
        self.assertIn(
            "approval-is-conventional-only",
            self.commands["lock-force-release"]["risk_codes"],
        )


if __name__ == "__main__":
    unittest.main()
