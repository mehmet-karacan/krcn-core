from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.exact_retrieval import (  # noqa: E402
    ExactRetrievalError,
    parse_exact_retrieval_query,
    retrieve_exact,
)
from krcn_core.information_records import (  # noqa: E402
    parse_information_record,
    payload_digest,
)
from krcn_core.knowledge_catalog import build_information_catalog  # noqa: E402
from tests.test_knowledge_catalog import (  # noqa: E402
    knowledge_record,
    source_binding,
    source_record,
)


def query(
    text: str,
    *,
    fields: list[str],
    include_unavailable: bool = False,
    limit: int = 20,
    case_sensitive: bool = False,
):
    return parse_exact_retrieval_query(
        {
            "schema_ref": "schemas/exact-retrieval-query.schema.json",
            "schema_version": 1,
            "query_id": "sample-query",
            "text": text,
            "fields": fields,
            "case_sensitive": case_sensitive,
            "include_unavailable": include_unavailable,
            "limit": limit,
        }
    )


def with_payload(record, **changes):
    payload = record.as_payload()
    content = dict(payload["payload"])
    content.update(changes)
    payload["payload"] = content
    payload["content_digest"] = payload_digest(content)
    return parse_information_record(payload)


class ExactRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_information_catalog(
            [source_binding()],
            [source_record(), knowledge_record()],
        )

    def test_identity_path_title_alias_and_keyword_are_exact(self) -> None:
        cases = (
            ("database-read-rule", ["record-id"], "database-read-rule"),
            (
                "project:sample-project/database",
                ["subject-ref"],
                "database-read-rule",
            ),
            ("sample-project/database", ["path"], "database-read-rule"),
            ("DATABASE ACCESS RULE", ["title"], "database-read-rule"),
            ("database rule", ["alias"], "database-read-rule"),
            ("READ-ONLY", ["keyword"], "database-read-rule"),
        )
        for text, fields, expected in cases:
            with self.subTest(text=text, fields=fields):
                result = retrieve_exact(self.catalog, query(text, fields=fields))
                self.assertEqual([expected], [hit.entry.record.record_id for hit in result.hits])

        partial_title = retrieve_exact(
            self.catalog,
            query("Database", fields=["title"]),
        )
        self.assertEqual((), partial_title.hits)

    def test_text_match_requires_the_exact_contiguous_phrase(self) -> None:
        matching = retrieve_exact(
            self.catalog,
            query("read operations are permitted", fields=["text"]),
        )
        self.assertEqual("database-read-rule", matching.hits[0].entry.record.record_id)
        missing = retrieve_exact(
            self.catalog,
            query("read permitted", fields=["text"]),
        )
        self.assertEqual((), missing.hits)

    def test_case_sensitive_query_is_explicit(self) -> None:
        result = retrieve_exact(
            self.catalog,
            query(
                "DATABASE ACCESS RULE",
                fields=["title"],
                case_sensitive=True,
            ),
        )
        self.assertEqual((), result.hits)

    def test_same_query_and_catalog_produce_same_order_and_digests(self) -> None:
        selected = query(
            "database-read-rule",
            fields=["text", "record-id", "alias"],
        )
        first = retrieve_exact(self.catalog, selected)
        second = retrieve_exact(self.catalog, selected)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(64, len(first.result_digest))
        self.assertEqual(["record-id"], list(first.hits[0].matched_fields))

    def test_unavailable_records_are_excluded_unless_requested(self) -> None:
        stale_catalog = build_information_catalog(
            [source_binding()],
            [
                source_record(source_revision="rev-2", source_digest="b" * 64),
                knowledge_record(),
            ],
        )
        current_only = retrieve_exact(
            stale_catalog,
            query("database-read-rule", fields=["record-id"]),
        )
        self.assertEqual((), current_only.hits)
        visible = retrieve_exact(
            stale_catalog,
            query(
                "database-read-rule",
                fields=["record-id"],
                include_unavailable=True,
            ),
        )
        self.assertEqual("stale", visible.hits[0].entry.availability)

    def test_authority_revision_and_evidence_break_equal_match_ties(self) -> None:
        title = "Shared exact title"
        source = with_payload(source_record(), title=title)
        knowledge = with_payload(knowledge_record(), title=title)
        catalog = build_information_catalog([source_binding()], [knowledge, source])
        result = retrieve_exact(catalog, query(title, fields=["title"]))
        self.assertEqual(
            ["authoritative-source", "knowledge"],
            [hit.entry.record.information_class for hit in result.hits],
        )

    def test_limit_is_deterministic_and_reports_truncation(self) -> None:
        source = with_payload(source_record(), aliases=["shared"])
        knowledge = with_payload(knowledge_record(), aliases=["shared"])
        catalog = build_information_catalog([source_binding()], [knowledge, source])
        result = retrieve_exact(
            catalog,
            query("shared", fields=["alias"], limit=1),
        )
        self.assertEqual(1, len(result.hits))
        self.assertTrue(result.truncated)
        self.assertEqual("authoritative-source", result.hits[0].entry.record.information_class)

    def test_result_summary_excludes_payload_text_and_locator(self) -> None:
        result = retrieve_exact(
            self.catalog,
            query("database-read-rule", fields=["record-id"]),
        )
        summary = json.dumps(result.as_dict())
        self.assertNotIn("Only read operations", summary)
        self.assertNotIn("synthetic-fixture", summary)
        self.assertNotIn("payload", summary)

    def test_invalid_or_duplicate_query_fields_are_rejected(self) -> None:
        payload = query("sample", fields=["title"]).as_dict()
        for fields in ([], ["title", "title"], ["semantic"]):
            with self.subTest(fields=fields):
                changed = copy.deepcopy(payload)
                changed["fields"] = fields
                with self.assertRaisesRegex(ExactRetrievalError, "fields"):
                    parse_exact_retrieval_query(changed)

    def test_retrieval_revalidates_catalog_record_payloads(self) -> None:
        entry = self.catalog.get("database-read-rule")
        entry.record.payload["text"] = "Changed after catalog construction"
        with self.assertRaisesRegex(ExactRetrievalError, "record is invalid"):
            retrieve_exact(
                self.catalog,
                query("database-read-rule", fields=["record-id"]),
            )


if __name__ == "__main__":
    unittest.main()
