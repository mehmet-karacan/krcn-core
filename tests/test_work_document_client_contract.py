from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    OPERATIONS,
    ServiceRequest,
    create_application_service,
)
from krcn_core.cli.app import (  # noqa: E402
    _phase_four_service_request,
    _work_document_migration_text,
    _work_document_processing_text,
    build_parser,
)
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.json_documents import pretty_json_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.repository_context import resolve_repository_context  # noqa: E402
from krcn_core.work_documents import (  # noqa: E402
    WorkDocumentError,
    _digest,
    work_documents_root,
)
from krcn_core.work_intent import parse_work_document_intent  # noqa: E402


class WorkDocumentClientContractTests(unittest.TestCase):
    def test_identity_specific_natural_request_reaches_service_arguments(self) -> None:
        intent = parse_work_document_intent(
            "gpu-fusion için 893614 talebini işle"
        )
        self.assertEqual(
            {
                "project_id": "gpu-fusion",
                "requested_external_id": "893614",
                "requested_work_type": "request",
            },
            intent.service_arguments(),
        )
        self.assertEqual(
            "893614", intent.public_summary()["requested_external_id"]
        )
        self.assertEqual(
            "request", intent.public_summary()["requested_work_type"]
        )
        defect = parse_work_document_intent(
            "gpu-fusion için 893614 hatasını işle"
        )
        self.assertEqual("defect", defect.requested_work_type)
        self.assertEqual(
            "request",
            parse_work_document_intent(
                "gpu-fusion için 893614 request işle"
            ).requested_work_type,
        )
        self.assertEqual(
            "defect",
            parse_work_document_intent(
                "gpu-fusion için 893614 hata işle"
            ).requested_work_type,
        )
        general = parse_work_document_intent("gpu-fusion gelen işlerini işle")
        self.assertIsNone(general.requested_work_type)

    def test_cli_routes_layout_migration_to_shared_application_operation(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "work",
            "migrate-document-layout",
            "gpu-fusion",
            "--identity-decision",
            "corpsms=request",
            "--identity-decision",
            "legacy-error=defect",
            "--identity-decision",
            "unassigned=exclude",
            "--repo",
            str(REPO_ROOT),
        ])
        request = _phase_four_service_request(args)
        self.assertEqual("work.documents.migrate-layout", request.operation)
        self.assertEqual({
            "project_id": "gpu-fusion",
            "reviewed_identity_decisions": {
                "corpsms": "request",
                "legacy-error": "defect",
                "unassigned": "exclude",
            },
        }, request.arguments)
        self.assertFalse(request.apply)

        rendered = _work_document_migration_text("planned", {
            "plan": {
                "project_id": "gpu-fusion",
                "document_count": 12,
                "copy_count": 12,
                "source_mapping_count": 14,
                "physical_target_count": 11,
                "collision_group_count": 3,
                "content_conflict_count": 2,
                "deduplicated_group_count": 1,
                "unresolved_review_count": 1,
                "excluded_count": 1,
                "target_layout_version": 2,
                "review_required": False,
                "no_op": False,
                "cleanup_required": True,
            },
            "next_actions": [
                "work.documents.process için ayrı exact plan hazırla."
            ],
        })
        self.assertIn("Belgeler: 12", rendered)
        self.assertIn("Kaynak eşleme: 14", rendered)
        self.assertIn("Fiziksel hedef: 11", rendered)
        self.assertIn("Ad çakışma grubu: 3", rendered)
        self.assertIn("İçerik çatışması: 2", rendered)
        self.assertIn("Tekilleştirilen grup: 1", rendered)
        self.assertIn("Çözümlenmemiş: 1", rendered)
        self.assertIn("Sonraki adımlar", rendered)
        self.assertIn("work.documents.process", rendered)
        self.assertIn("temizlik ayrı bir exact plan", rendered)

        processing = _work_document_processing_text("planned", {
            "plan": {
                "project_id": "gpu-fusion",
                "plan_id": "1" * 64,
                "manifest_update_required": True,
                "manifest_update": {
                    "new_document_count": 2,
                    "revised_document_count": 1,
                },
            },
            "next_actions": [
                "Manifest güncellemesinden sonra work.documents.process işlemini yeniden çalıştır."
            ],
        })
        self.assertIn("Önce belge manifesti güncellenecek", processing)
        self.assertIn("Yeni belge: 2", processing)
        self.assertIn("İçerik revizyonu: 1", processing)
        self.assertIn("Work Graph ve indeks güncellemesi bu onaya dahil değildir", processing)

    def test_transport_schemas_and_runtime_register_migration_operation(self) -> None:
        self.assertIn("work.documents.migrate-layout", OPERATIONS)
        ServiceRequest(
            "cli", "work.documents.migrate-layout", {"project_id": "gpu-fusion"}
        )
        for name in (
            "application-request.schema.json",
            "application-response.schema.json",
        ):
            payload = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertIn(
                "work.documents.migrate-layout",
                payload["properties"]["operation"]["enum"],
            )

    def test_repository_context_exposes_document_contract_and_schemas(self) -> None:
        resolved = resolve_repository_context(REPO_ROOT)
        canonical = resolved.manifest["canonical"]
        self.assertEqual(
            "docs/specifications/WORK-DOCUMENTS.md",
            canonical["work_documents_boundary"],
        )
        self.assertEqual(
            "schemas/work-document-manifest.schema.json",
            canonical["work_document_manifest_schema"],
        )
        self.assertEqual(
            "schemas/work-document-manifest-update-plan.schema.json",
            canonical["work_document_manifest_update_plan_schema"],
        )
        self.assertEqual(
            "schemas/work-document-layout-migration-plan.schema.json",
            canonical["work_document_layout_migration_plan_schema"],
        )


class WorkDocumentMigrationApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        store = LocalWorkspaceStore(self.home, ownership)
        project = {
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "name": "GPU Fusion",
            "description": "Work document client contract fixture",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        project_plan = store.prepare_put(
            "projects",
            "gpu-fusion",
            project,
            expected_revision=0,
            project_id="gpu-fusion",
        )
        authorization = authorize_mutation(
            project_plan.mutation,
            dry_run=DryRunEvidence(project_plan.mutation.plan_id, True),
            approval=ApprovalEvidence(
                project_plan.mutation.plan_id, "fixture-approval", True
            ),
        )
        store.apply_put(project_plan, authorization)

        root = work_documents_root(self.home, "gpu-fusion")
        source = (
            root
            / "requests"
            / "2026"
            / "893614"
            / "source"
            / "user"
            / "893614.txt"
        )
        source.parent.mkdir(parents=True)
        source.write_text("Talep belgesi", encoding="utf-8")
        import hashlib

        sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        manifest = {
            "schema_ref": "schemas/work-document-manifest.schema.json",
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "source_inventory_digests": {},
            "entries": [{
                "target_ref": (
                    "work-documents/requests/2026/893614/source/user/893614.txt"
                ),
                "sha256": sha256,
                "size_bytes": source.stat().st_size,
                "source_id": "mk-hub",
                "source_ref": "mk-hub/aktif/Talep_2026/893614/893614.txt",
                "work_item_ids": ["gpu-fusion-request-item-893614"],
                "semantic_policy": "safe-text",
                "sensitivity_classes": [],
            }],
            "source_files_copied": True,
            "source_files_modified": False,
            "source_files_deleted": False,
            "generated_content_separated": True,
            "absolute_paths_included": False,
        }
        manifest["manifest_digest"] = _digest(manifest)
        manifest_path = root / "_krcn" / "import-manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_bytes(pretty_json_bytes(manifest))
        self.root = root
        self.legacy_source = source
        self.service = create_application_service(REPO_ROOT, self.home)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_migration_operation_preserves_exact_plan_and_separate_processing_gate(self) -> None:
        arguments = {"project_id": "gpu-fusion"}
        planned = self.service.execute(ServiceRequest(
            "cli", "work.documents.migrate-layout", arguments
        ))
        self.assertEqual("planned", planned.status)
        self.assertTrue(planned.data["plan"]["work_document_processing_required"])
        self.assertEqual(
            "work.documents.process", planned.data["next_operation"]
        )
        self.assertFalse((self.root / "requests" / "893614" / "893614.txt").exists())

        with self.assertRaisesRegex(ApplicationServiceError, "exact plan"):
            self.service.execute(ServiceRequest(
                "cli",
                "work.documents.migrate-layout",
                arguments,
                apply=True,
                expected_plan_id="0" * 64,
                approval_id="migration-approval",
            ))
        with self.assertRaisesRegex(ApplicationServiceError, "approval"):
            self.service.execute(ServiceRequest(
                "cli",
                "work.documents.migrate-layout",
                arguments,
                apply=True,
                expected_plan_id=str(planned.data["plan"]["plan_id"]),
            ))

        applied = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.migrate-layout",
            arguments,
            apply=True,
            expected_plan_id=str(planned.data["plan"]["plan_id"]),
            approval_id="migration-approval",
        ))
        self.assertEqual("applied", applied.status)
        self.assertTrue((self.root / "requests" / "893614" / "893614.txt").is_file())
        self.assertTrue(self.legacy_source.is_file())
        self.assertTrue(applied.data["result"]["cleanup_required"])
        self.assertEqual(
            "work.documents.process", applied.data["next_operation"]
        )
        processing = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.process",
            {
                "project_id": "gpu-fusion",
                "requested_external_id": "893614",
                "requested_work_type": "request",
            },
        ))
        self.assertEqual(
            "893614", processing.data["plan"]["requested_external_id"]
        )
        self.assertEqual(
            "request", processing.data["plan"]["requested_work_type"]
        )

    def test_identity_review_is_first_and_apply_uses_only_reviewed_subset(self) -> None:
        manifest_path = self.root / "_krcn" / "import-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for external_id in ("corpsms", "unassigned"):
            source = (
                self.root
                / "requests"
                / "2026"
                / external_id
                / "source"
                / "user"
                / f"{external_id}.txt"
            )
            source.parent.mkdir(parents=True)
            source.write_text(external_id, encoding="utf-8")
            manifest["entries"].append({
                "target_ref": "work-documents/" + source.relative_to(self.root).as_posix(),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "size_bytes": source.stat().st_size,
                "source_id": "user",
                "source_ref": "user/" + source.name,
                "work_item_ids": [f"gpu-fusion-request-{external_id}"],
                "semantic_policy": "safe-text",
                "sensitivity_classes": [],
            })
        manifest.pop("manifest_digest")
        manifest["manifest_digest"] = _digest(manifest)
        manifest_path.write_bytes(pretty_json_bytes(manifest))

        unresolved = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.migrate-layout",
            {"project_id": "gpu-fusion"},
        ))
        self.assertEqual(2, unresolved.data["plan"]["unresolved_review_count"])
        self.assertIsNone(unresolved.data["next_operation"])
        self.assertTrue(
            unresolved.data["next_actions"][0].startswith("Çözümlenmemiş")
        )
        with self.assertRaisesRegex(ApplicationServiceError, "reviewed identity"):
            self.service.execute(ServiceRequest(
                "cli",
                "work.documents.migrate-layout",
                {"project_id": "gpu-fusion"},
                apply=True,
                expected_plan_id=str(unresolved.data["plan"]["plan_id"]),
                approval_id="unresolved-approval",
            ))

        arguments = {
            "project_id": "gpu-fusion",
            "reviewed_identity_decisions": {
                "corpsms": "request",
                "unassigned": "exclude",
            },
        }
        reviewed = self.service.execute(ServiceRequest(
            "cli", "work.documents.migrate-layout", arguments
        ))
        migration_schema = json.loads((
            REPO_ROOT / "schemas" / "work-document-layout-migration-plan.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(
            [],
            list(
                Draft202012Validator(migration_schema).iter_errors(
                    reviewed.data["plan"]
                )
            ),
        )
        self.assertEqual(0, reviewed.data["plan"]["unresolved_review_count"])
        self.assertEqual(1, reviewed.data["plan"]["excluded_count"])
        applied = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.migrate-layout",
            arguments,
            apply=True,
            expected_plan_id=str(reviewed.data["plan"]["plan_id"]),
            approval_id="reviewed-approval",
        ))
        self.assertEqual("applied", applied.status)
        self.assertTrue((self.root / "requests" / "corpsms" / "corpsms.txt").is_file())
        self.assertFalse(
            (self.root / "requests" / "unassigned" / "unassigned.txt").exists()
        )
        self.assertTrue(
            (self.root / "requests" / "2026" / "unassigned" / "source" / "user" / "unassigned.txt").is_file()
        )
        manifest = json.loads(
            (self.root / "_krcn" / "import-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(any(
            "/2026/unassigned/" in value["target_ref"]
            for value in manifest["entries"]
        ))
        self.assertEqual(1, len(manifest["legacy_preserved_entries"]))
        preserved = manifest["legacy_preserved_entries"][0]
        self.assertEqual("excluded-review", preserved["preservation_reason"])
        self.assertIn("/2026/unassigned/", preserved["entry"]["target_ref"])
        manifest_schema = json.loads((
            REPO_ROOT / "schemas" / "work-document-manifest.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(
            [],
            list(Draft202012Validator(manifest_schema).iter_errors(manifest)),
        )

    def test_unmanifested_v2_file_requires_manifest_exact_plan_first(self) -> None:
        migration_arguments = {"project_id": "gpu-fusion"}
        migration = self.service.execute(ServiceRequest(
            "cli", "work.documents.migrate-layout", migration_arguments
        ))
        self.service.execute(ServiceRequest(
            "cli",
            "work.documents.migrate-layout",
            migration_arguments,
            apply=True,
            expected_plan_id=str(migration.data["plan"]["plan_id"]),
            approval_id="migration-approval",
        ))
        incoming = self.root / "requests" / "777777" / "note.txt"
        incoming.parent.mkdir(parents=True)
        incoming.write_text("Yeni talep belgesi", encoding="utf-8")
        arguments = {
            "project_id": "gpu-fusion",
            "requested_external_id": "777777",
            "requested_work_type": "request",
        }
        planned = self.service.execute(ServiceRequest(
            "cli", "work.documents.process", arguments
        ))
        self.assertTrue(planned.data["plan"]["manifest_update_required"])
        self.assertEqual(
            1,
            planned.data["plan"]["manifest_update"]["new_document_count"],
        )
        manifest_update_schema = json.loads((
            REPO_ROOT / "schemas" / "work-document-manifest-update-plan.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(
            [],
            list(
                Draft202012Validator(manifest_update_schema).iter_errors(
                    planned.data["plan"]["manifest_update"]
                )
            ),
        )
        self.assertEqual("work.documents.process", planned.data["next_operation"])
        with self.assertRaisesRegex(ApplicationServiceError, "approval"):
            self.service.execute(ServiceRequest(
                "cli",
                "work.documents.process",
                arguments,
                apply=True,
                expected_plan_id=str(planned.data["plan"]["plan_id"]),
            ))
        applied = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.process",
            arguments,
            apply=True,
            expected_plan_id=str(planned.data["plan"]["plan_id"]),
            approval_id="manifest-approval",
        ))
        self.assertEqual("applied", applied.status)
        manifest = json.loads(
            (self.root / "_krcn" / "import-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(any(
            value["target_ref"] == "work-documents/requests/777777/note.txt"
            for value in manifest["entries"]
        ))
        follow_up = self.service.execute(ServiceRequest(
            "cli", "work.documents.process", arguments
        ))
        self.assertFalse(follow_up.data["plan"].get("manifest_update_required", False))
        self.assertTrue(follow_up.data["plan"]["work_import_required"])

        previous_sha256 = next(
            value["sha256"]
            for value in manifest["entries"]
            if value["target_ref"] == "work-documents/requests/777777/note.txt"
        )
        incoming.write_text("Revize talep belgesi", encoding="utf-8")
        revision = self.service.execute(ServiceRequest(
            "cli", "work.documents.process", arguments
        ))
        self.assertEqual(
            0,
            revision.data["plan"]["manifest_update"]["new_document_count"],
        )
        self.assertEqual(
            1,
            revision.data["plan"]["manifest_update"]["revised_document_count"],
        )
        revised = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.process",
            arguments,
            apply=True,
            expected_plan_id=str(revision.data["plan"]["plan_id"]),
            approval_id="revision-approval",
        ))
        self.assertEqual("applied", revised.status)
        revised_manifest = json.loads(
            (self.root / "_krcn" / "import-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        revised_entry = next(
            value
            for value in revised_manifest["entries"]
            if value["target_ref"] == "work-documents/requests/777777/note.txt"
        )
        self.assertEqual(2, revised_entry["document_revision"])
        self.assertEqual(previous_sha256, revised_entry["previous_sha256"])

    def test_same_external_id_in_two_types_requires_explicit_type(self) -> None:
        migration_arguments = {"project_id": "gpu-fusion"}
        migration = self.service.execute(ServiceRequest(
            "cli", "work.documents.migrate-layout", migration_arguments
        ))
        self.service.execute(ServiceRequest(
            "cli",
            "work.documents.migrate-layout",
            migration_arguments,
            apply=True,
            expected_plan_id=str(migration.data["plan"]["plan_id"]),
            approval_id="migration-approval",
        ))
        for category in ("requests", "defects"):
            incoming = self.root / category / "888888" / f"{category}.txt"
            incoming.parent.mkdir(parents=True)
            incoming.write_text(category, encoding="utf-8")
        with self.assertRaisesRegex(WorkDocumentError, "multiple work types"):
            self.service.execute(ServiceRequest(
                "cli",
                "work.documents.process",
                {
                    "project_id": "gpu-fusion",
                    "requested_external_id": "888888",
                },
            ))
        request_plan = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.process",
            {
                "project_id": "gpu-fusion",
                "requested_external_id": "888888",
                "requested_work_type": "request",
            },
        ))
        self.assertEqual(
            1,
            request_plan.data["plan"]["manifest_update"]["new_document_count"],
        )

    def test_reviewed_non_numeric_work_item_allows_v2_document_plan(self) -> None:
        migration_arguments = {"project_id": "gpu-fusion"}
        migration = self.service.execute(ServiceRequest(
            "cli", "work.documents.migrate-layout", migration_arguments
        ))
        self.service.execute(ServiceRequest(
            "cli",
            "work.documents.migrate-layout",
            migration_arguments,
            apply=True,
            expected_plan_id=str(migration.data["plan"]["plan_id"]),
            approval_id="migration-approval",
        ))
        work_item = {
            "work_item_id": "gpu-fusion-request-manual-review",
            "project_id": "gpu-fusion",
            "work_type": "request",
            "title": "Talep manual-review",
            "description": "İncelenmiş nonnumeric talep.",
            "status": "active",
            "acceptance_criteria": [],
            "relations": [],
            "evidence": [],
            "provenance": {
                "source_kind": "user",
                "source_ref": "test-reviewed-work-item",
            },
        }
        item_plan = self.service.execute(ServiceRequest(
            "cli", "work.item.put", work_item
        ))
        self.service.execute(ServiceRequest(
            "cli",
            "work.item.put",
            work_item,
            apply=True,
            expected_plan_id=str(item_plan.data["plan"]["plan_id"]),
            approval_id="work-item-approval",
        ))
        incoming = self.root / "requests" / "manual-review" / "note.txt"
        incoming.parent.mkdir(parents=True)
        incoming.write_text("İncelenmiş talep belgesi", encoding="utf-8")
        planned = self.service.execute(ServiceRequest(
            "cli",
            "work.documents.process",
            {
                "project_id": "gpu-fusion",
                "requested_external_id": "manual-review",
                "requested_work_type": "request",
            },
        ))
        self.assertEqual(
            1,
            planned.data["plan"]["manifest_update"]["new_document_count"],
        )
        self.service.execute(ServiceRequest(
            "cli",
            "work.documents.process",
            {
                "project_id": "gpu-fusion",
                "requested_external_id": "manual-review",
                "requested_work_type": "request",
            },
            apply=True,
            expected_plan_id=str(planned.data["plan"]["plan_id"]),
            approval_id="manifest-approval",
        ))
        manifest = json.loads(
            (self.root / "_krcn" / "import-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        manifest_entry = next(
            value
            for value in manifest["entries"]
            if value["target_ref"]
            == "work-documents/requests/manual-review/note.txt"
        )
        self.assertEqual(
            ["gpu-fusion-request-manual-review"],
            manifest_entry["work_item_ids"],
        )


if __name__ == "__main__":
    unittest.main()
