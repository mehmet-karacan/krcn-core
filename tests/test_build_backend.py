from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "build_backend"))

import krcn_build_backend  # noqa: E402


class BuildBackendTests(unittest.TestCase):
    def test_wheel_build_has_no_external_requirements(self) -> None:
        self.assertEqual([], krcn_build_backend.get_requires_for_build_wheel())

    def test_wheel_contains_cli_and_console_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            filename = krcn_build_backend.build_wheel(directory)
            wheel_path = Path(directory) / filename
            self.assertTrue(wheel_path.is_file())
            with zipfile.ZipFile(wheel_path) as wheel:
                names = set(wheel.namelist())
                self.assertIn("krcn_core/cli/app.py", names)
                entry_points_name = next(
                    name for name in names if name.endswith("/entry_points.txt")
                )
                entry_points = wheel.read(entry_points_name).decode("utf-8")
                self.assertIn("krcn=krcn_core.cli.app:main", entry_points)
                self.assertIn("krcn-context=krcn_core.repository_context:main", entry_points)
                self.assertIn("krcn-verify=krcn_core.foundation:main", entry_points)


if __name__ == "__main__":
    unittest.main()
