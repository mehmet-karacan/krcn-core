from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.installation import InstallationState, ManagedFile  # noqa: E402
from krcn_core.merge_plan import (  # noqa: E402
    MergePlanError,
    authorize_merge_plan,
    prepare_merge_plan,
)
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.release_diff import (  # noqa: E402
    DiffConflict,
    FileChange,
    ReleaseDiff,
)
from krcn_core.update_effects import (  # noqa: E402
    DerivedActionRegistry,
    DerivedActionSpec,
    MigrationRegistry,
    MigrationSpec,
)


class MergePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = InstallationState(
            installation_id="sample-installation",
            core_version="0.1.0",
            release_id="krcn-core-0.1.0",
            source_commit="a" * 40,
            managed_files=(
                ManagedFile("README.md", "1" * 64, 10),
                ManagedFile("config/old.txt", "2" * 64, 20),
            ),
            schema_versions={"workspace": 1},
            completed_migrations=(),
            pending_derived_actions=(),
            revision=1,
        )
        self.diff = ReleaseDiff(
            diff_id="3" * 64,
            inspection_id="4" * 64,
            installation_id="sample-installation",
            from_core_version="0.1.0",
            release_id="krcn-core-0.2.0",
            to_core_version="0.2.0",
            manifest_sha256="5" * 64,
            changes=(
                FileChange(
                    "README.md",
                    "update",
                    "core",
                    "1" * 64,
                    "6" * 64,
                    11,
                ),
                FileChange(
                    "config/old.txt",
                    "delete",
                    "core",
                    "2" * 64,
                    None,
                    None,
                ),
                FileChange(
                    "src/new.py",
                    "create",
                    "core",
                    None,
                    "7" * 64,
                    12,
                ),
            ),
            conflicts=(),
            pending_migrations=("workspace-v2",),
            derived_actions=("rebuild-source-state",),
        )
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.migrations = MigrationRegistry(
            [
                MigrationSpec(
                    "workspace-v2",
                    "workspace",
                    1,
                    2,
                    "user-data",
                    ".krcn/workspaces",
                )
            ]
        )
        self.derived = DerivedActionRegistry(
            [
                DerivedActionSpec(
                    "rebuild-source-state",
                    ".krcn/derived/source-states",
                    "rebuild",
                )
            ]
        )

    def _plan(self):
        return prepare_merge_plan(
            self.diff,
            self.state,
            self.ownership,
            self.migrations,
            self.derived,
            source_commit="b" * 40,
        )

    def test_plan_binds_files_effects_and_desired_state(self) -> None:
        plan = self._plan()
        self.assertEqual(3, len(plan.file_mutations))
        self.assertTrue(plan.approval_required)
        self.assertEqual("0.2.0", plan.desired_state.core_version)
        self.assertEqual(2, plan.desired_state.schema_versions["workspace"])
        self.assertEqual(2, plan.desired_state.revision)
        self.assertEqual(
            {"README.md", "src/new.py"},
            {item.path for item in plan.desired_state.managed_files},
        )
        summary = plan.public_summary()
        self.assertRegex(summary["plan_id"], r"^[a-f0-9]{64}$")
        self.assertNotIn(str(REPO_ROOT), json.dumps(summary))

    def test_exact_plan_and_approval_are_required(self) -> None:
        plan = self._plan()
        with self.assertRaisesRegex(MergePlanError, "exact dry-run"):
            authorize_merge_plan(
                plan,
                expected_plan_id="0" * 64,
                approval_id="merge-approval",
            )
        with self.assertRaisesRegex(MergePlanError, "explicit approval"):
            authorize_merge_plan(
                plan,
                expected_plan_id=plan.plan_id,
                approval_id=None,
            )
        authorization = authorize_merge_plan(
            plan,
            expected_plan_id=plan.plan_id,
            approval_id="merge-approval",
        )
        self.assertTrue(authorization.approval_verified)
        self.assertEqual(
            len(plan.file_mutations) + 1,
            len(authorization.mutation_authorizations),
        )

    def test_conflict_and_unregistered_effects_block_planning(self) -> None:
        conflicted = ReleaseDiff(
            **{
                **self.diff.__dict__,
                "conflicts": (
                    DiffConflict("managed-modified", "README.md", "README.md"),
                ),
            }
        )
        with self.assertRaisesRegex(MergePlanError, "conflicts"):
            prepare_merge_plan(
                conflicted,
                self.state,
                self.ownership,
                self.migrations,
                self.derived,
                source_commit="b" * 40,
            )
        with self.assertRaisesRegex(MergePlanError, "unregistered migrations"):
            prepare_merge_plan(
                self.diff,
                self.state,
                self.ownership,
                MigrationRegistry(),
                self.derived,
                source_commit="b" * 40,
            )

    def test_migration_schema_version_must_match(self) -> None:
        changed_state = InstallationState(
            **{
                **self.state.__dict__,
                "schema_versions": {"workspace": 2},
            }
        )
        with self.assertRaisesRegex(MergePlanError, "source version"):
            prepare_merge_plan(
                self.diff,
                changed_state,
                self.ownership,
                self.migrations,
                self.derived,
                source_commit="b" * 40,
            )

    def test_same_release_and_content_produce_a_true_no_op_plan(self) -> None:
        unchanged_diff = ReleaseDiff(
            **{
                **self.diff.__dict__,
                "release_id": self.state.release_id,
                "to_core_version": self.state.core_version,
                "changes": (
                    FileChange(
                        "README.md",
                        "unchanged",
                        "core",
                        "1" * 64,
                        "1" * 64,
                        10,
                    ),
                ),
                "pending_migrations": (),
                "derived_actions": (),
            }
        )
        plan = prepare_merge_plan(
            unchanged_diff,
            self.state,
            self.ownership,
            MigrationRegistry(),
            DerivedActionRegistry(),
            source_commit=self.state.source_commit,
        )
        self.assertFalse(plan.has_effects)
        self.assertIsNone(plan.state_mutation)
        self.assertEqual(self.state, plan.desired_state)


if __name__ == "__main__":
    unittest.main()
