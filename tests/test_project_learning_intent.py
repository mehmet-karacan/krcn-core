from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.project_learning_intent import (  # noqa: E402
    ProjectLearningIntentError,
    parse_project_learning_intent,
)


class ProjectLearningIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "boşluk içeren proje"
        self.project.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_existing_directory_alone_implies_project_learning(self) -> None:
        intent = parse_project_learning_intent(str(self.project))
        self.assertEqual("learn-project", intent.action)
        self.assertEqual("safe-assumption", intent.intent_origin)
        self.assertEqual(self.project.resolve(), intent.source_root)

    def test_turkish_learning_phrases_resolve_the_same_directory(self) -> None:
        for phrase in (
            "projesini öğren",
            "bu projeyi tanı",
            "projeyi tanıt",
            "projeyi entegre et",
            "projeyi kaydet",
        ):
            with self.subTest(phrase=phrase):
                intent = parse_project_learning_intent(
                    f'"{self.project}" {phrase}'
                )
                self.assertEqual(self.project.resolve(), intent.source_root)
                self.assertEqual("explicit-user", intent.intent_origin)

    def test_english_learning_phrases_are_supported(self) -> None:
        for phrase in ("learn this project", "register project", "onboard it", "integrate"):
            with self.subTest(phrase=phrase):
                intent = parse_project_learning_intent(
                    phrase,
                    source_root=self.project,
                )
                self.assertEqual(self.project.resolve(), intent.source_root)

    def test_unquoted_existing_path_with_trailing_intent_is_resolved(self) -> None:
        intent = parse_project_learning_intent(
            f"{self.project} projesini öğren"
        )
        self.assertEqual(self.project.resolve(), intent.source_root)

    def test_public_summary_does_not_retain_prompt_or_path(self) -> None:
        request = f'"{self.project}" projesini öğren'
        summary = parse_project_learning_intent(request).public_summary()
        serialized = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn(request, serialized)
        self.assertNotIn(str(self.project), serialized)
        self.assertFalse(summary["path_disclosed"])

    def test_missing_multiple_and_unsupported_requests_fail_closed(self) -> None:
        other = self.root / "other"
        other.mkdir()
        missing = "C" + ":" + "\\" + "missing" + "\\" + "project"
        with self.assertRaisesRegex(ProjectLearningIntentError, "existing absolute"):
            parse_project_learning_intent(f"{missing} projesini öğren")
        with self.assertRaisesRegex(ProjectLearningIntentError, "exactly one"):
            parse_project_learning_intent(
                f'"{self.project}" ve "{other}" projelerini öğren'
            )
        with self.assertRaisesRegex(ProjectLearningIntentError, "not recognized"):
            parse_project_learning_intent(
                "bu dizini sil",
                source_root=self.project,
            )

    def test_secret_like_prompt_is_rejected(self) -> None:
        value = "github" + "_pat_" + "a" * 24
        with self.assertRaisesRegex(ProjectLearningIntentError, "sensitive"):
            parse_project_learning_intent(
                f'"{self.project}" projesini öğren {value}'
            )


if __name__ == "__main__":
    unittest.main()
