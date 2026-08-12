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
from krcn_core.portable_backup import apply_portable_backup, prepare_portable_backup  # noqa: E402
from krcn_core.portable_restore import (  # noqa: E402
    PortableRestoreError,
    apply_portable_restore,
    prepare_portable_restore,
)


class PortableRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.source_home = root / "source-home"
        self.target_home = root / "restored-home"
        self.external_source = root / "external-project"
        self.archive = root / "portable.zip"
        self.external_source.mkdir()
        (self.external_source / "main.py").write_text("print('external')\n", encoding="utf-8")
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.source_home, self.ownership)
        self._put("source-bindings", "sample-project-local", self._binding_payload())
        (self.source_home / "policies").mkdir()
        (self.source_home / "policies" / "database-select-only.json").write_text(
            json.dumps({"effect": "deny", "operation": "delete"}),
            encoding="utf-8",
        )
        backup = prepare_portable_backup(self.source_home, self.archive, self.ownership)
        apply_portable_backup(backup, self._authorize(backup.mutation, "backup"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _binding_payload(self) -> dict:
        return {
            "schema_version": 1,
            "binding_id": "sample-project-local",
            "source_id": "sample-project",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": str(self.external_source)},
            "default_access": "read-only",
            "capabilities": ["read", "metadata"],
            "policy_refs": [],
            "revision": 1,
        }

    def _put(self, record_type: str, record_id: str, payload: dict) -> None:
        plan = self.store.prepare_put(record_type, record_id, payload, expected_revision=0)
        self.store.apply_put(plan, self._authorize(plan.mutation, "setup"))

    @staticmethod
    def _authorize(mutation, approval_id):
        return authorize_mutation(
            mutation,
            dry_run=DryRunEvidence(mutation.plan_id, True),
            approval=ApprovalEvidence(mutation.plan_id, approval_id, True),
        )

    def test_restore_preserves_policy_and_requires_external_rebind(self) -> None:
        source_bytes = (self.external_source / "main.py").read_bytes()
        plan = prepare_portable_restore(self.archive, self.target_home, self.ownership)
        self.assertEqual(1, plan.public_summary()["rebind_required_count"])
        result = apply_portable_restore(
            plan,
            self._authorize(plan.mutation, "restore"),
        )
        policy = self.target_home / "policies" / "database-select-only.json"
        self.assertEqual(
            {"effect": "deny", "operation": "delete"},
            json.loads(policy.read_text(encoding="utf-8")),
        )
        restored_store = LocalWorkspaceStore(self.target_home, self.ownership)
        binding = restored_store.read("source-bindings", "sample-project-local")
        self.assertEqual("unbound", binding.payload["locator"]["kind"])
        self.assertEqual(1, result.rebind_required_count)
        self.assertEqual(source_bytes, (self.external_source / "main.py").read_bytes())
        self.assertFalse((self.target_home / "external-project").exists())

    def test_restore_rejects_nonempty_target(self) -> None:
        self.target_home.mkdir()
        (self.target_home / "existing.txt").write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(PortableRestoreError, "empty"):
            prepare_portable_restore(self.archive, self.target_home, self.ownership)
        self.assertEqual("preserve", (self.target_home / "existing.txt").read_text())

    def test_restore_rejects_undeclared_or_traversal_payload(self) -> None:
        malicious = self.archive.parent / "malicious.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("manifest.json", "{}")
            archive.writestr("payload/../outside.txt", "bad")
        with self.assertRaises(PortableRestoreError):
            prepare_portable_restore(malicious, self.target_home, self.ownership)
        self.assertFalse((self.target_home.parent / "outside.txt").exists())

    def test_restore_rejects_corrupted_backup_without_creating_target(self) -> None:
        corrupted = self.archive.parent / "corrupted.zip"
        corrupted.write_bytes(self.archive.read_bytes()[:37])
        with self.assertRaisesRegex(PortableRestoreError, "invalid"):
            prepare_portable_restore(corrupted, self.target_home, self.ownership)
        self.assertFalse(self.target_home.exists())


if __name__ == "__main__":
    unittest.main()
