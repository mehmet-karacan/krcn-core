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
from krcn_core.onboarding import (  # noqa: E402
    OnboardingError,
    OnboardingRequest,
    apply_read_only_onboarding,
    prepare_read_only_onboarding,
)


def source_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    snapshot = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        snapshot[relative] = (path.stat().st_mtime_ns, hashlib.sha256(content).hexdigest())
    return snapshot


class ReadOnlyOnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_temp = tempfile.TemporaryDirectory()
        self.data_temp = tempfile.TemporaryDirectory()
        self.source_root = Path(self.source_temp.name)
        (self.source_root / "README.md").write_text("Synthetic project\n", encoding="utf-8")
        (self.source_root / "src").mkdir()
        (self.source_root / "src" / "sample.py").write_text(
            "print('sample')\n", encoding="utf-8"
        )
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(Path(self.data_temp.name), ownership)
        self.request = OnboardingRequest(
            workspace_id="sample-workspace",
            project_id="sample-project",
            binding_id="sample-project-local",
            project_name="Sample Project",
            description="Synthetic fixture",
            source_root=self.source_root,
        )

    def tearDown(self) -> None:
        self.source_temp.cleanup()
        self.data_temp.cleanup()

    @staticmethod
    def authorizations(plan):
        result = {}
        for record_plan in plan.record_plans:
            mutation = record_plan.mutation
            result[mutation.plan_id] = authorize_mutation(
                mutation,
                dry_run=DryRunEvidence(mutation.plan_id, verified=True),
                approval=ApprovalEvidence(
                    mutation.plan_id,
                    f"approval-{record_plan.record_type}",
                    approved=True,
                ),
            )
        return result

    def test_prepare_is_a_redacted_and_non_mutating_dry_run(self) -> None:
        before = source_snapshot(self.source_root)
        plan = prepare_read_only_onboarding(self.store, self.request)
        after = source_snapshot(self.source_root)
        self.assertEqual(before, after)
        self.assertEqual((), self.store.list_summaries("workspaces"))
        summary = plan.public_summary()
        self.assertEqual("read-only", summary["source_access"])
        self.assertNotIn(str(self.source_root), json.dumps(summary))

    def test_missing_authorization_blocks_all_record_writes(self) -> None:
        plan = prepare_read_only_onboarding(self.store, self.request)
        authorizations = self.authorizations(plan)
        authorizations.pop(plan.record_plans[1].mutation.plan_id)
        with self.assertRaisesRegex(OnboardingError, "every record plan"):
            apply_read_only_onboarding(self.store, plan, authorizations)
        for record_type in ("workspaces", "projects", "source-bindings"):
            self.assertEqual((), self.store.list_summaries(record_type))

    def test_apply_registers_logical_records_without_source_write(self) -> None:
        before = source_snapshot(self.source_root)
        plan = prepare_read_only_onboarding(self.store, self.request)
        result = apply_read_only_onboarding(
            self.store,
            plan,
            self.authorizations(plan),
        )
        self.assertEqual(before, source_snapshot(self.source_root))
        self.assertEqual(3, len(result.records))
        binding = self.store.read("source-bindings", "sample-project-local")
        project = self.store.read("projects", "sample-project")
        workspace = self.store.read("workspaces", "sample-workspace")
        self.assertEqual("read-only", binding.payload["default_access"])
        self.assertNotIn("write", binding.payload["capabilities"])
        self.assertEqual(["sample-project-local"], project.payload["source_refs"])
        self.assertEqual(["sample-project"], workspace.payload["project_refs"])
        self.assertNotIn(str(self.source_root), json.dumps(result.public_summary()))

    def test_source_inside_user_data_is_rejected(self) -> None:
        request = OnboardingRequest(
            **{
                **self.request.__dict__,
                "source_root": Path(self.data_temp.name),
            }
        )
        with self.assertRaisesRegex(OnboardingError, "user-data"):
            prepare_read_only_onboarding(self.store, request)

    def test_relative_source_path_is_rejected(self) -> None:
        request = OnboardingRequest(
            **{
                **self.request.__dict__,
                "source_root": Path("relative-project"),
            }
        )
        with self.assertRaisesRegex(OnboardingError, "absolute"):
            prepare_read_only_onboarding(self.store, request)


if __name__ == "__main__":
    unittest.main()
