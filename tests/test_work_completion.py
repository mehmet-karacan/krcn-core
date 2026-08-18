from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore, LocalStoreError  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    MutationGateError,
    OwnershipResolver,
    authorize_mutation,
    plan_mutation,
)
from krcn_core.work_completion import (  # noqa: E402
    WorkCompletionError,
    apply_verified_work_completion,
    build_work_completion_attestation,
    persist_work_completion_attestation,
    prepare_verified_work_completion,
)
from krcn_core.work_graph import apply_work_item, prepare_work_item  # noqa: E402
import test_orchestration_verifier as verifier_fixtures  # noqa: E402


def authorize(effect):
    return authorize_mutation(
        effect,
        dry_run=DryRunEvidence(effect.plan_id, True),
        approval=(
            ApprovalEvidence(effect.plan_id, "test-approval", True)
            if effect.approval_required
            else None
        ),
    )


class WorkCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / ".krcn"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        project = {
            "schema_version": 1,
            "project_id": "sample",
            "name": "Sample",
            "description": "Completion test",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        project_plan = self.store.prepare_put(
            "projects", "sample", project,
            expected_revision=0, project_id="sample",
        )
        self.store.apply_put(project_plan, authorize(project_plan.mutation))
        fixture = verifier_fixtures.OrchestrationVerifierTests(
            methodName="test_all_constraints_criteria_and_requirements_need_passing_evidence"
        )
        fixture.setUp()
        self.fixture = fixture
        self.verification = fixture.verify(fixture.evidence_for_all)
        self._put("target")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _arguments(self, work_id: str, *, relations=()):
        return {
            "work_item_id": work_id,
            "project_id": "sample",
            "work_type": "task",
            "title": f"Task {work_id}",
            "description": "Evidence-bound completion",
            "status": "active",
            "acceptance_criteria": [
                item.value for item in self.fixture.intent.acceptance_criteria
            ],
            "relations": list(relations),
            "evidence": [],
            "provenance": {"source_kind": "user", "source_ref": "test"},
        }

    def _put(self, work_id: str, *, relations=()):
        plan = prepare_work_item(
            self.store,
            self.ownership,
            self._arguments(work_id, relations=relations),
            repo_root=REPO_ROOT,
        )
        apply_work_item(
            self.store,
            plan,
            {effect.plan_id: authorize(effect) for effect in plan.effect_plans},
        )

    def _update(self, arguments):
        plan = prepare_work_item(
            self.store,
            self.ownership,
            arguments,
            repo_root=REPO_ROOT,
        )
        apply_work_item(
            self.store,
            plan,
            {effect.plan_id: authorize(effect) for effect in plan.effect_plans},
        )

    def test_unrelated_work_item_does_not_stale_verified_target_completion(self) -> None:
        attestation = build_work_completion_attestation(
            self.store,
            project_id="sample",
            work_item_id="target",
            plan=self.fixture.plan,
            verification=self.verification,
        )
        persist_work_completion_attestation(self.store, attestation)
        completion = prepare_verified_work_completion(
            REPO_ROOT, self.store, attestation
        )

        self._put("unrelated")
        result = apply_verified_work_completion(
            self.store, self.ownership, completion
        )

        self.assertEqual("completed", result["status"])
        self.assertFalse(result["second_approval_required"])
        self.assertEqual("completed", self.store.read("work-items", "target").payload["status"])
        self.assertEqual("active", self.store.read("work-items", "unrelated").payload["status"])

        reopened_arguments = self._arguments("target")
        reopened_plan = prepare_work_item(
            self.store,
            self.ownership,
            reopened_arguments,
            repo_root=REPO_ROOT,
        )
        self.assertTrue(reopened_plan.record_plan.mutation.approval_required)

    def test_relevant_relation_change_stales_completion_but_unrelated_does_not(self) -> None:
        self._put(
            "related",
            relations=({"relation_type": "depends-on", "target_ref": "target"},),
        )
        attestation = build_work_completion_attestation(
            self.store,
            project_id="sample",
            work_item_id="target",
            plan=self.fixture.plan,
            verification=self.verification,
        )
        completion = prepare_verified_work_completion(
            REPO_ROOT, self.store, attestation
        )
        changed = self._arguments(
            "related",
            relations=({"relation_type": "depends-on", "target_ref": "target"},),
        )
        changed["description"] = "Relevant relation source changed"
        self._update(changed)
        with self.assertRaisesRegex(WorkCompletionError, "dependencies changed"):
            apply_verified_work_completion(
                self.store, self.ownership, completion
            )

    def test_missing_exact_acceptance_proof_blocks_automatic_completion(self) -> None:
        changed = self._arguments("target")
        changed["acceptance_criteria"] = ["Different unverified criterion"]
        self._update(changed)
        with self.assertRaisesRegex(WorkCompletionError, "acceptance criteria"):
            build_work_completion_attestation(
                self.store,
                project_id="sample",
                work_item_id="target",
                plan=self.fixture.plan,
                verification=self.verification,
            )

    def test_generic_mutation_planner_cannot_claim_verified_completion_scope(self) -> None:
        with self.assertRaises(MutationGateError):
            plan_mutation(
                self.ownership,
                operation="update",
                target_ref=".krcn/projects/sample/work/items/target.json",
                expected_ownership="user-data",
                change_digest="a" * 64,
                reversible=True,
                approval_scope="verified-work-completion",
            )
        current = self.store.read("work-items", "target")
        payload = dict(current.payload)
        payload["revision"] = current.revision + 1
        with self.assertRaises(LocalStoreError):
            self.store.prepare_put(
                "work-items",
                "target",
                payload,
                expected_revision=current.revision,
                project_id="sample",
                approval_scope="verified-work-completion",
            )


if __name__ == "__main__":
    unittest.main()
