from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


class ProjectHomeClientIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "örnek-proje"
        self.project.mkdir()
        self.source = self.project / "README.md"
        self.source.write_text("Değişmemesi gereken proje kaynağı.\n", encoding="utf-8")
        self.source_digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        store = LocalWorkspaceStore(
            self.root / "legacy-service-home",
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _run_cli(arguments: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with patch.dict(os.environ, {"KRCN_HOME": ""}), redirect_stdout(
            output
        ), redirect_stderr(error):
            result = main(arguments)
        return result, output.getvalue(), error.getvalue()

    def test_every_client_receives_the_same_first_use_choice(self) -> None:
        resolutions = []
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
                ServiceRequest(
                    client_kind,
                    "project.home.resolve",
                    {"project_root": str(self.project)},
                )
            )
            self.assertEqual("choice-required", response.status)
            resolutions.append(response.data)
        self.assertTrue(all(item == resolutions[0] for item in resolutions))
        resolution = resolutions[0]["resolution"]
        self.assertEqual(
            ["use-default", "choose-parent", "cancel"],
            resolution["choices"],
        )
        self.assertEqual(str(self.project / ".krcn"), resolution["target_path"])
        self.assertFalse((self.project / ".krcn").exists())

    def test_cancel_is_non_mutating_for_every_client(self) -> None:
        for client_kind in ("cli", "sdk", "mcp", "plugin", "codex", "claude"):
            response = self.service.execute(
                ServiceRequest(
                    client_kind,
                    "project.home.initialize",
                    {
                        "project_root": str(self.project),
                        "choice": "cancel",
                    },
                )
            )
            self.assertEqual("cancelled", response.status)
        self.assertFalse((self.project / ".krcn").exists())
        self.assertEqual(
            self.source_digest,
            hashlib.sha256(self.source.read_bytes()).hexdigest(),
        )

    def test_cli_requires_choice_then_initializes_and_learns_in_place(self) -> None:
        common = ["--repo", str(REPO_ROOT)]
        result, output, error = self._run_cli(
            ["project", "learn", str(self.project), *common]
        )
        self.assertEqual(0, result, error)
        proposal = json.loads(output)
        self.assertEqual("choice-required", proposal["status"])
        self.assertEqual(
            str(self.project / ".krcn"),
            proposal["data"]["resolution"]["target_path"],
        )
        self.assertFalse((self.project / ".krcn").exists())

        result, output, error = self._run_cli(
            [
                "project",
                "learn",
                str(self.project),
                *common,
                "--home-choice",
                "use-default",
            ]
        )
        self.assertEqual(0, result, error)
        dry_run = json.loads(output)
        self.assertEqual("planned", dry_run["status"])
        plan_id = dry_run["data"]["plan"]["plan_id"]

        result, output, error = self._run_cli(
            [
                "project",
                "learn",
                str(self.project),
                *common,
                "--home-choice",
                "use-default",
                "--apply",
                "--expected-plan",
                plan_id,
                "--approval-id",
                "proje-konumu-onayi",
            ]
        )
        self.assertEqual(0, result, error)
        self.assertEqual("applied", json.loads(output)["status"])
        marker = self.project / ".krcn" / "project-home.json"
        self.assertTrue(marker.is_file())

        result, output, error = self._run_cli(
            ["project", "learn", str(self.project), *common]
        )
        self.assertEqual(0, result, error)
        learned = json.loads(output)
        self.assertEqual("project.learn", learned["operation"])
        self.assertEqual("planned", learned["status"])
        self.assertEqual(
            self.source_digest,
            hashlib.sha256(self.source.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            [".krcn", "README.md"],
            sorted(item.name for item in self.project.iterdir()),
        )

    def test_custom_parent_plan_uses_the_same_service_contract(self) -> None:
        selected_parent = self.root / "özel-veri"
        selected_parent.mkdir()
        arguments = {
            "project_root": str(self.project),
            "choice": "choose-parent",
            "selected_parent": str(selected_parent),
        }
        dry_run = self.service.execute(
            ServiceRequest("plugin", "project.home.initialize", arguments)
        )
        self.assertEqual("planned", dry_run.status)
        target = dry_run.data["plan"]["resolution"]["target_path"]
        self.assertEqual(str(selected_parent / ".krcn"), target)
        applied = self.service.execute(
            ServiceRequest(
                "plugin",
                "project.home.initialize",
                arguments,
                apply=True,
                expected_plan_id=dry_run.data["plan"]["plan_id"],
                approval_id="özel-konum-onayi",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertTrue((selected_parent / ".krcn" / "project-home.json").is_file())
        self.assertFalse((self.project / ".krcn").exists())
        self.assertEqual(
            self.source_digest,
            hashlib.sha256(self.source.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
