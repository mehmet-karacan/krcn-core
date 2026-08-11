from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.source_bindings import (  # noqa: E402
    SourceBindingError,
    parse_source_binding,
)


def sample_binding() -> dict:
    return {
        "schema_version": 1,
        "binding_id": "sample-project-local",
        "source_id": "sample-project",
        "source_kind": "project",
        "locator": {"kind": "local-path", "value": "local-fixture-path"},
        "default_access": "read-only",
        "capabilities": ["read", "metadata", "search"],
        "policy_refs": ["project-read-only"],
        "revision": 1,
    }


class SourceBindingTests(unittest.TestCase):
    def test_source_binding_schema_is_versioned(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "source-binding.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("urn:krcn:schemas:source-binding:1", schema["$id"])

    def test_binding_keeps_logical_identity_separate_from_locator(self) -> None:
        binding = parse_source_binding(sample_binding())
        self.assertEqual("sample-project", binding.source_id)
        self.assertEqual("local-fixture-path", binding.locator.value)
        self.assertNotIn("locator", binding.public_summary())
        self.assertNotIn("local-fixture-path", json.dumps(binding.public_summary()))

    def test_read_only_binding_rejects_write_capability(self) -> None:
        payload = sample_binding()
        payload["capabilities"].append("write")
        with self.assertRaisesRegex(SourceBindingError, "read-only"):
            parse_source_binding(payload)

    def test_binding_rejects_machine_identity_as_logical_id(self) -> None:
        payload = sample_binding()
        payload["source_id"] = "invalid/source"
        with self.assertRaisesRegex(SourceBindingError, "portable identifier"):
            parse_source_binding(payload)

    def test_source_bindings_are_preserved_user_data(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "config" / "ownership-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        user_data = next(item for item in manifest["classes"] if item["id"] == "user-data")
        self.assertIn(".krcn/source-bindings/**", user_data["paths"])
        self.assertEqual("preserve", user_data["merge_strategy"])


if __name__ == "__main__":
    unittest.main()
