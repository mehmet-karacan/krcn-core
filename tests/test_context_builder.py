from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.context_builder import (  # noqa: E402
    ContextCandidate,
    ContextBuilderError,
    build_context_package,
    candidates_from_dependency_result,
    candidates_from_exact_result,
    candidates_from_semantic_result,
    context_candidate_from_entry,
    parse_context_build_request,
)
from krcn_core.dependency_retrieval import (  # noqa: E402
    parse_dependency_query,
    retrieve_dependencies,
)
from krcn_core.exact_retrieval import (  # noqa: E402
    parse_exact_retrieval_query,
    retrieve_exact,
)
from krcn_core.information_records import parse_information_record, payload_digest  # noqa: E402
from krcn_core.knowledge_catalog import build_information_catalog  # noqa: E402
from krcn_core.provider_gate import load_provider_gate_policy  # noqa: E402
from krcn_core.semantic_retrieval import (  # noqa: E402
    create_semantic_provider_request,
    parse_semantic_query,
    retrieve_semantic,
)
from phase_four_fixtures import (  # noqa: E402
    knowledge_record,
    source_binding,
    source_record,
)


def build_request(
    *,
    budget_unit: str = "bytes",
    budget_limit: int = 10000,
    item_limit: int = 20,
    required_record_ids: list[str] | None = None,
    allow_optional_truncation: bool = True,
    minimum_fragment_units: int = 1,
):
    return parse_context_build_request(
        {
            "schema_ref": "schemas/context-build-request.schema.json",
            "schema_version": 1,
            "context_id": "sample-context",
            "task_ref": "task:sample-project/active",
            "project_ref": "project:sample-project",
            "budget_unit": budget_unit,
            "budget_limit": budget_limit,
            "item_limit": item_limit,
            "allow_optional_truncation": allow_optional_truncation,
            "minimum_fragment_units": minimum_fragment_units,
            "required_record_ids": required_record_ids or [],
        }
    )


def with_text(record, text: str):
    payload = record.as_payload()
    content = dict(payload["payload"])
    content["text"] = text
    payload["payload"] = content
    payload["content_digest"] = payload_digest(content)
    return parse_information_record(payload)


class ContextBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = source_record()
        self.knowledge = knowledge_record()
        self.catalog = build_information_catalog(
            [source_binding()],
            [self.source, self.knowledge],
        )
        self.knowledge_entry = self.catalog.get("database-read-rule")
        self.source_entry = self.catalog.get("sample-project-source")

    def candidate(
        self,
        entry=None,
        *,
        layer: str = "task",
        required: bool = False,
        priority: int = 100,
        allow_truncation: bool = True,
    ):
        return context_candidate_from_entry(
            entry or self.knowledge_entry,
            layer=layer,
            selection_source="exact",
            selection_reason="exact:record-id",
            required=required,
            priority=priority,
            allow_truncation=allow_truncation,
        )

    def test_required_context_is_complete_and_evidence_bound(self) -> None:
        package = build_context_package(
            build_request(required_record_ids=["database-read-rule"]),
            [self.candidate()],
        )
        self.assertEqual(1, len(package.items))
        item = package.items[0]
        self.assertTrue(item.required)
        self.assertFalse(item.truncated)
        self.assertEqual(self.knowledge.content_digest, item.record.content_digest)
        self.assertIn(
            "record:database-read-rule",
            [evidence.source_ref for evidence in item.evidence],
        )
        self.assertLessEqual(package.budget_used, package.request.budget_limit)

        candidate_required = build_context_package(
            build_request(),
            [self.candidate(required=True)],
        )
        self.assertEqual(
            ["database-read-rule"],
            candidate_required.as_dict()["required_record_ids"],
        )

    def test_missing_or_oversized_mandatory_context_fails_closed(self) -> None:
        with self.assertRaisesRegex(ContextBuilderError, "was not supplied"):
            build_context_package(
                build_request(required_record_ids=["database-read-rule"]),
                [],
            )
        with self.assertRaisesRegex(ContextBuilderError, "content budget"):
            build_context_package(
                build_request(
                    budget_limit=5,
                    required_record_ids=["database-read-rule"],
                ),
                [self.candidate()],
            )

    def test_optional_utf8_content_truncates_on_character_boundary(self) -> None:
        changed = with_text(self.knowledge, "şğüİ context")
        catalog = build_information_catalog(
            [source_binding()],
            [self.source, changed],
        )
        candidate = self.candidate(catalog.get("database-read-rule"))
        package = build_context_package(
            build_request(budget_unit="bytes", budget_limit=5),
            [candidate],
        )
        self.assertTrue(package.items[0].truncated)
        package.items[0].content.encode("utf-8")
        self.assertLessEqual(package.items[0].included_units, 5)

    def test_token_budget_uses_deterministic_word_and_punctuation_units(self) -> None:
        changed = with_text(self.knowledge, "Bir, iki üç.")
        catalog = build_information_catalog(
            [source_binding()],
            [self.source, changed],
        )
        package = build_context_package(
            build_request(budget_unit="tokens", budget_limit=3),
            [self.candidate(catalog.get("database-read-rule"))],
        )
        self.assertEqual("Bir, iki", package.items[0].content)
        self.assertEqual(3, package.items[0].included_units)
        self.assertTrue(package.items[0].truncated)

    def test_stale_optional_context_is_excluded_and_required_is_rejected(self) -> None:
        stale_catalog = build_information_catalog(
            [source_binding()],
            [
                source_record(source_revision="rev-2", source_digest="b" * 64),
                self.knowledge,
            ],
        )
        stale = self.candidate(stale_catalog.get("database-read-rule"))
        optional = build_context_package(build_request(), [stale])
        self.assertEqual((), optional.items)
        self.assertEqual("stale-or-unavailable", optional.exclusions[0].reason)
        with self.assertRaisesRegex(ContextBuilderError, "stale or unavailable"):
            build_context_package(
                build_request(required_record_ids=["database-read-rule"]),
                [stale],
            )

    def test_retrieval_layers_merge_without_duplicate_content(self) -> None:
        exact_query = parse_exact_retrieval_query(
            {
                "schema_ref": "schemas/exact-retrieval-query.schema.json",
                "schema_version": 1,
                "query_id": "context-exact-query",
                "text": "database-read-rule",
                "fields": ["record-id"],
                "case_sensitive": False,
                "include_unavailable": False,
                "limit": 10,
            }
        )
        exact = retrieve_exact(self.catalog, exact_query)
        dependency_query = parse_dependency_query(
            {
                "schema_ref": "schemas/dependency-query.schema.json",
                "schema_version": 1,
                "query_id": "context-dependency-query",
                "seed_record_ids": ["database-read-rule"],
                "direction": "outbound",
                "relation_types": ["related-to"],
                "max_depth": 1,
                "node_budget": 5,
                "edge_budget": 5,
                "include_stale_edges": False,
                "include_unavailable_nodes": False,
            }
        )
        dependency = retrieve_dependencies(self.catalog, [], dependency_query)
        semantic_query = parse_semantic_query(
            {
                "schema_ref": "schemas/semantic-query.schema.json",
                "schema_version": 1,
                "query_id": "context-semantic-query",
                "text": "database read operations",
                "provider": "deterministic-hashing",
                "remote": False,
                "session_id": "context-session",
                "limit": 10,
                "minimum_score": 0.01,
                "include_unavailable": False,
            }
        )
        provider_request = create_semantic_provider_request(
            semantic_query,
            endpoint="local-process",
            retention_assumptions="No remote retention",
        )
        semantic = retrieve_semantic(
            self.catalog,
            semantic_query,
            load_provider_gate_policy(REPO_ROOT),
            provider_request,
        )
        candidates = (
            *candidates_from_exact_result(exact),
            *candidates_from_dependency_result(dependency),
            *candidates_from_semantic_result(semantic),
        )
        package = build_context_package(build_request(), candidates)
        self.assertEqual(1, len(package.items))
        self.assertEqual(
            ("exact", "dependency", "semantic"),
            package.items[0].selection_sources,
        )

    def test_candidate_order_does_not_change_context_digest(self) -> None:
        source = self.candidate(self.source_entry, layer="static", priority=100)
        knowledge = self.candidate(priority=100)
        first = build_context_package(build_request(), [knowledge, source])
        second = build_context_package(build_request(), [source, knowledge])
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual("sample-project-source", first.items[0].record.record_id)

    def test_item_budget_records_deterministic_exclusion(self) -> None:
        package = build_context_package(
            build_request(item_limit=1),
            [
                self.candidate(self.source_entry, layer="static", priority=100),
                self.candidate(priority=100),
            ],
        )
        self.assertEqual(1, len(package.items))
        self.assertEqual("item-budget", package.exclusions[0].reason)

    def test_candidate_record_is_revalidated_before_content_projection(self) -> None:
        candidate = self.candidate()
        candidate.record.payload["text"] = "Changed after candidate creation"
        with self.assertRaisesRegex(ContextBuilderError, "record is invalid"):
            build_context_package(build_request(), [candidate])

    def test_invalid_candidate_selection_metadata_is_rejected_cleanly(self) -> None:
        candidate = self.candidate()
        invalid = ContextCandidate(
            record=candidate.record,
            availability=candidate.availability,
            layer=candidate.layer,
            selection_sources=(),
            selection_reasons=candidate.selection_reasons,
            required=False,
            priority=100,
            allow_truncation=True,
        )
        with self.assertRaisesRegex(ContextBuilderError, "selection sources"):
            build_context_package(build_request(), [invalid])

    def test_context_does_not_expose_source_locator(self) -> None:
        package = build_context_package(
            build_request(),
            [self.candidate(self.source_entry, layer="static")],
        )
        summary = json.dumps(package.as_dict())
        self.assertNotIn("synthetic-fixture", summary)
        self.assertNotIn("local-path", summary)


if __name__ == "__main__":
    unittest.main()
