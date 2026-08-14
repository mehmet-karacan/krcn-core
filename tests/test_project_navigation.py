from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import _project_resume_text, main as cli_main  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_navigation import (  # noqa: E402
    parse_project_navigation_intent,
)
from krcn_core.work_graph import apply_work_item, prepare_work_item  # noqa: E402


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


class ProjectNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        for project_id in ("gpu-fusion", "sky-ui"):
            payload = {
                "schema_version": 1,
                "project_id": project_id,
                "name": project_id,
                "description": "Navigation test project",
                "status": "active",
                "source_refs": [],
                "modules": [],
                "technologies": [],
                "skill_refs": [],
            }
            plan = self.store.prepare_put(
                "projects", project_id, payload,
                expected_revision=0, project_id=project_id,
            )
            self.store.apply_put(plan, authorize(plan.mutation))
        for work_id, work_type, status in (
            ("gpu-fusion-request-item-100", "request", "active"),
            ("gpu-fusion-defect-item-200", "defect", "archived"),
            ("gpu-fusion-task-g-20260813-001", "task", "active"),
        ):
            plan = prepare_work_item(self.store, self.ownership, {
                "project_id": "gpu-fusion",
                "work_item_id": work_id,
                "work_type": work_type,
                "title": work_id,
                "description": "Navigation work fixture",
                "status": status,
                "acceptance_criteria": [],
                "relations": [],
                "evidence": [],
                "provenance": {"source_kind": "user", "source_ref": "test"},
            })
            apply_work_item(
                self.store,
                plan,
                {effect.plan_id: authorize(effect) for effect in plan.effect_plans},
            )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_project_list_contains_positions_work_types_and_update_time(self) -> None:
        response = self.service.execute(ServiceRequest("cli", "project.list", {}))
        self.assertEqual(2, response.data["project_count"])
        first = response.data["projects"][0]
        self.assertEqual(1, first["position"])
        self.assertEqual("gpu-fusion", first["project_id"])
        self.assertEqual(1, first["work_counts"]["requests"]["active"])
        self.assertEqual(1, first["work_counts"]["defects"]["historical"])
        self.assertEqual(1, first["work_counts"]["tasks"]["active"])
        self.assertEqual(3, first["work_counts"]["total"])
        self.assertIsInstance(first["last_updated_at"], str)
        self.assertFalse(response.data["selection_grants_authority"])
        self.assertFalse(response.data["paths_disclosed"])

    def test_ordinal_opens_read_only_resume_with_recent_items(self) -> None:
        response = self.service.execute(ServiceRequest(
            "cli",
            "project.resume",
            {"working_directory": str(self.root), "project_ref": "1"},
        ))
        self.assertTrue(response.data["matched"])
        self.assertEqual("ordinal-project", response.data["selection_basis"])
        self.assertEqual("gpu-fusion", response.data["project"]["project_id"])
        self.assertEqual(2, response.data["resume"]["work"]["active_task_count"])
        self.assertEqual(
            1,
            response.data["resume"]["work"]["work_counts"]["requests"]["active"],
        )
        self.assertEqual(
            1,
            response.data["resume"]["work"]["work_counts"]["defects"][
                "historical"
            ],
        )
        self.assertTrue(all(
            item["last_updated_at"]
            for item in response.data["resume"]["work"]["items"]
        ))

    def test_project_name_with_spaces_resolves_without_fuzzy_selection(self) -> None:
        response = self.service.execute(ServiceRequest(
            "cli",
            "project.resume",
            {
                "working_directory": str(self.root),
                "project_ref": "GPU Fusion",
            },
        ))
        self.assertTrue(response.data["matched"])
        self.assertEqual("gpu-fusion", response.data["project"]["project_id"])

    def test_wrong_name_returns_menu_and_suggestion_without_selecting(self) -> None:
        response = self.service.execute(ServiceRequest(
            "cli",
            "project.resume",
            {
                "working_directory": str(self.root),
                "project_ref": "gpu-fuson",
            },
        ))
        self.assertFalse(response.data["matched"])
        self.assertEqual(2, response.data["navigation"]["project_count"])
        self.assertEqual(
            "gpu-fusion",
            response.data["suggested_projects"][0]["project_id"],
        )

    def test_resume_table_shows_durable_step_progress(self) -> None:
        rendered = _project_resume_text({
            "matched": True,
            "project": {"project_id": "sample"},
            "resume": {
                "work": {
                    "work_counts": {
                        "requests": {"active": 0, "historical": 0},
                        "defects": {"active": 0, "historical": 0},
                        "tasks": {"active": 1, "historical": 0},
                    },
                    "active_progress": [
                        {
                            "work_item_id": "sample-task",
                            "status": "running",
                            "completed_step_count": 4,
                            "total_step_count": 10,
                            "current_step": {
                                "step_id": "step-05",
                                "title": "Beşinci adımı doğrula",
                            },
                            "next_steps": [
                                {
                                    "step_id": "step-06",
                                    "title": "Altıncı adıma geç",
                                }
                            ],
                        }
                    ],
                    "items": [],
                }
            },
        })
        self.assertIn("Aktif ilerleme:", rendered)
        self.assertIn("4/10", rendered)
        self.assertIn("Beşinci adımı doğrula", rendered)
        self.assertIn("Altıncı adıma geç", rendered)

    def test_natural_list_and_number_are_routed(self) -> None:
        listed = parse_project_navigation_intent("proje listesi")
        selected = parse_project_navigation_intent("1")
        checked = parse_project_navigation_intent(
            "gpu-fuson projesini kontrol et"
        )
        self.assertEqual("project.list", listed.operation)
        self.assertEqual("1", selected.project_ref)
        self.assertEqual("gpu-fuson", checked.project_ref)

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli_main([
                "ask", "proje listesi",
                "--repo", str(REPO_ROOT),
                "--data-root", str(self.home),
                "--format", "json",
            ])
        self.assertEqual(0, exit_code)
        payload = json.loads(output.getvalue())
        self.assertEqual("project.list", payload["operation"])
        self.assertEqual(2, payload["data"]["project_count"])

    def test_default_natural_navigation_uses_human_readable_tables(self) -> None:
        listed_output = io.StringIO()
        with redirect_stdout(listed_output):
            listed_exit = cli_main([
                "ask", "proje listesi",
                "--repo", str(REPO_ROOT),
                "--data-root", str(self.home),
            ])
        self.assertEqual(0, listed_exit)
        listed = listed_output.getvalue()
        self.assertIn("Proje", listed)
        self.assertIn("Talep A/G", listed)
        self.assertIn("Defect A/G", listed)
        self.assertIn("Son düzenleme UTC", listed)
        self.assertIn("gpu-fusion", listed)
        self.assertFalse(listed.lstrip().startswith("{"))

        selected_output = io.StringIO()
        with redirect_stdout(selected_output):
            selected_exit = cli_main([
                "ask", "1",
                "--repo", str(REPO_ROOT),
                "--data-root", str(self.home),
            ])
        self.assertEqual(0, selected_exit)
        selected = selected_output.getvalue()
        self.assertIn("Proje: gpu-fusion", selected)
        self.assertIn("Son işler:", selected)
        self.assertIn("request-item-100", selected)

    def test_direct_project_list_defaults_to_table_and_supports_json(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli_main([
                "project", "list",
                "--repo", str(REPO_ROOT),
                "--data-root", str(self.home),
            ])
        self.assertEqual(0, exit_code)
        self.assertIn("Talep A/G", output.getvalue())
        self.assertFalse(output.getvalue().lstrip().startswith("{"))

        json_output = io.StringIO()
        with redirect_stdout(json_output):
            json_exit = cli_main([
                "project", "list",
                "--repo", str(REPO_ROOT),
                "--data-root", str(self.home),
                "--format", "json",
            ])
        self.assertEqual(0, json_exit)
        self.assertEqual(
            "project.list",
            json.loads(json_output.getvalue())["operation"],
        )

    def test_work_lists_support_natural_and_direct_table_output(self) -> None:
        intent = parse_project_navigation_intent("gpu-fusion görev listesi")
        self.assertEqual("work.list", intent.operation)
        self.assertEqual("gpu-fusion", intent.project_ref)
        self.assertEqual("task", intent.work_type)

        natural_output = io.StringIO()
        with redirect_stdout(natural_output):
            natural_exit = cli_main([
                "ask", "gpu-fusion görev listesi",
                "--repo", str(REPO_ROOT),
                "--data-root", str(self.home),
            ])
        self.assertEqual(0, natural_exit)
        natural = natural_output.getvalue()
        self.assertIn("Proje: gpu-fusion", natural)
        self.assertIn("task-g-20260813-001", natural)
        self.assertNotIn("request-item-100", natural)
        self.assertFalse(natural.lstrip().startswith("{"))

        direct_output = io.StringIO()
        with redirect_stdout(direct_output):
            direct_exit = cli_main([
                "work", "list",
                "--project", "gpu-fusion",
                "--type", "defect",
                "--repo", str(REPO_ROOT),
                "--data-root", str(self.home),
            ])
        self.assertEqual(0, direct_exit)
        direct = direct_output.getvalue()
        self.assertIn("defect-item-200", direct)
        self.assertNotIn("task-g-20260813-001", direct)

    def test_work_list_can_use_current_project_and_lifecycle_filter(self) -> None:
        source_root = self.root / "source"
        source_root.mkdir()
        binding = {
            "schema_version": 1,
            "binding_id": "gpu-fusion-source",
            "source_id": "gpu-fusion",
            "source_kind": "project",
            "locator": {"kind": "local-path", "value": str(source_root)},
            "default_access": "read-only",
            "capabilities": ["read", "metadata"],
            "policy_refs": [],
            "revision": 1,
        }
        binding_plan = self.store.prepare_put(
            "source-bindings",
            "gpu-fusion-source",
            binding,
            expected_revision=0,
            project_id="gpu-fusion",
        )
        self.store.apply_put(binding_plan, authorize(binding_plan.mutation))
        project = self.store.read("projects", "gpu-fusion")
        assert project is not None
        project_payload = dict(project.payload)
        project_payload["source_refs"] = ["gpu-fusion-source"]
        project_plan = self.store.prepare_put(
            "projects",
            "gpu-fusion",
            project_payload,
            expected_revision=project.revision,
            project_id="gpu-fusion",
        )
        self.store.apply_put(project_plan, authorize(project_plan.mutation))

        output = io.StringIO()
        previous = Path.cwd()
        try:
            import os
            os.chdir(source_root)
            with redirect_stdout(output):
                exit_code = cli_main([
                    "work", "list",
                    "--type", "defect",
                    "--status", "historical",
                    "--repo", str(REPO_ROOT),
                    "--data-root", str(self.home),
                ])
        finally:
            os.chdir(previous)
        self.assertEqual(0, exit_code)
        self.assertIn("defect-item-200", output.getvalue())


if __name__ == "__main__":
    unittest.main()
