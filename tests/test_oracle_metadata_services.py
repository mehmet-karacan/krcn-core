from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.oracle_metadata import (  # noqa: E402
    OracleInventoryEntry,
    OracleObjectIdentity,
)


class FakeOracleTransport:
    def __init__(self) -> None:
        self.table = OracleObjectIdentity("APP", "TABLE", "CUSTOMERS")
        self.calls: list[str] = []

    def inventory(self, owners, object_types):
        self.calls.append("inventory")
        return [OracleInventoryEntry(self.table, "change-1")]

    def fetch_ddl_select(self, identity):
        self.calls.append("select")
        return "CREATE TABLE APP.CUSTOMERS (ID NUMBER);"

    def fetch_ddl_batch(self, identity):
        self.calls.append("batch")
        return "CREATE TABLE APP.CUSTOMERS (ID NUMBER);"

    def fetch_structured_metadata(self, identity):
        return {"columns": [{"name": "ID", "data_type": "NUMBER"}]}

    def fetch_dependencies(self, identity):
        return ()


class OracleMetadataServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / ".krcn"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        policy_path = self.home / "policies" / "oracle-select-only.json"
        policy_path.parent.mkdir()
        policy_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy_id": "oracle-select-only",
                    "scope": {"kind": "integration", "ref": "app-oracle"},
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
                            "rule_id": "deny-execute",
                            "resource_type": "database",
                            "operations": ["execute"],
                            "effect": "deny",
                            "provenance": {"kind": "explicit-user"},
                            "active": True,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.store = LocalWorkspaceStore(
            self.home,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self._put(
            "projects",
            "sample-project",
            {"schema_version": 1, "project_id": "sample-project"},
        )
        self._put(
            "source-bindings",
            "app-oracle-local",
            {
                "schema_version": 1,
                "binding_id": "app-oracle-local",
                "source_id": "app-oracle",
                "source_kind": "database",
                "locator": {"kind": "connection-ref", "value": "connection"},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": ["oracle-select-only"],
                "revision": 1,
            },
        )
        self._put(
            "integrations",
            "app-oracle",
            {
                "schema_version": 1,
                "integration_id": "app-oracle",
                "adapter_id": "oracle-metadata-read-only",
                "source_binding_ref": "app-oracle-local",
                "status": "active",
                "configuration": {"driver": "oracle", "read_only": True},
                "secret_refs": {"connection": "secret://database/app-oracle"},
                "policy_refs": ["oracle-select-only"],
                "revision": 1,
            },
        )
        self.transport = FakeOracleTransport()
        self.service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            oracle_metadata_transports={"app-oracle": self.transport},
        )
        self.arguments = {
            "project_id": "sample-project",
            "integration_id": "app-oracle",
            "binding_id": "app-oracle-local",
            "owners": ["APP"],
            "object_types": ["TABLE"],
            "mode": "select-compatible",
            "complete": True,
        }

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

    def test_collect_requires_session_then_exact_user_data_approval(self) -> None:
        with self.assertRaisesRegex(ApplicationServiceError, "session approval"):
            self.service.execute(
                ServiceRequest("cli", "database.oracle.collect", self.arguments)
            )
        planned = self.service.execute(
            ServiceRequest(
                "cli",
                "database.oracle.collect",
                self.arguments,
                approval_id="network-session",
            )
        )
        self.assertEqual("planned", planned.status)
        plan_id = planned.data["plan"]["plan_id"]
        applied = self.service.execute(
            ServiceRequest(
                "sdk",
                "database.oracle.collect",
                self.arguments,
                apply=True,
                expected_plan_id=plan_id,
                approval_id="metadata-write-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertFalse(applied.data["result"]["row_data_collected"])

    def test_select_only_policy_blocks_batch_mode_without_overwrite(self) -> None:
        arguments = {**self.arguments, "mode": "batch-open"}
        with self.assertRaisesRegex(ValueError, "requires execute"):
            self.service.execute(
                ServiceRequest(
                    "codex",
                    "database.oracle.collect",
                    arguments,
                    approval_id="network-session",
                )
            )
        policy = json.loads(
            (self.home / "policies" / "oracle-select-only.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            "deny",
            next(
                rule["effect"]
                for rule in policy["rules"]
                if rule["rule_id"] == "deny-execute"
            ),
        )

    def test_index_search_and_status_share_the_application_service(self) -> None:
        planned = self.service.execute(
            ServiceRequest(
                "cli",
                "database.oracle.collect",
                self.arguments,
                approval_id="network-session",
            )
        )
        self.service.execute(
            ServiceRequest(
                "cli",
                "database.oracle.collect",
                self.arguments,
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
                approval_id="metadata-write-approval",
            )
        )
        index_plan = self.service.execute(
            ServiceRequest(
                "cli",
                "database.oracle.index",
                {"project_id": "sample-project"},
            )
        )
        self.service.execute(
            ServiceRequest(
                "mcp",
                "database.oracle.index",
                {"project_id": "sample-project"},
                apply=True,
                expected_plan_id=index_plan.data["plan"]["plan_id"],
            )
        )
        searched = self.service.execute(
            ServiceRequest(
                "plugin",
                "database.oracle.search",
                {"project_id": "sample-project", "text": "CUSTOMERS ID"},
            )
        )
        status = self.service.execute(
            ServiceRequest(
                "codex",
                "database.oracle.status",
                {"project_id": "sample-project"},
            )
        )
        self.assertGreater(searched.data["result"]["hit_count"], 0)
        self.assertTrue(status.data["result"]["index_available"])
        serialized = json.dumps(
            {"search": searched.as_dict(), "status": status.as_dict()}
        )
        self.assertNotIn("secret://", serialized)
        self.assertNotIn(str(self.home), serialized)


if __name__ == "__main__":
    unittest.main()
