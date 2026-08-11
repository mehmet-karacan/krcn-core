from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_learning import (  # noqa: E402
    ProjectLearningError,
    apply_project_learning,
    prepare_project_learning,
)
from krcn_core.project_learning_intent import (  # noqa: E402
    parse_project_learning_intent,
)


def source_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result[path.relative_to(root).as_posix()] = (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return result


class UnifiedProjectLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "Örnek Proje"
        self.source.mkdir()
        (self.source / "pyproject.toml").write_text(
            '[project]\nname = "Örnek Uygulama"\n',
            encoding="utf-8",
        )
        (self.source / "README.md").write_text(
            "Sentetik proje içeriği\n",
            encoding="utf-8",
        )
        self.data_root = self.root / "user-data"
        self.store = LocalWorkspaceStore(
            self.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.intent = parse_project_learning_intent(str(self.source))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _authorizations(plan):
        authorizations = {}
        for item in plan.record_plans:
            mutation = item.mutation
            approval = None
            if mutation.approval_required:
                approval = ApprovalEvidence(
                    mutation.plan_id,
                    "single-project-learning-approval",
                    approved=True,
                )
            authorizations[mutation.plan_id] = authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, verified=True),
                approval=approval,
            )
        return authorizations

    def test_prepare_combines_four_records_without_mutation_or_path_disclosure(self) -> None:
        before = source_snapshot(self.source)
        plan = prepare_project_learning(REPO_ROOT, self.store, self.intent)
        summary = plan.public_summary()
        self.assertEqual(before, source_snapshot(self.source))
        self.assertEqual(
            ["source-bindings", "projects", "workspaces", "source-states"],
            [item.record_type for item in plan.record_plans],
        )
        self.assertEqual("ornek-uygulama", summary["metadata"]["project_id"])
        self.assertEqual(["Python"], summary["discovery"]["technologies"])
        self.assertEqual("read-only", summary["source_access"])
        self.assertFalse(summary["source_copy"])
        self.assertNotIn(str(self.source), json.dumps(summary, ensure_ascii=False))
        self.assertFalse(self.data_root.exists())

    def test_one_approval_applies_onboarding_and_first_discovery(self) -> None:
        before = source_snapshot(self.source)
        plan = prepare_project_learning(REPO_ROOT, self.store, self.intent)
        result = apply_project_learning(
            REPO_ROOT,
            self.store,
            plan,
            self._authorizations(plan),
        )
        self.assertEqual(4, len(result.records))
        self.assertEqual(before, source_snapshot(self.source))
        metadata = plan.metadata
        project = self.store.read("projects", metadata.project_id)
        binding = self.store.read("source-bindings", metadata.binding_id)
        workspace = self.store.read("workspaces", metadata.workspace_id)
        state = self.store.read("source-states", metadata.binding_id)
        self.assertEqual(
            [{"name": "Python", "category": "discovered"}],
            project.payload["technologies"],
        )
        self.assertEqual("read-only", binding.payload["default_access"])
        self.assertEqual([metadata.project_id], workspace.payload["project_refs"])
        self.assertEqual(plan.discovery.root_digest, state.payload["root_digest"])
        self.assertFalse(any(path.name == "README.md" for path in self.data_root.rglob("*")))

    def test_missing_authorization_blocks_every_record(self) -> None:
        plan = prepare_project_learning(REPO_ROOT, self.store, self.intent)
        authorizations = self._authorizations(plan)
        authorizations.pop(plan.record_plans[1].mutation.plan_id)
        with self.assertRaisesRegex(ProjectLearningError, "every project-learning"):
            apply_project_learning(REPO_ROOT, self.store, plan, authorizations)
        for record_type in ("source-bindings", "projects", "workspaces", "source-states"):
            self.assertEqual((), self.store.list_records(record_type))

    def test_changed_source_invalidates_plan_before_any_write(self) -> None:
        plan = prepare_project_learning(REPO_ROOT, self.store, self.intent)
        (self.source / "README.md").write_text("Değişti\n", encoding="utf-8")
        with self.assertRaisesRegex(ProjectLearningError, "stale"):
            apply_project_learning(
                REPO_ROOT,
                self.store,
                plan,
                self._authorizations(plan),
            )
        for record_type in ("source-bindings", "projects", "workspaces", "source-states"):
            self.assertEqual((), self.store.list_records(record_type))


if __name__ == "__main__":
    unittest.main()
