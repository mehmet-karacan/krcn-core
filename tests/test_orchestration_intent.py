from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.orchestration_intent import (  # noqa: E402
    TaskIntentError,
    create_task_intent,
    parse_task_intent,
)


def value(text: str, *, origin: str = "explicit-user", reversible: bool = False):
    return {"value": text, "origin": origin, "reversible": reversible}


def extraction(*, ambiguities=None, assumptions=None):
    return {
        "task_id": "protect-database-task",
        "goal": value("Veritabanı erişimini salt okunur tut"),
        "scope": [
            value("sample-database"),
            value(
                "Mevcut ayarları koru",
                origin="safe-assumption",
                reversible=True,
            ),
        ],
        "sources": [value("integration:sample-database")],
        "constraints": [value("Yalnız SELECT işlemlerine izin ver")],
        "acceptance_criteria": [value("DELETE işlemi reddedilir")],
        "ownership_impact": ["user-data", "runtime"],
        "verification_requirements": [value("Policy kararı deny olmalıdır")],
        "assumptions": assumptions
        if assumptions is not None
        else [
            {
                "assumption_id": "preserve-settings",
                "statement": "Mevcut ayarlar korunur",
                "rationale": "Kullanıcı aksini istemedi",
                "reversible": True,
                "impact": "minor",
            }
        ],
        "ambiguities": ambiguities or [],
    }


class OrchestrationIntentTests(unittest.TestCase):
    def test_intent_is_deterministic_and_does_not_retain_raw_request(self) -> None:
        request = "Veritabanında delete istemiyorum, sadece select kullan."
        first = create_task_intent(request, extraction())
        changed_order = extraction()
        changed_order["scope"].reverse()
        changed_order["ownership_impact"].reverse()
        second = create_task_intent(request, changed_order)
        self.assertEqual(first.as_dict(), second.as_dict())
        serialized = json.dumps(first.as_dict(), ensure_ascii=False)
        self.assertNotIn(request, serialized)
        self.assertEqual("ready", first.status)
        self.assertFalse(first.clarification_required)
        self.assertEqual(
            ["runtime", "user-data"],
            first.as_dict()["ownership_impact"],
        )

    def test_material_ambiguity_blocks_planning(self) -> None:
        intent = create_task_intent(
            "Projeyi güncelle.",
            extraction(
                ambiguities=[
                    {
                        "ambiguity_id": "target-project",
                        "question": "Hangi proje güncellenecek?",
                        "impact_categories": ["scope", "user-data"],
                        "blocking": True,
                    }
                ]
            ),
        )
        self.assertEqual("needs-clarification", intent.status)
        self.assertTrue(intent.clarification_required)
        self.assertEqual(("scope", "user-data"), intent.ambiguities[0].impact_categories)

    def test_safe_assumption_must_be_minor_reversible_and_explained(self) -> None:
        unsafe = extraction()
        unsafe["scope"][1]["reversible"] = False
        with self.assertRaisesRegex(TaskIntentError, "must be reversible"):
            create_task_intent("Mevcut ayarları koru.", unsafe)

        missing_evidence = extraction(assumptions=[])
        with self.assertRaisesRegex(TaskIntentError, "assumption evidence"):
            create_task_intent("Mevcut ayarları koru.", missing_evidence)

    def test_goal_must_be_explicit_and_sensitive_text_is_rejected(self) -> None:
        inferred_goal = extraction()
        inferred_goal["goal"] = value(
            "Veritabanını değiştir",
            origin="safe-assumption",
            reversible=True,
        )
        with self.assertRaisesRegex(TaskIntentError, "explicit user"):
            create_task_intent("Veritabanına bak.", inferred_goal)
        with self.assertRaisesRegex(TaskIntentError, "sensitive"):
            create_task_intent("token=github_pat_" + "a" * 24, extraction())

    def test_digest_and_clarification_state_cannot_be_forged(self) -> None:
        intent = create_task_intent("Salt okunur çalış.", extraction())
        changed = copy.deepcopy(intent.as_dict())
        changed["constraints"][0]["value"] = "DELETE işlemine izin ver"
        with self.assertRaisesRegex(TaskIntentError, "digest does not match"):
            parse_task_intent(changed)

        forged = copy.deepcopy(intent.as_dict())
        forged["clarification_required"] = True
        forged["status"] = "needs-clarification"
        with self.assertRaisesRegex(TaskIntentError, "clarification state"):
            parse_task_intent(forged)

    def test_task_intent_schema_is_versioned(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "task-intent.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("urn:krcn:schemas:task-intent:1", schema["$id"])


if __name__ == "__main__":
    unittest.main()
