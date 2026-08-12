from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.dependency_retrieval import (  # noqa: E402
    parse_information_relation,
    relation_digest,
)
from krcn_core.information_records import (  # noqa: E402
    EvidenceRef,
    Provenance,
    parse_information_record,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.memory_gate import (  # noqa: E402
    apply_memory_persistence,
    prepare_memory_persistence,
)
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from phase_four_fixtures import (  # noqa: E402
    knowledge_record,
    source_binding,
    source_record,
)
from test_context_builder import build_request  # noqa: E402
from test_dependency_retrieval import dependency_query  # noqa: E402
from test_memory_gate import memory_action, memory_candidate, memory_review  # noqa: E402
from test_semantic_retrieval import semantic_query  # noqa: E402


def binding_payload() -> dict[str, object]:
    binding = source_binding()
    return {
        "schema_version": binding.schema_version,
        "binding_id": binding.binding_id,
        "source_id": binding.source_id,
        "source_kind": binding.source_kind,
        "locator": {
            "kind": binding.locator.kind,
            "value": binding.locator.value,
        },
        "default_access": binding.default_access,
        "capabilities": list(binding.capabilities),
        "policy_refs": list(binding.policy_refs),
        "revision": binding.revision,
    }


def exact_arguments() -> dict[str, object]:
    return {
        "query": {
            "schema_ref": "schemas/exact-retrieval-query.schema.json",
            "schema_version": 1,
            "query_id": "service-exact-query",
            "text": "database-read-rule",
            "fields": ["record-id", "title", "text"],
            "case_sensitive": False,
            "include_unavailable": False,
            "limit": 10,
        }
    }


class PhaseFourServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.data_root, self.ownership)
        self.source = source_record()
        self.knowledge = knowledge_record()
        self._put("source-bindings", source_binding().binding_id, binding_payload())
        self._put(
            "authoritative-sources",
            self.source.record_id,
            self.source.as_payload(),
        )
        self._put("knowledge", self.knowledge.record_id, self.knowledge.as_payload())
        provenance = Provenance(
            "source-derived",
            (
                EvidenceRef(
                    f"record:{self.source.record_id}",
                    str(self.source.revision),
                    self.source.content_digest,
                    "supports",
                ),
            ),
        )
        relation = parse_information_relation(
            {
                "schema_ref": "schemas/information-relation.schema.json",
                "schema_version": 1,
                "relation_id": "source-documents-rule",
                "from_record_id": self.source.record_id,
                "to_record_id": self.knowledge.record_id,
                "relation_type": "documents",
                "revision": 1,
                "relation_digest": relation_digest(
                    self.source.record_id,
                    self.knowledge.record_id,
                    "documents",
                    provenance,
                ),
                "provenance": provenance.as_dict(),
                "lifecycle": "current",
            }
        )
        self._put(
            "information-relations",
            relation.relation_id,
            relation.as_payload(),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _put(
        self,
        collection: str,
        record_id: str,
        payload: dict[str, object],
    ) -> None:
        plan = self.store.prepare_put(
            collection,
            record_id,
            payload,
            expected_revision=0,
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                "synthetic-fixture-approval",
                approved=True,
            ),
        )
        self.store.apply_put(plan, authorization)

    def test_catalog_exact_dependency_semantic_and_context_share_one_service(self) -> None:
        catalog = self.service.execute(
            ServiceRequest("sdk", "knowledge.catalog", {})
        )
        encoded_catalog = json.dumps(catalog.as_dict())
        self.assertNotIn("synthetic-fixture", encoded_catalog)
        self.assertEqual(2, catalog.data["catalog"]["entry_count"])

        exact_results = []
        for client_kind in ("cli", "sdk", "mcp", "plugin", "codex", "claude"):
            response = self.service.execute(
                ServiceRequest(
                    client_kind,
                    "knowledge.search-exact",
                    exact_arguments(),
                )
            )
            exact_results.append(response.data)
        self.assertTrue(all(item == exact_results[0] for item in exact_results))
        self.assertEqual(
            "database-read-rule",
            exact_results[0]["result"]["hits"][0]["record_id"],
        )

        dependencies = self.service.execute(
            ServiceRequest(
                "mcp",
                "knowledge.search-dependencies",
                {"query": dependency_query([self.source.record_id]).as_dict()},
            )
        )
        self.assertEqual(2, dependencies.data["result"]["node_count"])

        semantic = self.service.execute(
            ServiceRequest(
                "plugin",
                "knowledge.search-semantic",
                {
                    "query": semantic_query(
                        provider="deterministic-hashing",
                        remote=False,
                    ).as_dict(),
                    "endpoint": "local-process",
                    "retention_assumptions": "No remote retention",
                },
            )
        )
        self.assertEqual(
            "offline-deterministic-fallback",
            semantic.data["result"]["mode"],
        )

        context_arguments = {
            "request": build_request(
                required_record_ids=[self.knowledge.record_id]
            ).as_dict(),
            "candidates": [
                {
                    "record_id": self.knowledge.record_id,
                    "layer": "task",
                    "selection_source": "exact",
                    "selection_reason": "exact:record-id",
                    "required": True,
                    "priority": 100,
                    "allow_truncation": False,
                }
            ],
        }
        contexts = [
            self.service.execute(
                ServiceRequest(kind, "context.build", context_arguments)
            ).data
            for kind in ("cli", "sdk", "mcp", "plugin", "codex", "claude")
        ]
        self.assertTrue(all(item == contexts[0] for item in contexts))
        self.assertEqual(
            "Only read operations are permitted",
            contexts[0]["context"]["items"][0]["content"],
        )

    def test_remote_semantic_service_requires_injected_scorer_after_approval(self) -> None:
        query = semantic_query(provider="approved-remote", remote=True)
        arguments = {
            "query": query.as_dict(),
            "endpoint": "configured-endpoint",
            "retention_assumptions": "User reviewed provider terms",
        }
        with self.assertRaisesRegex(ValueError, "must be supplied"):
            self.service.execute(
                ServiceRequest(
                    "sdk",
                    "knowledge.search-semantic",
                    arguments,
                    approval_id="synthetic-session-approval",
                )
            )

    def test_source_revision_change_excludes_stale_memory_from_context(self) -> None:
        candidate = memory_candidate(origin="explicit-user")
        review = memory_review(candidate)
        plan = prepare_memory_persistence(
            self.store,
            candidate,
            review,
            expected_revision=0,
        )
        apply_memory_persistence(
            self.store,
            plan,
            candidate,
            review,
            authorize_mutation(
                plan.write_plan.mutation,
                dry_run=DryRunEvidence(plan.write_plan.mutation.plan_id, True),
                approval=ApprovalEvidence(
                    plan.write_plan.mutation.plan_id,
                    "memory-kayit-onayi",
                    True,
                ),
            ),
        )
        changed_source = source_record(
            record_revision=2,
            source_revision="rev-2",
            source_digest="b" * 64,
        )
        update = self.store.prepare_put(
            "authoritative-sources",
            self.source.record_id,
            changed_source.as_payload(),
            expected_revision=1,
        )
        self.store.apply_put(
            update,
            authorize_mutation(
                update.mutation,
                dry_run=DryRunEvidence(update.mutation.plan_id, True),
                approval=ApprovalEvidence(update.mutation.plan_id, "kaynak-onayi", True),
            ),
        )
        request = build_request().as_dict()
        response = self.service.execute(
            ServiceRequest(
                "codex",
                "context.build",
                {
                    "request": request,
                    "candidates": [
                        {
                            "record_id": "database-access-memory",
                            "layer": "persistent",
                            "selection_source": "memory",
                            "selection_reason": "memory:approved",
                            "required": False,
                            "priority": 100,
                            "allow_truncation": True,
                        }
                    ],
                },
            )
        )
        context = response.data["context"]
        self.assertEqual([], context["items"])
        self.assertEqual("stale-or-unavailable", context["exclusions"][0]["reason"])

    def test_memory_propose_review_persist_and_lifecycle_keep_exact_gates(self) -> None:
        candidate = memory_candidate(origin="explicit-user")
        review = memory_review(candidate)
        proposed = self.service.execute(
            ServiceRequest(
                "codex",
                "memory.propose",
                {"candidate": candidate.as_payload()},
            )
        )
        self.assertFalse(proposed.data["persisted"])
        reviewed = self.service.execute(
            ServiceRequest(
                "claude",
                "memory.review",
                {
                    "candidate": candidate.as_payload(),
                    "review": review.as_payload(),
                },
            )
        )
        self.assertTrue(reviewed.data["persistence_eligible"])
        arguments = {
            "candidate": candidate.as_payload(),
            "review": review.as_payload(),
            "expected_revision": 0,
        }
        plans = [
            self.service.execute(
                ServiceRequest(kind, "memory.persist", arguments)
            ).data["plan"]
            for kind in ("cli", "sdk", "mcp", "plugin", "codex", "claude")
        ]
        self.assertTrue(all(item == plans[0] for item in plans))
        plan_id = plans[0]["plan_id"]
        applied = self.service.execute(
            ServiceRequest(
                "sdk",
                "memory.persist",
                arguments,
                apply=True,
                expected_plan_id=plan_id,
                approval_id=review.approval_id,
            )
        )
        self.assertEqual("applied", applied.status)

        stored = self.store.read("memory", candidate.proposed_memory.record_id)
        self.assertIsNotNone(stored)
        approved_record = self.store.read("memory", candidate.proposed_memory.record_id)
        self.assertIsNotNone(approved_record)
        action = memory_action(
            parse_information_record(dict(approved_record.payload)),
            action="revoke",
        )
        lifecycle_plan = self.service.execute(
            ServiceRequest(
                "plugin",
                "memory.lifecycle",
                {"action": action.as_payload()},
            )
        )
        lifecycle_plan_id = lifecycle_plan.data["plan"]["plan_id"]
        lifecycle_result = self.service.execute(
            ServiceRequest(
                "plugin",
                "memory.lifecycle",
                {"action": action.as_payload()},
                apply=True,
                expected_plan_id=lifecycle_plan_id,
                approval_id=action.approval_id,
            )
        )
        self.assertEqual("applied", lifecycle_result.status)

    def test_cli_exact_command_uses_the_same_service_result(self) -> None:
        request_path = self.data_root / "exact-request.json"
        request_path.write_text(
            json.dumps(exact_arguments(), ensure_ascii=False),
            encoding="utf-8",
        )
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = main(
                [
                    "knowledge",
                    "exact",
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(self.data_root),
                    "--request-file",
                    str(request_path),
                ]
            )
        self.assertEqual(0, result, error.getvalue())
        cli_payload = json.loads(output.getvalue())
        service_payload = self.service.execute(
            ServiceRequest("cli", "knowledge.search-exact", exact_arguments())
        ).as_dict()
        self.assertEqual(service_payload, cli_payload)


if __name__ == "__main__":
    unittest.main()
