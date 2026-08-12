from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.secret_provider import LocalFileSecretProvider  # noqa: E402
from krcn_core.sqlite_reference_runtime import (  # noqa: E402
    SqliteReferenceRuntime,
    SqliteReferenceRuntimeError,
)


def _policy_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "policy_id": "database-select-only",
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
                "rule_id": "deny-delete",
                "resource_type": "database",
                "operations": ["delete"],
                "effect": "deny",
                "provenance": {"kind": "explicit-user"},
                "active": True,
            },
        ],
    }


class PhaseEightRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / ".krcn"
        self.database = self.root / "reporting.sqlite"
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("CREATE TABLE items (id INTEGER, name TEXT)")
            connection.executemany(
                "INSERT INTO items VALUES (?, ?)",
                ((1, "alpha"), (2, "beta")),
            )
            connection.commit()
        finally:
            connection.close()
        connection_reference_path = (
            self.home / "secrets" / "database" / "reporting.secret"
        )
        connection_reference_path.parent.mkdir(parents=True)
        connection_reference_path.write_text(
            self.database.resolve().as_uri() + "?mode=ro",
            encoding="utf-8",
        )
        policy = self.home / "policies" / "database-select-only.json"
        policy.parent.mkdir(parents=True)
        policy.write_text(
            json.dumps(_policy_payload(), ensure_ascii=False),
            encoding="utf-8",
        )
        self.store = LocalWorkspaceStore(
            self.home,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self._put(
            "source-bindings",
            "reporting-database-local",
            {
                "schema_version": 1,
                "binding_id": "reporting-database-local",
                "source_id": "reporting-database",
                "source_kind": "database",
                "locator": {"kind": "connection-ref", "value": "connection"},
                "default_access": "read-only",
                "capabilities": ["read", "execute"],
                "policy_refs": ["database-select-only"],
                "revision": 1,
            },
        )
        self._put(
            "integrations",
            "reporting-database",
            {
                "schema_version": 1,
                "integration_id": "reporting-database",
                "adapter_id": "sqlite-read-only",
                "source_binding_ref": "reporting-database-local",
                "status": "active",
                "configuration": {"driver": "sqlite", "read_only": True},
                "secret_refs": {"connection": "secret://database/reporting"},
                "policy_refs": ["database-select-only"],
                "revision": 1,
            },
        )
        self.runtime = SqliteReferenceRuntime(REPO_ROOT, self.home / "secrets")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _put(self, record_type: str, record_id: str, payload: dict[str, object]) -> None:
        plan = self.store.prepare_put(
            record_type,
            record_id,
            payload,
            expected_revision=0,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            approval=ApprovalEvidence(plan.mutation.plan_id, "test-approval", True),
        )
        self.store.apply_put(plan, authorization)

    def _execute(self, client_kind: str = "cli"):
        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            sqlite_runtime=self.runtime,
        )
        return service.execute(
            ServiceRequest(
                client_kind=client_kind,
                operation="integration.select-read-only",
                arguments={
                    "integration_id": "reporting-database",
                    "binding_id": "reporting-database-local",
                    "statement": "SELECT id, name FROM items ORDER BY id",
                    "maximum_rows": 10,
                },
            )
        )

    def test_components_are_explicitly_registered_without_authority(self) -> None:
        catalog = self.runtime.component_catalog()
        self.assertEqual(
            {"adapter", "secret-provider", "skill", "verifier", "worker"},
            {item["kind"] for item in catalog},
        )
        self.assertTrue(all(item["callback_registered"] for item in catalog))
        self.assertTrue(all(not item["grants_authority"] for item in catalog))
        self.assertEqual((), self.runtime.selection.approval_triggers)

    def test_read_only_sqlite_flow_returns_evidence_without_rows_or_secret(self) -> None:
        response = self._execute().as_dict()
        result = response["data"]["result"]
        self.assertEqual("ok", response["status"])
        self.assertEqual(2, result["row_count"])
        self.assertEqual(["id", "name"], result["column_names"])
        self.assertFalse(result["rows_disclosed"])
        self.assertFalse(result["secret_value_disclosed"])
        serialized = json.dumps(response)
        self.assertNotIn("alpha", serialized)
        self.assertNotIn(self.database.as_posix(), serialized)

    def test_every_client_gets_the_same_shared_contract(self) -> None:
        payloads = []
        for client in ("cli", "sdk", "mcp", "plugin", "codex", "claude"):
            payload = self._execute(client).as_dict()
            payload.pop("request_id")
            payloads.append(payload)
        self.assertTrue(all(item == payloads[0] for item in payloads[1:]))

    def test_delete_and_missing_secret_fail_closed_without_mutation(self) -> None:
        integration = self.store.read("integrations", "reporting-database")
        binding = self.store.read("source-bindings", "reporting-database-local")
        assert integration is not None and binding is not None
        from krcn_core.integrations import parse_integration_metadata
        from krcn_core.policies import load_user_policies
        from krcn_core.source_bindings import parse_source_binding

        with self.assertRaises(ValueError):
            self.runtime.execute_select(
                parse_integration_metadata(dict(integration.payload)),
                parse_source_binding(dict(binding.payload)),
                "DELETE FROM items",
                load_user_policies(self.home / "policies"),
            )
        (self.home / "secrets" / "database" / "reporting.secret").unlink()
        with self.assertRaises(ValueError):
            self._execute()
        connection = sqlite3.connect(self.database)
        try:
            count = connection.execute("SELECT count(*) FROM items").fetchone()[0]
            self.assertEqual(2, count)
        finally:
            connection.close()

    def test_secret_provider_summary_never_reveals_value(self) -> None:
        lease = LocalFileSecretProvider(self.home / "secrets").resolve(
            "secret://" + "database/reporting"
        )
        summary = lease.public_summary()
        self.assertFalse(summary["value_disclosed"])
        self.assertNotIn("file:", json.dumps(summary))

    def test_cli_uses_the_same_registered_runtime(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "integration",
                    "select",
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(self.home),
                    "--integration-id",
                    "reporting-database",
                    "--binding-id",
                    "reporting-database-local",
                    "--statement",
                    "SELECT id FROM items ORDER BY id",
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(0, exit_code)
        self.assertEqual(2, json.loads(output.getvalue())["data"]["result"]["row_count"])


if __name__ == "__main__":
    unittest.main()
