from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.migrations import (  # noqa: E402
    MigrationError,
    MigrationHandler,
    MigrationHandlerRegistry,
    plan_migration_writes,
)
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.update_effects import (  # noqa: E402
    MigrationSpec,
    UpdateEffectError,
)


class MigrationPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.directory = self.root / ".krcn" / "workspaces"
        self.directory.mkdir(parents=True)
        self.target = self.directory / "sample.json"
        self.target.write_text(
            json.dumps({"schema_version": 1, "workspace_id": "sample"}),
            encoding="utf-8",
        )
        self.spec = MigrationSpec(
            "workspace-v2",
            "workspace",
            1,
            2,
            "user-data",
            ".krcn/workspaces",
        )
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _upgrade(payload):
        payload["schema_version"] = 2
        payload.setdefault("metadata", {})
        return payload

    def test_idempotent_transform_produces_exact_write_without_mutation(self) -> None:
        before = self.target.read_bytes()
        registry = MigrationHandlerRegistry(
            [MigrationHandler("workspace-v2", self._upgrade)]
        )
        writes = plan_migration_writes(
            self.root,
            (self.spec,),
            registry,
            self.ownership,
        )
        self.assertEqual(1, len(writes))
        self.assertEqual(".krcn/workspaces/sample.json", writes[0].target_ref)
        self.assertEqual("user-data", writes[0].ownership)
        self.assertTrue(writes[0].mutation.approval_required)
        self.assertEqual(before, self.target.read_bytes())

    def test_non_idempotent_transform_is_rejected(self) -> None:
        def increment(payload):
            payload["counter"] = payload.get("counter", 0) + 1
            return payload

        registry = MigrationHandlerRegistry(
            [MigrationHandler("workspace-v2", increment)]
        )
        with self.assertRaisesRegex(MigrationError, "idempotent"):
            plan_migration_writes(
                self.root,
                (self.spec,),
                registry,
                self.ownership,
            )

    def test_unregistered_handler_is_rejected(self) -> None:
        with self.assertRaisesRegex(MigrationError, "not registered"):
            plan_migration_writes(
                self.root,
                (self.spec,),
                MigrationHandlerRegistry(),
                self.ownership,
            )

    def test_generic_policy_migration_is_prohibited(self) -> None:
        with self.assertRaisesRegex(UpdateEffectError, "semantic preservation"):
            MigrationSpec(
                "policy-v2",
                "policy",
                1,
                2,
                "user-data",
                ".krcn/policies",
            )


if __name__ == "__main__":
    unittest.main()
