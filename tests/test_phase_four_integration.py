from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.policies import evaluate_policies, load_user_policies  # noqa: E402
from phase_four_fixtures import (  # noqa: E402
    knowledge_record,
    source_record,
)
from test_context_builder import build_request  # noqa: E402
from test_memory_gate import (  # noqa: E402
    database_policy,
    memory_candidate,
    memory_review,
)
from test_phase_four_services import binding_payload, exact_arguments  # noqa: E402
from test_semantic_retrieval import semantic_query  # noqa: E402


def file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


class PhaseFourIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.data_root, self.ownership)

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
                "synthetic-integration-approval",
                approved=True,
            ),
        )
        self.store.apply_put(plan, authorization)

    def _catalog_records(self, *, stale: bool = False) -> None:
        source = source_record(
            source_revision="rev-2" if stale else "rev-1",
            source_digest="b" * 64 if stale else "a" * 64,
        )
        knowledge = knowledge_record()
        self._put("source-bindings", "sample-project-local", binding_payload())
        self._put("authoritative-sources", source.record_id, source.as_payload())
        self._put("knowledge", knowledge.record_id, knowledge.as_payload())

    @staticmethod
    def _context_arguments(
        *,
        budget_limit: int = 1000,
        required: bool = True,
    ) -> dict[str, object]:
        record_id = "database-read-rule"
        return {
            "request": build_request(
                budget_unit="characters",
                budget_limit=budget_limit,
                required_record_ids=[record_id] if required else [],
                minimum_fragment_units=1,
            ).as_dict(),
            "candidates": [
                {
                    "record_id": record_id,
                    "layer": "task",
                    "selection_source": "exact",
                    "selection_reason": "exact:record-id",
                    "required": required,
                    "priority": 100,
                    "allow_truncation": not required,
                }
            ],
        }

    def test_context_rebuilds_after_model_session_and_compaction_change(self) -> None:
        self._catalog_records()
        before = file_snapshot(self.data_root)
        first_service = KrcnApplicationService(REPO_ROOT, self.store)
        first = first_service.execute(
            ServiceRequest(
                "codex",
                "context.build",
                self._context_arguments(),
            )
        )

        del first_service
        reopened_store = LocalWorkspaceStore(self.data_root, self.ownership)
        resumed_service = KrcnApplicationService(REPO_ROOT, reopened_store)
        resumed = resumed_service.execute(
            ServiceRequest(
                "claude",
                "context.build",
                self._context_arguments(),
            )
        )
        future_model = resumed_service.execute(
            ServiceRequest(
                "future-model",
                "context.build",
                self._context_arguments(),
            )
        )

        self.assertEqual(first.data, resumed.data)
        self.assertEqual(first.data, future_model.data)
        self.assertEqual(
            first.data["context"]["context_digest"],
            resumed.data["context"]["context_digest"],
        )
        self.assertEqual(before, file_snapshot(self.data_root))

    def test_stale_source_is_visible_and_cannot_be_required_context(self) -> None:
        self._catalog_records(stale=True)
        service = KrcnApplicationService(REPO_ROOT, self.store)
        catalog = service.execute(
            ServiceRequest("sdk", "knowledge.catalog", {})
        )
        availability = {
            item["record_id"]: item["availability"]
            for item in catalog.data["catalog"]["entries"]
        }
        self.assertEqual("stale", availability["database-read-rule"])
        exact = service.execute(
            ServiceRequest(
                "mcp",
                "knowledge.search-exact",
                exact_arguments(),
            )
        )
        self.assertEqual(0, exact.data["result"]["hit_count"])
        with self.assertRaisesRegex(ValueError, "stale or unavailable"):
            service.execute(
                ServiceRequest(
                    "plugin",
                    "context.build",
                    self._context_arguments(),
                )
            )

    def test_context_budget_is_deterministic_and_fails_closed_for_required_data(self) -> None:
        self._catalog_records()
        service = KrcnApplicationService(REPO_ROOT, self.store)
        optional_arguments = self._context_arguments(
            budget_limit=10,
            required=False,
        )
        first = service.execute(
            ServiceRequest("codex", "context.build", optional_arguments)
        )
        second = service.execute(
            ServiceRequest("claude", "context.build", optional_arguments)
        )
        self.assertEqual(first.data, second.data)
        self.assertLessEqual(first.data["context"]["budget"]["used"], 10)
        self.assertTrue(first.data["context"]["items"][0]["truncated"])
        with self.assertRaisesRegex(ValueError, "mandatory context exceeds"):
            service.execute(
                ServiceRequest(
                    "sdk",
                    "context.build",
                    self._context_arguments(budget_limit=10, required=True),
                )
            )

    def test_explicit_delete_deny_survives_memory_review_attempt(self) -> None:
        policy_directory = self.data_root / "policies"
        policy_directory.mkdir()
        policy_path = policy_directory / "database-read-only.json"
        policy_path.write_text(
            json.dumps(
                database_policy(
                    revision=1,
                    delete_effect="deny",
                    provenance="explicit-user",
                ),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        before = file_snapshot(policy_directory)
        candidate = memory_candidate(
            origin="conversation-summary",
            conflicts=("policy:database-read-only",),
        )
        review = memory_review(candidate)
        service = KrcnApplicationService(REPO_ROOT, self.store)
        with self.assertRaisesRegex(ValueError, "cannot override"):
            service.execute(
                ServiceRequest(
                    "codex",
                    "memory.review",
                    {
                        "candidate": candidate.as_payload(),
                        "review": review.as_payload(),
                    },
                )
            )
        decision = evaluate_policies(
            load_user_policies(policy_directory),
            resource_type="database",
            operation="delete",
            scope_refs={"integration": "sample-database"},
        )
        self.assertEqual("deny", decision.effect)
        self.assertEqual(before, file_snapshot(policy_directory))
        self.assertEqual((), self.store.list_records("memory"))

    def test_remote_provider_gate_runs_only_the_injected_approved_scorer(self) -> None:
        self._catalog_records()
        calls: list[tuple[str, int]] = []

        def scorer(query_text, documents):
            calls.append((query_text, len(documents)))
            return {item.record_id: 0.5 for item in documents}

        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            semantic_remote_scorers={"approved-remote": scorer},
        )
        arguments = {
            "query": semantic_query(
                provider="approved-remote",
                remote=True,
            ).as_dict(),
            "endpoint": "configured-endpoint",
            "retention_assumptions": "User reviewed provider terms",
        }
        with self.assertRaisesRegex(ValueError, "session approval"):
            service.execute(
                ServiceRequest(
                    "plugin",
                    "knowledge.search-semantic",
                    arguments,
                )
            )
        self.assertEqual([], calls)
        approved = service.execute(
            ServiceRequest(
                "plugin",
                "knowledge.search-semantic",
                arguments,
                approval_id="synthetic-provider-approval",
            )
        )
        self.assertEqual(1, len(calls))
        self.assertTrue(approved.data["result"]["approval_verified"])


if __name__ == "__main__":
    unittest.main()
