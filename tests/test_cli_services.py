from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.cli import app as cli_app  # noqa: E402
from krcn_core.cli.app import main  # noqa: E402


class CliServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_temp = tempfile.TemporaryDirectory()
        self.data_temp = tempfile.TemporaryDirectory()
        self.source_root = Path(self.source_temp.name)
        (self.source_root / "README.md").write_text(
            "Synthetic project\n",
            encoding="utf-8",
        )
        self.base = [
            "project",
            "onboard",
            "--repo",
            str(REPO_ROOT),
            "--data-root",
            self.data_temp.name,
            "--workspace-id",
            "sample-workspace",
            "--project-id",
            "sample-project",
            "--binding-id",
            "sample-project-local",
            "--name",
            "Sample Project",
            "--source",
            str(self.source_root),
        ]

    def tearDown(self) -> None:
        self.source_temp.cleanup()
        self.data_temp.cleanup()

    def test_cli_configures_utf8_output_for_legacy_windows_consoles(self) -> None:
        class ReconfigurableStream:
            def __init__(self) -> None:
                self.calls: list[dict[str, str]] = []

            def reconfigure(self, **kwargs: str) -> None:
                self.calls.append(kwargs)

        output = ReconfigurableStream()
        error = ReconfigurableStream()
        with patch.object(cli_app.sys, "stdout", output), patch.object(
            cli_app.sys,
            "stderr",
            error,
        ):
            cli_app._configure_cli_stream_encoding()
        self.assertEqual(
            [{"encoding": "utf-8", "errors": "strict"}],
            output.calls,
        )
        self.assertEqual(output.calls, error.calls)

    @staticmethod
    def _run(arguments: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = main(arguments)
        return result, output.getvalue(), error.getvalue()

    def test_cli_onboarding_plan_apply_and_list(self) -> None:
        result, output, error = self._run(self.base)
        self.assertEqual(0, result, error)
        plan_id = json.loads(output)["data"]["plan"]["plan_id"]
        result, output, error = self._run(
            [
                *self.base,
                "--apply",
                "--expected-plan",
                plan_id,
                "--approval-id",
                "cli-approval",
            ]
        )
        self.assertEqual(0, result, error)
        self.assertEqual("applied", json.loads(output)["status"])
        result, output, error = self._run(
            [
                "project",
                "list",
                "--repo",
                str(REPO_ROOT),
                "--data-root",
                self.data_temp.name,
                "--format",
                "json",
            ]
        )
        self.assertEqual(0, result, error)
        projects = json.loads(output)["data"]["projects"]
        self.assertEqual("sample-project", projects[0]["project_id"])
        self.assertNotIn(str(self.source_root), output)

    def test_cli_rejects_apply_without_a_prior_plan(self) -> None:
        result, _, error = self._run(
            [*self.base, "--apply", "--approval-id", "cli-approval"]
        )
        self.assertEqual(2, result)
        self.assertIn("exact plan", error)

    def test_cli_migrates_flat_home_to_project_capsules(self) -> None:
        result, output, error = self._run(self.base)
        self.assertEqual(0, result, error)
        onboarding_plan = json.loads(output)["data"]["plan"]["plan_id"]
        result, _, error = self._run(
            [
                *self.base,
                "--apply",
                "--expected-plan",
                onboarding_plan,
                "--approval-id",
                "onboarding-approval",
            ]
        )
        self.assertEqual(0, result, error)
        backup = (
            Path(self.data_temp.name).parent
            / f"{Path(self.data_temp.name).name}-layout-backup.zip"
        )
        migration = [
            "portability",
            "migrate-project-capsules",
            "--repo",
            str(REPO_ROOT),
            "--data-root",
            self.data_temp.name,
            "--backup-output",
            str(backup),
        ]
        result, output, error = self._run(migration)
        self.assertEqual(0, result, error)
        migration_plan = json.loads(output)["data"]["plan"]["plan_id"]
        result, output, error = self._run(
            [
                *migration,
                "--apply",
                "--expected-plan",
                migration_plan,
                "--approval-id",
                "migration-approval",
            ]
        )
        self.assertEqual(0, result, error)
        self.assertEqual("applied", json.loads(output)["status"])
        backup.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
