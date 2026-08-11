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
    DeploymentError,
    authorize_deployment_plan,
    prepare_deployment_plan,
    start_deployment,
    write_deployment_status,
)
from krcn_core.installation import InstallationState, ManagedFile  # noqa: E402
from krcn_core.merge_plan import prepare_merge_plan  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.release_diff import FileChange, ReleaseDiff  # noqa: E402
from krcn_core.update_effects import (  # noqa: E402
    DerivedActionRegistry,
    DerivedActionSpec,
    MigrationRegistry,
    MigrationSpec,
    UpdateEffectError,
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class DeploymentBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.readme = b"Old readme\n"
        self.old_config = b"Old config\n"
        (self.root / "README.md").write_bytes(self.readme)
        (self.root / "config").mkdir()
        (self.root / "config" / "old.txt").write_bytes(self.old_config)
        workspace_directory = self.root / ".krcn" / "workspaces"
        workspace_directory.mkdir(parents=True)
        self.workspace_path = workspace_directory / "sample.json"
        self.workspace_path.write_text(
            '{"schema_version":1,"workspace_id":"sample"}\n',
            encoding="utf-8",
        )
        derived_directory = self.root / ".krcn" / "derived" / "source-states"
        derived_directory.mkdir(parents=True)
        self.derived_path = derived_directory / "sample.json"
        self.derived_path.write_text('{"derived":true}\n', encoding="utf-8")
        runtime = self.root / ".krcn" / "runtime"
        runtime.mkdir()
        self.state = InstallationState(
            installation_id="sample-installation",
            core_version="0.1.0",
            release_id="krcn-core-0.1.0",
            source_commit="a" * 40,
            managed_files=(
                ManagedFile("README.md", sha256(self.readme), len(self.readme)),
                ManagedFile(
                    "config/old.txt",
                    sha256(self.old_config),
                    len(self.old_config),
                ),
            ),
            schema_versions={"workspace": 1},
            completed_migrations=(),
            pending_derived_actions=(),
            revision=1,
        )
        self.state_path = runtime / "installation-state.json"
        self.state_path.write_text(
            json.dumps(self.state.as_payload(), sort_keys=True),
            encoding="utf-8",
        )
        new_readme = b"New readme\n"
        new_module = b"print('new')\n"
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
                    sha256(self.readme),
                    sha256(new_readme),
                    len(new_readme),
                ),
                FileChange(
                    "config/old.txt",
                    "delete",
                    "core",
                    sha256(self.old_config),
                    None,
                    None,
                ),
                FileChange(
                    "src/new.py",
                    "create",
                    "core",
                    None,
                    sha256(new_module),
                    len(new_module),
                ),
            ),
            conflicts=(),
            pending_migrations=("workspace-v2",),
            derived_actions=("rebuild-source-state",),
        )
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
        self.merge_plan = prepare_merge_plan(
            self.diff,
            self.state,
            self.ownership,
            self.migrations,
            self.derived,
            source_commit="b" * 40,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_backup_plan_covers_core_state_user_data_and_derived(self) -> None:
        plan = prepare_deployment_plan(
            self.root,
            self.merge_plan,
            self.ownership,
        )
        entries = {item.target_ref: item for item in plan.backup_manifest.entries}
        self.assertTrue(entries["README.md"].existed)
        self.assertTrue(entries["config/old.txt"].existed)
        self.assertFalse(entries["src/new.py"].existed)
        self.assertTrue(entries[".krcn/runtime/installation-state.json"].existed)
        self.assertTrue(entries[".krcn/workspaces/sample.json"].existed)
        self.assertTrue(entries[".krcn/derived/source-states/sample.json"].existed)
        self.assertNotIn(str(self.root), json.dumps(plan.public_summary()))

    def test_exact_deployment_plan_creates_verified_backup_and_journal(self) -> None:
        plan = prepare_deployment_plan(
            self.root,
            self.merge_plan,
            self.ownership,
        )
        with self.assertRaisesRegex(DeploymentError, "exact dry-run"):
            authorize_deployment_plan(
                plan,
                expected_plan_id="0" * 64,
                approval_id="deployment-approval",
            )
        authorization = authorize_deployment_plan(
            plan,
            expected_plan_id=plan.plan_id,
            approval_id="deployment-approval",
        )
        original = {
            "readme": (self.root / "README.md").read_bytes(),
            "config": (self.root / "config" / "old.txt").read_bytes(),
            "workspace": self.workspace_path.read_bytes(),
            "derived": self.derived_path.read_bytes(),
            "state": self.state_path.read_bytes(),
        }
        result = start_deployment(self.root, plan, authorization)
        self.assertEqual("backed-up", result.status)
        journal_path = (
            self.root
            / ".krcn"
            / "runtime"
            / "deployments"
            / f"{plan.deployment_id}.json"
        )
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual("backed-up", journal["status"])
        manifest_path = (
            self.root
            / ".krcn"
            / "checkpoints"
            / plan.deployment_id
            / "backup-manifest.json"
        )
        self.assertTrue(manifest_path.is_file())
        self.assertEqual(original["readme"], (self.root / "README.md").read_bytes())
        self.assertEqual(
            original["config"],
            (self.root / "config" / "old.txt").read_bytes(),
        )
        self.assertEqual(original["workspace"], self.workspace_path.read_bytes())
        self.assertEqual(original["derived"], self.derived_path.read_bytes())
        self.assertEqual(original["state"], self.state_path.read_bytes())

    def test_changed_source_blocks_backup_before_journal_write(self) -> None:
        plan = prepare_deployment_plan(
            self.root,
            self.merge_plan,
            self.ownership,
        )
        authorization = authorize_deployment_plan(
            plan,
            expected_plan_id=plan.plan_id,
            approval_id="deployment-approval",
        )
        (self.root / "README.md").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentError, "changed before deployment"):
            start_deployment(self.root, plan, authorization)
        journal = (
            self.root
            / ".krcn"
            / "runtime"
            / "deployments"
            / f"{plan.deployment_id}.json"
        )
        self.assertFalse(journal.exists())

    def test_user_data_change_changes_final_deployment_plan(self) -> None:
        first = prepare_deployment_plan(
            self.root,
            self.merge_plan,
            self.ownership,
        )
        self.workspace_path.write_text(
            '{"schema_version":1,"workspace_id":"changed"}\n',
            encoding="utf-8",
        )
        second = prepare_deployment_plan(
            self.root,
            self.merge_plan,
            self.ownership,
        )
        self.assertNotEqual(first.plan_id, second.plan_id)

    def test_journal_cannot_skip_required_deployment_stages(self) -> None:
        plan = prepare_deployment_plan(
            self.root,
            self.merge_plan,
            self.ownership,
        )
        authorization = authorize_deployment_plan(
            plan,
            expected_plan_id=plan.plan_id,
            approval_id="deployment-approval",
        )
        start_deployment(self.root, plan, authorization)
        with self.assertRaisesRegex(DeploymentError, "transition"):
            write_deployment_status(
                self.root,
                plan,
                authorization,
                "completed",
            )

    def test_secret_migration_descriptor_is_prohibited(self) -> None:
        with self.assertRaisesRegex(UpdateEffectError, "may not target"):
            MigrationSpec(
                "secret-v2",
                "secret",
                1,
                2,
                "secrets",
                ".krcn/secrets",
            )


if __name__ == "__main__":
    unittest.main()
