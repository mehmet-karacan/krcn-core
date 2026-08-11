from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.deployment import (  # noqa: E402
    authorize_deployment_plan,
    prepare_deployment_plan,
    start_deployment,
)
from krcn_core.foundation import load_json  # noqa: E402
from krcn_core.merge_apply import (  # noqa: E402
    MergeApplyError,
    apply_managed_files,
    apply_migrations,
)
from krcn_core.verification import verify_and_commit  # noqa: E402
from krcn_core.merge_plan import prepare_merge_plan  # noqa: E402
from krcn_core.migrations import (  # noqa: E402
    MigrationHandler,
    MigrationHandlerRegistry,
)
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.release import manifest_sha256, validate_release_bundle  # noqa: E402
from krcn_core.release_diff import create_release_diff  # noqa: E402
from krcn_core.rollback import (  # noqa: E402
    RollbackError,
    apply_rollback,
    authorize_rollback_plan,
    prepare_rollback_plan,
)
from krcn_core.update_effects import (  # noqa: E402
    DerivedActionRegistry,
    MigrationRegistry,
    MigrationSpec,
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class ManagedApplyAndMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installation_temp = tempfile.TemporaryDirectory()
        self.release_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.installation_temp.name)
        self.release = Path(self.release_temp.name)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.old_readme = b"Old readme\n"
        self.old_config = b"Old config\n"
        self.new_readme = b"New readme\n"
        self.new_module = b"print('new')\n"
        (self.root / "README.md").write_bytes(self.old_readme)
        (self.root / "config").mkdir()
        (self.root / "config" / "old.txt").write_bytes(self.old_config)
        workspace_directory = self.root / ".krcn" / "workspaces"
        workspace_directory.mkdir(parents=True)
        self.workspace_path = workspace_directory / "sample.json"
        self.workspace_path.write_text(
            json.dumps({"schema_version": 1, "workspace_id": "sample"}),
            encoding="utf-8",
        )
        policy_directory = self.root / ".krcn" / "policies"
        policy_directory.mkdir()
        self.policy_path = policy_directory / "database-read-only.json"
        self.policy_path.write_text(
            '{"policy_id":"database-read-only","effect":"deny-delete"}\n',
            encoding="utf-8",
        )
        runtime = self.root / ".krcn" / "runtime"
        runtime.mkdir()
        state_payload = {
            "schema_ref": "schemas/installation-state.schema.json",
            "schema_version": 1,
            "installation_id": "sample-installation",
            "core_version": "0.1.0",
            "release_id": "krcn-core-0.1.0",
            "source_commit": "a" * 40,
            "managed_files": [
                {
                    "path": "README.md",
                    "sha256": sha256(self.old_readme),
                    "size": len(self.old_readme),
                },
                {
                    "path": "config/old.txt",
                    "sha256": sha256(self.old_config),
                    "size": len(self.old_config),
                },
            ],
            "schema_versions": {"workspace": 1},
            "completed_migrations": [],
            "pending_derived_actions": [],
            "revision": 1,
        }
        self.state_path = runtime / "installation-state.json"
        self.state_path.write_text(
            json.dumps(state_payload, sort_keys=True),
            encoding="utf-8",
        )
        payload = self.release / "payload"
        (payload / "src").mkdir(parents=True)
        (payload / "README.md").write_bytes(self.new_readme)
        (payload / "src" / "new.py").write_bytes(self.new_module)
        self.manifest = {
            "schema_ref": "schemas/release-manifest.schema.json",
            "schema_version": 1,
            "release_id": "krcn-core-0.2.0",
            "core_version": "0.2.0",
            "compatibility": {
                "minimum_core_version": "0.1.0",
                "maximum_core_version": "0.1.9",
            },
            "source_commit": "b" * 40,
            "files": [
                {
                    "path": "README.md",
                    "operation": "upsert",
                    "sha256": sha256(self.new_readme),
                    "size": len(self.new_readme),
                },
                {
                    "path": "config/old.txt",
                    "operation": "delete",
                    "previous_sha256": sha256(self.old_config),
                },
                {
                    "path": "src/new.py",
                    "operation": "upsert",
                    "sha256": sha256(self.new_module),
                    "size": len(self.new_module),
                },
            ],
            "migrations": ["workspace-v2"],
            "derived_actions": [],
        }
        (self.release / "release-manifest.json").write_text(
            json.dumps(self.manifest, sort_keys=True),
            encoding="utf-8",
        )
        self.bundle = validate_release_bundle(
            self.release,
            self.ownership,
            trusted_manifest_sha256=manifest_sha256(self.manifest),
            installed_core_version="0.1.0",
            import_policy=load_json(REPO_ROOT / "config" / "import-policy.json"),
        )
        release_diff = create_release_diff(self.root, self.bundle, self.ownership)
        self.migration_specs = MigrationRegistry(
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
        self.handlers = MigrationHandlerRegistry(
            [MigrationHandler("workspace-v2", self._migrate_workspace)]
        )
        from krcn_core.installation import load_installation_state

        state, _ = load_installation_state(self.root)
        self.merge_plan = prepare_merge_plan(
            release_diff,
            state,
            self.ownership,
            self.migration_specs,
            DerivedActionRegistry(),
            source_commit=self.manifest["source_commit"],
        )

    @staticmethod
    def _migrate_workspace(payload):
        payload["schema_version"] = 2
        payload["migration_marker"] = "workspace-v2"
        return payload

    def tearDown(self) -> None:
        self.installation_temp.cleanup()
        self.release_temp.cleanup()

    def _started(self):
        plan = prepare_deployment_plan(
            self.root,
            self.merge_plan,
            self.ownership,
            self.handlers,
        )
        authorization = authorize_deployment_plan(
            plan,
            expected_plan_id=plan.plan_id,
            approval_id="merge-approval",
        )
        start_deployment(self.root, plan, authorization)
        return plan, authorization

    def test_managed_apply_and_migration_follow_planned_stages(self) -> None:
        policy_before = self.policy_path.read_bytes()
        state_before = self.state_path.read_bytes()
        plan, authorization = self._started()
        managed = apply_managed_files(
            self.root,
            self.release,
            self.bundle,
            plan,
            authorization,
        )
        self.assertEqual(
            {"README.md", "src/new.py"},
            set(managed.applied_paths),
        )
        self.assertEqual(("config/old.txt",), managed.deleted_paths)
        self.assertEqual(self.new_readme, (self.root / "README.md").read_bytes())
        self.assertFalse((self.root / "config" / "old.txt").exists())
        self.assertEqual(
            self.new_module,
            (self.root / "src" / "new.py").read_bytes(),
        )
        migration = apply_migrations(self.root, plan, authorization)
        self.assertEqual(("workspace-v2",), migration.completed_migrations)
        workspace = json.loads(self.workspace_path.read_text(encoding="utf-8"))
        self.assertEqual(2, workspace["schema_version"])
        self.assertEqual("workspace-v2", workspace["migration_marker"])
        self.assertEqual(policy_before, self.policy_path.read_bytes())
        self.assertEqual(state_before, self.state_path.read_bytes())

    def test_payload_tampering_is_rejected_before_first_core_write(self) -> None:
        plan, authorization = self._started()
        (self.release / "payload" / "README.md").write_text(
            "tampered\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MergeApplyError, "payload changed"):
            apply_managed_files(
                self.root,
                self.release,
                self.bundle,
                plan,
                authorization,
            )
        self.assertEqual(self.old_readme, (self.root / "README.md").read_bytes())
        self.assertTrue((self.root / "config" / "old.txt").is_file())
        self.assertFalse((self.root / "src" / "new.py").exists())

    def test_mandatory_verification_commits_state_and_preserves_policy(self) -> None:
        policy_before = self.policy_path.read_bytes()
        plan, authorization = self._started()
        apply_managed_files(
            self.root,
            self.release,
            self.bundle,
            plan,
            authorization,
        )
        apply_migrations(self.root, plan, authorization)
        result = verify_and_commit(self.root, plan, authorization)
        self.assertEqual("completed", result.status)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual("0.2.0", state["core_version"])
        self.assertEqual(2, state["schema_versions"]["workspace"])
        self.assertEqual(["workspace-v2"], state["completed_migrations"])
        self.assertEqual(policy_before, self.policy_path.read_bytes())
        journal_path = (
            self.root
            / ".krcn"
            / "runtime"
            / "deployments"
            / f"{plan.deployment_id}.json"
        )
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual("completed", journal["status"])

    def test_completed_deployment_can_be_rolled_back_exactly(self) -> None:
        original_state = self.state_path.read_bytes()
        original_workspace = self.workspace_path.read_bytes()
        original_policy = self.policy_path.read_bytes()
        plan, authorization = self._started()
        apply_managed_files(
            self.root,
            self.release,
            self.bundle,
            plan,
            authorization,
        )
        apply_migrations(self.root, plan, authorization)
        verify_and_commit(self.root, plan, authorization)
        rollback = prepare_rollback_plan(
            self.root,
            plan.deployment_id,
            self.ownership,
        )
        with self.assertRaisesRegex(RollbackError, "explicit approval"):
            authorize_rollback_plan(
                rollback,
                expected_plan_id=rollback.plan_id,
                approval_id=None,
            )
        rollback_authorization = authorize_rollback_plan(
            rollback,
            expected_plan_id=rollback.plan_id,
            approval_id="rollback-approval",
        )
        result = apply_rollback(
            self.root,
            rollback,
            rollback_authorization,
        )
        self.assertEqual("rolled-back", result.status)
        self.assertEqual(self.old_readme, (self.root / "README.md").read_bytes())
        self.assertEqual(
            self.old_config,
            (self.root / "config" / "old.txt").read_bytes(),
        )
        self.assertFalse((self.root / "src" / "new.py").exists())
        self.assertEqual(original_workspace, self.workspace_path.read_bytes())
        self.assertEqual(original_state, self.state_path.read_bytes())
        self.assertEqual(original_policy, self.policy_path.read_bytes())

    def test_rollback_refuses_to_overwrite_post_deployment_user_change(self) -> None:
        plan, authorization = self._started()
        apply_managed_files(
            self.root,
            self.release,
            self.bundle,
            plan,
            authorization,
        )
        apply_migrations(self.root, plan, authorization)
        verify_and_commit(self.root, plan, authorization)
        self.workspace_path.write_text(
            '{"schema_version":2,"workspace_id":"user-change"}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RollbackError, "rollback conflict"):
            prepare_rollback_plan(
                self.root,
                plan.deployment_id,
                self.ownership,
            )


if __name__ == "__main__":
    unittest.main()
