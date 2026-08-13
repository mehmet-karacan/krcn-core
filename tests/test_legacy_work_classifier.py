from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from krcn_core.legacy_work_classifier import (  # noqa: E402
    LegacyWorkClassifierError,
    classify_legacy_work_source,
)
from krcn_core.work_import import parse_work_import_request  # noqa: E402


class LegacyWorkClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "isler"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: bytes = b"fixture") -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_combined_request_produces_three_related_import_candidates(self) -> None:
        for work_id in ("893614", "893609", "893508"):
            self.write(f"aktif/Talep_2026/{work_id}/{work_id}_ozet.md")
        binary = b"PK\x03\x04\x00\xffbinary fixture"
        self.write("aktif/Talep_2026/893614_893609_893508/belgeler.zip", binary)

        result = classify_legacy_work_source(self.root, project_id="gpu-fusion")
        request = result.work_import_request()
        project_id, _inventory, candidates = parse_work_import_request(request)

        self.assertEqual(project_id, "gpu-fusion")
        selected = [candidate for candidate in candidates if candidate.work_type == "request"]
        self.assertEqual(len(selected), 3)
        self.assertTrue(all(len(candidate.relations) == 2 for candidate in selected))
        serialized = json.dumps(request, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(binary.decode("latin-1"), serialized)

    def test_archive_is_not_classified_as_completed(self) -> None:
        self.write("arsiv/Defect_2025/419057/419057_GTD_FILE.docx")
        result = classify_legacy_work_source(self.root, project_id="gpu-fusion")
        candidate = result.work_import_request()["candidates"][0]
        self.assertEqual(candidate["status"], "archived")
        self.assertNotEqual(candidate["status"], "completed")

    def test_variant_directories_merge_as_evidence(self) -> None:
        self.write("aktif/Defect_2026/468337/468337_GTD_FILE.docx")
        self.write("aktif/Defect_2026/468337_2/468337_2_GTD_FILE.docx")
        self.write("aktif/Defect_2026/468337_3/468337_3_GTD_FILE.docx")
        result = classify_legacy_work_source(self.root, project_id="gpu-fusion")
        candidates = result.work_import_request()["candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["work_item_id"], "gpu-fusion-defect-item-468337")
        self.assertEqual(len(candidates[0]["evidence"]), 3)

    def test_conflicting_task_id_requires_review(self) -> None:
        self.write("aktif/G-20260812-001.md")
        self.write("aktif/20260812_G-20260812-001_DUPLICATE.md")
        result = classify_legacy_work_source(self.root, project_id="gpu-fusion")
        self.assertFalse(result.import_ready)
        self.assertEqual(result.reviews[0].code, "conflicting-task-id")
        with self.assertRaises(LegacyWorkClassifierError):
            result.work_import_request()

    def test_sensitive_source_reference_fails_closed(self) -> None:
        self.write("aktif/Talep_2026/123456/token=secret-value.txt")
        with self.assertRaises(LegacyWorkClassifierError):
            classify_legacy_work_source(self.root, project_id="gpu-fusion")


if __name__ == "__main__":
    unittest.main()
