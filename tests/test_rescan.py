from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.adapter_gate import (  # noqa: E402
    authorize_adapter_operation,
    prepare_adapter_operation,
)
from krcn_core.discovery import (  # noqa: E402
    LOCAL_DISCOVERY_ADAPTER,
    discover_local_source,
    load_discovery_policy,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.rescan import RescanError, apply_rescan, prepare_rescan  # noqa: E402
from krcn_core.source_bindings import parse_source_binding  # noqa: E402


class RescanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_temp = tempfile.TemporaryDirectory()
        self.data_temp = tempfile.TemporaryDirectory()
        self.source_root = Path(self.source_temp.name)
        (self.source_root / "src").mkdir()
        (self.source_root / "src" / "main.py").write_text(
            "print('first')\n", encoding="utf-8"
        )
        (self.source_root / "pyproject.toml").write_text(
            "[project]\nname='sample'\n", encoding="utf-8"
        )
        self.binding = parse_source_binding(
            {
                "schema_version": 1,
                "binding_id": "sample-project-local",
                "source_id": "sample-project",
                "source_kind": "project",
                "locator": {"kind": "local-path", "value": str(self.source_root)},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": [],
                "revision": 1,
            }
        )
        self.store = LocalWorkspaceStore(
            Path(self.data_temp.name), OwnershipResolver.from_repository(REPO_ROOT)
        )
        self.policy = load_discovery_policy(REPO_ROOT)
        self._create_project()

    def tearDown(self) -> None:
        self.source_temp.cleanup()
        self.data_temp.cleanup()

    def _create_project(self) -> None:
        payload = {
            "schema_version": 1,
            "project_id": "sample-project",
            "name": "Sample Project",
            "description": "Synthetic fixture",
            "source_refs": ["sample-project-local"],
            "technologies": [{"name": "Manual Tool", "category": "manual"}],
            "modules": [],
            "skill_refs": [],
            "status": "active",
        }
        plan = self.store.prepare_put(
            "projects", "sample-project", payload, expected_revision=0
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            approval=ApprovalEvidence(plan.mutation.plan_id, "setup-approval", True),
        )
        self.store.apply_put(plan, authorization)

    def _discover(self):
        request = prepare_adapter_operation(
            LOCAL_DISCOVERY_ADAPTER, self.binding, "discover", []
        )
        return discover_local_source(
            self.binding,
            self.policy,
            authorize_adapter_operation(request),
        )

    @staticmethod
    def _authorizations(plan):
        result = {}
        for record_plan in plan.record_plans:
            mutation = record_plan.mutation
            approval = None
            if mutation.approval_required:
                approval = ApprovalEvidence(
                    mutation.plan_id,
                    f"approval-{record_plan.record_type}",
                    True,
                )
            result[mutation.plan_id] = authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, True),
                approval=approval,
            )
        return result

    def test_initial_rescan_updates_discovered_metadata_and_state(self) -> None:
        plan = prepare_rescan(self.store, self.binding, self._discover())
        self.assertIn("pyproject.toml", plan.changes.added)
        self.assertEqual(("Python",), plan.changes.technologies_added)
        self.assertEqual(
            {"projects", "source-states"},
            {item.record_type for item in plan.record_plans},
        )
        result = apply_rescan(self.store, plan, self._authorizations(plan))
        self.assertEqual(2, len(result.records))
        project = self.store.read("projects", "sample-project")
        state = self.store.read("source-states", "sample-project-local")
        names = {item["name"] for item in project.payload["technologies"]}
        self.assertEqual({"Manual Tool", "Python"}, names)
        self.assertEqual(1, state.revision)
        self.assertNotIn(str(self.source_root), json.dumps(plan.public_summary()))

    def test_missing_user_approval_blocks_all_rescan_writes(self) -> None:
        plan = prepare_rescan(self.store, self.binding, self._discover())
        authorizations = self._authorizations(plan)
        project_plan = next(
            item for item in plan.record_plans if item.record_type == "projects"
        )
        authorizations.pop(project_plan.mutation.plan_id)
        with self.assertRaisesRegex(RescanError, "every rescan write"):
            apply_rescan(self.store, plan, authorizations)
        self.assertIsNone(self.store.read("source-states", "sample-project-local"))
        self.assertEqual(1, self.store.read("projects", "sample-project").revision)

    def test_unchanged_rescan_produces_no_writes(self) -> None:
        first = prepare_rescan(self.store, self.binding, self._discover())
        apply_rescan(self.store, first, self._authorizations(first))
        second = prepare_rescan(self.store, self.binding, self._discover())
        self.assertFalse(second.changes.changed)
        self.assertEqual((), second.record_plans)
        result = apply_rescan(self.store, second, {})
        self.assertEqual((), result.records)

    def test_file_change_updates_only_derived_state_when_technology_is_same(self) -> None:
        first = prepare_rescan(self.store, self.binding, self._discover())
        apply_rescan(self.store, first, self._authorizations(first))
        (self.source_root / "src" / "extra.py").write_text(
            "print('extra')\n", encoding="utf-8"
        )
        second = prepare_rescan(self.store, self.binding, self._discover())
        self.assertEqual(("src/extra.py",), second.changes.added)
        self.assertEqual(
            ["source-states"],
            [item.record_type for item in second.record_plans],
        )
        apply_rescan(self.store, second, self._authorizations(second))
        self.assertEqual(
            2,
            self.store.read("source-states", "sample-project-local").revision,
        )
        self.assertEqual(2, self.store.read("projects", "sample-project").revision)

    def test_removed_marker_preserves_manual_technology(self) -> None:
        first = prepare_rescan(self.store, self.binding, self._discover())
        apply_rescan(self.store, first, self._authorizations(first))
        (self.source_root / "pyproject.toml").unlink()
        second = prepare_rescan(self.store, self.binding, self._discover())
        self.assertEqual(("Python",), second.changes.technologies_removed)
        apply_rescan(self.store, second, self._authorizations(second))
        project = self.store.read("projects", "sample-project")
        self.assertEqual(
            [{"name": "Manual Tool", "category": "manual"}],
            project.payload["technologies"],
        )


if __name__ == "__main__":
    unittest.main()
