from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.work_graph import (  # noqa: E402
    apply_work_item,
    prepare_work_item,
    work_graph_index_path,
)
from krcn_core.work_import import (  # noqa: E402
    WorkImportError,
    apply_work_import,
    inventory_work_source,
    prepare_work_import,
)


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


class WorkImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.source = self.root / "legacy"
        self.source.mkdir()
        (self.source / "893609.md").write_text("İlişkili talep", encoding="utf-8")
        (self.source / "893614.md").write_text("Hazine payı oranı", encoding="utf-8")
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        project = {
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "name": "GPU Fusion",
            "description": "Work import test project",
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

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def inventory(self):
        return inventory_work_source(
            self.source,
            source_id="mk-hub-isler",
            logical_root="mk-hub/isler",
        )

    def request(self, *, description: str = "Hazine payı oranı incelenecek"):
        inventory = self.inventory()
        refs = {Path(entry.source_ref).name: entry.source_ref for entry in inventory.entries}
        return {
            "schema_ref": "schemas/work-import-request.schema.json",
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "source_inventory": inventory.as_dict(),
            "candidates": [
                {
                    "work_item_id": "gpu-fusion-request-893614",
                    "work_type": "request",
                    "title": "Kurumsal mobil SMS hakediş raporu",
                    "description": description,
                    "status": "active",
                    "acceptance_criteria": ["Finans kaynağı doğrulanmalı"],
                    "relations": [
                        {
                            "relation_type": "relates-to",
                            "target_ref": "gpu-fusion-request-893609",
                        }
                    ],
                    "evidence": [
                        {
                            "evidence_type": "document",
                            "reference": refs["893614.md"],
                            "digest": next(
                                entry.sha256
                                for entry in inventory.entries
                                if entry.source_ref == refs["893614.md"]
                            ),
                            "label": "Eski talep özeti",
                        }
                    ],
                    "source_ref": refs["893614.md"],
                },
                {
                    "work_item_id": "gpu-fusion-request-893609",
                    "work_type": "request",
                    "title": "İlişkili rapor talebi",
                    "description": "Aynı iş alanındaki ilişkili kayıt",
                    "status": "archived",
                    "acceptance_criteria": [],
                    "relations": [],
                    "evidence": [],
                    "source_ref": refs["893609.md"],
                },
            ],
        }

    @staticmethod
    def authorizations(plan):
        return {effect.plan_id: authorize(effect) for effect in plan.effect_plans}

    def test_batch_import_is_atomic_project_scoped_and_idempotent(self) -> None:
        request = self.request()
        plan = prepare_work_import(self.store, self.ownership, request)
        summary = plan.public_summary()
        serialized = json.dumps(summary, ensure_ascii=False)
        self.assertFalse(summary["no_op"])
        self.assertEqual(2, summary["item_count"])
        self.assertFalse(summary["paths_disclosed"])
        self.assertNotIn(str(self.root), serialized)
        result = apply_work_import(
            self.store,
            plan,
            self.authorizations(plan),
            expected_plan_id=plan.plan_id,
            current_source_inventory=self.inventory().as_dict(),
        )
        self.assertEqual("applied", result.status)
        item = self.store.read("work-items", "gpu-fusion-request-893614")
        self.assertIsNotNone(item)
        self.assertEqual("import", item.payload["provenance"]["source_kind"])
        relation = item.payload["relations"][0]
        self.assertEqual("gpu-fusion-request-893609", relation["target_ref"])
        manifest = (
            self.home / "projects" / "gpu-fusion" / "work" / "imports"
            / f"{plan.import_id}.json"
        )
        self.assertTrue(manifest.is_file())
        self.assertNotIn(str(self.root), manifest.read_text(encoding="utf-8"))
        projection = work_graph_index_path(self.home, "gpu-fusion")
        connection = sqlite3.connect(projection)
        try:
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()

        repeated = prepare_work_import(self.store, self.ownership, request)
        self.assertTrue(repeated.no_op)
        no_op_result = apply_work_import(
            self.store,
            repeated,
            {},
            expected_plan_id=repeated.plan_id,
            current_source_inventory=self.inventory().as_dict(),
        )
        self.assertEqual("already-applied", no_op_result.status)
        self.assertEqual(1, self.store.read("work-items", "gpu-fusion-request-893614").revision)

    def test_source_inventory_is_read_only_portable_and_checked_at_apply(self) -> None:
        before = {path.name: path.read_bytes() for path in self.source.iterdir()}
        inventory = self.inventory()
        self.assertEqual(2, len(inventory.entries))
        self.assertNotIn(str(self.source), json.dumps(inventory.as_dict()))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.source.iterdir()})
        plan = prepare_work_import(self.store, self.ownership, self.request())
        (self.source / "893614.md").write_text("Kaynak değişti", encoding="utf-8")
        with self.assertRaisesRegex(WorkImportError, "source inventory changed"):
            apply_work_import(
                self.store,
                plan,
                self.authorizations(plan),
                expected_plan_id=plan.plan_id,
                current_source_inventory=self.inventory().as_dict(),
            )
        self.assertIsNone(self.store.read("work-items", "gpu-fusion-request-893614"))

    def test_absolute_paths_and_secret_values_are_rejected(self) -> None:
        absolute_path = "C:" + "\\Users\\someone\\private"
        with self.assertRaisesRegex(WorkImportError, "absolute path"):
            prepare_work_import(
                self.store,
                self.ownership,
                self.request(description=f"Kaynak {absolute_path} altındadır"),
            )
        token_value = "github" + "_pat_" + "abcdefghijklmnopqrstuvwxyz"
        with self.assertRaisesRegex(WorkImportError, "secret value"):
            prepare_work_import(
                self.store,
                self.ownership,
                self.request(description="token=" + token_value),
            )

    def test_projection_failure_rolls_back_every_authoritative_record(self) -> None:
        plan = prepare_work_import(self.store, self.ownership, self.request())
        with patch(
            "krcn_core.work_import._write_projection",
            side_effect=OSError("synthetic projection failure"),
        ):
            with self.assertRaisesRegex(WorkImportError, "rolled back"):
                apply_work_import(
                    self.store,
                    plan,
                    self.authorizations(plan),
                    expected_plan_id=plan.plan_id,
                    current_source_inventory=self.inventory().as_dict(),
                )
        for work_item_id in (
            "gpu-fusion-request-893614",
            "gpu-fusion-request-893609",
        ):
            self.assertIsNone(self.store.read("work-items", work_item_id))
            self.assertIsNone(self.store.read("work-events", f"{work_item_id}-r1"))
        self.assertFalse(work_graph_index_path(self.home, "gpu-fusion").exists())
        imports = self.home / "projects" / "gpu-fusion" / "work" / "imports"
        self.assertFalse(imports.exists() and any(imports.iterdir()))

    def test_stale_graph_and_incomplete_authorization_fail_before_writes(self) -> None:
        request = self.request()
        plan = prepare_work_import(self.store, self.ownership, request)
        with self.assertRaisesRegex(WorkImportError, "authorization set"):
            apply_work_import(
                self.store,
                plan,
                {},
                expected_plan_id=plan.plan_id,
                current_source_inventory=self.inventory().as_dict(),
            )
        external = prepare_work_item(
            self.store,
            self.ownership,
            {
                "work_item_id": "gpu-fusion-task-external",
                "project_id": "gpu-fusion",
                "work_type": "task",
                "title": "Concurrent task",
                "description": "Changes the authoritative graph revision",
                "status": "active",
                "acceptance_criteria": [],
                "relations": [],
                "evidence": [],
                "provenance": {"source_kind": "user", "source_ref": "concurrent-test"},
            },
        )
        apply_work_item(
            self.store,
            external,
            {effect.plan_id: authorize(effect) for effect in external.effect_plans},
        )
        with self.assertRaisesRegex(WorkImportError, "work graph changed"):
            apply_work_import(
                self.store,
                plan,
                self.authorizations(plan),
                expected_plan_id=plan.plan_id,
                current_source_inventory=self.inventory().as_dict(),
            )
        self.assertIsNone(self.store.read("work-items", "gpu-fusion-request-893614"))

    def test_invalid_batch_relation_fails_before_any_write(self) -> None:
        request = self.request()
        request["candidates"][0]["relations"][0]["target_ref"] = "gpu-fusion-request-missing"
        with self.assertRaisesRegex(WorkImportError, "relation target"):
            prepare_work_import(self.store, self.ownership, request)
        self.assertIsNone(self.store.read("work-items", "gpu-fusion-request-893614"))

    def test_contract_documents_are_valid_json(self) -> None:
        for name in (
            "work-import-request.schema.json",
            "work-import-plan.schema.json",
            "work-import-result.schema.json",
            "work-import-manifest.schema.json",
        ):
            payload = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", payload["$schema"])
            self.assertTrue(payload["$id"].startswith("urn:krcn:schemas:work-import"))


if __name__ == "__main__":
    unittest.main()
