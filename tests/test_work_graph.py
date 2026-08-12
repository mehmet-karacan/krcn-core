from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ServiceRequest,
    create_application_service,
)
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.work_graph import (  # noqa: E402
    WorkGraphError,
    prepare_work_item,
    work_graph_index_path,
)


def authorize(plan):
    return authorize_mutation(
        plan,
        dry_run=DryRunEvidence(plan.plan_id, verified=True),
        approval=(
            ApprovalEvidence(plan.plan_id, "test-approval", approved=True)
            if plan.approval_required
            else None
        ),
    )


class WorkGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        project = {
            "schema_version": 1,
            "project_id": "sample",
            "name": "Sample",
            "description": "Work Graph test project",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        plan = self.store.prepare_put(
            "projects", "sample", project,
            expected_revision=0, project_id="sample",
        )
        self.store.apply_put(plan, authorize(plan.mutation))
        self.service = create_application_service(REPO_ROOT, self.home)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def request(self, arguments: dict[str, object], *, apply: bool = False, plan_id: str | None = None):
        return self.service.execute(ServiceRequest(
            client_kind="test-client",
            operation="work.item.put",
            arguments=arguments,
            apply=apply,
            expected_plan_id=plan_id,
            approval_id="test-approval" if apply else None,
        ))

    @staticmethod
    def item(work_item_id: str, **updates) -> dict[str, object]:
        payload: dict[str, object] = {
            "work_item_id": work_item_id,
            "project_id": "sample",
            "work_type": "task",
            "title": f"Task {work_item_id}",
            "description": "Deterministic work item",
            "status": "active",
            "acceptance_criteria": ["Tests pass"],
            "relations": [],
            "evidence": [],
            "provenance": {
                "source_kind": "user",
                "source_ref": "test-request",
            },
        }
        payload.update(updates)
        return payload

    def apply_item(self, arguments: dict[str, object]):
        planned = self.request(arguments)
        self.assertEqual("planned", planned.status)
        return self.request(
            arguments,
            apply=True,
            plan_id=str(planned.data["plan"]["plan_id"]),
        )

    def test_exact_plan_persists_authoritative_item_event_and_projection(self) -> None:
        result = self.apply_item(self.item("task-one"))
        self.assertEqual("applied", result.status)
        stored = self.store.read("work-items", "task-one")
        self.assertIsNotNone(stored)
        self.assertEqual("active", stored.payload["status"])
        event = self.store.read("work-events", "task-one-r1")
        self.assertIsNotNone(event)
        index = work_graph_index_path(self.home, "sample")
        connection = sqlite3.connect(index)
        try:
            self.assertEqual(
                ("task-one", "active"),
                connection.execute(
                    "SELECT work_item_id, status FROM items"
                ).fetchone(),
            )
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()

    def test_completed_item_requires_evidence_and_history_is_append_only(self) -> None:
        self.apply_item(self.item("task-one"))
        with self.assertRaises(WorkGraphError):
            prepare_work_item(
                self.store,
                self.ownership,
                self.item("task-one", status="completed"),
            )
        completed = self.item(
            "task-one",
            status="completed",
            evidence=[{
                "evidence_type": "test",
                "reference": "suite:work-graph",
                "digest": "a" * 64,
                "label": "Full work graph tests",
            }],
        )
        self.apply_item(completed)
        response = self.service.execute(ServiceRequest(
            client_kind="test-client",
            operation="work.history",
            arguments={"project_id": "sample", "work_item_id": "task-one"},
        ))
        self.assertEqual(2, response.data["result"]["event_count"])
        self.assertEqual(
            ["active", "completed"],
            [item["to_status"] for item in response.data["result"]["events"]],
        )

