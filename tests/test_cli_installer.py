from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "krcn_install_cli",
    REPO_ROOT / "tools" / "install_cli.py",
)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INSTALLER
SPEC.loader.exec_module(INSTALLER)


class CliInstallerTests(unittest.TestCase):
    def test_plan_only_is_cross_platform_and_does_not_apply(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "install_cli.py"), "--plan-only"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Plan completed. No change was applied.", result.stdout)

    def test_posix_profile_append_preserves_existing_content(self) -> None:
        original = b"# Existing shell settings\nexport SAMPLE=value\n"
        rendered = INSTALLER._render_posix_profile(
            original,
            core_home=PurePosixPath("/opt/example/KRCN Core"),
            scripts_directory=PurePosixPath(
                "/opt/example/.local/share/krcn/cli/bin"
            ),
        )
        self.assertTrue(rendered.startswith(original))
        text = rendered.decode("utf-8")
        self.assertEqual(1, text.count(INSTALLER.POSIX_BEGIN_MARKER))
        self.assertEqual(1, text.count(INSTALLER.POSIX_END_MARKER))
        self.assertIn("KRCN_CORE_HOME='/opt/example/KRCN Core'", text)

    def test_posix_profile_replaces_only_the_managed_block(self) -> None:
        original = (
            "# Before\n"
            f"{INSTALLER.POSIX_BEGIN_MARKER}\nold\n{INSTALLER.POSIX_END_MARKER}\n"
            "# After\n"
        ).encode("utf-8")
        rendered = INSTALLER._render_posix_profile(
            original,
            core_home=PurePosixPath("/opt/krcn-core"),
            scripts_directory=PurePosixPath("/tmp/krcn-cli/bin"),
        ).decode("utf-8")
        self.assertTrue(rendered.startswith("# Before\n"))
        self.assertTrue(rendered.endswith("# After\n"))
        self.assertNotIn("\nold\n", rendered)

    def test_posix_profile_rejects_malformed_markers(self) -> None:
        with self.assertRaisesRegex(INSTALLER.CliInstallationError, "markers"):
            INSTALLER._render_posix_profile(
                f"{INSTALLER.POSIX_BEGIN_MARKER}\n".encode("utf-8"),
                core_home=PurePosixPath("/opt/krcn-core"),
                scripts_directory=PurePosixPath("/tmp/krcn-cli/bin"),
            )

    def test_atomic_profile_write_preserves_existing_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".profile"
            target.write_bytes(b"before\n")
            target.chmod(0o600)
            INSTALLER._atomic_write(target, b"after\n")
            self.assertEqual(b"after\n", target.read_bytes())
            if os.name != "nt":
                self.assertEqual(0o600, target.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
