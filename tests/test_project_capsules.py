from __future__ import annotations

import json
import hashlib
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SRC_ROOT))

from krcn_core.home_layout import (  # noqa: E402
    home_layout_version,
    user_home_layout_bytes,
)
from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.hybrid_retrieval import hybrid_index_path  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    MutationAuthorization,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.onboarding import (  # noqa: E402
    OnboardingRequest,
    apply_read_only_onboarding,
    prepare_read_only_onboarding,
)
from krcn_core.project_capsule_migration import (  # noqa: E402
    ProjectCapsuleMigrationError,
    apply_project_capsule_migration,
    prepare_project_capsule_migration,
)
from krcn_core.project_capsule_portability import (  # noqa: E402
    apply_project_capsule_export,
    apply_project_capsule_import,
    prepare_project_capsule_export,
    prepare_project_capsule_import,
)
from krcn_core.source_code_index import source_code_index_path  # noqa: E402


def authorization(plan, approval_id: str = "test-approval") -> MutationAuthorization:
    return authorize_mutation(
        plan,
        dry_run=DryRunEvidence(plan.plan_id, verified=True),
        approval=(
            ApprovalEvidence(plan.plan_id, approval_id, approved=True)
            if plan.approval_required
            else None
        ),
    )


def authorizations(plans) -> dict[str, MutationAuthorization]:
    return {plan.plan_id: authorization(plan) for plan in plans}


