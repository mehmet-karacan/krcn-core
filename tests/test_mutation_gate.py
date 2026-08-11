from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    MutationGateError,
    OwnershipResolver,
    authorize_mutation,
    plan_mutation,
)


class MutationGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolver = OwnershipResolver.from_repository(REPO_ROOT)

    def test_ownership_resolver_separates_core_and_user_data(self) -> None:
        self.assertEqual("core", self.resolver.resolve("src/krcn_core/example.py"))
        self.assertEqual(
            "user-data", self.resolver.resolve(".krcn/projects/sample.json")
        )
        self.assertEqual("derived", self.resolver.resolve(".krcn/indexes/sample.db"))

    def test_core_update_requires_matching_dry_run(self) -> None:
        plan = plan_mutation(
            self.resolver,
            operation="update",
            target_ref="src/krcn_core/example.py",
            expected_ownership="core",
            reversible=True,
        )
        authorization = authorize_mutation(
            plan,
            dry_run=DryRunEvidence(plan.plan_id, verified=True),
        )
        self.assertTrue(authorization.dry_run_verified)
        self.assertFalse(authorization.approval_verified)

    def test_user_data_update_requires_exact_approval(self) -> None:
        plan = plan_mutation(
            self.resolver,
            operation="update",
            target_ref=".krcn/policies/database.json",
            expected_ownership="user-data",
            reversible=True,
        )
        dry_run = DryRunEvidence(plan.plan_id, verified=True)
        with self.assertRaisesRegex(MutationGateError, "approval"):
            authorize_mutation(plan, dry_run=dry_run)
        approval = ApprovalEvidence(plan.plan_id, "approval-1", approved=True)
        authorization = authorize_mutation(plan, dry_run=dry_run, approval=approval)
        self.assertTrue(authorization.approval_verified)

    def test_approval_for_another_plan_is_rejected(self) -> None:
        plan = plan_mutation(
            self.resolver,
            operation="delete",
            target_ref="docs/sample.md",
            reversible=True,
        )
        with self.assertRaisesRegex(MutationGateError, "approval"):
            authorize_mutation(
                plan,
                dry_run=DryRunEvidence(plan.plan_id, verified=True),
                approval=ApprovalEvidence("different-plan", "approval-2", True),
            )

    def test_secret_and_irreversible_mutations_are_blocked(self) -> None:
        secret_plan = plan_mutation(
            self.resolver,
            operation="update",
            target_ref=".krcn/secrets/provider.json",
            reversible=True,
        )
        with self.assertRaisesRegex(MutationGateError, "secret"):
            authorize_mutation(
                secret_plan,
                dry_run=DryRunEvidence(secret_plan.plan_id, verified=True),
                approval=ApprovalEvidence(secret_plan.plan_id, "approval-3", True),
            )
        irreversible = plan_mutation(
            self.resolver,
            operation="update",
            target_ref="src/krcn_core/example.py",
            reversible=False,
        )
        with self.assertRaisesRegex(MutationGateError, "irreversible"):
            authorize_mutation(
                irreversible,
                dry_run=DryRunEvidence(irreversible.plan_id, verified=True),
            )

    def test_absolute_and_parent_paths_are_rejected(self) -> None:
        for target in ("../outside", "C:/machine/path"):
            with self.subTest(target=target):
                with self.assertRaises(MutationGateError):
                    self.resolver.resolve(target)


if __name__ == "__main__":
    unittest.main()
