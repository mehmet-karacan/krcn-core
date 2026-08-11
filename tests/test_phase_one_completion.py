from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PhaseOneCompletionTests(unittest.TestCase):
    def test_current_work_marks_phase_one_completed(self) -> None:
        current = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-1", current["phase_id"])
        self.assertEqual("completed", current["status"])
        self.assertIn(
            "docs/progress/PHASE-1-COMPLETION.md", current["progress_refs"]
        )

    def test_sanitized_cli_baseline_is_ready(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "cli-baseline.json")
        self.assertEqual("ready", baseline["status"])
        self.assertFalse(baseline["legacy_source_imported"])
        self.assertEqual(29, baseline["compatibility_catalog_count"])
        self.assertEqual(
            {"catalog", "context", "doctor", "validate"},
            set(baseline["safe_commands"]),
        )
        self.assertEqual(
            {"database-statement", "mutation", "provider", "source-binding", "user-policy"},
            set(baseline["safety_gates"]),
        )
        self.assertEqual(
            {"hermetic_tests": "passed", "doctor": "passed", "offline_install": "passed"},
            baseline["verification"],
        )

    def test_cli_baseline_schema_is_versioned(self) -> None:
        schema = load_json(REPO_ROOT / "schemas" / "cli-baseline.schema.json")
        self.assertEqual("urn:krcn:schemas:cli-baseline:1", schema["$id"])


if __name__ == "__main__":
    unittest.main()