def create_sqlite(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO metadata VALUES ('label', ?)", (label,))
        connection.commit()
    finally:
        connection.close()


class ProjectCapsuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        records = (
            (
                "source-bindings",
                "sample-local",
                {
                    "schema_version": 1,
                    "binding_id": "sample-local",
                    "source_id": "sample",
                    "source_kind": "project",
                    "locator": {
                        "kind": "local-path",
                        "value": str((self.root / "sample-source").resolve()),
                    },
                    "default_access": "read-only",
                    "capabilities": ["read", "metadata"],
                    "policy_refs": [],
                    "revision": 1,
                },
            ),
            (
                "projects",
                "sample",
                {
                    "schema_version": 1,
                    "project_id": "sample",
                    "name": "sample",
                    "description": "sample project",
                    "source_refs": ["sample-local"],
                    "technologies": [],
                    "modules": [],
                    "skill_refs": [],
                    "status": "active",
                },
            ),
            (
                "workspaces",
                "sample-workspace",
                {
                    "schema_version": 1,
                    "workspace_id": "sample-workspace",
                    "project_refs": ["sample"],
                    "policy_refs": [],
                    "metadata": {},
                },
            ),
            (
                "source-states",
                "sample-local",
                {
                    "schema_version": 1,
                    "binding_id": "sample-local",
                    "binding_revision": 1,
                    "root_digest": hashlib.sha256(b"[]").hexdigest(),
                    "files": [],
                    "technologies": [],
                },
            ),
        )
        for record_type, record_id, payload in records:
            plan = self.store.prepare_put(
                record_type,
                record_id,
                payload,
                expected_revision=0,
            )
            self.store.apply_put(plan, authorization(plan.mutation))
        create_sqlite(
            self.home / "derived" / "retrieval" / "hybrid-v1.sqlite",
            "hybrid",
        )
        create_sqlite(
            self.home
            / "derived"
            / "retrieval"
            / "source-code-v1"
            / "sample.sqlite",
            "source-code",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def migrate(self):
        backup = self.root / "layout-v1-backup.zip"
        plan = prepare_project_capsule_migration(
            self.home,
            backup,
            self.ownership,
        )
        result = apply_project_capsule_migration(
            plan,
            authorizations(plan.effect_plans),
            self.ownership,
        )
        return plan, result, backup

    def test_migration_groups_project_records_and_indexes(self) -> None:
        plan, result, backup = self.migrate()

        self.assertEqual(2, home_layout_version(self.home))
        self.assertEqual(("sample",), plan.project_ids)
        self.assertEqual(1, result.project_count)
        self.assertTrue(backup.is_file())
        with zipfile.ZipFile(backup) as archive:
            self.assertIsNone(archive.testzip())
        self.assertTrue((self.home / "projects" / "sample" / "project.json").is_file())
        self.assertTrue(
            (
                self.home
                / "projects"
                / "sample"
                / "bindings"
                / "source-bindings"
                / "sample-local.json"
            ).is_file()
        )
        self.assertFalse((self.home / "projects" / "sample.json").exists())
        self.assertEqual(
            self.home
            / "projects"
            / "sample"
            / "derived"
            / "retrieval"
            / "source-code-v1.sqlite",
            source_code_index_path(self.home, "sample"),
        )
        self.assertEqual(
            self.home / "global" / "derived" / "retrieval" / "hybrid-v1.sqlite",
            hybrid_index_path(self.home),
        )
        migrated = LocalWorkspaceStore(self.home, self.ownership)
        self.assertIsNotNone(migrated.read("projects", "sample"))
        self.assertIsNotNone(migrated.read("project-capsules", "sample"))
        self.assertEqual(
            "local-path",
            migrated.read("source-bindings", "sample-local").payload["locator"]["kind"],
        )

    def test_stale_migration_does_not_write_backup_or_layout(self) -> None:
        backup = self.root / "stale-backup.zip"
        plan = prepare_project_capsule_migration(
            self.home,
            backup,
            self.ownership,
        )
        project_path = self.home / "projects" / "sample.json"
        payload = json.loads(project_path.read_text(encoding="utf-8"))
        payload["payload"]["description"] = "changed"
        project_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(ProjectCapsuleMigrationError):
            apply_project_capsule_migration(
                plan,
                authorizations(plan.effect_plans),
                self.ownership,
            )

        self.assertFalse(backup.exists())
        self.assertEqual(1, home_layout_version(self.home))
        self.assertTrue(project_path.is_file())

    def test_thin_export_sanitizes_binding_and_imports_into_existing_home(self) -> None:
        self.migrate()
        archive = self.root / "sample-thin.krcn-project"
        export_plan = prepare_project_capsule_export(
            self.home,
            "sample",
            archive,
            "thin",
            self.ownership,
        )
        export_result = apply_project_capsule_export(
            export_plan,
            authorization(export_plan.mutation),
        )
        self.assertTrue(archive.is_file())
        self.assertGreater(export_result.entry_count, 0)
        with zipfile.ZipFile(archive) as exported:
            names = set(exported.namelist())
            self.assertNotIn(
                "payload/derived/retrieval/source-code-v1.sqlite",
                names,
            )
            binding = json.loads(
                exported.read(
                    "payload/bindings/source-bindings/sample-local.json"
                ).decode("utf-8")
            )
            self.assertEqual("unbound", binding["payload"]["locator"]["kind"])

        target_home = self.root / "friend-home"
        target_home.mkdir()
        (target_home / "layout.json").write_bytes(user_home_layout_bytes())
        import_plan = prepare_project_capsule_import(
            archive,
            target_home,
            self.ownership,
        )
        import_result = apply_project_capsule_import(
            import_plan,
            authorizations(import_plan.effect_plans),
            self.ownership,
        )
        self.assertEqual(1, import_result.rebind_required_count)
        imported = LocalWorkspaceStore(target_home, self.ownership)
        binding = imported.read("source-bindings", "sample-local")
        self.assertIsNotNone(binding)
        self.assertEqual("unbound", binding.payload["locator"]["kind"])
        self.assertIsNotNone(imported.read("source-states", "sample-local"))
        self.assertFalse(source_code_index_path(target_home, "sample").exists())

    def test_ready_export_includes_verified_project_derived_index(self) -> None:
        self.migrate()
        archive = self.root / "sample-ready.krcn-project"
        plan = prepare_project_capsule_export(
            self.home,
            "sample",
            archive,
            "ready",
            self.ownership,
        )
        apply_project_capsule_export(plan, authorization(plan.mutation))

        with zipfile.ZipFile(archive) as exported:
            self.assertIn(
                "payload/derived/retrieval/source-code-v1.sqlite",
                exported.namelist(),
            )

    def test_application_service_exposes_exact_capsule_operations(self) -> None:
        backup = self.root / "service-layout-backup.zip"
        service = create_application_service(REPO_ROOT, self.home)
        planned = service.execute(
            ServiceRequest(
                "codex",
                "portability.migrate-project-capsules",
                {"backup_path": str(backup)},
            )
        )
        self.assertEqual("planned", planned.status)
        plan_id = planned.data["plan"]["plan_id"]
        applied = service.execute(
            ServiceRequest(
                "codex",
                "portability.migrate-project-capsules",
                {"backup_path": str(backup)},
                apply=True,
                expected_plan_id=plan_id,
                approval_id="service-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        archive = self.root / "service-thin.krcn-project"
        export = service.execute(
            ServiceRequest(
                "plugin",
                "portability.export-project-capsule",
                {
                    "project_id": "sample",
                    "archive_path": str(archive),
                    "mode": "thin",
                },
            )
        )
        self.assertEqual("planned", export.status)

    def test_new_layout_v2_onboarding_writes_one_project_capsule(self) -> None:
        home = self.root / "new-v2-home"
        home.mkdir()
        (home / "layout.json").write_bytes(user_home_layout_bytes())
        source = self.root / "new-project"
        source.mkdir()
        store = LocalWorkspaceStore(home, self.ownership)
        plan = prepare_read_only_onboarding(
            store,
            OnboardingRequest(
                workspace_id="new-project-workspace",
                project_id="new-project",
                binding_id="new-project-local",
                project_name="New Project",
                description="test",
                source_root=source,
            ),
        )
        self.assertEqual("project-capsules", plan.record_plans[0].record_type)
        apply_read_only_onboarding(
            store,
            plan,
            {
                item.mutation.plan_id: authorization(item.mutation)
                for item in plan.record_plans
            },
        )
        capsule = home / "projects" / "new-project"
        self.assertTrue((capsule / "manifest.json").is_file())
        self.assertTrue((capsule / "project.json").is_file())
        self.assertTrue(
            (capsule / "bindings" / "source-bindings" / "new-project-local.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
