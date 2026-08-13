from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


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
    apply_initial_work_document_copy,
    prepare_initial_work_document_copy,
    prepare_work_document_processing,
    work_documents_root,
)
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
        for path, (content, mtime) in source_before.items():
            self.assertEqual(content, path.read_bytes())
            self.assertEqual(mtime, path.stat().st_mtime_ns)
        repeated = prepare_initial_work_document_copy(
            self.store, self.ownership, "gpu-fusion", self.db, self.legacy,
        )
        self.assertTrue(repeated.no_op)

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
