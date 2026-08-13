from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.client_capabilities import (  # noqa: E402
    CAPABILITY_NAMES,
    ClientCapabilityError,
    create_client_capability_profile,
    load_client_capability_policy,
    parse_client_capability_policy,
)


def declaration(**overrides: bool) -> dict[str, bool]:
    result = {name: False for name in CAPABILITY_NAMES}
    result.update(overrides)
    return result


class ClientCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_client_capability_policy(REPO_ROOT)

    def profile(
        self,
        capabilities: dict[str, bool],
        *,
        max_parallel_agents: int = 1,
        session_id: str = "session-001",
    ):
        return create_client_capability_profile(
            self.policy,
            session_id=session_id,
            client_id="codex",
            capabilities=capabilities,
            max_parallel_agents=max_parallel_agents,
        )

    def test_native_parallel_is_preferred_when_supported(self) -> None:
        profile = self.profile(
            declaration(
                native_subagents=True,
                parallel_subagents=True,
                per_agent_model_selection=True,
                agent_cancellation=True,
                structured_results=True,
            ),
            max_parallel_agents=4,
        )
        self.assertEqual("native-parallel", profile.selected_mode)
        payload = profile.as_dict()
        self.assertTrue(payload["session_bound"])
        self.assertFalse(payload["declaration_grants_authority"])
        self.assertFalse(payload["secret_values_included"])
        self.assertFalse(payload["absolute_paths_included"])

    def test_native_result_channel_does_not_require_structured_schema(self) -> None:
        parallel = self.profile(
            declaration(
                native_subagents=True,
                parallel_subagents=True,
                agent_cancellation=True,
            ),
            max_parallel_agents=3,
        )
        sequential = self.profile(declaration(native_subagents=True))
        self.assertEqual("native-parallel", parallel.selected_mode)
        self.assertEqual("native-sequential", sequential.selected_mode)
        self.assertFalse(parallel.capabilities["structured_results"])
        self.assertFalse(sequential.capabilities["structured_results"])

    def test_sequential_and_isolated_fallbacks_are_explicit(self) -> None:
        sequential = self.profile(
            declaration(native_subagents=True, structured_results=True)
        )
        isolated = self.profile(
            declaration(structured_results=True, isolated_role_execution=True)
        )
        self.assertEqual("native-sequential", sequential.selected_mode)
        self.assertEqual("isolated-role-fallback", isolated.selected_mode)

    def test_missing_delegation_channel_or_incomplete_declaration_fails_closed(self) -> None:
        unavailable = self.profile(declaration())
        isolated_without_contract = self.profile(
            declaration(isolated_role_execution=True)
        )
        self.assertEqual("delegation-unavailable", unavailable.selected_mode)
        self.assertEqual(
            "delegation-unavailable", isolated_without_contract.selected_mode
        )
        incomplete = declaration()
        incomplete.pop("structured_results")
        with self.assertRaisesRegex(ClientCapabilityError, "incomplete"):
            self.profile(incomplete)

    def test_contradictory_parallel_declarations_are_rejected(self) -> None:
        with self.assertRaisesRegex(ClientCapabilityError, "require native"):
            self.profile(
                declaration(parallel_subagents=True, structured_results=True),
                max_parallel_agents=2,
            )
        with self.assertRaisesRegex(ClientCapabilityError, "at least two"):
            self.profile(
                declaration(
                    native_subagents=True,
                    parallel_subagents=True,
                    structured_results=True,
                )
            )
        with self.assertRaisesRegex(ClientCapabilityError, "one agent slot"):
            self.profile(declaration(), max_parallel_agents=2)

    def test_session_identity_is_portable_and_changes_the_digest(self) -> None:
        capabilities = declaration(native_subagents=True, structured_results=True)
        first = self.profile(capabilities, session_id="session-001")
        repeated = self.profile(capabilities, session_id="session-001")
        second = self.profile(capabilities, session_id="session-002")
        self.assertEqual(first.profile_digest, repeated.profile_digest)
        self.assertNotEqual(first.profile_digest, second.profile_digest)
        absolute_session = "C:" + "\\private\\session"
        with self.assertRaisesRegex(ClientCapabilityError, "session_id"):
            self.profile(capabilities, session_id=absolute_session)
        secret_like_session = "github" + "_pat_" + "A1B2C3D4E5F6"
        with self.assertRaisesRegex(ClientCapabilityError, "secret-like"):
            self.profile(capabilities, session_id=secret_like_session)

    def test_policy_digest_is_canonical_and_boundary_is_strict(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config" / "client-capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        reordered = {key: payload[key] for key in reversed(payload)}
        self.assertEqual(
            self.policy.policy_digest,
            parse_client_capability_policy(reordered).policy_digest,
        )
        changed = copy.deepcopy(payload)
        changed["invariants"]["declaration_grants_authority"] = True
        with self.assertRaisesRegex(ClientCapabilityError, "invariants"):
            parse_client_capability_policy(changed)


if __name__ == "__main__":
    unittest.main()
