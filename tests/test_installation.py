from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.installation import (  # noqa: E402
    InstallationError,
    inspect_installation,
    parse_installation_state,
)
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        content = path.read_bytes()
        result[path.relative_to(root).as_posix()] = (
            path.stat().st_mtime_ns,
            digest(content),
        )
    return result


class InstallationInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.readme_content = b"Synthetic core\n"
        (self.root / "README.md").write_bytes(self.readme_content)
        (self.root / ".krcn" / "runtime").mkdir(parents=True)
        (self.root / ".krcn" / "projects").mkdir(parents=True)
        (self.root / ".krcn" / "projects" / "sample.json").write_text(
            '{"user":"data"}\n',
            encoding="utf-8",
        )
        (self.root / ".env").write_text("local-value\n", encoding="utf-8")
        (self.root / "notes.local").write_text("unmanaged\n", encoding="utf-8")
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
                    "sha256": digest(self.readme_content),
                    "size": len(self.readme_content),
                }
            ],
            "schema_versions": {"workspace": 1},
            "completed_migrations": [],
            "pending_derived_actions": [],
            "revision": 1,
        }
        self.state_path = (
            self.root / ".krcn" / "runtime" / "installation-state.json"
        )
        self.state_path.write_text(
            json.dumps(self.state, sort_keys=True),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_inspection_is_read_only_redacted_and_classified(self) -> None:
        before = snapshot(self.root)
        inspection = inspect_installation(self.root, self.ownership)
        after = snapshot(self.root)
        summary = inspection.public_summary()
        self.assertEqual(before, after)
        self.assertTrue(summary["managed_clean"])
        self.assertEqual(["README.md"], summary["managed_files"]["verified"])
        self.assertGreaterEqual(summary["ownership_counts"]["user-data"], 1)
        self.assertGreaterEqual(summary["ownership_counts"]["secrets"], 1)
        self.assertGreaterEqual(summary["ownership_counts"]["unmanaged"], 1)
        self.assertNotIn(str(self.root), json.dumps(summary))

    def test_modified_and_missing_managed_files_are_reported(self) -> None:
        (self.root / "README.md").write_text("Modified\n", encoding="utf-8")
        modified = inspect_installation(self.root, self.ownership)
        self.assertEqual(("README.md",), modified.managed_modified)
        (self.root / "README.md").unlink()
        missing = inspect_installation(self.root, self.ownership)
        self.assertEqual(("README.md",), missing.managed_missing)

    def test_unregistered_installation_is_reported_without_mutation(self) -> None:
        self.state_path.unlink()
        before = snapshot(self.root)
        inspection = inspect_installation(self.root, self.ownership)
        self.assertFalse(inspection.state_present)
        self.assertEqual(before, snapshot(self.root))

    def test_interrupted_deployment_is_reported_without_path(self) -> None:
        journal_directory = self.root / ".krcn" / "runtime" / "deployments"
        journal_directory.mkdir()
        (journal_directory / "deploy-sample.json").write_text(
            json.dumps(
                {"deployment_id": "deploy-sample", "status": "applying"}
            ),
            encoding="utf-8",
        )
        inspection = inspect_installation(self.root, self.ownership)
        self.assertEqual(
            ({"deployment_id": "deploy-sample", "status": "applying"},),
            inspection.interrupted_deployments,
        )
        self.assertNotIn(str(self.root), json.dumps(inspection.public_summary()))

    def test_failed_deployment_is_interrupted_and_unknown_status_fails_closed(self) -> None:
        journal_directory = self.root / ".krcn" / "runtime" / "deployments"
        journal_directory.mkdir()
        journal = journal_directory / "deploy-failed.json"
        journal.write_text(
            json.dumps({"deployment_id": "deploy-failed", "status": "failed"}),
            encoding="utf-8",
        )
        inspection = inspect_installation(self.root, self.ownership)
        self.assertEqual(
            ({"deployment_id": "deploy-failed", "status": "failed"},),
            inspection.interrupted_deployments,
        )
        journal.write_text(
            json.dumps(
                {"deployment_id": "deploy-failed", "status": "backing-up"}
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InstallationError, "status is invalid"):
            inspect_installation(self.root, self.ownership)

    def test_managed_user_data_path_is_rejected(self) -> None:
        changed = dict(self.state)
        changed["managed_files"] = [
            {
                "path": ".krcn/projects/sample.json",
                "sha256": "0" * 64,
                "size": 0,
            }
        ]
        self.state_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(InstallationError, "core ownership"):
            inspect_installation(self.root, self.ownership)

    def test_duplicate_and_nonportable_managed_paths_are_rejected(self) -> None:
        changed = dict(self.state)
        changed["managed_files"] = [
            {"path": "../outside", "sha256": "0" * 64, "size": 0}
        ]
        with self.assertRaisesRegex(InstallationError, "stay within"):
            parse_installation_state(changed)
        changed["managed_files"] = [self.state["managed_files"][0]] * 2
        with self.assertRaisesRegex(InstallationError, "unique"):
            parse_installation_state(changed)


if __name__ == "__main__":
    unittest.main()
