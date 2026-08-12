from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.exact_retrieval import ExactRetrievalHit, ExactRetrievalResult  # noqa: E402
from krcn_core.hybrid_retrieval import HybridHit, HybridResult  # noqa: E402
from krcn_core.information_records import (  # noqa: E402
    EvidenceRef,
    InformationRecord,
    Provenance,
)
from krcn_core.knowledge_catalog import CatalogEntry  # noqa: E402
from krcn_core.provider_gate import (  # noqa: E402
    ProviderApproval,
    authorize_provider_request,
    create_provider_request,
)
from krcn_core.semantic_retrieval import SemanticHit, SemanticResult  # noqa: E402
from krcn_core.unified_retrieval import (  # noqa: E402
    RetrievalBatch,
    UnifiedCandidate,
    UnifiedRetrievalError,
    batch_from_exact,
    batch_from_hybrid,
    batch_from_oracle,
    batch_from_semantic,
    batch_from_source_code,
    batch_from_work_graph,
    classify_intent,
    create_unified_request,
    retrieve_unified,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def candidate(
    *,
    project_id: str = "sample",
    domain: str = "knowledge",
    hit_id: str = "sample-hit",
    logical_ref: str = "knowledge:sample-hit",
    mode: str = "exact",
    authority_rank: int = 0,
    score: float = 1.0,
    content: str = "short verified content",
    digest: str = DIGEST_A,
) -> UnifiedCandidate:
    return UnifiedCandidate(
        project_id=project_id,
        domain=domain,
        hit_id=hit_id,
        logical_ref=logical_ref,
        title=hit_id,
        content=content,
        authority="authoritative" if authority_rank == 0 else "derived",
        authority_rank=authority_rank,
        revision="1",
        digest=digest,
        evidence_refs=(f"source:{project_id}@r1:{digest}",),
        retrieval_mode=mode,
        score=score,
        score_breakdown={mode: score},
    )


def authoritative_batch(item: UnifiedCandidate) -> RetrievalBatch:
    return RetrievalBatch(item.project_id, item.domain, "authoritative", (item,))


def indexed_batch(item: UnifiedCandidate, *, indexed: str = DIGEST_B) -> RetrievalBatch:
    return RetrievalBatch(
        item.project_id,
        item.domain,
        "current",
        (item,),
        DIGEST_B,
        indexed,
        DIGEST_C,
    )


def information_record(record_id: str = "record-one") -> InformationRecord:
    return InformationRecord(
        record_id=record_id,
        information_class="knowledge",
        ownership="user-data",
        subject_ref=f"project:sample/{record_id}",
        revision=2,
        content_digest=DIGEST_A,
        provenance=Provenance(
            "source-derived",
            (EvidenceRef("source:sample", "r2", DIGEST_B, "supports"),),
        ),
        lifecycle="current",
        payload={
            "title": "Verified knowledge",
            "text": "A verified knowledge record.",
            "keywords": ["verified"],
            "aliases": [],
        },
    )


class UnifiedRetrievalTests(unittest.TestCase):
    def request(self, text: str = "Bilgi nedir?", **overrides):
        arguments = {
            "query_id": "unified-query",
            "text": text,
            "current_project_id": "sample",
            "intent": "knowledge",
            "result_limit": 20,
            "token_budget": 100,
        }
        arguments.update(overrides)
        return create_unified_request(**arguments)

    def test_intent_classification_is_deterministic_and_exact_first_for_status(self) -> None:
        self.assertEqual("status", classify_intent("Nerede kaldık, aktif görev nedir?"))
        self.assertEqual("code", classify_intent("Kaynak kod fonksiyonunu göster"))
        self.assertEqual("oracle", classify_intent("Oracle paket DDL bilgisini bul"))
        self.assertEqual("knowledge", classify_intent("Bu kararı açıkla"))
        self.assertEqual("broad", classify_intent("Aktif görevdeki kaynak kodu göster"))

    def test_scope_defaults_to_current_project_and_multi_project_is_explicit(self) -> None:
        default = create_unified_request(
            query_id="default-scope",
            text="Durum nedir?",
            current_project_id="sample",
        )
        self.assertEqual("project", default.scope)
        self.assertEqual(("sample",), default.project_ids)
        with self.assertRaisesRegex(UnifiedRetrievalError, "multi-project"):
            create_unified_request(
                query_id="unsafe-scope",
                text="Ara",
                current_project_id="sample",
                project_ids=("sample", "other"),
            )
        explicit = create_unified_request(
            query_id="explicit-scope",
            text="Ara",
            current_project_id="sample",
            project_ids=("sample", "other"),
            scope="multi-project",
        )
        self.assertEqual(("sample", "other"), explicit.project_ids)

    def test_batch_cannot_escape_project_scope(self) -> None:
        request = self.request()
        outside = candidate(project_id="other")
        with self.assertRaisesRegex(UnifiedRetrievalError, "escaped"):
            retrieve_unified(request, (authoritative_batch(outside),))

    def test_stale_index_fails_closed(self) -> None:
        request = self.request("Kaynak kod", intent="code")
        code = candidate(domain="code", logical_ref="source-code:sample/app.py#L1-L2")
        with self.assertRaisesRegex(UnifiedRetrievalError, "stale"):
            retrieve_unified(request, (indexed_batch(code, indexed=DIGEST_A),))
        explicitly_stale = RetrievalBatch("sample", "code", "stale", (code,))
        with self.assertRaisesRegex(UnifiedRetrievalError, "stale"):
            retrieve_unified(request, (explicitly_stale,))

    def test_semantic_requires_existing_provider_authorization(self) -> None:
        request = self.request()
        semantic = candidate(
            hit_id="semantic-hit",
            logical_ref="knowledge:semantic-hit",
            mode="semantic",
            authority_rank=1,
        )
        provider_request = create_provider_request(
            provider="approved-provider",
            endpoint="https://provider.invalid/embeddings",
            data_categories=("knowledge",),
            operation_scope="semantic-retrieval",
            retention_assumptions="No retention under the approved contract",
            session_id="session-one",
            remote=True,
        )
        batch = RetrievalBatch(
            "sample",
            "knowledge",
            "current",
            (semantic,),
            DIGEST_A,
            DIGEST_A,
            None,
            provider_request.request_id,
            True,
        )
        with self.assertRaisesRegex(UnifiedRetrievalError, "authorization"):
            retrieve_unified(request, (batch,))
        policy = {
            "default_mode": "offline",
            "implicit_provider_discovery": False,
            "remote_providers": {
                "explicit_opt_in_required": True,
                "required_disclosures": [
                    "provider",
                    "endpoint",
                    "data_categories",
                    "operation_scope",
                    "retention_assumptions",
                ],
            },
        }
        approval = ProviderApproval(
            provider_request.request_id,
            provider_request.session_id,
            "approved-for-session",
            True,
        )
        authorization = authorize_provider_request(policy, provider_request, approval=approval)
        result = retrieve_unified(
            request,
            (batch,),
            provider_authorizations={provider_request.request_id: authorization},
        )
        self.assertEqual(1, len(result.hits))
        self.assertFalse(result.as_dict()["remote_call_performed"])

    def test_semantic_score_cannot_override_exact_evidence(self) -> None:
        request = self.request()
        exact = candidate(
            hit_id="exact-hit",
            logical_ref="knowledge:exact-hit",
            mode="exact",
            score=0.01,
            digest=DIGEST_A,
        )
        semantic = candidate(
            hit_id="semantic-hit",
            logical_ref="knowledge:semantic-hit",
            mode="semantic",
            authority_rank=1,
            score=1.0,
            digest=DIGEST_B,
        )
        provider_request = create_provider_request(
            provider="deterministic-hashing",
            endpoint="local://deterministic-hashing",
            data_categories=("knowledge",),
            operation_scope="semantic-retrieval",
            retention_assumptions="Local and non-persistent",
            session_id="local-session",
            remote=False,
        )
        policy = {
            "default_mode": "offline",
            "implicit_provider_discovery": False,
            "local_providers": {
                "deterministic_hashing": {"enabled": True, "data_leaves_device": False}
            },
        }
        authorization = authorize_provider_request(policy, provider_request)
        semantic_batch = RetrievalBatch(
            "sample", "knowledge", "current", (semantic,), DIGEST_C, DIGEST_C,
            None, provider_request.request_id, False,
        )
        result = retrieve_unified(
            request,
            (semantic_batch, authoritative_batch(exact)),
            provider_authorizations={provider_request.request_id: authorization},
        )
        self.assertEqual(["exact-hit", "semantic-hit"], [hit.candidate.hit_id for hit in result.hits])
        self.assertFalse(result.as_dict()["semantic_can_override_exact"])

    def test_result_and_token_budgets_are_enforced(self) -> None:
        request = self.request(result_limit=2, token_budget=7)
        items = (
            candidate(hit_id="one", logical_ref="knowledge:one", content="one two", digest=DIGEST_A),
            candidate(hit_id="two", logical_ref="knowledge:two", content="one two three", digest=DIGEST_B),
            candidate(hit_id="three", logical_ref="knowledge:three", content="one two three four", digest=DIGEST_C),
        )
        batches = tuple(authoritative_batch(item) for item in items)
        first = retrieve_unified(request, batches)
        second = retrieve_unified(request, reversed(batches))
        self.assertLessEqual(len(first.hits), 2)
        self.assertLessEqual(first.token_budget_used, 7)
        self.assertEqual(first.result_digest, second.result_digest)
        self.assertEqual(first.as_dict(), second.as_dict())

    def test_context_candidates_preserve_evidence_and_revision(self) -> None:
        result = retrieve_unified(self.request(), (authoritative_batch(candidate()),))
        context = result.context_candidates[0].as_dict()
        self.assertEqual("sample", context["project_id"])
        self.assertEqual("1", context["revision"])
        self.assertEqual(DIGEST_A, context["digest"])
        self.assertTrue(context["evidence_refs"])
        self.assertIn("tier-0", context["selection_reason"])

    def test_exact_and_hybrid_adapters_preserve_catalog_authority(self) -> None:
        record = information_record()
        entry = CatalogEntry(record, "current", None)
        exact = ExactRetrievalResult(
            "exact-query", DIGEST_B, DIGEST_C,
            (ExactRetrievalHit(entry, ("title",)),), False,
        )
        exact_batch = batch_from_exact(exact, "sample")
        self.assertEqual("authoritative", exact_batch.freshness)
        self.assertEqual("exact", exact_batch.candidates[0].retrieval_mode)
        hybrid = HybridResult(
            "hybrid-query", DIGEST_B, DIGEST_C, DIGEST_A,
            (HybridHit(entry, 0.7, {"exact": 0.0, "fts": 0.7}),), 1, False,
        )
        hybrid_batch = batch_from_hybrid(hybrid, "sample")
        self.assertEqual(DIGEST_C, hybrid_batch.source_revision_digest)
        self.assertEqual("hybrid", hybrid_batch.candidates[0].retrieval_mode)

    def test_source_work_and_oracle_adapters_bind_domain_evidence(self) -> None:
        source = batch_from_source_code(
            {
                "project_id": "sample",
                "source_digest": DIGEST_A,
                "index_digest": DIGEST_B,
                "hits": [
                    {
                        "chunk_id": "chunk-one",
                        "relative_path": "src/app.py",
                        "start_line": 1,
                        "end_line": 3,
                        "content_sha256": DIGEST_C,
                        "symbols": ["main"],
                        "content": "def main(): pass",
                        "score": 0.8,
                        "score_breakdown": {"exact": 0.0, "fts": 0.8, "vector": 0.2},
                    }
                ],
            }
        )
        self.assertEqual("code", source.domain)
        self.assertIn("#L1-L3", source.candidates[0].logical_ref)
        work = batch_from_work_graph(
            {
                "project_id": "sample",
                "authoritative_status": True,
                "items": [
                    {
                        "work_item_id": "task-one",
                        "title": "Task one",
                        "description": "Do verified work",
                        "revision": 2,
                        "work_digest": DIGEST_A,
                        "evidence": [
                            {"reference": "commit:abc", "digest": DIGEST_B}
                        ],
                    }
                ],
            }
        )
        self.assertEqual("authoritative-work", work.candidates[0].authority)
        oracle = batch_from_oracle(
            {
                "project_id": "sample",
                "index_digest": DIGEST_C,
                "hits": [
                    {
                        "chunk_id": "oracle-chunk",
                        "object_id": "oracle-object",
                        "revision_id": "revision-one",
                        "identity": {"owner": "APP", "name": "PKG_TEST"},
                        "symbol_path": "package.body",
                        "content_digest": DIGEST_A,
                        "score": 0.9,
                        "text": "CREATE PACKAGE BODY",
                    }
                ],
            },
            current_catalog_digest=DIGEST_B,
            indexed_catalog_digest=DIGEST_B,
        )
        self.assertEqual("oracle", oracle.domain)
        self.assertIn("oracle-revision:", oracle.candidates[0].evidence_refs[0])

    def test_semantic_adapter_rejects_stale_catalog_at_unified_boundary(self) -> None:
        record = information_record("semantic-record")
        entry = CatalogEntry(record, "current", None)
        provider_request = create_provider_request(
            provider="deterministic-hashing",
            endpoint="local://deterministic-hashing",
            data_categories=("knowledge",),
            operation_scope="semantic-retrieval",
            retention_assumptions="Local and non-persistent",
            session_id="semantic-session",
            remote=False,
        )
        semantic = SemanticResult(
            "semantic-query", DIGEST_A, DIGEST_B, DIGEST_C,
            provider_request.request_id, "deterministic-hashing", False,
            "local-deterministic", False, (SemanticHit(entry, 0.8),), False,
        )
        batch = batch_from_semantic(
            semantic,
            "sample",
            current_catalog_digest=DIGEST_A,
        )
        authorization = authorize_provider_request(
            {
                "default_mode": "offline",
                "implicit_provider_discovery": False,
                "local_providers": {
                    "deterministic_hashing": {
                        "enabled": True,
                        "data_leaves_device": False,
                    }
                },
            },
            provider_request,
        )
        with self.assertRaisesRegex(UnifiedRetrievalError, "stale"):
            retrieve_unified(
                self.request(),
                (batch,),
                provider_authorizations={provider_request.request_id: authorization},
            )


if __name__ == "__main__":
    unittest.main()
