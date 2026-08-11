from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.repo_local_migration import (  # noqa: E402
    RepoLocalMigrationError,
    apply_repo_local_migration,
    prepare_repo_local_migration,
)


def snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


class RepoLocalMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.repository = root / "core-clone"
        self.source = self.repository / ".krcn"
        self.target = root / "portable-home"
        self.backup = root / "migration-backup.zip"
        (self.source / "policies").mkdir(parents=True)
        (self.source / "policies" / "select-only.json").write_text(
            json.dumps({"effect": "deny", "operation": "delete"}),
            encoding="utf-8",
        )
        (self.source / "memory").mkdir()
        (self.source / "memory" / "preference.json").write_text(
            json.dumps({"language": "tr"}),
            encoding="utf-8",
        )
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _authorizations(plan):
        return {
            mutation.plan_id: authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, True),
                approval=ApprovalEvidence(mutation.plan_id, "migration-approval", True),
            )
            for mutation in plan.effect_plans
        }

    def test_migration_creates_backup_and_target_without_deleting_source(self) -> None:
        before = snapshot(self.source)
        plan = prepare_repo_local_migration(
            self.repository,
            self.target,
            self.backup,
            self.ownership,
        )
        summary = plan.public_summary()
        self.assertTrue(summary["source_preserved"])
        self.assertFalse(summary["source_deleted"])
        self.assertNotIn(str(self.repository), json.dumps(summary))
        result = apply_repo_local_migration(plan, self._authorizations(plan))
        self.assertEqual(before, snapshot(self.source))
        self.assertTrue(self.backup.is_file())
        self.assertEqual(before, snapshot(self.target))
        self.assertTrue(result.rollback_ready)
        self.assertTrue(result.source_preserved)

    def test_migration_requires_target_outside_repository(self) -> None:
        with self.assertRaisesRegex(RepoLocalMigrationError, "outside the repository"):
            prepare_repo_local_migration(
                self.repository,
                self.repository / "portable-home",
                self.backup,
                self.ownership,
            )

    def test_migration_requires_every_effect_authorization(self) -> None:
        plan = prepare_repo_local_migration(
            self.repository,
            self.target,
            self.backup,
            self.ownership,
        )
        authorizations = self._authorizations(plan)
        authorizations.pop(plan.restore_mutation.plan_id)
        with self.assertRaisesRegex(RepoLocalMigrationError, "every migration effect"):
            apply_repo_local_migration(plan, authorizations)
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
