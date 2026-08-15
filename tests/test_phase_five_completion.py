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
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "build_backend"))

import krcn_build_backend  # noqa: E402
from krcn_core.application import OPERATIONS  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402
from progress_evidence import assert_progress_evidence  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseFiveCompletionTests(unittest.TestCase):
    def test_phase_five_baseline_is_complete_and_versioned(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-5-baseline.json")
        schema = load_json(REPO_ROOT / "schemas" / "phase-5-baseline.schema.json")
        self.assertEqual("urn:krcn:schemas:phase-5-baseline:1", schema["$id"])
        self.assertEqual("phase-5", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertEqual(
            {
                "orchestrator.intent",
                "orchestrator.plan",
                "orchestrator.authorize",
                "orchestrator.start",
                "orchestrator.execute",
                "orchestrator.verify",
                "orchestrator.status",
                "orchestrator.resume",
            },
            set(baseline["safe_operations"]),
        )
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertTrue(baseline["guarantees"]["user_data_preserved"])
        self.assertTrue(baseline["guarantees"]["user_policy_preserved"])
        self.assertTrue(baseline["guarantees"]["exact_plan_required"])
        self.assertTrue(baseline["guarantees"]["verification_required"])
        self.assertFalse(baseline["guarantees"]["planner_grants_execution"])
        self.assertFalse(baseline["guarantees"]["chat_history_required"])
        self.assertEqual("phase-6", baseline["next_phase"]["phase_id"])
        self.assertFalse(baseline["next_phase"]["implementation_started"])
        self.assertTrue(baseline["next_phase"]["user_approval_required"])

    def test_phase_five_work_plan_and_completion_evidence_are_closed(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        completion_ref = "docs/progress/PHASE-5-COMPLETION.md"
        integration_ref = "docs/progress/PHASE-5-INTEGRATION-TESTS.md"
        assert_progress_evidence(self, completion_ref)
        assert_progress_evidence(self, integration_ref)
        completion = (REPO_ROOT / completion_ref).read_text(encoding="utf-8")
        self.assertIn(
            "Faz 5 - orchestrator ve doğal dil görev akışı tamamlandı",
            completion,
        )
        self.assertIn("Faz 6 başlatılmadı", completion)
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-006-ORCHESTRATOR-DOGAL-DIL-GOREV-AKISI.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Tamamlandı", plan)

    def test_context_and_doctor_include_phase_five_baseline(self) -> None:
        context = load_json(REPO_ROOT / ".ai" / "repository-context.json")
        self.assertEqual(
            ".ai/phase-5-baseline.json",
            context["canonical"]["phase_five_baseline"],
        )
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-five-baseline", checks)
        self.assertTrue(checks["phase-five-baseline"].passed)

    def test_wheel_installs_offline_and_exposes_phase_five_services(self) -> None:
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
                        "from krcn_core.orchestration_service import OrchestrationApplicationService; "
                        "from krcn_core.orchestration_intent import create_task_intent; "
                        "from krcn_core.orchestration_plan import create_task_plan; "
                        "from krcn_core.orchestration_authorization import authorize_task_plan; "
                        "from krcn_core.orchestration_worker import execute_worker_step; "
                        "from krcn_core.orchestration_verifier import verify_task; "
                        "from krcn_core.orchestration_state import OrchestrationStateStore; "
                        "print(KrcnApplicationService.__name__, "
                        "OrchestrationApplicationService.__name__, "
                        "create_task_intent.__name__, create_task_plan.__name__, "
                        "authorize_task_plan.__name__, execute_worker_step.__name__, "
                        "verify_task.__name__, OrchestrationStateStore.__name__)"
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
                    "KrcnApplicationService OrchestrationApplicationService "
                    "create_task_intent create_task_plan authorize_task_plan "
                    "execute_worker_step verify_task OrchestrationStateStore"
                ),
                imported.stdout.strip(),
            )


if __name__ == "__main__":
    unittest.main()
