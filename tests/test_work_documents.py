from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_capsule_portability import _collect_capsule_entries  # noqa: E402
from krcn_core.work_documents import (  # noqa: E402
    WorkDocumentError,
    _digest,
    apply_work_document_manifest_update,
    apply_initial_work_document_copy,
    prepare_initial_work_document_copy,
    prepare_work_document_manifest_update,
    prepare_work_document_processing,
    work_documents_root,
)
from krcn_core.work_document_layout_migration import (  # noqa: E402
    apply_work_document_layout_migration,
    prepare_work_document_layout_migration,
)
from krcn_core.json_documents import pretty_json_bytes  # noqa: E402
from krcn_core.work_graph import apply_work_item, prepare_work_item  # noqa: E402
from krcn_core.work_intent import parse_work_document_intent  # noqa: E402


def authorize(plan):
    return authorize_mutation(
        plan,
        dry_run=DryRunEvidence(plan.plan_id, verified=True),
        approval=(
            ApprovalEvidence(plan.plan_id, "test-approval", approved=True)
            if plan.approval_required
            else None
        ),
    )


class WorkDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.db = self.root / "db"
        self.legacy = self.root / "legacy"
        db_request = self.db / "Talep" / "2026" / "893614"
        legacy_request = self.legacy / "aktif" / "Talep_2026" / "893614"
        db_request.mkdir(parents=True)
        legacy_request.mkdir(parents=True)
        (db_request / "893614.txt").write_text("Hazine payı oranı", encoding="utf-8")
        (legacy_request / "893614.txt").write_text("Hazine payı oranı", encoding="utf-8")
        (self.legacy / "aktif" / "G-20260812-001.md").write_text(
            "Görev özeti", encoding="utf-8"
        )
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        project = {
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "name": "GPU Fusion",
            "description": "Document test project",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        project_plan = self.store.prepare_put(
            "projects", "gpu-fusion", project,
            expected_revision=0, project_id="gpu-fusion",
        )
        self.store.apply_put(project_plan, authorize(project_plan.mutation))
        digest = hashlib.sha256("Hazine payı oranı".encode("utf-8")).hexdigest()
        item_plan = prepare_work_item(self.store, self.ownership, {
            "project_id": "gpu-fusion",
            "work_item_id": "gpu-fusion-request-item-893614",
            "work_type": "request",
            "title": "Talep 893614",
            "description": "Finans talebi",
            "status": "active",
            "acceptance_criteria": [],
            "relations": [],
            "evidence": [{
                "evidence_type": "document",
                "reference": "legacy-work/mk-hub-isler/aktif/Talep_2026/893614/893614.txt",
                "digest": digest,
                "label": "Eski belge",
            }],
            "provenance": {"source_kind": "import", "source_ref": "legacy-work/893614"},
        })
        apply_work_item(
            self.store,
            item_plan,
            {effect.plan_id: authorize(effect) for effect in item_plan.effect_plans},
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_copy_is_deduplicated_exact_and_source_preserving(self) -> None:
        source_before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for root in (self.db, self.legacy)
            for path in root.rglob("*") if path.is_file()
        }
        plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        self.assertEqual(2, len(plan.entries))
        self.assertNotIn(str(self.root), str(plan.public_summary()))
        result = apply_initial_work_document_copy(
            plan,
            {effect.plan_id: authorize(effect) for effect in plan.effect_plans},
            expected_plan_id=plan.plan_id,
        )
        self.assertEqual(2, result["copied_count"])
        document = next(
            value for value in plan.entries
            if value.target_path.name == "893614.txt"
        )
        self.assertEqual(
            "work-documents/requests/893614/893614.txt",
            document.target_ref,
        )
        self.assertNotIn("/source/", document.target_ref)
        self.assertNotIn("/2026/", document.target_ref)
        manifest_entry = next(
            value for value in plan.manifest_payload["entries"]
            if value["target_ref"] == document.target_ref
        )
        self.assertEqual("request", manifest_entry["work_type"])
        self.assertEqual("893614", manifest_entry["external_id"])
        self.assertEqual("2026", manifest_entry["document_year"])
        self.assertEqual("893614.txt", manifest_entry["original_name"])
        self.assertEqual(2, len(manifest_entry["source_provenance"]))
        for path, (content, mtime) in source_before.items():
            self.assertEqual(content, path.read_bytes())
            self.assertEqual(mtime, path.stat().st_mtime_ns)
        repeated = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        self.assertTrue(
            repeated.no_op,
            msg=str([value.as_dict() for value in repeated.effect_plans]),
        )

    def test_processing_replaces_legacy_reference_and_indexes_automatically(self) -> None:
        copy_plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        apply_initial_work_document_copy(
            copy_plan,
            {effect.plan_id: authorize(effect) for effect in copy_plan.effect_plans},
            expected_plan_id=copy_plan.plan_id,
        )
        import_plan, summary = prepare_work_document_processing(
            self.store, self.ownership, "gpu-fusion"
        )
        self.assertIsNotNone(import_plan)
        self.assertEqual(1, summary["changed_work_item_count"])
        service = create_application_service(REPO_ROOT, self.home)
        dry_run = service.execute(ServiceRequest(
            "cli", "work.documents.process", {"project_id": "gpu-fusion"}
        ))
        applied = service.execute(ServiceRequest(
            "cli", "work.documents.process", {"project_id": "gpu-fusion"},
            apply=True,
            expected_plan_id=dry_run.data["plan"]["plan_id"],
            approval_id="test-approval",
        ))
        self.assertEqual("applied", applied.status)
        item = self.store.read("work-items", "gpu-fusion-request-item-893614")
        references = [value["reference"] for value in item.payload["evidence"]]
        self.assertTrue(any(value.startswith("work-documents/") for value in references))
        self.assertFalse(any(value.startswith("legacy-work/") for value in references))
        semantic = self.home / "projects" / "gpu-fusion" / "derived" / "retrieval" / "work-semantic-v1.sqlite"
        self.assertTrue(semantic.is_file())

        incoming = (
            work_documents_root(self.home, "gpu-fusion")
            / "defects" / "512345"
        )
        incoming.mkdir(parents=True)
        (incoming / "512345.txt").write_text(
            "Yeni defect bilgisi", encoding="utf-8"
        )
        manifest_plan = prepare_work_document_manifest_update(
            self.store,
            self.ownership,
            "gpu-fusion",
            requested_external_id="512345",
            requested_work_type="defect",
        )
        apply_work_document_manifest_update(
            manifest_plan,
            authorize(manifest_plan.mutation),
            expected_plan_id=manifest_plan.plan_id,
        )
        next_plan = service.execute(ServiceRequest(
            "cli", "work.documents.process", {"project_id": "gpu-fusion"}
        ))
        self.assertEqual(0, next_plan.data["plan"]["incoming_document_count"])
        self.assertEqual(1, next_plan.data["plan"]["changed_work_item_count"])
        service.execute(ServiceRequest(
            "cli", "work.documents.process", {"project_id": "gpu-fusion"},
            apply=True,
            expected_plan_id=next_plan.data["plan"]["plan_id"],
            approval_id="test-approval",
        ))
        defect = self.store.read("work-items", "gpu-fusion-defect-item-512345")
        self.assertIsNotNone(defect)
        self.assertEqual("active", defect.payload["status"])

    def test_v2_copy_deduplicates_and_suffixes_case_insensitive_conflicts(self) -> None:
        first = self.db / "Defect" / "2026" / "512345"
        second = self.db / "Defect" / "2026" / "512345_2"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "Script.SQL").write_text("select 1", encoding="utf-8")
        (second / "script.sql").write_text("select 2", encoding="utf-8")
        (first / "same.txt").write_text("same", encoding="utf-8")
        (second / "SAME.TXT").write_text("same", encoding="utf-8")

        plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        defect_entries = [
            value for value in plan.entries
            if "/defects/512345/" in value.target_ref
        ]
        script_names = sorted(
            value.target_path.name for value in defect_entries
            if value.target_path.suffix.casefold() == ".sql"
        )
        self.assertEqual(2, len(script_names))
        self.assertTrue(all("__sha256-" in value for value in script_names))
        self.assertEqual(
            1,
            sum(value.target_path.name.casefold() == "same.txt" for value in defect_entries),
        )

    def test_processing_external_id_scope_does_not_update_other_work(self) -> None:
        copy_plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        apply_initial_work_document_copy(
            copy_plan,
            {effect.plan_id: authorize(effect) for effect in copy_plan.effect_plans},
            expected_plan_id=copy_plan.plan_id,
        )
        root = work_documents_root(self.home, "gpu-fusion")
        for external_id in ("511111", "522222"):
            target = root / "defects" / external_id
            target.mkdir(parents=True)
            (target / f"{external_id}.txt").write_text(
                f"Defect {external_id}", encoding="utf-8"
            )
        manifest_plan = prepare_work_document_manifest_update(
            self.store,
            self.ownership,
            "gpu-fusion",
            requested_external_id="511111",
            requested_work_type="defect",
        )
        apply_work_document_manifest_update(
            manifest_plan,
            authorize(manifest_plan.mutation),
            expected_plan_id=manifest_plan.plan_id,
        )
        plan, summary = prepare_work_document_processing(
            self.store,
            self.ownership,
            "gpu-fusion",
            requested_external_id="511111",
        )
        self.assertIsNotNone(plan)
        self.assertEqual("511111", summary["requested_external_id"])
        self.assertEqual(0, summary["incoming_document_count"])
        self.assertEqual(1, summary["changed_work_item_count"])
        self.assertEqual(
            ["gpu-fusion-defect-item-511111"],
            [value.work_item_id for value in plan.items],
        )

    def test_non_numeric_v2_identity_requires_reviewed_work_item(self) -> None:
        copy_plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        apply_initial_work_document_copy(
            copy_plan,
            {effect.plan_id: authorize(effect) for effect in copy_plan.effect_plans},
            expected_plan_id=copy_plan.plan_id,
        )
        root = work_documents_root(self.home, "gpu-fusion")
        target = root / "requests" / "manual-review"
        target.mkdir(parents=True)
        (target / "note.txt").write_text("review", encoding="utf-8")
        with self.assertRaisesRegex(WorkDocumentError, "requires reviewed Work Item"):
            prepare_work_document_manifest_update(
                self.store, self.ownership, "gpu-fusion"
            )

    def test_non_numeric_v2_identity_accepts_matching_reviewed_work_item(self) -> None:
        copy_plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        apply_initial_work_document_copy(
            copy_plan,
            {effect.plan_id: authorize(effect) for effect in copy_plan.effect_plans},
            expected_plan_id=copy_plan.plan_id,
        )
        item_plan = prepare_work_item(self.store, self.ownership, {
            "project_id": "gpu-fusion",
            "work_item_id": "gpu-fusion-request-manual-review",
            "work_type": "request",
            "title": "İncelenmiş manuel talep",
            "description": "Sayısal olmayan dış kimlik için kullanıcı incelemesi",
            "status": "active",
            "acceptance_criteria": [],
            "relations": [],
            "evidence": [],
            "provenance": {
                "source_kind": "user",
                "source_ref": "review/manual-review",
            },
        })
        apply_work_item(
            self.store,
            item_plan,
            {effect.plan_id: authorize(effect) for effect in item_plan.effect_plans},
        )
        root = work_documents_root(self.home, "gpu-fusion")
        target = root / "requests" / "manual-review" / "note.txt"
        target.parent.mkdir(parents=True)
        target.write_text("review", encoding="utf-8")
        plan = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        self.assertEqual(1, plan.public_summary()["new_document_count"])
        entry = next(
            value for value in plan.desired_manifest["entries"]
            if value["target_ref"] == "work-documents/requests/manual-review/note.txt"
        )
        self.assertEqual(
            ["gpu-fusion-request-manual-review"], entry["work_item_ids"]
        )

    def test_manifest_update_revises_same_reference_with_stale_and_rollback_safety(self) -> None:
        copy_plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        apply_initial_work_document_copy(
            copy_plan,
            {effect.plan_id: authorize(effect) for effect in copy_plan.effect_plans},
            expected_plan_id=copy_plan.plan_id,
        )
        root = work_documents_root(self.home, "gpu-fusion")
        target = root / "requests" / "893614" / "893614.txt"
        previous_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        target.write_text("Yeni kontrollü sürüm", encoding="utf-8")
        new_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        plan = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        summary = plan.public_summary()
        self.assertEqual(0, summary["new_document_count"])
        self.assertEqual(1, summary["revised_document_count"])
        change = plan.new_entries[0]
        self.assertEqual("revision", change.change_kind)
        self.assertEqual(previous_sha256, change.previous_sha256)
        self.assertEqual(new_sha256, change.sha256)
        self.assertEqual(2, change.document_revision)

        target.write_text("Plan sonrası değişiklik", encoding="utf-8")
        with self.assertRaisesRegex(WorkDocumentError, "changed after manifest update planning"):
            apply_work_document_manifest_update(
                plan, authorize(plan.mutation), expected_plan_id=plan.plan_id,
            )
        target.write_text("Yeni kontrollü sürüm", encoding="utf-8")
        current = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        manifest_before = current.manifest_path.read_bytes()
        from krcn_core import work_documents as work_documents_module
        real_read = work_documents_module._read_manifest
        reads = 0

        def fail_verification(path):
            nonlocal reads
            reads += 1
            if reads == 2:
                raise WorkDocumentError("forced manifest verification failure")
            return real_read(path)

        with patch.object(
            work_documents_module, "_read_manifest", side_effect=fail_verification,
        ):
            with self.assertRaisesRegex(WorkDocumentError, "forced manifest"):
                apply_work_document_manifest_update(
                    current,
                    authorize(current.mutation),
                    expected_plan_id=current.plan_id,
                )
        self.assertEqual(manifest_before, current.manifest_path.read_bytes())
        applied = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        result = apply_work_document_manifest_update(
            applied, authorize(applied.mutation), expected_plan_id=applied.plan_id,
        )
        self.assertEqual(1, result["revised_document_count"])
        repeated = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        self.assertTrue(repeated.no_op)

    def test_manifest_update_is_exact_stale_safe_and_idempotent(self) -> None:
        copy_plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        apply_initial_work_document_copy(
            copy_plan,
            {effect.plan_id: authorize(effect) for effect in copy_plan.effect_plans},
            expected_plan_id=copy_plan.plan_id,
        )
        root = work_documents_root(self.home, "gpu-fusion")
        target = root / "requests" / "899999" / "note.txt"
        target.parent.mkdir(parents=True)
        target.write_text("first", encoding="utf-8")
        stale = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        target.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(WorkDocumentError, "changed after manifest update planning"):
            apply_work_document_manifest_update(
                stale,
                authorize(stale.mutation),
                expected_plan_id=stale.plan_id,
            )
        current = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        with self.assertRaisesRegex(WorkDocumentError, "exact plan"):
            apply_work_document_manifest_update(
                current,
                authorize(current.mutation),
                expected_plan_id="f" * 64,
            )
        result = apply_work_document_manifest_update(
            current,
            authorize(current.mutation),
            expected_plan_id=current.plan_id,
        )
        self.assertEqual("applied", result["status"])
        repeated = prepare_work_document_manifest_update(
            self.store, self.ownership, "gpu-fusion"
        )
        self.assertTrue(repeated.no_op)
        self.assertEqual(
            "already-applied",
            apply_work_document_manifest_update(
                repeated, None, expected_plan_id=repeated.plan_id,
            )["status"],
        )

    def test_manifest_update_requires_type_for_ambiguous_external_id(self) -> None:
        copy_plan = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        apply_initial_work_document_copy(
            copy_plan,
            {effect.plan_id: authorize(effect) for effect in copy_plan.effect_plans},
            expected_plan_id=copy_plan.plan_id,
        )
        root = work_documents_root(self.home, "gpu-fusion")
        for category in ("requests", "defects"):
            target = root / category / "511111"
            target.mkdir(parents=True)
            (target / f"{category}.txt").write_text(category, encoding="utf-8")
        with self.assertRaisesRegex(WorkDocumentError, "matches multiple work types"):
            prepare_work_document_manifest_update(
                self.store,
                self.ownership,
                "gpu-fusion",
                requested_external_id="511111",
            )
        request_plan = prepare_work_document_manifest_update(
            self.store,
            self.ownership,
            "gpu-fusion",
            requested_external_id="511111",
            requested_work_type="request",
        )
        self.assertEqual(1, request_plan.public_summary()["new_document_count"])

    def _write_v1_manifest(self, entries: list[tuple[Path, str, tuple[str, ...]]]) -> Path:
        root = work_documents_root(self.home, "gpu-fusion")
        raw_entries = []
        for path, target_ref, work_ids in entries:
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            raw_entries.append({
                "target_ref": target_ref,
                "sha256": sha256,
                "size_bytes": path.stat().st_size,
                "source_id": "db-scripts",
                "source_ref": "db-scripts/source/" + path.name,
                "work_item_ids": list(work_ids),
                "semantic_policy": "safe-text",
                "sensitivity_classes": [],
            })
        manifest = {
            "schema_ref": "schemas/work-document-manifest.schema.json",
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "source_inventory_digests": {"db-scripts": "0" * 64},
            "entries": raw_entries,
            "source_files_copied": True,
            "source_files_modified": False,
            "source_files_deleted": False,
            "generated_content_separated": True,
            "absolute_paths_included": False,
        }
        manifest["manifest_digest"] = _digest(manifest)
        target = root / "_krcn" / "import-manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pretty_json_bytes(manifest))
        return target

    def test_v1_layout_migration_is_exact_idempotent_and_stale_safe(self) -> None:
        root = work_documents_root(self.home, "gpu-fusion")
        first = root / "defects" / "2026" / "512345" / "source" / "db-scripts" / "512345" / "script.sql"
        second = root / "defects" / "2026" / "512345" / "source" / "db-scripts" / "512345_2" / "SCRIPT.SQL"
        first.parent.mkdir(parents=True)
        second.parent.mkdir(parents=True)
        first.write_text("select 1", encoding="utf-8")
        second.write_text("select 2", encoding="utf-8")
        self._write_v1_manifest([
            (first, "work-documents/" + first.relative_to(root).as_posix(), ("gpu-fusion-defect-item-512345",)),
            (second, "work-documents/" + second.relative_to(root).as_posix(), ("gpu-fusion-defect-item-512345",)),
        ])

        stale = prepare_work_document_layout_migration(
            self.store, self.ownership, "gpu-fusion"
        )
        first.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(WorkDocumentError, "changed after migration planning"):
            apply_work_document_layout_migration(
                stale,
                {effect.plan_id: authorize(effect) for effect in stale.effect_plans},
                expected_plan_id=stale.plan_id,
            )
        first.write_text("select 1", encoding="utf-8")
        plan = prepare_work_document_layout_migration(
            self.store, self.ownership, "gpu-fusion"
        )
        with self.assertRaisesRegex(WorkDocumentError, "exact plan"):
            apply_work_document_layout_migration(
                plan,
                {effect.plan_id: authorize(effect) for effect in plan.effect_plans},
                expected_plan_id="f" * 64,
            )
        result = apply_work_document_layout_migration(
            plan,
            {effect.plan_id: authorize(effect) for effect in plan.effect_plans},
            expected_plan_id=plan.plan_id,
        )
        self.assertEqual("applied", result["status"])
        targets = sorted((root / "defects" / "512345").iterdir())
        self.assertEqual(2, len(targets))
        self.assertTrue(all("__sha256-" in value.name for value in targets))
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertTrue(result["cleanup_required"])
        migrated_manifest = json.loads((
            root / "_krcn" / "import-manifest.json"
        ).read_text(encoding="utf-8"))
        self.assertIn("legacy_reference_aliases", migrated_manifest)
        self.assertTrue(all(
            value["document_year"] == "2026"
            and value["work_type"] == "defect"
            and value["external_id"] == "512345"
            and value["source_provenance"]
            for value in migrated_manifest["entries"]
        ))
        processing, _ = prepare_work_document_processing(
            self.store, self.ownership, "gpu-fusion"
        )
        self.assertIsNotNone(processing)
        evidence_refs = [
            evidence.reference
            for item in processing.items
            for evidence in item.evidence
            if evidence.reference.startswith("work-documents/")
        ]
        self.assertTrue(evidence_refs)
        self.assertFalse(any("/source/" in value for value in evidence_refs))
        repeated = prepare_work_document_layout_migration(
            self.store, self.ownership, "gpu-fusion"
        )
        self.assertTrue(
            repeated.no_op,
            msg=str([value.as_dict() for value in repeated.effect_plans]),
        )

    def test_v1_layout_migration_rolls_back_partial_copy(self) -> None:
        root = work_documents_root(self.home, "gpu-fusion")
        first = root / "requests" / "2026" / "893614" / "source" / "db-scripts" / "893614" / "one.txt"
        second = root / "requests" / "2026" / "893614" / "source" / "db-scripts" / "893614" / "two.txt"
        first.parent.mkdir(parents=True)
        first.write_text("one", encoding="utf-8")
        second.write_text("two", encoding="utf-8")
        manifest_path = self._write_v1_manifest([
            (first, "work-documents/" + first.relative_to(root).as_posix(), ("gpu-fusion-request-item-893614",)),
            (second, "work-documents/" + second.relative_to(root).as_posix(), ("gpu-fusion-request-item-893614",)),
        ])
        before = manifest_path.read_bytes()
        plan = prepare_work_document_layout_migration(
            self.store, self.ownership, "gpu-fusion"
        )
        from krcn_core import work_document_layout_migration as migration
        real_copy = migration._atomic_copy
        calls = 0

        def fail_second(source: Path, target: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected copy failure")
            real_copy(source, target)

        with patch.object(migration, "_atomic_copy", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "injected copy failure"):
                apply_work_document_layout_migration(
                    plan,
                    {effect.plan_id: authorize(effect) for effect in plan.effect_plans},
                    expected_plan_id=plan.plan_id,
                )
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())
        self.assertEqual(before, manifest_path.read_bytes())
        self.assertFalse((root / "requests" / "893614").exists())

    def test_migration_preserves_out_of_scope_and_merges_duplicate_provenance(self) -> None:
        root = work_documents_root(self.home, "gpu-fusion")
        first = root / "requests" / "2026" / "893614" / "source" / "db-scripts" / "893614" / "same.txt"
        second = root / "requests" / "2026" / "893614" / "source" / "mk-hub" / "893614" / "SAME.TXT"
        task = root / "tasks" / "active" / "g-1" / "source" / "mk-hub" / "task.md"
        shared = root / "shared" / "requests" / "2026" / "893614-893615" / "source" / "db-scripts" / "shared.txt"
        for path in (first, second, task, shared):
            path.parent.mkdir(parents=True, exist_ok=True)
        first.write_text("same", encoding="utf-8")
        second.write_text("same", encoding="utf-8")
        task.write_text("task", encoding="utf-8")
        shared.write_text("shared", encoding="utf-8")
        self._write_v1_manifest([
            (first, "work-documents/" + first.relative_to(root).as_posix(), ("gpu-fusion-request-item-893614",)),
            (second, "work-documents/" + second.relative_to(root).as_posix(), ("gpu-fusion-request-item-893615",)),
            (task, "work-documents/" + task.relative_to(root).as_posix(), ("gpu-fusion-task-g-1",)),
            (shared, "work-documents/" + shared.relative_to(root).as_posix(), ("gpu-fusion-request-item-893614", "gpu-fusion-request-item-893615")),
        ])
        plan = prepare_work_document_layout_migration(
            self.store, self.ownership, "gpu-fusion"
        )
        summary = plan.public_summary()
        self.assertEqual(4, summary["document_count"])
        self.assertEqual(2, summary["source_mapping_count"])
        self.assertEqual(1, summary["physical_target_count"])
        self.assertEqual(1, summary["collision_group_count"])
        self.assertEqual(0, summary["content_conflict_count"])
        self.assertEqual(1, summary["deduplicated_group_count"])
        self.assertEqual(3, len(plan.desired_manifest["entries"]))
        migrated = next(
            value for value in plan.desired_manifest["entries"]
            if value["target_ref"] == "work-documents/requests/893614/same.txt"
        )
        self.assertEqual(
            ["gpu-fusion-request-item-893614", "gpu-fusion-request-item-893615"],
            migrated["work_item_ids"],
        )
        self.assertEqual(2, len(migrated["source_provenance"]))
        aliases = plan.desired_manifest["legacy_reference_aliases"]
        self.assertIn("work-documents/" + first.relative_to(root).as_posix(), aliases)
        self.assertIn("work-documents/" + second.relative_to(root).as_posix(), aliases)
        self.assertTrue(any(
            value["target_ref"].startswith("work-documents/tasks/")
            for value in plan.desired_manifest["entries"]
        ))
        self.assertTrue(any(
            value["target_ref"].startswith("work-documents/shared/")
            for value in plan.desired_manifest["entries"]
        ))

    def test_inventory_counts_preserve_372_sources_and_out_of_scope_entries(self) -> None:
        root = work_documents_root(self.home, "gpu-fusion")
        entries: list[tuple[Path, str, tuple[str, ...]]] = []

        def add(path: Path, content: str, work_ids: tuple[str, ...]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            entries.append((
                path,
                "work-documents/" + path.relative_to(root).as_posix(),
                work_ids,
            ))

        for offset in range(197):
            external_id = str(700000 + offset)
            add(
                root / "requests" / "2026" / external_id / "source" / "db-scripts" / external_id / f"{external_id}.txt",
                external_id,
                (f"gpu-fusion-request-item-{external_id}",),
            )
        for offset in range(106):
            external_id = str(400000 + offset)
            add(
                root / "defects" / "2026" / external_id / "source" / "db-scripts" / external_id / f"{external_id}.txt",
                external_id,
                (f"gpu-fusion-defect-item-{external_id}",),
            )
        for variant in ("500000", "500000_2"):
            add(
                root / "defects" / "2026" / "500000" / "source" / "db-scripts" / variant / "duplicate.txt",
                "same duplicate",
                ("gpu-fusion-defect-item-500000",),
            )
        for offset in range(59):
            task_id = f"g-{offset:03d}"
            add(
                root / "tasks" / "active" / task_id / "source" / "mk-hub" / f"{task_id}.md",
                task_id,
                (f"gpu-fusion-task-{task_id}",),
            )
        for offset in range(8):
            external_id = str(800000 + offset)
            add(
                root / "shared" / "requests" / "2026" / external_id / "source" / "db-scripts" / f"shared-{offset}.txt",
                external_id,
                (f"gpu-fusion-request-item-{external_id}",),
            )
        self._write_v1_manifest(entries)
        plan = prepare_work_document_layout_migration(
            self.store, self.ownership, "gpu-fusion"
        )
        summary = plan.public_summary()
        self.assertEqual(372, summary["document_count"])
        self.assertEqual(305, summary["source_mapping_count"])
        self.assertEqual(304, summary["physical_target_count"])
        self.assertEqual(1, summary["collision_group_count"])
        self.assertEqual(0, summary["content_conflict_count"])
        self.assertEqual(1, summary["deduplicated_group_count"])
        self.assertEqual(197, sum(
            value.target_ref.startswith("work-documents/requests/")
            for value in plan.entries
        ))
        self.assertEqual(107, sum(
            value.target_ref.startswith("work-documents/defects/")
            for value in plan.entries
        ))
        self.assertEqual(59, sum(
            str(value["target_ref"]).startswith("work-documents/tasks/")
            for value in plan.desired_manifest["entries"]
        ))
        self.assertEqual(8, sum(
            str(value["target_ref"]).startswith("work-documents/shared/")
            for value in plan.desired_manifest["entries"]
        ))

    def test_review_decisions_migrate_subset_without_blocking_unassigned(self) -> None:
        root = work_documents_root(self.home, "gpu-fusion")
        entries = []
        for external_id in ("corpsms", "pck", "unassigned"):
            path = root / "requests" / "2026" / external_id / "source" / "db-scripts" / external_id / f"{external_id}.txt"
            path.parent.mkdir(parents=True)
            path.write_text(external_id, encoding="utf-8")
            entries.append((
                path,
                "work-documents/" + path.relative_to(root).as_posix(),
                (f"gpu-fusion-request-{external_id}",),
            ))
        self._write_v1_manifest(entries)
        unresolved = prepare_work_document_layout_migration(
            self.store, self.ownership, "gpu-fusion"
        )
        reviewed = prepare_work_document_layout_migration(
            self.store,
            self.ownership,
            "gpu-fusion",
            reviewed_identity_decisions={
                "corpsms": "request",
                "pck": "request",
                "unassigned": "exclude",
            },
        )
        self.assertNotEqual(unresolved.plan_id, reviewed.plan_id)
        self.assertEqual(3, unresolved.public_summary()["unresolved_review_count"])
        with self.assertRaisesRegex(WorkDocumentError, "unresolved identity reviews"):
            apply_work_document_layout_migration(
                unresolved,
                {effect.plan_id: authorize(effect) for effect in unresolved.effect_plans},
                expected_plan_id=unresolved.plan_id,
            )
        self.assertEqual(0, reviewed.public_summary()["unresolved_review_count"])
        self.assertEqual(1, reviewed.public_summary()["excluded_count"])
        self.assertEqual(3, reviewed.public_summary()["physical_target_count"])
        self.assertEqual(2, reviewed.public_summary()["copy_count"])
        self.assertFalse(any(
            "/2026/unassigned/" in value["target_ref"]
            for value in reviewed.desired_manifest["entries"]
        ))
        self.assertTrue(any(
            value["preservation_reason"] == "excluded-review"
            and "/2026/unassigned/" in value["entry"]["target_ref"]
            for value in reviewed.desired_manifest["legacy_preserved_entries"]
        ))
        applied = apply_work_document_layout_migration(
            reviewed,
            {effect.plan_id: authorize(effect) for effect in reviewed.effect_plans},
            expected_plan_id=reviewed.plan_id,
        )
        self.assertEqual("applied", applied["status"])

    def test_short_intent_and_capsule_exclusion(self) -> None:
        intent = parse_work_document_intent("gpu-fusion gelen işlerini işle")
        self.assertEqual("work.documents.process", intent.public_summary()["operation"])
        local_root = work_documents_root(self.home, "gpu-fusion")
        local_root.mkdir(parents=True)
        (local_root / "belge.txt").write_text("yerel belge", encoding="utf-8")
        entries, dependencies, _, _ = _collect_capsule_entries(
            self.home / "projects" / "gpu-fusion", "ready"
        )
        self.assertFalse(any(value.path.startswith("local-data/work-documents/") for value in entries))
        self.assertTrue(any(value.get("dependency_type") == "project-local-work-documents" for value in dependencies))


if __name__ == "__main__":
    unittest.main()
