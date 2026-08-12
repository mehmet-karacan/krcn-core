from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.oracle_metadata import (  # noqa: E402
    OracleApplyAuthorization,
    OracleCollectionPolicy,
    OracleDependencyEvidence,
    OracleIndexAuthorization,
    OracleInventoryEntry,
    OracleMetadataError,
    OracleObjectIdentity,
    OracleReadAuthorization,
    apply_oracle_index,
    apply_oracle_plan,
    collect_oracle_snapshot,
    oracle_index_path,
    prepare_oracle_apply,
    prepare_oracle_index,
    retrieve_oracle_dependencies,
    search_oracle_metadata,
)


def digest(marker: str) -> str:
    import hashlib

    return hashlib.sha256(marker.encode("utf-8")).hexdigest()


class FakeOracleTransport:
    """Named metadata operations only. It has no arbitrary SQL entry point."""

    def __init__(self, objects):
        self.objects = dict(objects)
        self.calls = []

    def inventory(self, owners, object_types):
        self.calls.append(("inventory", owners, object_types))
        return [
            value["inventory"]
            for value in self.objects.values()
            if value["inventory"].identity.owner in owners
            and value["inventory"].identity.object_type in object_types
        ]

    def fetch_ddl_select(self, identity):
        self.calls.append(("select", identity.object_id))
        return self.objects[identity.object_id]["ddl"]

    def fetch_ddl_batch(self, identity):
        self.calls.append(("batch", identity.object_id))
        return self.objects[identity.object_id]["ddl"]

    def fetch_structured_metadata(self, identity):
        self.calls.append(("structured", identity.object_id))
        return self.objects[identity.object_id].get("structured", {})

    def fetch_dependencies(self, identity):
        self.calls.append(("dependencies", identity.object_id))
        return self.objects[identity.object_id].get("dependencies", ())


def entry(identity, change_token, ddl, *, structured=None, dependencies=()):
    return {
        "inventory": OracleInventoryEntry(identity, change_token),
        "ddl": ddl,
        "structured": structured or {},
        "dependencies": dependencies,
    }


class OracleMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name) / ".krcn"
        self.data_root.mkdir()
        (self.data_root / "layout.json").write_bytes(user_home_layout_bytes())
        self.table = OracleObjectIdentity("APP", "TABLE", "CUSTOMERS")
        self.package_spec = OracleObjectIdentity("APP", "PACKAGE", "CUSTOMER_API", "V1")
        self.package_body = OracleObjectIdentity("APP", "PACKAGE BODY", "CUSTOMER_API", "V1")
        self.base_objects = {
            self.table.object_id: entry(
                self.table,
                "2026-08-12T08:00:00Z",
                "CREATE TABLE APP.CUSTOMERS (ID NUMBER, NAME VARCHAR2(100));",
                structured={
                    "columns": [
                        {"name": "ID", "data_type": "NUMBER", "nullable": False},
                        {"name": "NAME", "data_type": "VARCHAR2", "nullable": True},
                    ],
                    "constraints": [{"name": "CUSTOMERS_PK", "kind": "PRIMARY KEY"}],
                },
            ),
            self.package_spec.object_id: entry(
                self.package_spec,
                "2026-08-12T08:10:00Z",
                "CREATE OR REPLACE PACKAGE APP.CUSTOMER_API AS\n  FUNCTION find_name(p_id NUMBER) RETURN VARCHAR2;\nEND;",
                structured={"members": [{"name": "FIND_NAME", "kind": "FUNCTION"}]},
                dependencies=(
                    OracleDependencyEvidence(
                        self.table,
                        "references",
                        "dictionary",
                        digest("spec-table"),
                    ),
                ),
            ),
            self.package_body.object_id: entry(
                self.package_body,
                "2026-08-12T08:11:00Z",
                "CREATE OR REPLACE PACKAGE BODY APP.CUSTOMER_API AS\n  FUNCTION find_name(p_id NUMBER) RETURN VARCHAR2 IS\n    l_name VARCHAR2(100);\n  BEGIN\n    SELECT name INTO l_name FROM app.customers WHERE id = p_id;\n    RETURN l_name;\n  END;\nEND;",
                dependencies=(
                    OracleDependencyEvidence(
                        self.package_spec,
                        "implements",
                        "structural",
                        digest("body-spec"),
                    ),
                    OracleDependencyEvidence(
                        self.table,
                        "depends-on",
                        "plscope",
                        digest("body-table"),
                    ),
                ),
            ),
        }

    def tearDown(self):
        self.temporary.cleanup()

    def policy(self, mode="select-compatible", types=None):
        return OracleCollectionPolicy(
            ("APP",),
            tuple(types or ("TABLE", "PACKAGE_SPEC", "PACKAGE_BODY")),
            mode,
        )

    def authorization(self, mode="select-compatible"):
        return OracleReadAuthorization(
            "app-oracle-local",
            1,
            "metadata-select" if mode == "select-compatible" else "metadata-batch-open",
            True,
        )

    def collect(
        self,
        objects=None,
        *,
        complete=True,
        mode="select-compatible",
        types=None,
        reuse=False,
    ):
        transport = FakeOracleTransport(objects or self.base_objects)
        snapshot = collect_oracle_snapshot(
            "sample-project",
            "app-oracle",
            transport,
            self.policy(mode, types),
            self.authorization(mode),
            complete=complete,
            data_root=self.data_root if reuse else None,
        )
        return transport, snapshot

    def apply_snapshot(self, snapshot):
        plan = prepare_oracle_apply(self.data_root, snapshot)
        result = apply_oracle_plan(
            plan,
            OracleApplyAuthorization(plan.plan_id, "oracle-test-approval", True),
        )
        self.assertTrue(result["integrity_verified"])
        return plan

    def index(self):
        plan = prepare_oracle_index(self.data_root, "sample-project")
        result = apply_oracle_index(
            self.data_root,
            plan,
            OracleIndexAuthorization(plan.plan_id),
        )
        self.assertTrue(result["integrity_verified"])
        return plan, result

    def test_select_and_batch_authorizations_are_separate(self):
        transport, snapshot = self.collect(mode="select-compatible")
        self.assertEqual(3, len(snapshot.objects))
        self.assertTrue(any(call[0] == "select" for call in transport.calls))
        self.assertFalse(any(call[0] == "batch" for call in transport.calls))
        with self.assertRaisesRegex(OracleMetadataError, "does not match"):
            collect_oracle_snapshot(
                "sample-project",
                "app-oracle",
                FakeOracleTransport(self.base_objects),
                self.policy("batch-open"),
                self.authorization("select-compatible"),
                complete=True,
            )
        batch, _ = self.collect(mode="batch-open")
        self.assertTrue(any(call[0] == "batch" for call in batch.calls))
        self.assertFalse(any(call[0] == "select" for call in batch.calls))

    def test_transport_cannot_escape_owner_or_type_allowlist(self):
        rogue = OracleObjectIdentity("OTHER", "TABLE", "SECRET_ROWS")

        class RogueTransport(FakeOracleTransport):
            def inventory(self, owners, object_types):
                return [OracleInventoryEntry(rogue, "changed")]

        with self.assertRaisesRegex(OracleMetadataError, "outside the allowlist"):
            collect_oracle_snapshot(
                "sample-project",
                "app-oracle",
                RogueTransport({rogue.object_id: entry(rogue, "changed", "CREATE TABLE OTHER.SECRET_ROWS (ID NUMBER)")}),
                self.policy(types=("TABLE",)),
                self.authorization(),
                complete=True,
            )

    def test_package_spec_and_body_are_separate_revisions_in_one_group(self):
        _, snapshot = self.collect()
        by_type = {item.inventory.identity.object_type: item for item in snapshot.objects}
        spec = by_type["PACKAGE_SPEC"]
        body = by_type["PACKAGE_BODY"]
        self.assertNotEqual(spec.inventory.identity.object_id, body.inventory.identity.object_id)
        self.assertNotEqual(spec.revision_id, body.revision_id)
        self.assertEqual(
            spec.inventory.identity.logical_group_id,
            body.inventory.identity.logical_group_id,
        )
        self.apply_snapshot(snapshot)
        revisions = list(
            (self.data_root / "projects" / "sample-project" / "database" / "oracle" / "revisions").glob("*.json")
        )
        self.assertEqual(3, len(revisions))

    def test_database_link_credentials_are_not_persisted(self):
        database_link = OracleObjectIdentity("APP", "DATABASE LINK", "REMOTE_HR")
        objects = {
            database_link.object_id: entry(
                database_link,
                "changed",
                "CREATE DATABASE LINK REMOTE_HR CONNECT TO secret_user IDENTIFIED BY very_secret USING 'prod-db'",
                structured={
                    "credential": "do-not-store",
                    "connection_string": "prod-db",
                    "username": "secret_user",
                    "host": "prod-db.internal",
                    "public": False,
                },
            )
        }
        _, snapshot = self.collect(objects, types=("DATABASE_LINK",))
        item = snapshot.objects[0]
        self.assertEqual(
            'CREATE DATABASE LINK "APP"."REMOTE_HR" /* connection details redacted */',
            item.normalized_ddl,
        )
        self.assertEqual({"public": False}, item.structured_metadata)
        self.apply_snapshot(snapshot)
        raw = "".join(
            path.read_text(encoding="utf-8")
            for path in (self.data_root / "projects" / "sample-project" / "database" / "oracle").rglob("*.json")
        )
        self.assertNotIn("very_secret", raw)
        self.assertNotIn("secret_user", raw)
        self.assertNotIn("prod-db", raw)
        self.assertNotIn("prod-db.internal", raw)

    def test_partial_snapshot_never_retires_missing_objects(self):
        _, initial = self.collect()
        self.apply_snapshot(initial)
        only_table = {self.table.object_id: self.base_objects[self.table.object_id]}
        _, partial = self.collect(only_table, complete=False)
        plan = self.apply_snapshot(partial)
        self.assertEqual(0, plan.retired_object_count)
        object_dir = self.data_root / "projects" / "sample-project" / "database" / "oracle" / "objects"
        body = json.loads((object_dir / f"{self.package_body.object_id}.json").read_text(encoding="utf-8"))
        self.assertEqual("current", body["lifecycle"])

        _, complete = self.collect(only_table, complete=True)
        plan = self.apply_snapshot(complete)
        self.assertEqual(2, plan.retired_object_count)
        body = json.loads((object_dir / f"{self.package_body.object_id}.json").read_text(encoding="utf-8"))
        self.assertEqual("retired", body["lifecycle"])

    def test_unchanged_revisions_and_chunks_are_reused(self):
        _, snapshot = self.collect()
        first_apply = self.apply_snapshot(snapshot)
        self.assertEqual(3, first_apply.new_revision_count)
        first_index, first_result = self.index()
        self.assertEqual(len(first_index.chunks), first_result["processed_chunk_count"])

        repeated_transport, repeated = self.collect(reuse=True)
        self.assertEqual(3, repeated.reused_object_count)
        self.assertEqual(
            ["inventory"],
            [call[0] for call in repeated_transport.calls],
        )
        second_apply = self.apply_snapshot(repeated)
        self.assertEqual(0, second_apply.new_revision_count)
        second_index, second_result = self.index()
        self.assertEqual(0, second_result["processed_chunk_count"])
        self.assertEqual(len(second_index.chunks), second_result["reused_chunk_count"])

        changed = dict(self.base_objects)
        changed[self.package_body.object_id] = entry(
            self.package_body,
            "2026-08-12T09:00:00Z",
            self.base_objects[self.package_body.object_id]["ddl"].replace("RETURN l_name", "RETURN upper(l_name)"),
            dependencies=self.base_objects[self.package_body.object_id]["dependencies"],
        )
        changed_transport, changed_snapshot = self.collect(changed, reuse=True)
        self.assertEqual(2, changed_snapshot.reused_object_count)
        self.assertEqual(1, sum(call[0] == "select" for call in changed_transport.calls))
        changed_apply = self.apply_snapshot(changed_snapshot)
        self.assertEqual(1, changed_apply.new_revision_count)
        _, changed_index = self.index()
        self.assertGreater(changed_index["processed_chunk_count"], 0)
        self.assertGreater(changed_index["reused_chunk_count"], 0)

    def test_search_and_dependency_retrieval_use_project_index(self):
        _, snapshot = self.collect()
        self.apply_snapshot(snapshot)
        self.index()
        result = search_oracle_metadata(
            self.data_root,
            "sample-project",
            "find_name customers",
            owner="APP",
            object_type="PACKAGE_BODY",
        )
        self.assertGreater(result["hit_count"], 0)
        self.assertEqual("PACKAGE_BODY", result["hits"][0]["identity"]["object_type"])
        self.assertFalse(result["row_data_collected"])

        graph = retrieve_oracle_dependencies(
            self.data_root,
            "sample-project",
            self.package_body.object_id,
            max_depth=2,
        )
        self.assertIn(self.package_spec.object_id, graph["node_ids"])
        self.assertIn(self.table.object_id, graph["node_ids"])
        self.assertTrue(graph["provenance_preserved"])
        self.assertTrue(all(item["source_digest"] for item in graph["edges"]))

        index_path = oracle_index_path(self.data_root, "sample-project")
        self.assertEqual(
            self.data_root / "projects" / "sample-project" / "derived" / "retrieval" / "oracle-metadata-v1.sqlite",
            index_path,
        )
        connection = sqlite3.connect(index_path)
        try:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        finally:
            connection.close()
        self.assertEqual("false", metadata["row_data_collected"])

    def test_refreshed_object_retires_removed_dependency_with_provenance(self):
        _, snapshot = self.collect()
        self.apply_snapshot(snapshot)
        changed = dict(self.base_objects)
        changed[self.package_body.object_id] = entry(
            self.package_body,
            "2026-08-12T10:00:00Z",
            self.base_objects[self.package_body.object_id]["ddl"] + "\n-- metadata refresh",
            dependencies=(self.base_objects[self.package_body.object_id]["dependencies"][0],),
        )
        _, refreshed = self.collect(changed, reuse=True)
        self.apply_snapshot(refreshed)
        dependency_dir = self.data_root / "projects" / "sample-project" / "database" / "oracle" / "dependencies"
        dependencies = [json.loads(path.read_text(encoding="utf-8")) for path in dependency_dir.glob("*.json")]
        body_edges = [item for item in dependencies if item["from_object_id"] == self.package_body.object_id]
        self.assertEqual(1, sum(item["lifecycle"] == "current" for item in body_edges))
        self.assertEqual(1, sum(item["lifecycle"] == "retired" for item in body_edges))
        self.assertTrue(all(item["source_digest"] for item in body_edges))

    def test_apply_and_index_reject_stale_or_wrong_authorization(self):
        _, snapshot = self.collect()
        plan = prepare_oracle_apply(self.data_root, snapshot)
        with self.assertRaisesRegex(OracleMetadataError, "approval"):
            apply_oracle_plan(plan, OracleApplyAuthorization(plan.plan_id, "", True))
        first_effect = plan.effects[0]
        first_effect.target.parent.mkdir(parents=True, exist_ok=True)
        first_effect.target.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(OracleMetadataError, "stale"):
            apply_oracle_plan(
                plan,
                OracleApplyAuthorization(plan.plan_id, "approved", True),
            )

    def test_no_arbitrary_sql_or_row_api_is_exposed(self):
        transport = FakeOracleTransport(self.base_objects)
        self.assertFalse(hasattr(transport, "execute"))
        self.assertFalse(hasattr(transport, "query"))
        _, snapshot = self.collect()
        plan = prepare_oracle_apply(self.data_root, snapshot)
        self.assertFalse(plan.public_summary()["row_data_collected"])
        self.assertFalse(plan.public_summary()["source_sql_accepted"])

        row_payload = {
            self.table.object_id: entry(
                self.table,
                "changed",
                "CREATE TABLE APP.CUSTOMERS (ID NUMBER)",
                structured={"rows": [{"ID": 42}]},
            )
        }
        with self.assertRaisesRegex(OracleMetadataError, "row data"):
            self.collect(row_payload, types=("TABLE",))


if __name__ == "__main__":
    unittest.main()
