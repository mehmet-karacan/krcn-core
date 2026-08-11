from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.knowledge_catalog import build_information_catalog  # noqa: E402
from krcn_core.provider_gate import (  # noqa: E402
    ProviderApproval,
    load_provider_gate_policy,
    select_default_provider,
)
from krcn_core.semantic_retrieval import (  # noqa: E402
    SemanticRetrievalError,
    create_semantic_provider_request,
    parse_semantic_query,
    retrieve_semantic,
)
from phase_four_fixtures import (  # noqa: E402
    knowledge_record,
    source_binding,
    source_record,
)


def semantic_query(*, provider: str, remote: bool, include_unavailable: bool = False):
    return parse_semantic_query(
        {
            "schema_ref": "schemas/semantic-query.schema.json",
            "schema_version": 1,
            "query_id": "sample-semantic-query",
            "text": "database read operations",
            "provider": provider,
            "remote": remote,
            "session_id": "semantic-session-1",
            "limit": 10,
            "minimum_score": 0.01,
            "include_unavailable": include_unavailable,
        }
    )


class SemanticRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_provider_gate_policy(REPO_ROOT)
        self.catalog = build_information_catalog(
            [source_binding()],
            [source_record(), knowledge_record()],
        )

    def test_local_fallback_is_default_offline_and_deterministic(self) -> None:
        provider = select_default_provider(self.policy)
        selected = semantic_query(provider=provider, remote=False)
        request = create_semantic_provider_request(
            selected,
            endpoint="local-process",
            retention_assumptions="No remote retention",
        )
        first = retrieve_semantic(self.catalog, selected, self.policy, request)
        second = retrieve_semantic(self.catalog, selected, self.policy, request)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual("offline-deterministic-fallback", first.mode)
        self.assertFalse(first.remote)
        self.assertFalse(first.approval_verified)
        self.assertEqual("database-read-rule", first.hits[0].entry.record.record_id)

    def test_remote_scorer_is_not_called_without_exact_session_approval(self) -> None:
        selected = semantic_query(provider="approved-remote", remote=True)
        request = create_semantic_provider_request(
            selected,
            endpoint="configured-endpoint",
            retention_assumptions="Provider terms reviewed by the user",
        )
        calls = []

        def scorer(query_text, documents):
            calls.append((query_text, documents))
            return {}

        with self.assertRaisesRegex(SemanticRetrievalError, "session approval"):
            retrieve_semantic(
                self.catalog,
                selected,
                self.policy,
                request,
                remote_scorer=scorer,
            )
        self.assertEqual([], calls)

    def test_approved_remote_scorer_is_adapter_supplied_and_ranked(self) -> None:
        selected = semantic_query(provider="approved-remote", remote=True)
        request = create_semantic_provider_request(
            selected,
            endpoint="configured-endpoint",
            retention_assumptions="Provider terms reviewed by the user",
        )
        approval = ProviderApproval(
            request_id=request.request_id,
            session_id=selected.session_id,
            approval_id="synthetic-semantic-approval",
            approved=True,
        )
        received = []

        def scorer(query_text, documents):
            received.append((query_text, documents))
            return {
                "database-read-rule": 0.91,
                "sample-project-source": 0.12,
            }

        result = retrieve_semantic(
            self.catalog,
            selected,
            self.policy,
            request,
            approval=approval,
            remote_scorer=scorer,
        )
        self.assertTrue(result.approval_verified)
        self.assertEqual("remote-provider", result.mode)
        self.assertEqual(1, len(received))
        self.assertEqual(
            ["database-read-rule", "sample-project-source"],
            [hit.entry.record.record_id for hit in result.hits],
        )

    def test_approved_remote_request_does_not_discover_a_network_client(self) -> None:
        selected = semantic_query(provider="approved-remote", remote=True)
        request = create_semantic_provider_request(
            selected,
            endpoint="configured-endpoint",
            retention_assumptions="Provider terms reviewed by the user",
        )
        approval = ProviderApproval(
            request_id=request.request_id,
            session_id=selected.session_id,
            approval_id="synthetic-semantic-approval",
            approved=True,
        )
        with self.assertRaisesRegex(SemanticRetrievalError, "must be supplied"):
            retrieve_semantic(
                self.catalog,
                selected,
                self.policy,
                request,
                approval=approval,
            )

    def test_provider_request_must_match_query_and_disclosures(self) -> None:
        local = semantic_query(provider="deterministic-hashing", remote=False)
        request = create_semantic_provider_request(
            local,
            endpoint="local-process",
            retention_assumptions="No remote retention",
        )
        remote = semantic_query(provider="approved-remote", remote=True)
        with self.assertRaisesRegex(SemanticRetrievalError, "does not match"):
            retrieve_semantic(self.catalog, remote, self.policy, request)

    def test_remote_scores_are_bounded_and_cannot_name_unknown_records(self) -> None:
        selected = semantic_query(provider="approved-remote", remote=True)
        request = create_semantic_provider_request(
            selected,
            endpoint="configured-endpoint",
            retention_assumptions="Provider terms reviewed by the user",
        )
        approval = ProviderApproval(
            request_id=request.request_id,
            session_id=selected.session_id,
            approval_id="synthetic-semantic-approval",
            approved=True,
        )
        for scores, error in (
            ({"missing-record": 0.5}, "unknown record"),
            ({"database-read-rule": 1.5}, "score is invalid"),
        ):
            with self.subTest(scores=scores):
                with self.assertRaisesRegex(SemanticRetrievalError, error):
                    retrieve_semantic(
                        self.catalog,
                        selected,
                        self.policy,
                        request,
                        approval=approval,
                        remote_scorer=lambda query_text, documents, value=scores: value,
                    )

    def test_stale_candidates_are_excluded_by_default(self) -> None:
        stale_catalog = build_information_catalog(
            [source_binding()],
            [
                source_record(source_revision="rev-2", source_digest="b" * 64),
                knowledge_record(),
            ],
        )
        selected = semantic_query(provider="deterministic-hashing", remote=False)
        request = create_semantic_provider_request(
            selected,
            endpoint="local-process",
            retention_assumptions="No remote retention",
        )
        result = retrieve_semantic(stale_catalog, selected, self.policy, request)
        self.assertNotIn(
            "database-read-rule",
            [hit.entry.record.record_id for hit in result.hits],
        )

    def test_public_result_excludes_query_payload_and_endpoint(self) -> None:
        selected = semantic_query(provider="deterministic-hashing", remote=False)
        request = create_semantic_provider_request(
            selected,
            endpoint="private-local-endpoint",
            retention_assumptions="No remote retention",
        )
        result = retrieve_semantic(self.catalog, selected, self.policy, request)
        summary = json.dumps(result.as_dict())
        self.assertNotIn(selected.text, summary)
        self.assertNotIn("private-local-endpoint", summary)
        self.assertNotIn("Only read operations", summary)
        self.assertNotIn("payload", summary)


if __name__ == "__main__":
    unittest.main()
