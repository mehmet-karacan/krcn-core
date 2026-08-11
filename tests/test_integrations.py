from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.integrations import (  # noqa: E402
    IntegrationMetadataError,
    parse_integration_metadata,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


def integration_payload() -> dict:
    return {
        "schema_version": 1,
        "integration_id": "reporting-database",
        "adapter_id": "database-metadata",
        "source_binding_ref": "reporting-database-local",
        "status": "active",
        "configuration": {
            "driver": "postgresql",
            "database": "reporting",
            "options": {"read_only": True},
        },
        "secret_refs": {
            "connection": "keyring://database/reporting-connection"
        },
        "policy_refs": ["database-select-only"],
        "revision": 1,
    }


class IntegrationMetadataTests(unittest.TestCase):
    def test_valid_metadata_keeps_secret_values_out_of_public_summary(self) -> None:
        integration = parse_integration_metadata(integration_payload())
        summary = integration.public_summary()
        serialized = json.dumps(summary)
        self.assertEqual(["connection"], summary["secret_ref_names"])
        self.assertNotIn("keyring://", serialized)
        self.assertNotIn("reporting-connection", serialized)
        self.assertNotIn("postgresql", serialized)

    def test_secret_like_configuration_keys_are_rejected(self) -> None:
        for key in ("password", "api_key", "access-token", "credential"):
            with self.subTest(key=key):
                payload = integration_payload()
                payload["configuration"][key] = "literal-value"
                with self.assertRaisesRegex(IntegrationMetadataError, "secret_refs"):
                    parse_integration_metadata(payload)

    def test_secret_like_values_are_rejected(self) -> None:
        values = [
            "pass" + "word=literal-value",
            "scheme://user:literal-value@service",
            "-----BEGIN " + "PRIVATE KEY-----",
        ]
        for value in values:
            with self.subTest(value=value):
                payload = integration_payload()
                payload["configuration"]["sample"] = value
                with self.assertRaisesRegex(IntegrationMetadataError, "secret_refs"):
                    parse_integration_metadata(payload)

    def test_literal_secret_reference_is_rejected(self) -> None:
        payload = integration_payload()
        payload["secret_refs"]["connection"] = "literal-value"
        with self.assertRaisesRegex(IntegrationMetadataError, "reference"):
            parse_integration_metadata(payload)

    def test_parent_traversal_in_secret_reference_is_rejected(self) -> None:
        payload = integration_payload()
        payload["secret_refs"]["connection"] = "secret://database/../other"
        with self.assertRaisesRegex(IntegrationMetadataError, "portable"):
            parse_integration_metadata(payload)

    def test_integration_collection_is_preserved_user_data(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "config" / "ownership-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        user_data = next(item for item in manifest["classes"] if item["id"] == "user-data")
        self.assertIn(".krcn/integrations/**", user_data["paths"])
        with tempfile.TemporaryDirectory() as directory:
            store = LocalWorkspaceStore(
                Path(directory), OwnershipResolver.from_repository(REPO_ROOT)
            )
            plan = store.prepare_put(
                "integrations",
                "reporting-database",
                integration_payload(),
                expected_revision=0,
            )
            self.assertEqual("user-data", plan.mutation.ownership)
            self.assertTrue(plan.mutation.approval_required)


if __name__ == "__main__":
    unittest.main()
