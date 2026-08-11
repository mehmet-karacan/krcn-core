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
from krcn_core.application import OPERATIONS  # noqa: E402
from krcn_core.doctor import run_doctor  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseFourCompletionTests(unittest.TestCase):
    def test_phase_four_baseline_is_complete_and_versioned(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-4-baseline.json")
        schema = load_json(
            REPO_ROOT / "schemas" / "phase-4-baseline.schema.json"
        )
        self.assertEqual("urn:krcn:schemas:phase-4-baseline:1", schema["$id"])
        self.assertEqual("phase-4", baseline["phase_id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertEqual(
            {
                "knowledge.catalog",
                "knowledge.search-exact",
                "knowledge.search-dependencies",
                "knowledge.search-semantic",
                "context.build",
                "memory.propose",
                "memory.review",
                "memory.persist",
                "memory.lifecycle",
            },
            set(baseline["safe_operations"]),
        )
        self.assertTrue(set(baseline["safe_operations"]).issubset(OPERATIONS))
        self.assertTrue(baseline["guarantees"]["user_data_preserved"])
        self.assertTrue(baseline["guarantees"]["user_policy_preserved"])
        self.assertTrue(baseline["guarantees"]["context_budget_enforced"])
        self.assertTrue(baseline["guarantees"]["memory_approval_required"])
        self.assertFalse(baseline["guarantees"]["chat_history_required"])
        self.assertFalse(baseline["guarantees"]["implicit_network_access"])
        self.assertEqual("phase-5", baseline["next_phase"]["phase_id"])
        self.assertFalse(baseline["next_phase"]["implementation_started"])

    def test_phase_four_work_and_completion_evidence_are_closed(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-4", current["phase_id"])
        self.assertEqual("completed", current["status"])
        completion_ref = "docs/progress/PHASE-4-COMPLETION.md"
        integration_ref = "docs/progress/PHASE-4-INTEGRATION-TESTS.md"
        self.assertIn(completion_ref, current["progress_refs"])
        self.assertIn(integration_ref, current["progress_refs"])
        completion = (REPO_ROOT / completion_ref).read_text(encoding="utf-8")
        self.assertIn(
            "Faz 4 - context, knowledge ve memory tamamlandı",
            completion,
        )
        plan = (
            REPO_ROOT
            / "docs"
            / "plans"
            / "PLAN-005-CONTEXT-KNOWLEDGE-MEMORY.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Tamamlandı", plan)

    def test_repository_context_and_doctor_include_phase_four_baseline(self) -> None:
        context = load_json(REPO_ROOT / ".ai" / "repository-context.json")
        self.assertEqual(
            ".ai/phase-4-baseline.json",
            context["canonical"]["phase_four_baseline"],
        )
        checks = {item.check_id: item for item in run_doctor(REPO_ROOT)}
        self.assertIn("phase-four-baseline", checks)
        self.assertTrue(checks["phase-four-baseline"].passed)

    def test_wheel_installs_offline_and_exposes_phase_four_services(self) -> None:
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
                        "from krcn_core.context_builder import build_context_package; "
                        "from krcn_core.dependency_retrieval import retrieve_dependencies; "
                        "from krcn_core.exact_retrieval import retrieve_exact; "
                        "from krcn_core.memory_gate import prepare_memory_persistence; "
                        "from krcn_core.semantic_retrieval import retrieve_semantic; "
                        "print(KrcnApplicationService.__name__, "
                        "retrieve_exact.__name__, retrieve_dependencies.__name__, "
                        "retrieve_semantic.__name__, build_context_package.__name__, "
                        "prepare_memory_persistence.__name__)"
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
                    "KrcnApplicationService retrieve_exact retrieve_dependencies "
                    "retrieve_semantic build_context_package "
                    "prepare_memory_persistence"
                ),
                imported.stdout.strip(),
            )


if __name__ == "__main__":
    unittest.main()
