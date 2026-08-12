from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.database_policy import (  # noqa: E402
    DatabaseStatementError,
    classify_database_statement,
    require_database_statement,
    require_oracle_metadata_template,
)
from krcn_core.policies import parse_user_policy  # noqa: E402


def select_only_policy():
    return parse_user_policy(
        {
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
                    "rule_id": "deny-other-statements",
                    "resource_type": "database",
                    "operations": [
                        "delete",
                        "insert",
                        "update",
                        "merge",
                        "ddl",
                        "session",
                        "transaction",
                        "execute",
                        "select-into",
                        "select-for-update",
                        "multiple",
                        "unknown"
                    ],
                    "effect": "deny",
                    "provenance": {"kind": "explicit-user"},
                    "active": True,
                },
            ],
        }
    )


class DatabasePolicyTests(unittest.TestCase):
    def test_plain_and_cte_select_are_classified_as_select(self) -> None:
        statements = [
            "SELECT id FROM items",
            "-- comment\nselect id from items;",
            "WITH recent AS (SELECT id FROM items) SELECT id FROM recent",
            "SELECT 'delete from items' AS sample",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                self.assertEqual("select", classify_database_statement(statement))

    def test_mutating_and_session_statements_are_not_select(self) -> None:
        cases = {
            "DELETE FROM items": "delete",
            "WITH old AS (SELECT id FROM items) DELETE FROM items": "delete",
            "ALTER SESSION SET sample = true": "session",
            "BEGIN do_work(); END;": "multiple",
            "SELECT id INTO copied_items FROM items": "select-into",
            "SELECT id FROM items FOR UPDATE": "select-for-update",
            "SELECT 1; DELETE FROM items": "multiple",
        }
        for statement, expected in cases.items():
            with self.subTest(statement=statement):
                self.assertEqual(expected, classify_database_statement(statement))

    def test_select_only_policy_permits_select(self) -> None:
        authorization = require_database_statement(
            "SELECT id FROM items",
            [select_only_policy()],
            integration_id="reporting-database",
        )
        self.assertTrue(authorization.permitted)

    def test_select_only_policy_blocks_delete_and_legacy_session_command(self) -> None:
        statements = [
            "DELETE FROM items",
            "ALTER SESSION SET sample = true",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(DatabaseStatementError):
                    require_database_statement(
                        statement,
                        [select_only_policy()],
                        integration_id="reporting-database",
                    )

    def test_missing_policy_fails_closed(self) -> None:
        with self.assertRaises(DatabaseStatementError):
            require_database_statement(
                "SELECT id FROM items",
                [],
                integration_id="reporting-database",
            )

    def test_select_policy_permits_only_registered_oracle_select_templates(self) -> None:
        authorization = require_oracle_metadata_template(
            "fetch-ddl",
            {
                "object_type": "PACKAGE_SPEC",
                "object_name": "REPORTING_API",
                "owner": "APP",
            },
            [select_only_policy()],
            integration_id="reporting-database",
        )
        self.assertTrue(authorization.permitted)
        with self.assertRaises(DatabaseStatementError):
            require_oracle_metadata_template(
                "free-sql",
                {},
                [select_only_policy()],
                integration_id="reporting-database",
            )

    def test_select_policy_cannot_authorize_oracle_batch_open(self) -> None:
        with self.assertRaises(DatabaseStatementError):
            require_oracle_metadata_template(
                "batch-open",
                {"object_type": "PACKAGE_SPEC"},
                [select_only_policy()],
                integration_id="reporting-database",
                session_approved=True,
            )

    def test_batch_open_requires_execute_metadata_and_session_approval(self) -> None:
        batch_policy = parse_user_policy(
            {
                "schema_version": 1,
                "policy_id": "oracle-batch-metadata",
                "scope": {"kind": "integration", "ref": "reporting-database"},
                "revision": 1,
                "rules": [
                    {
                        "rule_id": "allow-execute",
                        "resource_type": "database",
                        "operations": ["execute"],
                        "effect": "allow",
                        "provenance": {"kind": "explicit-user"},
                        "active": True,
                    },
                    {
                        "rule_id": "allow-batch-metadata",
                        "resource_type": "database-metadata",
                        "operations": ["batch-open"],
                        "effect": "allow",
                        "provenance": {"kind": "explicit-user"},
                        "active": True,
                    },
                ],
            }
        )
        with self.assertRaises(DatabaseStatementError):
            require_oracle_metadata_template(
                "batch-open",
                {"object_type": "PACKAGE_SPEC"},
                [batch_policy],
                integration_id="reporting-database",
            )
        authorization = require_oracle_metadata_template(
            "batch-open",
            {"object_type": "PACKAGE_SPEC"},
            [batch_policy],
            integration_id="reporting-database",
            session_approved=True,
        )
        self.assertTrue(authorization.permitted)


if __name__ == "__main__":
    unittest.main()
