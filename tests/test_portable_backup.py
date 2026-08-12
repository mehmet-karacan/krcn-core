from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.portable_backup import (  # noqa: E402
    PortableBackupError,
    apply_portable_backup,
    prepare_portable_backup,
)


class PortableBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.user_home = root / "krcn-home"
        self.source_root = root / "external-project"
        self.output = root / "backups" / "portable.krcn.zip"
        self.source_root.mkdir()
        (self.source_root / "main.py").write_text("print('external')\n", encoding="utf-8")
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.user_home, self.ownership)
        self._put_binding()
        (self.user_home / "policies").mkdir()
        (self.user_home / "policies" / "database-select-only.json").write_text(
            json.dumps({"effect": "deny", "operation": "delete"}),
            encoding="utf-8",
        )
        (self.user_home / "secrets").mkdir()
        (self.user_home / "secrets" / "provider.txt").write_text(
            "synthetic-secret-value",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _put_binding(self) -> None:
        payload = {
            "schema_version": 1,
            "binding_id": "external-project-local",
            "source_id": "external-project",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": str(self.source_root)},
            "default_access": "read-only",
            "capabilities": ["read", "metadata"],
            "policy_refs": [],
            "revision": 1,
        }
        plan = self.store.prepare_put(
            "source-bindings",
            "external-project-local",
            payload,
            expected_revision=0,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            approval=ApprovalEvidence(plan.mutation.plan_id, "setup", True),
        )
        self.store.apply_put(plan, authorization)

    @staticmethod
    def _authorize(plan):
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            approval=ApprovalEvidence(plan.mutation.plan_id, "backup-approval", True),
        )

    def test_backup_excludes_secrets_and_external_source_content(self) -> None:
        source_before = (self.source_root / "main.py").read_bytes()
        plan = prepare_portable_backup(self.user_home, self.output, self.ownership)
        summary = plan.public_summary()
        self.assertFalse(summary["source_content_included"])
        self.assertFalse(summary["secret_values_included"])
        self.assertEqual(1, summary["excluded_secret_count"])
        result = apply_portable_backup(plan, self._authorize(plan))
        self.assertTrue(self.output.is_file())
        self.assertEqual(source_before, (self.source_root / "main.py").read_bytes())
        with zipfile.ZipFile(self.output) as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertNotIn("payload/secrets/provider.txt", names)
            self.assertFalse(any(name.startswith("payload/locks/") for name in names))
            archive_bytes = b"".join(archive.read(name) for name in names)
            self.assertNotIn(str(self.source_root).encode(), archive_bytes)
            self.assertNotIn(b"synthetic-secret-value", archive_bytes)
            self.assertNotIn(b"print('external')", archive_bytes)
            binding_name = "payload/source-bindings/external-project-local.json"
            binding = json.loads(archive.read(binding_name))
            self.assertEqual("unbound", binding["payload"]["locator"]["kind"])
            self.assertEqual(
                "external-source-required",
                binding["payload"]["locator"]["value"],
            )
        self.assertEqual(plan.backup_id, result.backup_id)

    def test_changed_user_home_blocks_stale_backup_plan(self) -> None:
        plan = prepare_portable_backup(self.user_home, self.output, self.ownership)
        (self.user_home / "policies" / "new-policy.json").write_text(
            "{}",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PortableBackupError, "changed"):
            apply_portable_backup(plan, self._authorize(plan))
        self.assertFalse(self.output.exists())

    def test_secret_like_content_outside_secret_area_fails_closed(self) -> None:
        value = "github" + "_pat_" + "a" * 24
        (self.user_home / "policies" / "bad.txt").write_text(value, encoding="utf-8")
        with self.assertRaisesRegex(PortableBackupError, "secret-like"):
            prepare_portable_backup(self.user_home, self.output, self.ownership)

    def test_archive_cannot_be_created_inside_user_home(self) -> None:
        with self.assertRaisesRegex(PortableBackupError, "outside"):
            prepare_portable_backup(
                self.user_home,
                self.user_home / "backup.zip",
                self.ownership,
            )


if __name__ == "__main__":
    unittest.main()
