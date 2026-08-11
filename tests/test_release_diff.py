from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.foundation import load_json  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.release import manifest_sha256, validate_release_bundle  # noqa: E402
from krcn_core.release_diff import create_release_diff  # noqa: E402


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        content = path.read_bytes()
        result[path.relative_to(root).as_posix()] = (
            path.stat().st_mtime_ns,
            sha256(content),
        )
    return result


class ReleaseDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installation_temp = tempfile.TemporaryDirectory()
        self.release_temp = tempfile.TemporaryDirectory()
        self.installation = Path(self.installation_temp.name)
        self.release = Path(self.release_temp.name)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.import_policy = load_json(REPO_ROOT / "config" / "import-policy.json")
        self.old_readme = b"Old readme\n"
        self.old_config = b"Old config\n"
        (self.installation / "README.md").write_bytes(self.old_readme)
        (self.installation / "config").mkdir()
        (self.installation / "config" / "old.txt").write_bytes(self.old_config)
        runtime = self.installation / ".krcn" / "runtime"
        runtime.mkdir(parents=True)
        self.state = {
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
            "completed_migrations": ["already-complete"],
            "pending_derived_actions": [],
            "revision": 1,
        }
        self.state_path = runtime / "installation-state.json"
        self._write_state()
        self.new_readme = b"New readme\n"
        self.new_module = b"print('new')\n"
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
            "migrations": ["already-complete", "workspace-v2"],
            "derived_actions": ["rebuild-source-state"],
        }
        self.manifest_path = self.release / "release-manifest.json"
        self._write_manifest()

    def tearDown(self) -> None:
        self.installation_temp.cleanup()
        self.release_temp.cleanup()

    def _write_state(self) -> None:
        self.state_path.write_text(
            json.dumps(self.state, sort_keys=True),
            encoding="utf-8",
        )

    def _write_manifest(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.manifest, sort_keys=True),
            encoding="utf-8",
        )

    def _bundle(self):
        return validate_release_bundle(
            self.release,
            self.ownership,
            trusted_manifest_sha256=manifest_sha256(self.manifest),
            installed_core_version="0.1.0",
            import_policy=self.import_policy,
        )

    def test_diff_classifies_changes_without_mutation_or_path_leak(self) -> None:
        before = tree_snapshot(self.installation)
        release_before = tree_snapshot(self.release)
        diff = create_release_diff(
            self.installation,
            self._bundle(),
            self.ownership,
        )
        self.assertTrue(diff.applicable)
        self.assertEqual(
            {"README.md": "update", "config/old.txt": "delete", "src/new.py": "create"},
            {item.path: item.action for item in diff.changes},
        )
        self.assertEqual(("workspace-v2",), diff.pending_migrations)
        self.assertEqual(before, tree_snapshot(self.installation))
        self.assertEqual(release_before, tree_snapshot(self.release))
        self.assertNotIn(str(self.installation), json.dumps(diff.public_summary()))
        self.assertNotIn(str(self.release), json.dumps(diff.public_summary()))

    def test_unchanged_target_is_classified(self) -> None:
        (self.installation / "README.md").write_bytes(self.new_readme)
        self.state["managed_files"][0] = {
            "path": "README.md",
            "sha256": sha256(self.new_readme),
            "size": len(self.new_readme),
        }
        self._write_state()
        diff = create_release_diff(self.installation, self._bundle(), self.ownership)
        action = next(item.action for item in diff.changes if item.path == "README.md")
        self.assertEqual("unchanged", action)

    def test_local_managed_change_is_a_conflict(self) -> None:
        (self.installation / "README.md").write_text(
            "Local change\n",
            encoding="utf-8",
        )
        diff = create_release_diff(self.installation, self._bundle(), self.ownership)
        self.assertFalse(diff.applicable)
        self.assertIn(
            ("managed-modified", "README.md"),
            {(item.conflict_code, item.path) for item in diff.conflicts},
        )
        self.assertNotIn("README.md", {item.path for item in diff.changes})

    def test_unmanaged_overlap_and_delete_base_mismatch_are_conflicts(self) -> None:
        target = self.installation / "src" / "new.py"
        target.parent.mkdir()
        target.write_text("local\n", encoding="utf-8")
        delete_entry = next(
            item
            for item in self.manifest["files"]
            if item["operation"] == "delete"
        )
        delete_entry["previous_sha256"] = "0" * 64
        self._write_manifest()
        diff = create_release_diff(self.installation, self._bundle(), self.ownership)
        codes = {item.conflict_code for item in diff.conflicts}
        self.assertIn("unmanaged-overlap", codes)
        self.assertIn("release-base-mismatch", codes)

    def test_interrupted_deployment_blocks_new_diff(self) -> None:
        journal_directory = (
            self.installation / ".krcn" / "runtime" / "deployments"
        )
        journal_directory.mkdir()
        (journal_directory / "deploy-old.json").write_text(
            json.dumps({"deployment_id": "deploy-old", "status": "verifying"}),
            encoding="utf-8",
        )
        diff = create_release_diff(self.installation, self._bundle(), self.ownership)
        self.assertFalse(diff.applicable)
        self.assertIn(
            "interrupted-deployment",
            {item.conflict_code for item in diff.conflicts},
        )


if __name__ == "__main__":
    unittest.main()
