from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.work_intent import (  # noqa: E402
    WorkIntentError,
    parse_work_create_intent,
)


class WorkIntentTests(unittest.TestCase):
    def test_turkish_request_routes_to_exact_work_plan(self) -> None:
        intent = parse_work_create_intent(
            "893614 talebini gpu-fusion için oluştur."
        )
        self.assertEqual("gpu-fusion", intent.project_id)
        self.assertEqual("request", intent.work_type)
        self.assertEqual("893614", intent.external_id)
        self.assertEqual("gpu-fusion-request-893614", intent.work_item_id)
        self.assertEqual("proposed", intent.status)
        self.assertTrue(intent.public_summary()["exact_plan_required"])
        self.assertTrue(intent.public_summary()["same_request_apply_supported"])
        self.assertFalse(intent.public_summary()["second_approval_required"])

    def test_project_first_defect_request_is_supported(self) -> None:
        intent = parse_work_create_intent(
            "gpu-fusion için 468337 defectini aç"
        )
        self.assertEqual("defect", intent.work_type)
        self.assertEqual("gpu-fusion-defect-468337", intent.work_item_id)

    def test_missing_project_or_type_is_not_guessed(self) -> None:
        for request in (
            "893614 talebini oluştur",
            "gpu-fusion için yeni kayıt oluştur",
            "893614 hakkında konuşalım",
        ):
            with self.subTest(request=request):
                with self.assertRaises(WorkIntentError):
                    parse_work_create_intent(request)

    def test_service_arguments_do_not_claim_completion_or_evidence(self) -> None:
        arguments = parse_work_create_intent(
            "893614 talebini gpu-fusion için kaydet"
        ).service_arguments()
        self.assertEqual("proposed", arguments["status"])
        self.assertEqual([], arguments["evidence"])
        self.assertEqual([], arguments["acceptance_criteria"])
        self.assertEqual("Talep 893614", arguments["title"])


if __name__ == "__main__":
    unittest.main()
