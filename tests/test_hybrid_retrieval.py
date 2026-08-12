from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.dependency_retrieval import (  # noqa: E402
    EvidenceRef,
    Provenance,
    parse_information_relation,
    relation_digest,
)
from krcn_core.hybrid_retrieval import (  # noqa: E402
    HybridRetrievalError,
    apply_hybrid_index,
    hybrid_index_path,
    parse_hybrid_query,
    prepare_hybrid_index,
    retrieve_hybrid,
)
from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.information_records import parse_information_record, payload_digest  # noqa: E402
from krcn_core.knowledge_catalog import build_information_catalog  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.retrieval_evaluation import (  # noqa: E402
    evaluate_hybrid_retrieval,
    load_retrieval_evaluation,
)
from phase_four_fixtures import source_binding, source_record  # noqa: E402


def knowledge_record(record_id: str, title: str, text: str, keywords: list[str]):
    content = {
        "title": title,
        "text": text,
        "keywords": keywords,
        "aliases": [],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": record_id,
            "information_class": "knowledge",
            "ownership": "user-data",
            "subject_ref": f"project:sample-project/{record_id}",
            "revision": 1,
            "content_digest": payload_digest(content),
            "provenance": {
                "kind": "source-derived",
                "evidence": [
                    {
                        "source_ref": "source:sample-project",
                        "revision_id": "rev-1",
                        "digest": "a" * 64,
                        "relation": "supports",
                    }
                ],
            },
            "lifecycle": "current",
            "payload": content,
        }
    )


def relation(source, target):
    provenance = Provenance(
        "source-derived",
        (
            EvidenceRef(
                f"record:{source.record_id}",
                str(source.revision),
                source.content_digest,
                "supports",
            ),
        ),
    )
    digest = relation_digest(
        source.record_id,
        target.record_id,
        "references",
        provenance,
    )
    return parse_information_relation(
        {
            "schema_ref": "schemas/information-relation.schema.json",
            "schema_version": 1,
            "relation_id": "database-references-deployment",
            "from_record_id": source.record_id,
            "to_record_id": target.record_id,
            "relation_type": "references",
            "revision": 1,
            "relation_digest": digest,
            "provenance": provenance.as_dict(),
            "lifecycle": "current",
        }
    )