    def test_dependency_cycle_and_stale_plan_fail_closed(self) -> None:
        self.apply_item(self.item("task-one"))
        self.apply_item(self.item(
            "task-two",
            relations=[{"relation_type": "depends-on", "target_ref": "task-one"}],
        ))
        with self.assertRaises(WorkGraphError):
            prepare_work_item(
                self.store,
                self.ownership,
                self.item(
                    "task-one",
                    relations=[{"relation_type": "depends-on", "target_ref": "task-two"}],
                ),
            )
        planned = self.request(self.item("task-three"))
        self.apply_item(self.item("task-four"))
        with self.assertRaises(ValueError):
            self.request(
                self.item("task-three"),
                apply=True,
                plan_id=str(planned.data["plan"]["plan_id"]),
            )

    def test_query_returns_exact_active_and_historical_counts(self) -> None:
        self.apply_item(self.item("task-active"))
        self.apply_item(self.item(
            "task-done",
            status="completed",
            evidence=[{
                "evidence_type": "commit",
                "reference": "git:abc123",
                "digest": "b" * 64,
                "label": "Implementation commit",
            }],
        ))
        response = self.service.execute(ServiceRequest(
            client_kind="test-client",
            operation="work.query",
            arguments={"project_id": "sample", "statuses": ["active"]},
        ))
        self.assertEqual(1, response.data["result"]["active_count"])
        self.assertEqual("task-active", response.data["result"]["items"][0]["work_item_id"])
        resume = self.service.execute(ServiceRequest(
            client_kind="test-client",
            operation="project.resume",
            arguments={
                "working_directory": str(self.home),
                "project_ref": "sample",
            },
        ))
        work = resume.data["resume"]["work"]
        self.assertEqual(1, work["active_task_count"])
        self.assertEqual(1, work["historical_task_count"])
        self.assertTrue(work["authoritative_status"])

    def test_json_documents_remain_pretty_and_machine_readable(self) -> None:
        self.apply_item(self.item("task-json"))
        path = self.home / "projects" / "sample" / "work" / "items" / "task-json.json"
        text = path.read_text(encoding="utf-8")
        self.assertIn("\n  \"payload\": {\n", text)
        self.assertEqual("task-json", json.loads(text)["record_id"])

    def test_unified_status_retrieval_uses_authoritative_work_without_vector_index(self) -> None:
        self.apply_item(self.item("task-unified"))
        response = self.service.execute(ServiceRequest(
            client_kind="codex",
            operation="retrieval.unified",
            arguments={
                "query": {
                    "schema_ref": "schemas/unified-retrieval-query.schema.json",
                    "schema_version": 1,
                    "query_id": "resume-query",
                    "text": "Nerede kaldık?",
                    "project_ids": ["sample"],
                    "scope": "project",
                    "intent": "auto",
                    "result_limit": 12,
                    "token_budget": 1024,
                }
            },
        ))
        result = response.data["result"]
        self.assertEqual("status", result["intent"])
        self.assertEqual("task-unified", result["hits"][0]["hit_id"])
        self.assertEqual("work", result["hits"][0]["domain"])
        self.assertEqual(0, result["hits"][0]["evidence_tier"])
        self.assertEqual("current", response.data["domain_status"]["sample:work"])
        self.assertEqual(
            "unavailable",
            response.data["domain_status"]["sample:knowledge"],
        )
        serialized = json.dumps(response.as_dict(), ensure_ascii=False)
        self.assertNotIn(str(self.home), serialized)
        self.assertFalse(result["remote_call_performed"])

    def test_unified_retrieval_requires_explicit_multi_project_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "multi-project"):
            self.service.execute(ServiceRequest(
                client_kind="plugin",
                operation="retrieval.unified",
                arguments={
                    "query": {
                        "schema_ref": "schemas/unified-retrieval-query.schema.json",
                        "schema_version": 1,
                        "query_id": "unsafe-scope",
                        "text": "Durum nedir?",
                        "project_ids": ["sample", "another"],
                        "scope": "project",
                        "intent": "status",
                        "result_limit": 12,
                        "token_budget": 1024,
                    }
                },
            ))


if __name__ == "__main__":
    unittest.main()
