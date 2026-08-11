from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.local_store import (  # noqa: E402
    LocalStoreError,
    LocalWorkspaceStore,
    RevisionConflictError,
)
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)


def workspace_payload() -> dict:
    return {
        "schema_version": 1,
        "workspace_id": "sample-workspace",
        "project_refs": [],
        "policy_refs": [],
        "metadata": {},
    }


class LocalWorkspaceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(Path(self.temporary.name), ownership)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def authorize(plan):
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                "synthetic-test-approval",
                approved=True,
            ),
        )

    def test_create_requires_authorization_for_exact_plan(self) -> None:
        plan = self.store.prepare_put(
            "workspaces",
            "sample-workspace",
            workspace_payload(),
            expected_revision=0,
        )
        self.assertEqual("user-data", plan.mutation.ownership)
        self.assertTrue(plan.mutation.approval_required)
        with self.assertRaisesRegex(LocalStoreError, "authorization"):
            other = self.store.prepare_put(
                "workspaces",
                "another-workspace",
                {**workspace_payload(), "workspace_id": "another-workspace"},
                expected_revision=0,
            )
            self.store.apply_put(other, self.authorize(plan))

    def test_atomic_create_and_revision_update(self) -> None:
        first_plan = self.store.prepare_put(
            "workspaces",
            "sample-workspace",
            workspace_payload(),
            expected_revision=0,
        )
        first = self.store.apply_put(first_plan, self.authorize(first_plan))
        self.assertEqual(1, first.revision)
        updated_payload = workspace_payload()
        updated_payload["project_refs"] = ["sample-project"]
        second_plan = self.store.prepare_put(
            "workspaces",
            "sample-workspace",
            updated_payload,
            expected_revision=1,
        )
        second = self.store.apply_put(second_plan, self.authorize(second_plan))
        self.assertEqual(2, second.revision)
        self.assertEqual(["sample-project"], second.payload["project_refs"])

    def test_stale_revision_is_rejected(self) -> None:
        first_plan = self.store.prepare_put(
            "workspaces",
            "sample-workspace",
            workspace_payload(),
            expected_revision=0,
        )
        self.store.apply_put(first_plan, self.authorize(first_plan))
        with self.assertRaises(RevisionConflictError):
            self.store.prepare_put(
                "workspaces",
                "sample-workspace",
                workspace_payload(),
                expected_revision=0,
            )

    def test_payload_tampering_is_detected(self) -> None:
        plan = self.store.prepare_put(
            "workspaces",
            "sample-workspace",
            workspace_payload(),
            expected_revision=0,
        )
        self.store.apply_put(plan, self.authorize(plan))
        target = Path(self.temporary.name) / "workspaces" / "sample-workspace.json"
        envelope = json.loads(target.read_text(encoding="utf-8"))
        envelope["payload"]["project_refs"] = ["tampered-project"]
        target.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(LocalStoreError, "payload hash"):
            self.store.read("workspaces", "sample-workspace")

    def test_public_summary_does_not_expose_source_locator(self) -> None:
        payload = {
            "schema_version": 1,
            "binding_id": "sample-source-local",
            "source_id": "sample-source",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": "private-local-location"},
            "default_access": "read-only",
            "capabilities": ["read", "metadata"],
            "policy_refs": [],
            "revision": 1,
        }
        plan = self.store.prepare_put(
            "source-bindings",
            "sample-source-local",
            payload,
            expected_revision=0,
        )
        self.store.apply_put(plan, self.authorize(plan))
        summaries = self.store.list_summaries("source-bindings")
        self.assertEqual(1, len(summaries))
        self.assertNotIn("private-local-location", json.dumps(summaries))

    def test_workspace_paths_are_preserved_user_data(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "config" / "ownership-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        user_data = next(item for item in manifest["classes"] if item["id"] == "user-data")
        self.assertIn(".krcn/workspaces/**", user_data["paths"])


if __name__ == "__main__":
    unittest.main()