def hybrid_query(
    text: str,
    *,
    seeds: list[str] | None = None,
    limit: int = 10,
):
    return parse_hybrid_query(
        {
            "schema_ref": "schemas/hybrid-retrieval-query.schema.json",
            "schema_version": 1,
            "query_id": "sample-hybrid-query",
            "text": text,
            "seed_record_ids": seeds or [],
            "include_unavailable": False,
            "limit": limit,
        }
    )


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / ".krcn"
        self.database_rule = knowledge_record(
            "database-read-rule",
            "Database read policy",
            "Only read operations and SELECT statements are permitted",
            ["database", "read-only", "select"],
        )
        self.deployment = knowledge_record(
            "deployment-guide",
            "Release deployment guide",
            "Use a verified plan and rollback checkpoint",
            ["release", "deployment"],
        )
        self.catalog = build_information_catalog(
            [source_binding()],
            [source_record(), self.database_rule, self.deployment],
        )
        self.relations = (relation(self.database_rule, self.deployment),)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build(self):
        plan = prepare_hybrid_index(self.home, self.catalog, self.ownership)
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.plan_id, True),
        )
        result = apply_hybrid_index(
            self.home,
            self.catalog,
            plan,
            authorization,
        )
        return plan, result

    def test_index_build_is_planned_rebuildable_and_integrity_checked(self) -> None:
        plan, result = self._build()
        self.assertEqual("derived", plan.mutation.ownership)
        self.assertFalse(plan.mutation.approval_required)
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["external_source_content_copied"])
        self.assertTrue(hybrid_index_path(self.home).is_file())

    def test_hybrid_ranking_explains_exact_fts_vector_and_dependency_signals(self) -> None:
        self._build()
        result = retrieve_hybrid(
            self.home,
            self.catalog,
            self.relations,
            hybrid_query("database read operations", seeds=["database-read-rule"]),
        )
        self.assertEqual("database-read-rule", result.hits[0].entry.record.record_id)
        breakdown = result.hits[0].score_breakdown
        self.assertGreater(breakdown["fts"], 0)
        self.assertGreater(breakdown["vector"], 0)
        self.assertGreater(breakdown["dependency"], 0)
        self.assertEqual(set(breakdown), {"exact", "fts", "vector", "dependency", "authority", "availability"})

    def test_deterministic_vector_handles_a_typographical_query_offline(self) -> None:
        self._build()
        query = hybrid_query("databse read operatons")
        first = retrieve_hybrid(self.home, self.catalog, (), query)
        second = retrieve_hybrid(self.home, self.catalog, (), query)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual("database-read-rule", first.hits[0].entry.record.record_id)
        self.assertGreater(first.hits[0].score_breakdown["vector"], 0)
        self.assertFalse(first.as_dict()["remote"])

    def test_dependency_signal_can_recall_related_material(self) -> None:
        self._build()
        result = retrieve_hybrid(
            self.home,
            self.catalog,
            self.relations,
            hybrid_query("database", seeds=["database-read-rule"]),
        )
        hits = {item.entry.record.record_id: item for item in result.hits}
        self.assertIn("deployment-guide", hits)
        self.assertGreater(hits["deployment-guide"].score_breakdown["dependency"], 0)

    def test_stale_catalog_and_corrupt_vector_fail_closed(self) -> None:
        self._build()
        changed = build_information_catalog(
            [source_binding()],
            [source_record(), self.database_rule],
        )
        with self.assertRaisesRegex(HybridRetrievalError, "stale"):
            retrieve_hybrid(self.home, changed, (), hybrid_query("database"))

        connection = sqlite3.connect(hybrid_index_path(self.home))
        try:
            connection.execute(
                "UPDATE documents SET vector_json = ? WHERE record_id = ?",
                (json.dumps([1.0]), "database-read-rule"),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(HybridRetrievalError, "dimensions"):
            retrieve_hybrid(self.home, self.catalog, (), hybrid_query("database"))

    def test_search_requires_an_index_and_exact_build_plan(self) -> None:
        with self.assertRaisesRegex(HybridRetrievalError, "build it"):
            retrieve_hybrid(self.home, self.catalog, (), hybrid_query("database"))
        plan = prepare_hybrid_index(self.home, self.catalog, self.ownership)
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.plan_id, True),
        )
        self.home.mkdir(parents=True)
        hybrid_index_path(self.home).parent.mkdir(parents=True)
        hybrid_index_path(self.home).touch()
        with self.assertRaisesRegex(HybridRetrievalError, "no longer current"):
            apply_hybrid_index(
                self.home,
                self.catalog,
                plan,
                authorization,
            )

    def test_application_clients_share_index_and_hybrid_search_contract(self) -> None:
        store = LocalWorkspaceStore(self.home, self.ownership)

        def put(record_type: str, record_id: str, payload: dict[str, object]) -> None:
            plan = store.prepare_put(
                record_type,
                record_id,
                payload,
                expected_revision=0,
            )
            approval = None
            if plan.mutation.approval_required:
                approval = ApprovalEvidence(
                    plan.mutation.plan_id,
                    "test-approval",
                    True,
                )
            store.apply_put(
                plan,
                authorize_mutation(
                    plan.mutation,
                    dry_run=DryRunEvidence(plan.mutation.plan_id, True),
                    approval=approval,
                ),
            )

        binding = source_binding()
        put(
            "source-bindings",
            binding.binding_id,
            {
                "schema_version": 1,
                "binding_id": binding.binding_id,
                "source_id": binding.source_id,
                "source_kind": binding.source_kind,
                "locator": {"kind": binding.locator.kind, "value": binding.locator.value},
                "default_access": binding.default_access,
                "capabilities": list(binding.capabilities),
                "policy_refs": list(binding.policy_refs),
                "revision": binding.revision,
            },
        )
        put("authoritative-sources", "sample-project-source", source_record().as_payload())
        put("knowledge", self.database_rule.record_id, self.database_rule.as_payload())
        put("knowledge", self.deployment.record_id, self.deployment.as_payload())
        put("information-relations", self.relations[0].relation_id, self.relations[0].as_payload())
        service = KrcnApplicationService(REPO_ROOT, store)
        planned = service.execute(ServiceRequest("cli", "knowledge.index-hybrid", {}))
        applied = service.execute(
            ServiceRequest(
                "cli",
                "knowledge.index-hybrid",
                {},
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
            )
        )
        self.assertEqual("applied", applied.status)
        arguments = {"query": hybrid_query("database read operations").as_dict()}
        results = [
            service.execute(
                ServiceRequest(client, "knowledge.search-hybrid", arguments)
            ).data
            for client in ("cli", "sdk", "mcp", "plugin", "codex", "claude")
        ]
        self.assertTrue(all(item == results[0] for item in results[1:]))
        self.assertEqual(
            "database-read-rule",
            results[0]["result"]["hits"][0]["record_id"],
        )

    def test_versioned_evaluation_set_meets_quality_thresholds(self) -> None:
        self._build()
        evaluation = evaluate_hybrid_retrieval(
            self.home,
            self.catalog,
            self.relations,
            load_retrieval_evaluation(REPO_ROOT),
        )
        self.assertEqual(4, evaluation["case_count"])
        self.assertEqual(1.0, evaluation["recall_at_five"])
        self.assertEqual(1.0, evaluation["mean_reciprocal_rank"])
        self.assertFalse(evaluation["remote"])


if __name__ == "__main__":
    unittest.main()
