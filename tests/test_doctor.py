from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.cli.app import main  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402


class DoctorTests(unittest.TestCase):
    def test_all_completed_phase_health_checks_pass(self) -> None:
        checks = run_doctor(REPO_ROOT)
        self.assertEqual(
            {
                "repository-context",
                "foundation-contracts",
                "repository-content",
                "cli-catalog",
                "offline-provider",
                "tracked-local-data",
                "release-quality",
                "sqlite-runtime",
                "coverage-baseline",
                "phase-one-baseline",
                "phase-two-baseline",
                "phase-three-baseline",
                "phase-four-baseline",
                "phase-five-baseline",
                "phase-six-baseline",
                "phase-seven-baseline",
                "phase-eight-baseline",
                "phase-nine-baseline",
            },
            {item.check_id for item in checks},
        )
        self.assertTrue(all(item.passed for item in checks))

    def test_runtime_home_health_is_checked_only_when_requested(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            checks = run_doctor(REPO_ROOT, Path(directory))
        runtime = next(item for item in checks if item.check_id == "runtime-home")
        self.assertTrue(runtime.passed)

    def test_doctor_json_output_is_machine_readable(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = main(
                ["doctor", "--repo", str(REPO_ROOT), "--format", "json"]
            )
        self.assertEqual(0, return_code)
        self.assertTrue(all(item["passed"] for item in json.loads(output.getvalue())))

    def test_legacy_validate_routes_to_the_same_safe_checks(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = main(["validate", "--repo", str(REPO_ROOT)])
        self.assertEqual(0, return_code)
        self.assertIn("PASS\trepository-context", output.getvalue())

    def test_console_script_entrypoints_are_declared(self) -> None:
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('krcn = "krcn_core.cli.app:main"', pyproject)
        self.assertIn('krcn-context = "krcn_core.repository_context:main"', pyproject)
        self.assertIn('krcn-verify = "krcn_core.foundation:main"', pyproject)


if __name__ == "__main__":
    unittest.main()
