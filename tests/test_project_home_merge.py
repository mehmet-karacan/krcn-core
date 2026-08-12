from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.json_documents import pretty_json_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_home_merge import (  # noqa: E402
    ProjectHomeMergeError,
    apply_project_home_merge,
    prepare_project_home_merge,
)


def snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def record_bytes(record_id: str, identity_field: str) -> bytes:
    payload = {"schema_version": 1, identity_field: record_id}
    payload_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    ).hexdigest()
    return pretty_json_bytes(
        {
            "record_type": identity_field.removesuffix("_id"),
            "record_id": record_id,
            "revision": 1,
            "payload_sha256": payload_hash,
            "payload": payload,
        }
    )


class ProjectHomeMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "project" / ".krcn"
        self.target = self.root / "core" / ".krcn"
        self.backups = self.root / "backups" / "merge-1"
        self.source.mkdir(parents=True)
        self.target.mkdir(parents=True)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)

        selected = {
            "projects/sample.json": record_bytes("sample", "project_id"),
            "workspaces/sample-workspace.json": record_bytes(
                "sample-workspace", "workspace_id"
            ),
            "policies/select-only.json": pretty_json_bytes(
                {"schema_version": 1, "effect": "deny", "operation": "delete"}
            ),
        }
        for relative, content in selected.items():
            path = self.source.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        excluded = {
            "project-home.json": b"{}\n",
            "derived/source-states/sample.json": b"{}\n",
            "local-data/reports/summary.md": b"machine-local\n",
            "locks/records/sample.lock": b"lock",
            "secrets/provider.txt": b"sentetik-gizli-deger",
        }
        for relative, content in excluded.items():
            path = self.source.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        staging = self.target / "staging" / "package-1" / "package-manifest.json"
        staging.parent.mkdir(parents=True)
        staging.write_text("staging-content\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def authorizations(plan):
        return {
            mutation.plan_id: authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, True),
                approval=ApprovalEvidence(mutation.plan_id, "merge-approval", True),
            )
            for mutation in plan.effect_plans
        }

    def test_merge_preserves_source_target_and_excluded_areas(self) -> None:
        source_before = snapshot(self.source)
        target_before = snapshot(self.target)
        plan = prepare_project_home_merge(
            self.source,
            self.target,
            self.backups,
            self.ownership,
        )
        summary = plan.public_summary()
        self.assertEqual(3, summary["merge_entry_count"])
        self.assertTrue(summary["source_preserved"])
        self.assertTrue(summary["target_existing_content_preserved"])
        self.assertFalse(summary["derived_included"])
        self.assertFalse(summary["local_data_included"])
        self.assertFalse(summary["runtime_included"])
        self.assertFalse(summary["secret_values_included"])
        self.assertNotIn(str(self.source), json.dumps(summary))
        self.assertNotIn(str(self.target), json.dumps(summary))

        result = apply_project_home_merge(plan, self.authorizations(plan))

        self.assertEqual(source_before, snapshot(self.source))
        for relative, digest in target_before.items():
            self.assertEqual(digest, snapshot(self.target)[relative])
        self.assertEqual(3, result.merged_entry_count)
        self.assertTrue((self.target / "projects" / "sample.json").is_file())
        self.assertTrue((self.target / "policies" / "select-only.json").is_file())
        self.assertFalse((self.target / "project-home.json").exists())
        self.assertFalse((self.target / "derived").exists())
        self.assertFalse((self.target / "local-data").exists())
        self.assertFalse((self.target / "locks").exists())
        self.assertFalse((self.target / "secrets").exists())

        for archive_name in ("source-home-backup.zip", "target-home-backup.zip"):
            archive_path = self.backups / archive_name
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                content = b"".join(archive.read(name) for name in archive.namelist())
                self.assertNotIn(b"sentetik-gizli-deger", content)
                self.assertFalse(any("locks/" in name for name in archive.namelist()))

    def test_conflicting_record_fails_closed_before_backup(self) -> None:
        target_record = self.target / "projects" / "sample.json"
        target_record.parent.mkdir(parents=True)
        target_record.write_bytes(record_bytes("other", "project_id"))
        before = snapshot(self.target)
        with self.assertRaisesRegex(ProjectHomeMergeError, "merge conflict"):
            prepare_project_home_merge(
                self.source,
                self.target,
                self.backups,
                self.ownership,
            )
        self.assertEqual(before, snapshot(self.target))
        self.assertFalse(self.backups.exists())

    def test_stale_plan_is_rejected_without_target_writes(self) -> None:
        plan = prepare_project_home_merge(
            self.source,
            self.target,
            self.backups,
            self.ownership,
        )
        target_before = snapshot(self.target)
        (self.source / "projects" / "sample.json").write_bytes(
            record_bytes("changed", "project_id")
        )
        with self.assertRaisesRegex(ProjectHomeMergeError, "changed"):
            apply_project_home_merge(plan, self.authorizations(plan))
        self.assertEqual(target_before, snapshot(self.target))

    def test_all_clients_receive_the_same_merge_plan(self) -> None:
        service = KrcnApplicationService(
            REPO_ROOT,
            LocalWorkspaceStore(self.target, self.ownership),
        )
        arguments = {
            "source_home": str(self.source),
            "target_home": str(self.target),
            "backup_directory": str(self.backups),
        }
        plans = []
        for client in ("cli", "sdk", "mcp", "plugin", "codex", "claude"):
            response = service.execute(
                ServiceRequest(client, "portability.merge-project-home", arguments)
            )
            self.assertEqual("planned", response.status)
            plans.append(response.data["plan"])
        self.assertTrue(all(plan == plans[0] for plan in plans))


if __name__ == "__main__":
    unittest.main()
