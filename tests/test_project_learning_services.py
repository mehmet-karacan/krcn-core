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
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


class ProjectLearningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "servis projesi"
        self.source.mkdir()
        (self.source / "package.json").write_text(
            '{"name":"shared-service-project"}\n',
            encoding="utf-8",
        )
        self.data_root = self.root / "data"
        self.store = LocalWorkspaceStore(
            self.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)
        self.arguments = {
            "request_text": "bu projeyi öğren",
            "source_root": str(self.source),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _run_cli(arguments: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = main(arguments)
        return result, output.getvalue(), error.getvalue()

    def test_all_clients_receive_the_same_inferred_plan(self) -> None:
        plans = []
        for client_kind in (
            "cli",
            "sdk",
            "mcp",
            "plugin",
            "codex",
            "claude",
            "future-client",
        ):
            response = self.service.execute(
                ServiceRequest(client_kind, "project.learn", self.arguments)
            )
            plans.append(response.data["plan"])
        self.assertTrue(all(plan == plans[0] for plan in plans))
        self.assertEqual(
            "shared-service-project",
            plans[0]["metadata"]["project_id"],
        )

    def test_service_requires_exact_plan_and_one_approval(self) -> None:
        dry_run = self.service.execute(
            ServiceRequest("plugin", "project.learn", self.arguments)
        )
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan"):
            self.service.execute(
                ServiceRequest(
                    "plugin",
                    "project.learn",
                    self.arguments,
                    apply=True,
                    expected_plan_id="0" * 64,
                    approval_id="project-learning-approval",
                )
            )
        plan_id = dry_run.data["plan"]["plan_id"]
        applied = self.service.execute(
            ServiceRequest(
                "plugin",
                "project.learn",
                self.arguments,
                apply=True,
                expected_plan_id=plan_id,
                approval_id="project-learning-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertEqual(4, len(applied.data["records"]))

    def test_directory_command_and_natural_language_ask_share_plan(self) -> None:
        common = [
            "--repo",
            str(REPO_ROOT),
            "--data-root",
            str(self.data_root),
        ]
        result, output, error = self._run_cli(
            ["project", "learn", str(self.source), *common]
        )
        self.assertEqual(0, result, error)
        directory_plan = json.loads(output)["data"]["plan"]
        result, output, error = self._run_cli(
            ["ask", f'"{self.source}" projesini öğren', *common]
        )
        self.assertEqual(0, result, error)
        prompt_plan = json.loads(output)["data"]["plan"]
        self.assertEqual(directory_plan["plan_id"], prompt_plan["plan_id"])
        self.assertEqual(
            directory_plan["metadata"]["project_id"],
            prompt_plan["metadata"]["project_id"],
        )
        self.assertNotIn(str(self.source), output)

    def test_ask_rejects_unrelated_request(self) -> None:
        result, _, error = self._run_cli(
            [
                "ask",
                "bu dizini sil",
                "--source",
                str(self.source),
                "--repo",
                str(REPO_ROOT),
                "--data-root",
                str(self.data_root),
            ]
        )
        self.assertEqual(2, result)
        self.assertIn("not recognized", error)

    def test_integrate_phrase_and_direct_command_share_complete_lifecycle(self) -> None:
        common = [
            "--repo",
            str(REPO_ROOT),
            "--data-root",
            str(self.data_root),
        ]
        result, output, error = self._run_cli(
            [
                "ask",
                f'"{self.source}" projesini öğren ve entegre et',
                *common,
            ]
        )
        self.assertEqual(0, result, error)
        asked = json.loads(output)
        self.assertEqual("project.integrate", asked["operation"])
        self.assertEqual("manual", asked["data"]["plan"]["scan"]["mode"])

        result, output, error = self._run_cli(
            [
                "project",
                "integrate",
                "--source",
                str(self.source),
                *common,
            ]
        )
        self.assertEqual(0, result, error)
        direct = json.loads(output)
        self.assertEqual("project.integrate", direct["operation"])
        self.assertEqual(
            asked["data"]["plan"]["plan_id"],
            direct["data"]["plan"]["plan_id"],
        )


if __name__ == "__main__":
    unittest.main()
