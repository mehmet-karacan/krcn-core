from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    ServiceRequest,
    create_application_service,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.work_import import inventory_work_source  # noqa: E402


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


class WorkApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.source = self.root / "legacy"
        self.source.mkdir()
        (self.source / "893614.md").write_text(
            "Hazine payı oranı",
            encoding="utf-8",
        )
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        store = LocalWorkspaceStore(self.home, ownership)
        project = {
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "name": "GPU Fusion",
            "description": "Work application test project",
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
        store.apply_put(project_plan, authorize(project_plan.mutation))
        self.service = create_application_service(REPO_ROOT, self.home)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def import_request(self) -> dict[str, object]:
        inventory = inventory_work_source(
            self.source,
            source_id="mk-hub-isler",
            logical_root="mk-hub/isler",
        )
        source_ref = inventory.entries[0].source_ref
        return {
            "source_root": str(self.source.resolve()),
            "import_request": {
                "schema_ref": "schemas/work-import-request.schema.json",
                "schema_version": 1,
                "project_id": "gpu-fusion",
                "source_inventory": inventory.as_dict(),
                "candidates": [{
                    "work_item_id": "gpu-fusion-request-893614",
                    "work_type": "request",
                    "title": "Kurumsal Mobil SMS Hakediş Raporu",
                    "description": "Hazine payı oranı doğrulanacak",
                    "status": "active",
                    "acceptance_criteria": ["Finans kaynağı doğrulanmalı"],
                    "relations": [],
                    "evidence": [],
                    "source_ref": source_ref,
                }],
            },
        }

    def apply_import(self) -> None:
        arguments = self.import_request()
        planned = self.service.execute(
            ServiceRequest("codex", "work.import", arguments)
        )
        serialized = json.dumps(planned.as_dict(), ensure_ascii=False)
        self.assertNotIn(str(self.source), serialized)
        applied = self.service.execute(ServiceRequest(
            "codex",
            "work.import",
            arguments,
            apply=True,
            expected_plan_id=str(planned.data["plan"]["plan_id"]),
            approval_id="work-import-approval",
        ))
        self.assertEqual("applied", applied.status)
        self.assertFalse(applied.data["result"]["paths_disclosed"])

    def apply_semantic_index(self) -> None:
        arguments = {"project_id": "gpu-fusion"}
        planned = self.service.execute(ServiceRequest(
            "plugin",
            "work.index-semantic",
            arguments,
        ))
        with self.assertRaisesRegex(ApplicationServiceError, "exact"):
            self.service.execute(ServiceRequest(
                "plugin",
                "work.index-semantic",
                arguments,
                apply=True,
                expected_plan_id="0" * 64,
            ))
        applied = self.service.execute(ServiceRequest(
            "plugin",
            "work.index-semantic",
            arguments,
            apply=True,
            expected_plan_id=str(planned.data["plan"]["plan_id"]),
        ))
        self.assertEqual("applied", applied.status)

    def test_import_rechecks_physical_inventory_and_does_not_disclose_path(self) -> None:
        arguments = self.import_request()
        planned = self.service.execute(
            ServiceRequest("cli", "work.import", arguments)
        )
        (self.source / "893614.md").write_text(
            "Kaynak değişti",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "physical source"):
            self.service.execute(ServiceRequest(
                "cli",
                "work.import",
                arguments,
                apply=True,
                expected_plan_id=str(planned.data["plan"]["plan_id"]),
                approval_id="work-import-approval",
            ))
        store = LocalWorkspaceStore(
            self.home,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.assertIsNone(
            store.read("work-items", "gpu-fusion-request-893614")
        )

    def test_service_import_index_and_hybrid_work_search(self) -> None:
        self.apply_import()
        self.apply_semantic_index()
        response = self.service.execute(ServiceRequest(
            "mcp",
            "work.search",
            {
                "project_id": "gpu-fusion",
                "text": "hazine payı oranı",
                "limit": 10,
            },
        ))
        result = response.data["result"]
        self.assertEqual("gpu-fusion-request-893614", result["hits"][0]["work_item_id"])
        self.assertEqual("current", result["semantic_status"])
        self.assertFalse(result["paths_disclosed"])
        with self.assertRaisesRegex(ApplicationServiceError, "read-only"):
            self.service.execute(ServiceRequest(
                "mcp",
                "work.search",
                {"project_id": "gpu-fusion", "text": "893614"},
                apply=True,
            ))

    def test_cli_request_files_and_natural_language_ask_share_service(self) -> None:
        request_file = self.root / "import-request.json"
        request_file.write_text(
            json.dumps(self.import_request()["import_request"], ensure_ascii=False),
            encoding="utf-8",
        )
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            exit_code = main([
                "work",
                "import",
                "--source-root",
                str(self.source),
                "--request-file",
                str(request_file),
                "--repo",
                str(REPO_ROOT),
                "--data-root",
                str(self.home),
            ])
        self.assertEqual(0, exit_code, error.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual("work.import", payload["operation"])
        self.assertNotIn(str(self.source), output.getvalue())

        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            exit_code = main([
                "ask",
                "893614 talebini gpu-fusion için oluştur.",
                "--repo",
                str(REPO_ROOT),
                "--data-root",
                str(self.home),
            ])
        self.assertEqual(0, exit_code, error.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual("work.item.put", payload["operation"])
        self.assertEqual("gpu-fusion", payload["data"]["route"]["project_id"])
        self.assertTrue(payload["data"]["route"]["exact_plan_required"])
        self.assertEqual("planned", payload["status"])


if __name__ == "__main__":
    unittest.main()
