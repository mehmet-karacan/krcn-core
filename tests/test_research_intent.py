from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.research_intent import (  # noqa: E402
    ResearchIntentError,
    parse_research_intent,
)


class ResearchIntentTests(unittest.TestCase):
    def validate(self, schema_name: str, payload: object) -> None:
        schema = json.loads((REPO_ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))

    def test_policy_and_result_schemas_are_valid(self) -> None:
        for name in (
            "research-intent-policy.schema.json",
            "research-intent-result.schema.json",
        ):
            schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        policy = json.loads((REPO_ROOT / "config" / "research-intent.json").read_text(encoding="utf-8"))
        self.validate("research-intent-policy.schema.json", policy)

    def test_turkish_and_english_modes_are_deterministic(self) -> None:
        cases = {
            "Python 3.14 yeniliklerini hızlıca araştır": "quick",
            "Oracle metadata yaklaşımını derinlemesine araştır": "deep",
            "BGE-M3 ile Qwen embedding modellerini karşılaştır": "comparison",
            "Bu hatanın kök nedenini bul": "root-cause",
            "Research Python packaging changes": "standard",
        }
        for text, expected_mode in cases.items():
            with self.subTest(text=text):
                first = parse_research_intent(REPO_ROOT, text)
                second = parse_research_intent(REPO_ROOT, text)
                self.assertIsNotNone(first)
                self.assertEqual(expected_mode, first.mode)
                self.assertEqual(first, second)
                self.validate("research-intent-result.schema.json", first.public_summary())

    def test_outcomes_do_not_grant_implementation_or_provider_authority(self) -> None:
        cases = {
            "Oracle bağımlılıklarını araştır": "research-only",
            "Oracle bağımlılıklarını araştır ve planla": "research-and-plan",
            "Oracle bağımlılıklarını araştır ve uygula": "research-and-implement",
            "Research and implement the cache strategy": "research-and-implement",
        }
        for text, outcome in cases.items():
            with self.subTest(text=text):
                intent = parse_research_intent(REPO_ROOT, text)
                self.assertEqual(outcome, intent.outcome)
                summary = intent.public_summary()
                self.assertFalse(summary["authority_granted"])
                self.assertFalse(summary["mutation_authorized"])
                self.assertFalse(summary["provider_authorized"])

    def test_generic_action_is_not_silently_routed_to_research(self) -> None:
        for text in (
            "bunu yap",
            "şunu düzelt",
            "do this",
            "implement it",
            "araştırma durumunu göster",
            "araştırmayı iptal et",
            "araştırmacı rolünü oluştur",
            "research status",
            "cancel research",
            "show research history",
            "resume research",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_research_intent(REPO_ROOT, text))

    def test_missing_reference_requests_context_and_never_builds_a_run(self) -> None:
        intent = parse_research_intent(REPO_ROOT, "Bunu araştır")
        self.assertTrue(intent.needs_context)
        self.assertFalse(intent.needs_project)
        self.assertEqual("provide-context", intent.public_summary()["next_action"])
        with self.assertRaisesRegex(ResearchIntentError, "needs context"):
            intent.research_request()
        resolved = parse_research_intent(
            REPO_ROOT,
            "Bunu araştır",
            context_text="Python 3.14 free-threaded runtime behavior",
        )
        self.assertFalse(resolved.needs_context)
        self.assertEqual("Python 3.14 free-threaded runtime behavior", resolved.objective)

    def test_project_scope_requires_project_only_when_explicitly_referenced(self) -> None:
        missing = parse_research_intent(REPO_ROOT, "Bu projedeki cache hatasını araştır")
        self.assertTrue(missing.needs_project)
        self.assertTrue(missing.needs_context)
        self.assertEqual("project", missing.scope_preference)
        self.assertEqual("select-project", missing.public_summary()["next_action"])
        project = parse_research_intent(
            REPO_ROOT,
            "Bu projedeki cache hatasını araştır",
            project_id="gpu-fusion",
        )
        self.assertFalse(project.needs_project)
        self.assertFalse(project.needs_context)
        self.assertEqual("project", project.research_request()["scope"])
        global_intent = parse_research_intent(REPO_ROOT, "Java ve Python performansını karşılaştır")
        self.assertEqual("global", global_intent.scope_preference)
        self.assertEqual("global", global_intent.research_request()["scope"])
        automatic = parse_research_intent(
            REPO_ROOT, "Oracle metadata stratejisini araştır", project_id="gpu-fusion"
        )
        self.assertEqual("auto", automatic.scope_preference)
        self.assertEqual("project", automatic.research_request()["scope"])

    def test_research_request_is_deterministic_and_schema_valid(self) -> None:
        intent = parse_research_intent(
            REPO_ROOT,
            "BGE-M3 ile Qwen embedding modellerini karşılaştır ve planla",
        )
        first = intent.research_request()
        second = intent.research_request()
        self.assertEqual(first, second)
        self.assertRegex(first["research_id"], r"^research-[a-f0-9]{24}$")
        self.validate("research-run-request.schema.json", first)

    def test_public_summary_never_contains_raw_text_path_or_secret(self) -> None:
        text = "Python 3.14 scheduler davranışını araştır"
        intent = parse_research_intent(REPO_ROOT, text)
        public = intent.public_summary()
        encoded = json.dumps(public, ensure_ascii=False)
        self.assertNotIn(text, encoded)
        self.assertFalse(public["raw_request_included"])
        self.assertFalse(public["physical_paths_included"])
        self.assertFalse(public["credential_values_included"])
        for unsafe in (
            "C:" + "\\private\\source projesini araştır",
            "/etc" + "/passwd içeriğini araştır",
            "tok" + "en=super-sensitive-value ile sağlayıcıyı araştır",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ResearchIntentError):
                    parse_research_intent(REPO_ROOT, unsafe)

    def test_bare_research_verb_needs_context(self) -> None:
        for text in ("araştır", "research", "kök nedenini bul"):
            with self.subTest(text=text):
                intent = parse_research_intent(REPO_ROOT, text)
                self.assertTrue(intent.needs_context)

    def test_natural_turkish_morphology_routes_expected_modes(self) -> None:
        unresolved = parse_research_intent(
            REPO_ROOT,
            "Bunu detaylı bir şekilde araştır.",
        )
        self.assertTrue(unresolved.needs_context)
        detailed = parse_research_intent(
            REPO_ROOT,
            "Bunu detaylı bir şekilde araştır.",
            context_text="Java virtual threads behavior under load",
        )
        self.assertEqual("deep", detailed.mode)
        self.assertFalse(detailed.needs_context)
        root_cause = parse_research_intent(
            REPO_ROOT,
            "Kök nedenini araştır",
            context_text="The build intermittently fails after dependency updates",
        )
        self.assertEqual("root-cause", root_cause.mode)
        comparison = parse_research_intent(
            REPO_ROOT,
            "Spring Boot ile Quarkus'u karşılaştır",
        )
        self.assertEqual("comparison", comparison.mode)
        self.assertFalse(comparison.needs_context)

    def test_mode_and_filler_words_are_not_mistaken_for_a_topic(self) -> None:
        for text, mode in (
            ("Kök nedenini araştır", "root-cause"),
            ("Detaylı bir şekilde araştır", "deep"),
        ):
            with self.subTest(text=text):
                intent = parse_research_intent(REPO_ROOT, text)
                self.assertEqual(mode, intent.mode)
                self.assertTrue(intent.needs_context)
        topical = parse_research_intent(
            REPO_ROOT,
            "Derleme hatasının kök nedenini araştır",
        )
        self.assertEqual("root-cause", topical.mode)
        self.assertFalse(topical.needs_context)

    def test_unresolved_generic_subject_and_incomplete_comparison_need_context(self) -> None:
        for text in (
            "Bu hatanın kök nedenini araştır",
            "A yaklaşımını karşılaştır",
        ):
            with self.subTest(text=text):
                intent = parse_research_intent(REPO_ROOT, text)
                self.assertTrue(intent.needs_context)
        resolved = parse_research_intent(
            REPO_ROOT,
            "Bu hatanın kök nedenini araştır",
            context_text="Derleme bağımlılık güncellemesinden sonra aralıklı hata veriyor.",
        )
        self.assertFalse(resolved.needs_context)

    def test_named_unregistered_project_requires_project_selection(self) -> None:
        intent = parse_research_intent(
            REPO_ROOT,
            "unknown-project projesini detaylı araştır",
        )
        self.assertTrue(intent.needs_project)
        self.assertEqual("select-project", intent.public_summary()["next_action"])

    def test_project_like_words_do_not_create_a_project_requirement(self) -> None:
        for text in (
            "Görüntü projeksiyon tekniklerini araştır",
            "Projectile motion research",
        ):
            with self.subTest(text=text):
                intent = parse_research_intent(REPO_ROOT, text)
                self.assertFalse(intent.needs_project)


if __name__ == "__main__":
    unittest.main()
