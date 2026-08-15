from __future__ import annotations

import copy
import json
import sys
import unittest
from itertools import islice
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.retrieval_quality import (  # noqa: E402
    RetrievalQualityError,
    build_retrieval_scale_manifest,
    evaluate_retrieval_golden_set,
    iter_retrieval_scale_documents,
    iter_retrieval_scale_queries,
    load_retrieval_golden_set,
    load_retrieval_scale_policy,
    parse_retrieval_golden_set,
    parse_retrieval_observations,
)


def perfect_observations(golden_set):
    observations = []
    for index, case in enumerate(golden_set.cases, 1):
        if case.expected_outcome == "stale-rejected":
            status = "stale-rejected"
            refs = ()
        elif case.expected_outcome == "empty":
            status = "completed"
            refs = ()
        else:
            status = "completed"
            refs = case.expected_relevant_refs
        observations.append(
            {
                "case_id": case.case_id,
                "status": status,
                "hits": [
                    {
                        "logical_ref": ref,
                        "project_id": case.scope_project_ids[0],
                        "revision_digest": f"{index:064x}",
                    }
                    for ref in refs
                ],
                "latency_ms": 10 + index,
            }
        )
    return observations


class RetrievalQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.golden_payload = json.loads(
            (REPO_ROOT / "config" / "retrieval-golden-set.json").read_text(
                encoding="utf-8"
            )
        )
        self.scale_payload = json.loads(
            (REPO_ROOT / "config" / "retrieval-scale-fixtures.json").read_text(
                encoding="utf-8"
            )
        )
        self.golden = load_retrieval_golden_set(REPO_ROOT)
        self.scale = load_retrieval_scale_policy(REPO_ROOT)

    def test_configs_and_results_match_public_schemas(self) -> None:
        pairs = (
            ("retrieval-golden-set.schema.json", self.golden_payload),
            ("retrieval-scale-policy.schema.json", self.scale_payload),
        )
        for schema_name, payload in pairs:
            with self.subTest(schema=schema_name):
                schema = json.loads(
                    (REPO_ROOT / "schemas" / schema_name).read_text(encoding="utf-8")
                )
                self.assertEqual([], list(Draft202012Validator(schema).iter_errors(payload)))
        result = evaluate_retrieval_golden_set(
            self.golden,
            parse_retrieval_observations(perfect_observations(self.golden), self.golden),
            engine_profile_id="deterministic-hashing-v1",
        )
        result_schema = json.loads(
            (REPO_ROOT / "schemas" / "retrieval-golden-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft202012Validator(result_schema).iter_errors(result)))
        manifest = build_retrieval_scale_manifest(self.scale, "smoke")
        manifest_schema = json.loads(
            (REPO_ROOT / "schemas" / "retrieval-scale-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft202012Validator(manifest_schema).iter_errors(manifest)))

    def test_golden_set_covers_real_user_retrieval_categories(self) -> None:
        self.assertEqual(
            {
                "exact-id",
                "typo-lexical",
                "business-concept",
                "symbol-lookup",
                "dependency-impact",
                "continuity-resume",
                "plsql-symbol",
                "cross-project-isolation",
                "stale-revision",
            },
            {case.category for case in self.golden.cases},
        )
        self.assertEqual({"tr", "en", "polyglot"}, {case.language for case in self.golden.cases})
        self.assertFalse(self.golden.as_dict()["invariants"]["source_content_included"])

    def test_perfect_evidence_passes_recall_mrr_ndcg_and_safety(self) -> None:
        observations = parse_retrieval_observations(
            perfect_observations(self.golden), self.golden
        )
        result = evaluate_retrieval_golden_set(
            self.golden,
            observations,
            engine_profile_id="reference-engine",
        )
        self.assertTrue(result["passed"])
        self.assertEqual(10000, result["metrics"]["recall_at_k_basis_points"])
        self.assertEqual(10000, result["metrics"]["mean_reciprocal_rank_basis_points"])
        self.assertEqual(10000, result["metrics"]["ndcg_at_k_basis_points"])
        self.assertEqual(0, result["metrics"]["cross_project_leakage_count"])
        self.assertEqual(0, result["metrics"]["stale_acceptance_count"])
        self.assertFalse(result["provider_call_performed"])
        self.assertFalse(result["source_content_copied"])
        self.assertFalse(result["grants_authority"])

    def test_leakage_stale_acceptance_and_missed_critical_case_fail(self) -> None:
        observations = perfect_observations(self.golden)
        by_id = {item["case_id"]: item for item in observations}
        by_id["java-symbol-lookup"]["hits"] = []
        by_id["cross-project-isolation"]["hits"] = [
            {
                "logical_ref": "work:beta-project/request-42",
                "project_id": "beta-project",
                "revision_digest": "a" * 64,
            }
        ]
        by_id["stale-source-revision"]["status"] = "completed"
        by_id["stale-source-revision"]["hits"] = [
            {
                "logical_ref": "code:java-service/payment-controller",
                "project_id": "java-service",
                "revision_digest": "b" * 64,
            }
        ]
        result = evaluate_retrieval_golden_set(
            self.golden,
            parse_retrieval_observations(observations, self.golden),
            engine_profile_id="unsafe-engine",
        )
        self.assertFalse(result["passed"])
        self.assertGreater(result["metrics"]["cross_project_leakage_count"], 0)
        self.assertEqual(1, result["metrics"]["stale_acceptance_count"])
        self.assertIn("java-symbol-lookup", result["critical_failure_case_ids"])

    def test_observations_require_exact_coverage_and_portable_evidence(self) -> None:
        observations = perfect_observations(self.golden)
        with self.assertRaisesRegex(RetrievalQualityError, "exact golden set"):
            parse_retrieval_observations(observations[:-1], self.golden)
        tampered = copy.deepcopy(observations)
        tampered[0]["hits"][0]["logical_ref"] = "code:C:/private/source.py"
        with self.assertRaisesRegex(RetrievalQualityError, "physical path"):
            parse_retrieval_observations(tampered, self.golden)
        mismatched = copy.deepcopy(observations)
        mismatched[0]["hits"][0]["project_id"] = "other-project"
        with self.assertRaisesRegex(RetrievalQualityError, "must match"):
            parse_retrieval_observations(mismatched, self.golden)
        golden = copy.deepcopy(self.golden_payload)
        golden["cases"][0]["query_text"] = "token=" + "a" * 40
        with self.assertRaisesRegex(RetrievalQualityError, "sensitive"):
            parse_retrieval_golden_set(golden)

    def test_scale_fixtures_are_lazy_deterministic_and_content_safe(self) -> None:
        first = list(islice(iter_retrieval_scale_documents(self.scale, "large"), 5))
        second = list(islice(iter_retrieval_scale_documents(self.scale, "large"), 5))
        self.assertEqual(first, second)
        self.assertEqual(5, len(first))
        self.assertTrue(all(item.logical_ref.startswith("fixture:scale-project-") for item in first))
        self.assertTrue(all("Users" not in item.text and "home/" not in item.text for item in first))
        first_manifest = build_retrieval_scale_manifest(self.scale, "smoke")
        second_manifest = build_retrieval_scale_manifest(self.scale, "smoke")
        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(128, first_manifest["document_count"])
        self.assertTrue(first_manifest["synthetic_only"])
        self.assertFalse(first_manifest["source_content_included"])
        queries = list(iter_retrieval_scale_queries(self.scale, "smoke"))
        self.assertEqual(16, len(queries))
        self.assertEqual(queries[0].expected_ref, "fixture:scale-project-001/scale-doc-000001")
        self.assertRegex(first_manifest["query_digest"], r"^[a-f0-9]{64}$")

    def test_application_is_read_only_and_client_neutral(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / ".krcn"
            home.mkdir()
            (home / "layout.json").write_bytes(user_home_layout_bytes())
            service = KrcnApplicationService(
                REPO_ROOT,
                LocalWorkspaceStore(home, OwnershipResolver.from_repository(REPO_ROOT)),
            )
            arguments = {
                "engine_profile_id": "reference-engine",
                "observations": perfect_observations(self.golden),
            }
            results = [
                service.execute(
                    ServiceRequest(client, "retrieval.evaluate-golden", arguments)
                ).data
                for client in ("cli", "sdk", "mcp", "codex", "claude", "opencode")
            ]
            self.assertTrue(all(item == results[0] for item in results[1:]))
            self.assertTrue(results[0]["result"]["passed"])
            scale = service.execute(
                ServiceRequest(
                    "cli",
                    "retrieval.scale-fixture",
                    {"profile_id": "smoke"},
                )
            )
            self.assertEqual("ok", scale.status)
            self.assertEqual(128, scale.data["manifest"]["document_count"])
            with self.assertRaisesRegex(ValueError, "read-only"):
                service.execute(
                    ServiceRequest(
                        "cli",
                        "retrieval.scale-fixture",
                        {"profile_id": "smoke"},
                        apply=True,
                    )
                )


if __name__ == "__main__":
    unittest.main()
