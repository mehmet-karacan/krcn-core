from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_home import choose_project_home, resolve_project_home  # noqa: E402
from krcn_core.project_home_portability import (  # noqa: E402
    ProjectHomePortabilityError,
    apply_project_home_migration,
    apply_project_home_restore,
    prepare_project_home_migration,
    prepare_project_home_restore,
)


def snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )


class ProjectHomePortabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_home = self.root / "merkezi-krcn"
        self.project = self.root / "proje"
        self.project.mkdir()
        self.project_source = self.project / "main.py"
        self.project_source.write_text("print('yerinde')\n", encoding="utf-8")
        self.backup = self.root / "yedekler" / "proje-krcn.zip"
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.source_home, self.ownership)
        self._put_binding()
        (self.source_home / "policies").mkdir()
        self.policy = self.source_home / "policies" / "veritabani-salt-okunur.json"
        self.policy.write_bytes(
            '{"effect":"deny","operation":"delete","allow":["select"]}\n'.encode(
                "utf-8"
            )
        )
        (self.source_home / "secrets").mkdir()
        (self.source_home / "secrets" / "provider.txt").write_text(
            "sentetik-gizli-deger",
            encoding="utf-8",
        )
        initialized = git(self.project, "init", "--quiet")
        self.assertEqual(0, initialized.returncode, initialized.stderr)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _put_binding(self) -> None:
        payload = {
            "schema_version": 1,
            "binding_id": "proje-local",
            "source_id": "proje",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": str(self.project)},
            "default_access": "read-only",
            "capabilities": ["read", "metadata"],
            "policy_refs": ["veritabani-salt-okunur"],
            "revision": 1,
        }
        plan = self.store.prepare_put(
            "source-bindings", "proje-local", payload, expected_revision=0
        )
        self.store.apply_put(
            plan,
            authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, True),
                approval=ApprovalEvidence(plan.mutation.plan_id, "kurulum", True),
            ),
        )

    @staticmethod
    def _authorizations(plan):
        return {
            mutation.plan_id: authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, True),
                approval=ApprovalEvidence(
                    mutation.plan_id, "tasima-onayi", True
                ),
            )
            for mutation in plan.effect_plans
        }

    def _resolution(self, project: Path):
        proposal = resolve_project_home(project, environ={})
        selected = choose_project_home(proposal, "use-default")
        assert selected is not None
        return selected

    def test_migration_preserves_source_policy_and_project_content(self) -> None:
        source_before = snapshot(self.source_home)
        project_before = self.project_source.read_bytes()
        policy_before = self.policy.read_bytes()
        plan = prepare_project_home_migration(
            self.source_home,
            self._resolution(self.project),
            self.backup,
            self.ownership,
        )
        summary = plan.public_summary()
        self.assertTrue(summary["source_preserved"])
        self.assertFalse(summary["source_content_included"])
        self.assertFalse(summary["secret_values_included"])
        self.assertNotIn(str(self.source_home), json.dumps(summary))
        result = apply_project_home_migration(plan, self._authorizations(plan))
        target = self.project / ".krcn"
        self.assertTrue((target / "project-home.json").is_file())
        self.assertEqual(policy_before, (target / "policies" / self.policy.name).read_bytes())
        self.assertEqual(source_before, snapshot(self.source_home))
        self.assertEqual(project_before, self.project_source.read_bytes())
        self.assertFalse((target / "main.py").exists())
        self.assertTrue(result.source_preserved)
        self.assertTrue(result.rollback_ready)
        self.assertIn("/.krcn/", (self.project / ".git" / "info" / "exclude").read_text())
        with zipfile.ZipFile(self.backup) as archive:
            names = set(archive.namelist())
            self.assertIn("payload/project-home.json", names)
            self.assertNotIn("payload/secrets/provider.txt", names)
            payload = b"".join(archive.read(name) for name in names)
            self.assertNotIn(project_before, payload)
            self.assertNotIn(b"sentetik-gizli-deger", payload)

    def test_clean_clone_restore_recovers_home_and_git_protection(self) -> None:
        migration = prepare_project_home_migration(
            self.source_home,
            self._resolution(self.project),
            self.backup,
            self.ownership,
        )
        apply_project_home_migration(migration, self._authorizations(migration))
        clean_project = self.root / "temiz-klon"
        clean_project.mkdir()
        (clean_project / "main.py").write_bytes(self.project_source.read_bytes())
        initialized = git(clean_project, "init", "--quiet")
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        restore = prepare_project_home_restore(
            self.backup,
            self._resolution(clean_project),
            self.ownership,
        )
        result = apply_project_home_restore(restore, self._authorizations(restore))
        target = clean_project / ".krcn"
        self.assertTrue(result["project_home_verified"])
        self.assertEqual(
            self.policy.read_bytes(),
            (target / "policies" / self.policy.name).read_bytes(),
        )
        self.assertEqual(self.project_source.read_bytes(), (clean_project / "main.py").read_bytes())
        self.assertFalse((target / "main.py").exists())
        self.assertEqual(
            0,
            git(
                clean_project,
                "check-ignore",
                "--no-index",
                "-q",
                "--",
                ".krcn/project-home.json",
            ).returncode,
        )

    def test_nonempty_target_is_never_overwritten(self) -> None:
        target = self.project / ".krcn"
        target.mkdir()
        existing = target / "kullanici.txt"
        existing.write_text("koru", encoding="utf-8")
        with self.assertRaisesRegex(ProjectHomePortabilityError, "empty"):
            prepare_project_home_migration(
                self.source_home,
                self._resolution(self.project),
                self.backup,
                self.ownership,
            )
        self.assertEqual("koru", existing.read_text(encoding="utf-8"))

    def test_interrupted_migration_keeps_backup_source_and_git_state(self) -> None:
        exclude = self.project / ".git" / "info" / "exclude"
        exclude_before = exclude.read_bytes()
        source_before = snapshot(self.source_home)
        plan = prepare_project_home_migration(
            self.source_home,
            self._resolution(self.project),
            self.backup,
            self.ownership,
        )
        with patch(
            "krcn_core.project_home_portability.apply_portable_restore",
            side_effect=RuntimeError("sentetik restore kesintisi"),
        ):
            with self.assertRaisesRegex(RuntimeError, "restore kesintisi"):
                apply_project_home_migration(plan, self._authorizations(plan))
        self.assertTrue(self.backup.is_file())
        self.assertEqual(source_before, snapshot(self.source_home))
        self.assertFalse((self.project / ".krcn").exists())
        self.assertEqual(exclude_before, exclude.read_bytes())

    def test_all_clients_receive_the_same_migration_plan(self) -> None:
        service = KrcnApplicationService(REPO_ROOT, self.store)
        arguments = {
            "source_home": str(self.source_home),
            "project_root": str(self.project),
            "backup_path": str(self.backup),
            "choice": "use-default",
        }
        plans = []
        for client in ("cli", "sdk", "mcp", "plugin", "codex", "claude"):
            response = service.execute(
                ServiceRequest(client, "portability.migrate-project-home", arguments)
            )
            self.assertEqual("planned", response.status)
            plans.append(response.data["plan"])
        self.assertTrue(all(plan == plans[0] for plan in plans))


if __name__ == "__main__":
    unittest.main()
