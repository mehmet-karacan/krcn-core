from __future__ import annotations

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
from krcn_core.work_graph import apply_work_item, prepare_work_item  # noqa: E402
from krcn_core.work_retrieval import (  # noqa: E402
    WorkRetrievalError,
    search_work,
)
from krcn_core.work_semantic_index import (  # noqa: E402
    apply_work_semantic_index,
    prepare_work_semantic_index,
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


class WorkRetrievalTests(unittest.TestCase):
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
            "description": "Hybrid work retrieval test project",
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
        self.apply_item(self.item(
            "gpu-fusion-request-893609",
            title="Dönem oranı kaynağını doğrula",
        ))
        self.apply_item(self.item(
            "gpu-fusion-request-893508",
            title="Mobil SMS raporu veri akışı",
        ))
        self.apply_item(self.item(
            "gpu-fusion-request-893614",
            title="Kurumsal Mobil SMS Hakediş Raporu",
            description=(
                "Hazine payı oranı için GPU_USER.FACT_TOTAL_CORP_SMS_REVENUE "
                "ve DIM_SMS_PAR akışı incelenecek"
            ),
            relations=[
                {
                    "relation_type": "relates-to",
                    "target_ref": "gpu-fusion-request-893609",
                },
                {
                    "relation_type": "relates-to",
                    "target_ref": "gpu-fusion-request-893508",
                },
            ],
        ))
        self.apply_item(self.item(
            "gpu-fusion-defect-468337",
            work_type="defect",
            title="Unrelated login defect",
            description="Authentication screen validation fails",
        ))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def item(work_item_id: str, **updates) -> dict[str, object]:
        payload: dict[str, object] = {
            "work_item_id": work_item_id,
            "project_id": "gpu-fusion",
            "work_type": "request",
            "title": f"Request {work_item_id}",
            "description": "Imported work item",
            "status": "active",
            "acceptance_criteria": ["Analysis is verified"],
            "relations": [],
            "evidence": [],
            "provenance": {
                "source_kind": "import",
                "source_ref": "mk-hub-isler",
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

    def apply_index(self) -> None:
        plan = prepare_work_semantic_index(
            REPO_ROOT,
            self.store,
            self.ownership,
            "gpu-fusion",
        )
        apply_work_semantic_index(
            REPO_ROOT,
            self.store,
            plan,
            authorize(plan.mutation),
        )

    def test_exact_external_id_precedes_graph_and_semantic(self) -> None:
        self.apply_index()
        result = search_work(REPO_ROOT, self.store, {
            "project_id": "gpu-fusion",
            "text": "893614",
            "limit": 10,
        })
        self.assertEqual(
            "gpu-fusion-request-893614",
            result["hits"][0]["work_item_id"],
        )
        self.assertEqual(0, result["hits"][0]["score_breakdown"]["rank_tier"])
        self.assertIn("exact", result["hits"][0]["matched_by"])
        related = {
            hit["work_item_id"]: hit for hit in result["hits"][1:]
        }
        self.assertEqual(
            2,
            related["gpu-fusion-request-893609"]["score_breakdown"][
                "rank_tier"
            ],
        )
        self.assertFalse(result["paths_disclosed"])
        self.assertFalse(result["remote_provider_used"])

    def test_hazine_payi_query_returns_893614_as_lexical_hit(self) -> None:
        self.apply_index()
        result = search_work(REPO_ROOT, self.store, {
            "project_id": "gpu-fusion",
            "text": "hazine payı oranı",
            "limit": 10,
        })
        first = result["hits"][0]
        self.assertEqual("gpu-fusion-request-893614", first["work_item_id"])
        self.assertEqual(1, first["score_breakdown"]["rank_tier"])
        self.assertIn("lexical", first["matched_by"])
        self.assertEqual("current", result["semantic_status"])
        self.assertEqual(
            ["exact", "lexical", "graph", "semantic"],
            result["ranking_order"],
        )

    def test_exact_and_lexical_remain_available_before_semantic_build(self) -> None:
        result = search_work(REPO_ROOT, self.store, {
            "project_id": "gpu-fusion",
            "text": "893614",
            "limit": 3,
        })
        self.assertEqual("unavailable", result["semantic_status"])
        self.assertIsNone(result["semantic_index_digest"])
        self.assertEqual(
            "gpu-fusion-request-893614",
            result["hits"][0]["work_item_id"],
        )

    def test_stale_semantic_index_is_never_silently_used(self) -> None:
        self.apply_index()
        self.apply_item(self.item(
            "gpu-fusion-defect-468337",
            work_type="defect",
            title="Changed defect title",
        ))
        with self.assertRaisesRegex(WorkRetrievalError, "stale"):
            search_work(REPO_ROOT, self.store, {
                "project_id": "gpu-fusion",
                "text": "defect",
            })

    def test_work_type_filter_is_applied_before_ranking(self) -> None:
        self.apply_index()
        result = search_work(REPO_ROOT, self.store, {
            "project_id": "gpu-fusion",
            "text": "validation",
            "work_types": ["defect"],
            "limit": 10,
        })
        self.assertTrue(result["hits"])
        self.assertTrue(
            all(hit["work_type"] == "defect" for hit in result["hits"])
        )


if __name__ == "__main__":
    unittest.main()
