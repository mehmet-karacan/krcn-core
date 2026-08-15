from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "build_backend"))

import krcn_build_backend  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402
from progress_evidence import assert_progress_evidence  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseThreeCompletionTests(unittest.TestCase):
    def test_phase_three_baseline_is_complete_and_versioned(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-3-baseline.json")
        schema = load_json(
            REPO_ROOT / "schemas" / "phase-3-baseline.schema.json"
        )
        self.assertEqual("urn:krcn:schemas:phase-3-baseline:1", schema["$id"])
        self.assertEqual("phase-3", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertEqual(
            {
                "installation.inspect",
                "installation.verify",
                "release.diff",
                "release.merge",
                "deployment.rollback",
            },
            set(baseline["safe_operations"]),
        )
        self.assertTrue(baseline["guarantees"]["user_data_preserved"])
        self.assertTrue(baseline["guarantees"]["user_policy_preserved"])
        self.assertTrue(baseline["guarantees"]["automatic_rollback"])
        self.assertFalse(baseline["guarantees"]["local_data_tracked"])
        self.assertEqual("phase-4", baseline["next_phase"]["phase_id"])
        self.assertFalse(baseline["next_phase"]["implementation_started"])

    def test_phase_three_work_and_completion_evidence_are_closed(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        completion_ref = "docs/progress/PHASE-3-COMPLETION.md"
        integration_ref = "docs/progress/PHASE-3-INTEGRATION-TESTS.md"
        assert_progress_evidence(self, completion_ref)
        assert_progress_evidence(self, integration_ref)
        completion = (REPO_ROOT / completion_ref).read_text(encoding="utf-8")
        self.assertIn(
            "Faz 3 - güvenli `merge into` güncelleme motoru tamamlandı",
            completion,
        )
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-004-GUVENLI-MERGE-INTO-MOTORU.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Tamamlandı", plan)

    def test_doctor_includes_completed_phase_three_baseline(self) -> None:
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-three-baseline", checks)
        self.assertTrue(checks["phase-three-baseline"].passed)

    def test_wheel_installs_offline_and_exposes_phase_three_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel_directory = root / "wheel"
            target = root / "installed"
            filename = krcn_build_backend.build_wheel(str(wheel_directory))
            wheel = wheel_directory / filename
            environment = os.environ.copy()
            environment["PIP_NO_INDEX"] = "1"
            install = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--disable-pip-version-check",
                    "--target",
                    str(target),
                    str(wheel),
                ],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertEqual(0, install.returncode, install.stderr)
            imported = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {str(target)!r}); "
                        "from krcn_core.application import KrcnApplicationService; "
                        "from krcn_core.merge_engine import execute_deployment; "
                        "from krcn_core.rollback import prepare_rollback_plan; "
                        "from krcn_core.verification import verify_installation; "
                        "print(KrcnApplicationService.__name__, "
                        "execute_deployment.__name__, "
                        "prepare_rollback_plan.__name__, "
                        "verify_installation.__name__)"
                    ),
                ],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, imported.returncode, imported.stderr)
            self.assertEqual(
                (
                    "KrcnApplicationService execute_deployment "
                    "prepare_rollback_plan verify_installation"
                ),
                imported.stdout.strip(),
            )


if __name__ == "__main__":
    unittest.main()
