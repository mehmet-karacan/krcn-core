from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.work_graph import (  # noqa: E402
    apply_work_item,
    build_work_item,
    prepare_work_item,
)
from krcn_core.work_semantic_index import (  # noqa: E402
    WorkSemanticIndexError,
    apply_work_semantic_index,
    canonical_work_document,
    load_work_retrieval_policy,
    prepare_work_semantic_index,
    semantic_work_scores,
    work_semantic_index_path,
    work_semantic_index_summary,
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


class WorkSemanticIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        project = {
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "name": "GPU Fusion",
            "description": "Semantic work test project",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        plan = self.store.prepare_put(
            "projects",
            "gpu-fusion",
            project,
            expected_revision=0,
            project_id="gpu-fusion",
        )
        self.store.apply_put(plan, authorize(plan.mutation))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def item(work_item_id: str, **updates) -> dict[str, object]:
        payload: dict[str, object] = {
            "work_item_id": work_item_id,
            "project_id": "gpu-fusion",
            "work_type": "request",
            "title": f"Request {work_item_id}",
            "description": "Deterministic work item",
            "status": "active",
            "acceptance_criteria": ["The acceptance test passes"],
            "relations": [],
            "evidence": [],
            "provenance": {
                "source_kind": "import",
                "source_ref": "legacy-work-source",
            },
        }
        payload.update(updates)
        return payload

    def apply_item(self, arguments: dict[str, object]) -> None:
        plan = prepare_work_item(self.store, self.ownership, arguments)
        authorizations = {
            effect.plan_id: authorize(effect) for effect in plan.effect_plans
        }
        apply_work_item(self.store, plan, authorizations)

    def apply_index(self):
        plan = prepare_work_semantic_index(
            REPO_ROOT,
            self.store,
            self.ownership,
            "gpu-fusion",
        )
        result = apply_work_semantic_index(
            REPO_ROOT,
            self.store,
            plan,
            authorize(plan.mutation),
        )
        return plan, result

    def test_canonical_document_redacts_paths_and_secrets(self) -> None:
        separator = chr(92)
        private_path = separator.join(("C:", "Users", "local-user", "secret.txt"))
        token_prefix = "github" + "_pat_"
        item = build_work_item(self.item(
            "gpu-fusion-request-893614",
            title=f"Hazine payı {private_path}",
            description=f"token={token_prefix}example123456789",
            evidence=[{
                "evidence_type": "document",
                "reference": separator.join(("C:", "private", "legacy.md")),
                "digest": "a" * 64,
                "label": "Legacy analysis",
            }],
            provenance={
                "source_kind": "import",
                "source_ref": separator.join(("C:", "legacy", "isler")),
            },
        ), 1)
        policy = load_work_retrieval_policy(REPO_ROOT)
        document = canonical_work_document(item, policy)
        self.assertIn("[redacted-path]", document.canonical_text)
        self.assertIn("[redacted-secret]", document.canonical_text)
        self.assertNotIn("local-user", document.canonical_text)
        self.assertNotIn(token_prefix, document.canonical_text)
        self.assertNotIn("private", document.canonical_text)
        self.assertNotIn("legacy-work-source", document.canonical_text)

    def test_atomic_contentless_index_is_current_and_queryable(self) -> None:
        self.apply_item(self.item(
            "gpu-fusion-request-893614",
            title="Kurumsal Mobil SMS Hakediş Raporu",
            description="Hazine payı oranı doğrulanacak",
        ))
        plan, result = self.apply_index()
        self.assertEqual(1, result["vector_count"])
        self.assertEqual(1, result["processed_item_count"])
        self.assertFalse(result["source_content_persisted"])
        summary = work_semantic_index_summary(
            REPO_ROOT,
            self.store,
            "gpu-fusion",
        )
        self.assertEqual("current", summary["status"])
        self.assertEqual(plan.index_digest, summary["index_digest"])
        scores = semantic_work_scores(
            REPO_ROOT,
            self.store,
            "gpu-fusion",
            "hazine payı oranı",
        )
        self.assertIn("gpu-fusion-request-893614", scores)
        connection = sqlite3.connect(
            work_semantic_index_path(self.home, "gpu-fusion")
        )
        try:
            self.assertEqual(
                ["metadata", "vectors"],
                sorted(row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )),
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(vectors)")
            }
            self.assertNotIn("content", columns)
            self.assertNotIn("path", columns)
        finally:
            connection.close()

    def test_incremental_plan_reuses_unchanged_work_digest(self) -> None:
        self.apply_item(self.item("gpu-fusion-request-893614"))
        self.apply_item(self.item("gpu-fusion-defect-468337", work_type="defect"))
        self.apply_index()
        self.apply_item(self.item(
            "gpu-fusion-request-893614",
            description="Updated request detail",
        ))
        plan = prepare_work_semantic_index(
            REPO_ROOT,
            self.store,
            self.ownership,
            "gpu-fusion",
        )
        self.assertEqual(1, plan.processed_item_count)
        self.assertEqual(1, plan.reused_item_count)
        self.assertEqual(0, plan.removed_item_count)

    def test_stale_index_fails_closed_after_work_change(self) -> None:
        self.apply_item(self.item("gpu-fusion-request-893614"))
        self.apply_index()
        self.apply_item(self.item(
            "gpu-fusion-request-893614",
            description="Work changed after semantic indexing",
        ))
        summary = work_semantic_index_summary(
            REPO_ROOT,
            self.store,
            "gpu-fusion",
        )
        self.assertEqual("stale", summary["status"])
        with self.assertRaisesRegex(WorkSemanticIndexError, "stale"):
            semantic_work_scores(
                REPO_ROOT,
                self.store,
                "gpu-fusion",
                "893614",
            )


if __name__ == "__main__":
    unittest.main()
