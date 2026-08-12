from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.cli.app import main  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402


class PhaseEightQualityUxTests(unittest.TestCase):
    def test_linux_ci_and_coverage_baseline_are_versioned(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "quality.yml").read_text(
            encoding="utf-8"
        )
        baseline = json.loads(
            (REPO_ROOT / ".ai" / "coverage-baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("measure_coverage.py --minimum 60", workflow)
        self.assertGreaterEqual(
            baseline["line_coverage_percent"],
            baseline["minimum_line_coverage_percent"],
        )
        self.assertEqual("python-monitoring-line-events", baseline["method"])

    def test_runtime_doctor_checks_sqlite_and_local_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checks = run_doctor(REPO_ROOT, Path(directory))
        by_id = {item.check_id: item for item in checks}
        self.assertTrue(by_id["sqlite-runtime"].passed)
        self.assertTrue(by_id["coverage-baseline"].passed)
        self.assertTrue(by_id["runtime-home"].passed)

    def test_cli_error_includes_a_safe_next_action(self) -> None:
        error = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(error):
            result = main(
                [
                    "knowledge",
                    "index",
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(Path(directory) / ".krcn"),
                    "--apply",
                ]
            )
        self.assertEqual(2, result)
        self.assertIn("ERROR:", error.getvalue())
        self.assertIn("NEXT:", error.getvalue())
        self.assertIn("exact plan", error.getvalue())

    def test_runtime_doctor_fails_closed_for_a_corrupt_derived_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = root / "derived" / "retrieval" / "hybrid-v1.sqlite"
            index.parent.mkdir(parents=True)
            index.write_bytes(b"not-a-database")
            checks = run_doctor(REPO_ROOT, root)
        runtime = next(item for item in checks if item.check_id == "runtime-home")
        self.assertFalse(runtime.passed)


if __name__ == "__main__":
    unittest.main()
