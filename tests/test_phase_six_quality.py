from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.doctor import run_doctor  # noqa: E402
from krcn_core.release_quality import validate_release_quality  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseSixQualityTests(unittest.TestCase):
    def test_release_quality_profile_is_complete_and_fail_closed(self) -> None:
        profile = load_json(REPO_ROOT / "config" / "release-quality.json")
        self.assertEqual([], validate_release_quality(profile))
        changed = copy.deepcopy(profile)
        changed["required_gates"].remove("external-source-no-copy")
        self.assertTrue(validate_release_quality(changed))

    def test_doctor_enforces_release_quality_profile(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("release-quality", checks)
        self.assertTrue(checks["release-quality"].passed)

    def test_ci_matrix_covers_linux_windows_macos_and_offline_wheel(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "quality.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("windows-latest", workflow)
        self.assertIn("macos-latest", workflow)
        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("measure_coverage.py", workflow)
        self.assertIn("python tools/verify_wheel.py", workflow)
        self.assertIn("python tools/run_tests.py", workflow)
        self.assertIn("python tools/krcn.py doctor", workflow)

    def test_wheel_installs_offline_with_portability_services(self) -> None:
        result = subprocess.run(
            [sys.executable, "tools/verify_wheel.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("portability verification passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
