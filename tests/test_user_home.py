from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.user_home import UserHomeError, resolve_user_home


class UserHomeResolutionTests(unittest.TestCase):
    def test_explicit_home_has_highest_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = resolve_user_home(
                root,
                environ={"KRCN_HOME": str(root / "ignored")},
                platform_name="win32",
                home_directory=root / "profile",
            )
            self.assertEqual(root.resolve(), result.path)
            self.assertEqual("explicit", result.source)
            self.assertNotIn(str(root), str(result.public_summary()))

    def test_environment_home_is_independent_from_core_clone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = root / "portable-krcn-home"
            result = resolve_user_home(
                environ={"KRCN_HOME": str(configured)},
                platform_name="win32",
                home_directory=root / "profile",
            )
            self.assertEqual(configured.resolve(), result.path)
            self.assertEqual("environment", result.source)

    def test_windows_and_macos_defaults_use_one_platform_user_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            windows = resolve_user_home(
                environ={"LOCALAPPDATA": str(root / "local")},
                platform_name="win32",
                home_directory=root / "profile",
            )
            macos = resolve_user_home(
                environ={},
                platform_name="darwin",
                home_directory=root / "profile",
            )
            self.assertEqual((root / "local" / "KRCN").resolve(), windows.path)
            self.assertEqual(
                (root / "profile" / "Library" / "Application Support" / "KRCN").resolve(),
                macos.path,
            )

    def test_relative_environment_home_is_rejected(self) -> None:
        with self.assertRaisesRegex(UserHomeError, "absolute path"):
            resolve_user_home(
                environ={"KRCN_HOME": "relative-krcn-home"},
                platform_name="win32",
                home_directory=Path.cwd(),
            )


if __name__ == "__main__":
    unittest.main()
