from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.client_capabilities import (  # noqa: E402
    CAPABILITY_NAMES,
    create_client_capability_profile,
    load_client_capability_policy,
)
from krcn_core.delegation_policy import (  # noqa: E402
    DelegationPolicyError,
    decide_delegation,
    load_delegation_policy,
    parse_delegation_policy,
)


def capabilities(**overrides: bool) -> dict[str, bool]:
    result = {name: False for name in CAPABILITY_NAMES}
    result.update(overrides)
    return result


class DelegationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client_policy = load_client_capability_policy(REPO_ROOT)
        self.policy = load_delegation_policy(REPO_ROOT)

    def profile(self, declared: dict[str, bool], slots: int = 1):
        return create_client_capability_profile(
            self.client_policy,
            session_id="session-001",
            client_id="codex",
            capabilities=declared,
            max_parallel_agents=slots,
        )

    def test_meaningful_project_work_requires_coordinator_delegation(self) -> None:
        profile = self.profile(
            capabilities(
                native_subagents=True,
                parallel_subagents=True,
                structured_results=True,
            ),
            3,
        )
        decision = decide_delegation(
            self.policy,
            profile,
            work_class="project-implementation",
            project_matched=True,
        )
        self.assertTrue(decision.delegation_required)
        self.assertTrue(decision.execution_allowed)
        self.assertTrue(decision.parallel_preferred)
        self.assertTrue(decision.coordinator_only)
        self.assertEqual("native-parallel", decision.selected_mode)
        self.assertEqual("delegated-project-work", decision.decision_basis)
        self.assertFalse(decision.as_dict()["client_declaration_grants_authority"])

    def test_codex_native_text_results_allow_parallel_delegation(self) -> None:
        profile = self.profile(
            capabilities(
                native_subagents=True,
                parallel_subagents=True,
                agent_cancellation=True,
            ),
            3,
        )
        decision = decide_delegation(
            self.policy,
            profile,
            work_class="project-design",
            project_matched=True,
        )
        self.assertEqual("native-parallel", decision.selected_mode)
        self.assertTrue(decision.execution_allowed)
        self.assertTrue(decision.delegation_required)
        self.assertTrue(decision.coordinator_only)
        self.assertFalse(decision.as_dict()["client_declaration_grants_authority"])

    def test_sequential_subagents_remain_a_visible_fallback(self) -> None:
        profile = self.profile(
            capabilities(native_subagents=True, structured_results=True)
        )
        decision = decide_delegation(
            self.policy,
            profile,
            work_class="project-analysis",
            project_matched=True,
        )
        self.assertTrue(decision.execution_allowed)
        self.assertEqual("native-sequential", decision.selected_mode)
        self.assertTrue(decision.parallel_preferred)

    def test_unavailable_delegation_blocks_project_execution(self) -> None:
        profile = self.profile(capabilities())
        decision = decide_delegation(
            self.policy,
            profile,
            work_class="project-verification",
            project_matched=True,
        )
        self.assertTrue(decision.delegation_required)
        self.assertFalse(decision.execution_allowed)
        self.assertEqual("delegation-unavailable", decision.selected_mode)
        self.assertEqual(
            "delegation-capability-unavailable", decision.decision_basis
        )

    def test_chat_status_and_exact_lookup_are_coordinator_exceptions(self) -> None:
        profile = self.profile(capabilities())
        for work_class in ("general-chat", "status", "exact-lookup"):
            with self.subTest(work_class=work_class):
                decision = decide_delegation(
                    self.policy,
                    profile,
                    work_class=work_class,
                    project_matched=True,
                )
                self.assertFalse(decision.delegation_required)
                self.assertTrue(decision.execution_allowed)
                self.assertFalse(decision.coordinator_only)
                self.assertEqual("coordinator-exception", decision.decision_basis)

    def test_unknown_work_is_denied_instead_of_silently_downgraded(self) -> None:
        profile = self.profile(capabilities())
        with self.assertRaisesRegex(DelegationPolicyError, "unknown"):
            decide_delegation(
                self.policy,
                profile,
                work_class="unreviewed-operation",
                project_matched=True,
            )

    def test_project_work_without_project_context_does_not_claim_delegation(self) -> None:
        profile = self.profile(capabilities())
        decision = decide_delegation(
            self.policy,
            profile,
            work_class="project-analysis",
            project_matched=False,
        )
        self.assertFalse(decision.delegation_required)
        self.assertTrue(decision.execution_allowed)
        self.assertEqual("project-context-unmatched", decision.decision_basis)

    def test_decisions_and_policy_digests_are_deterministic(self) -> None:
        profile = self.profile(
            capabilities(structured_results=True, isolated_role_execution=True)
        )
        first = decide_delegation(
            self.policy,
            profile,
            work_class="project-integration",
            project_matched=True,
        )
        repeated = decide_delegation(
            self.policy,
            profile,
            work_class="project-integration",
            project_matched=True,
        )
        self.assertEqual(first.decision_digest, repeated.decision_digest)

        payload = json.loads(
            (REPO_ROOT / "config" / "delegation-policy.json").read_text(
                encoding="utf-8"
            )
        )
        reordered = {key: payload[key] for key in reversed(payload)}
        self.assertEqual(
            self.policy.policy_digest,
            parse_delegation_policy(reordered).policy_digest,
        )

    def test_coordinator_boundary_forbids_direct_project_work(self) -> None:
        self.assertIn("decompose-work", self.policy.coordinator_responsibilities)
        self.assertIn("assign-subagents", self.policy.coordinator_responsibilities)
        self.assertIn(
            "modify-project-source", self.policy.coordinator_prohibited_actions
        )
        self.assertIn("run-project-tests", self.policy.coordinator_prohibited_actions)


if __name__ == "__main__":
    unittest.main()
