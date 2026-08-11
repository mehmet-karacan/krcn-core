from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.dependency_retrieval import (  # noqa: E402
    DependencyRetrievalError,
    parse_dependency_query,
    parse_information_relation,
    relation_digest,
    retrieve_dependencies,
)
from krcn_core.information_records import (  # noqa: E402
    EvidenceRef,
    Provenance,
    parse_information_record,
    payload_digest,
)
from krcn_core.knowledge_catalog import build_information_catalog  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from phase_four_fixtures import source_binding, source_record  # noqa: E402


def knowledge_node(record_id: str, subject_ref: str, title: str, *, revision: int = 1):
    content = {
        "title": title,
        "text": f"Synthetic knowledge for {title}",
        "keywords": [record_id],
        "aliases": [],
    }
    return parse_information_record(
        {
            "schema_ref": "schemas/information-record.schema.json",
            "schema_version": 1,
            "record_id": record_id,
            "information_class": "knowledge",
            "ownership": "user-data",
            "subject_ref": subject_ref,
            "revision": revision,
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


def information_relation(
    relation_id: str,
    from_record_id: str,
    to_record_id: str,
    relation_type: str,
    evidence_record,
    *,
    evidence_digest: str | None = None,
):
    provenance = Provenance(
        "source-derived",
        (
            EvidenceRef(
                f"record:{evidence_record.record_id}",
                str(evidence_record.revision),
                evidence_digest or evidence_record.content_digest,
                "supports",
            ),
        ),
    )
    digest = relation_digest(
        from_record_id,
        to_record_id,
        relation_type,
        provenance,
    )
    return parse_information_relation(
        {
            "schema_ref": "schemas/information-relation.schema.json",
            "schema_version": 1,
            "relation_id": relation_id,
            "from_record_id": from_record_id,
            "to_record_id": to_record_id,
            "relation_type": relation_type,
            "revision": 1,
            "relation_digest": digest,
            "provenance": provenance.as_dict(),
            "lifecycle": "current",
        }
    )


def dependency_query(
    seeds: list[str],
    *,
    direction: str = "outbound",
    relation_types: list[str] | None = None,
    max_depth: int = 5,
    node_budget: int = 20,
    edge_budget: int = 20,
    include_stale_edges: bool = False,
    include_unavailable_nodes: bool = False,
):
    return parse_dependency_query(
        {
            "schema_ref": "schemas/dependency-query.schema.json",
            "schema_version": 1,
            "query_id": "sample-dependency-query",
            "seed_record_ids": seeds,
            "direction": direction,
            "relation_types": relation_types
            or ["contains", "depends-on", "references", "documents", "tracks"],
            "max_depth": max_depth,
            "node_budget": node_budget,
            "edge_budget": edge_budget,
            "include_stale_edges": include_stale_edges,
            "include_unavailable_nodes": include_unavailable_nodes,
        }
    )


class DependencyRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = source_record()
        self.project = knowledge_node(
            "project-overview",
            "project:sample-project",
            "Project overview",
        )
        self.module = knowledge_node(
            "module-context",
            "module:sample-project/core",
            "Core module",
        )
        self.document = knowledge_node(
            "architecture-document",
            "document:sample-project/architecture",
            "Architecture document",
        )
        self.task = knowledge_node(
            "active-task",
            "task:sample-project/active",
            "Active task",
        )
        self.catalog = build_information_catalog(
            [source_binding()],
            [self.source, self.project, self.module, self.document, self.task],
        )
        self.relations = [
            information_relation(
                "source-documents-project",
                self.source.record_id,
                self.project.record_id,
                "documents",
                self.source,
            ),
            information_relation(
                "project-contains-module",
                self.project.record_id,
                self.module.record_id,
                "contains",
                self.project,
            ),
            information_relation(
                "module-references-document",
                self.module.record_id,
                self.document.record_id,
                "references",
                self.module,
            ),
            information_relation(
                "document-depends-on-project",
                self.document.record_id,
                self.project.record_id,
                "depends-on",
                self.document,
            ),
            information_relation(
                "project-tracks-task",
                self.project.record_id,
                self.task.record_id,
                "tracks",
                self.project,
            ),
        ]

    def test_outbound_traversal_tracks_depth_and_terminates_cycles(self) -> None:
        result = retrieve_dependencies(
            self.catalog,
            self.relations,
            dependency_query([self.project.record_id]),
        )
        self.assertEqual(
            {
                "project-overview": 0,
                "module-context": 1,
                "active-task": 1,
                "architecture-document": 2,
            },
            {node.entry.record.record_id: node.depth for node in result.nodes},
        )
        self.assertEqual(
            (
                "document-depends-on-project",
                "module-references-document",
                "project-contains-module",
            ),
            result.cycle_relation_ids,
        )

    def test_direction_and_relation_type_filters_are_explicit(self) -> None:
        incoming = retrieve_dependencies(
            self.catalog,
            self.relations,
            dependency_query(
                [self.project.record_id],
                direction="inbound",
                relation_types=["documents"],
            ),
        )
        self.assertEqual(
            ["project-overview", "sample-project-source"],
            [node.entry.record.record_id for node in incoming.nodes],
        )
        contains = retrieve_dependencies(
            self.catalog,
            self.relations,
            dependency_query(
                [self.project.record_id],
                relation_types=["contains"],
            ),
        )
        self.assertEqual(
            ["project-overview", "module-context"],
            [node.entry.record.record_id for node in contains.nodes],
        )

    def test_node_budget_and_depth_limit_are_reported(self) -> None:
        budgeted = retrieve_dependencies(
            self.catalog,
            self.relations,
            dependency_query([self.project.record_id], node_budget=2),
        )
        self.assertEqual(2, len(budgeted.nodes))
        self.assertTrue(budgeted.truncated)
        depth_limited = retrieve_dependencies(
            self.catalog,
            self.relations,
            dependency_query([self.project.record_id], max_depth=1),
        )
        self.assertTrue(depth_limited.depth_limited)

    def test_stale_edge_is_excluded_unless_explicitly_requested(self) -> None:
        stale = information_relation(
            "project-contains-module",
            self.project.record_id,
            self.module.record_id,
            "contains",
            self.project,
            evidence_digest="b" * 64,
        )
        hidden = retrieve_dependencies(
            self.catalog,
            [stale],
            dependency_query([self.project.record_id], relation_types=["contains"]),
        )
        self.assertEqual((), hidden.edges)
        visible = retrieve_dependencies(
            self.catalog,
            [stale],
            dependency_query(
                [self.project.record_id],
                relation_types=["contains"],
                include_stale_edges=True,
            ),
        )
        self.assertEqual("stale", visible.edges[0].availability)

    def test_relation_order_does_not_change_graph_result(self) -> None:
        selected = dependency_query([self.project.record_id])
        first = retrieve_dependencies(self.catalog, self.relations, selected)
        second = retrieve_dependencies(
            self.catalog,
            list(reversed(self.relations)),
            selected,
        )
        self.assertEqual(first.as_dict(), second.as_dict())

    def test_cycle_detection_covers_cross_branch_cycles(self) -> None:
        module_to_task = information_relation(
            "module-depends-on-task",
            self.module.record_id,
            self.task.record_id,
            "depends-on",
            self.module,
        )
        task_to_module = information_relation(
            "task-depends-on-module",
            self.task.record_id,
            self.module.record_id,
            "depends-on",
            self.task,
        )
        result = retrieve_dependencies(
            self.catalog,
            [module_to_task, task_to_module],
            dependency_query(
                [self.module.record_id],
                relation_types=["depends-on"],
            ),
        )
        self.assertEqual(
            ("module-depends-on-task", "task-depends-on-module"),
            result.cycle_relation_ids,
        )

    def test_relation_digest_tampering_and_missing_endpoint_are_rejected(self) -> None:
        payload = self.relations[0].as_payload()
        payload["to_record_id"] = "another-record"
        with self.assertRaisesRegex(DependencyRetrievalError, "does not match"):
            parse_information_relation(payload)

        missing = information_relation(
            "project-tracks-missing",
            self.project.record_id,
            "missing-task",
            "tracks",
            self.project,
        )
        with self.assertRaisesRegex(DependencyRetrievalError, "endpoint"):
            retrieve_dependencies(
                self.catalog,
                [missing],
                dependency_query([self.project.record_id]),
            )

    def test_result_excludes_payload_content_and_source_locator(self) -> None:
        result = retrieve_dependencies(
            self.catalog,
            self.relations,
            dependency_query([self.project.record_id]),
        )
        summary = json.dumps(result.as_dict())
        self.assertNotIn("Synthetic knowledge", summary)
        self.assertNotIn("synthetic-fixture", summary)
        self.assertNotIn("payload", summary)

    def test_query_rejects_budget_that_cannot_fit_seeds(self) -> None:
        payload = dependency_query([self.project.record_id]).as_dict()
        payload["seed_record_ids"] = [self.project.record_id, self.module.record_id]
        payload["node_budget"] = 1
        with self.assertRaisesRegex(DependencyRetrievalError, "cannot fit"):
            parse_dependency_query(payload)


class RelationPersistenceTests(unittest.TestCase):
    def test_relation_write_uses_exact_approval_and_preserved_user_data(self) -> None:
        source = source_record()
        project = knowledge_node(
            "project-overview",
            "project:sample-project",
            "Project overview",
        )
        relation = information_relation(
            "source-documents-project",
            source.record_id,
            project.record_id,
            "documents",
            source,
        )
        with tempfile.TemporaryDirectory() as temporary:
            ownership = OwnershipResolver.from_repository(REPO_ROOT)
            store = LocalWorkspaceStore(Path(temporary), ownership)
            plan = store.prepare_put(
                "information-relations",
                relation.relation_id,
                relation.as_payload(),
                expected_revision=0,
            )
            self.assertEqual("user-data", plan.mutation.ownership)
            self.assertTrue(plan.mutation.approval_required)
            authorization = authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
                approval=ApprovalEvidence(
                    plan.mutation.plan_id,
                    "synthetic-test-approval",
                    approved=True,
                ),
            )
            stored = store.apply_put(plan, authorization)
            self.assertEqual(1, stored.revision)

        manifest = json.loads(
            (REPO_ROOT / "config" / "ownership-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        user_data = next(item for item in manifest["classes"] if item["id"] == "user-data")
        self.assertIn(".krcn/knowledge/**", user_data["paths"])


if __name__ == "__main__":
    unittest.main()
