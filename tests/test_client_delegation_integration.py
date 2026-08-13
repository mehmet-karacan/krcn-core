from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.client_capabilities import CAPABILITY_NAMES  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


def declared(**overrides: bool) -> dict[str, bool]:
    result = {name: False for name in CAPABILITY_NAMES}
    result.update(overrides)
    return result


class ClientDelegationApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name) / ".krcn"
        self.store = LocalWorkspaceStore(
            self.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def arguments(
        self,
        capabilities: dict[str, bool],
        *,
        slots: int = 1,
    ) -> dict[str, object]:
        return {
            "session_id": "session-001",
            "client_id": "codex",
            "capabilities": capabilities,
            "max_parallel_agents": slots,
        }

    def test_capability_profile_is_read_only_and_transport_neutral(self) -> None:
        arguments = self.arguments(
            declared(native_subagents=True, structured_results=True)
        )
        responses = []
        for client in ("cli", "sdk", "mcp", "plugin", "codex", "claude"):
            response = self.service.execute(
                ServiceRequest(client, "client.capabilities", arguments)
            )
            responses.append(response.data)
        self.assertTrue(all(response == responses[0] for response in responses))
        self.assertEqual(
            "native-sequential", responses[0]["profile"]["selected_mode"]
        )
        self.assertFalse(responses[0]["profile"]["declaration_grants_authority"])
        self.assertFalse(self.data_root.exists())

        with self.assertRaisesRegex(ApplicationServiceError, "read-only"):
            self.service.execute(
                ServiceRequest(
                    "cli",
                    "client.capabilities",
                    arguments,
                    apply=True,
                )
            )

    def test_native_parallel_project_work_is_coordinator_only(self) -> None:
        arguments = self.arguments(
            declared(
                native_subagents=True,
                parallel_subagents=True,
                structured_results=True,
            ),
            slots=4,
        )
        arguments.update(
            {"work_class": "project-implementation", "project_matched": True}
        )
        response = self.service.execute(
            ServiceRequest("codex", "client.delegation", arguments)
        )
        self.assertEqual("ok", response.status)
        self.assertTrue(response.data["decision"]["coordinator_only"])
        self.assertTrue(response.data["decision"]["parallel_preferred"])
        self.assertEqual("native-parallel", response.data["decision"]["selected_mode"])
        self.assertIsNone(response.data["degradation"])
        self.assertFalse(response.data["authority_granted"])

    def test_native_text_results_are_supported_for_every_client(self) -> None:
        client_matrix = (
            ("cli", "codex-desktop"),
            ("sdk", "claude-desktop"),
            ("mcp", "claude-cli"),
            ("plugin", "opencode"),
            ("plugin", "custom-agent-client"),
        )
        for transport, client_id in client_matrix:
            with self.subTest(client_id=client_id):
                arguments = self.arguments(
                    declared(
                        native_subagents=True,
                        parallel_subagents=True,
                        agent_cancellation=True,
                    ),
                    slots=3,
                )
                arguments["client_id"] = client_id
                arguments.update(
                    {"work_class": "project-design", "project_matched": True}
                )
                response = self.service.execute(
                    ServiceRequest(transport, "client.delegation", arguments)
                )
                self.assertEqual("ok", response.status)
                self.assertEqual(
                    "native-parallel", response.data["profile"]["selected_mode"]
                )
                self.assertFalse(
                    response.data["profile"]["capabilities"]["structured_results"]
                )
                self.assertTrue(response.data["decision"]["execution_allowed"])
                self.assertTrue(response.data["decision"]["coordinator_only"])
                self.assertFalse(response.data["authority_granted"])

    def test_sequential_is_degraded_and_unavailable_is_blocked(self) -> None:
        sequential = self.arguments(
            declared(native_subagents=True, structured_results=True)
        )
        sequential.update(
            {"work_class": "project-analysis", "project_matched": True}
        )
        degraded = self.service.execute(
            ServiceRequest("codex", "client.delegation", sequential)
        )
        self.assertEqual("degraded", degraded.status)
        self.assertFalse(degraded.data["degradation"]["execution_blocked"])

        unavailable = self.arguments(declared())
        unavailable.update(
            {"work_class": "project-analysis", "project_matched": True}
        )
        blocked = self.service.execute(
            ServiceRequest("codex", "client.delegation", unavailable)
        )
        self.assertEqual("blocked", blocked.status)
        self.assertFalse(blocked.data["decision"]["execution_allowed"])
        self.assertTrue(blocked.data["degradation"]["execution_blocked"])
        self.assertTrue(
            blocked.data["degradation"]["user_visible_notice_required"]
        )

    def test_exact_lookup_remains_a_coordinator_exception(self) -> None:
        arguments = self.arguments(declared())
        arguments.update({"work_class": "exact-lookup", "project_matched": True})
        response = self.service.execute(
            ServiceRequest("plugin", "client.delegation", arguments)
        )
        self.assertEqual("ok", response.status)
        self.assertFalse(response.data["decision"]["delegation_required"])
        self.assertTrue(response.data["decision"]["execution_allowed"])
        self.assertIsNone(response.data["degradation"])


class ClientDelegationCliTests(unittest.TestCase):
    def run_cli(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "client",
                        *arguments,
                        "--repo",
                        str(REPO_ROOT),
                        "--data-root",
                        str(Path(temporary) / ".krcn"),
                        "--format",
                        "json",
                    ]
                )
            return result, json.loads(output.getvalue())

    def test_cli_reports_native_parallel_selection(self) -> None:
        result, payload = self.run_cli(
            [
                "delegation",
                "--session-id",
                "session-001",
                "--client-id",
                "codex",
                "--work-class",
                "project-analysis",
                "--project-matched",
                "--native-subagents",
                "--parallel-subagents",
                "--structured-results",
                "--max-parallel-agents",
                "4",
            ]
        )
        self.assertEqual(0, result)
        self.assertEqual("ok", payload["status"])
        self.assertEqual(
            "native-parallel", payload["data"]["decision"]["selected_mode"]
        )

    def test_cli_supports_native_text_results_for_every_client(self) -> None:
        for client_id in (
            "codex-desktop",
            "claude-desktop",
            "claude-cli",
            "opencode",
            "custom-agent-client",
        ):
            with self.subTest(client_id=client_id):
                result, payload = self.run_cli(
                    [
                        "delegation",
                        "--session-id",
                        f"{client_id}-session",
                        "--client-id",
                        client_id,
                        "--work-class",
                        "project-design",
                        "--project-matched",
                        "--native-subagents",
                        "--parallel-subagents",
                        "--agent-cancellation",
                        "--max-parallel-agents",
                        "3",
                    ]
                )
                self.assertEqual(0, result)
                self.assertEqual("ok", payload["status"])
                self.assertEqual(
                    "native-parallel", payload["data"]["decision"]["selected_mode"]
                )
                self.assertFalse(
                    payload["data"]["profile"]["capabilities"][
                        "structured_results"
                    ]
                )
                self.assertFalse(payload["data"]["authority_granted"])

    def test_cli_infers_safe_minimum_parallel_slots(self) -> None:
        result, payload = self.run_cli(
            [
                "delegation",
                "--session-id",
                "opencode-session",
                "--client-id",
                "opencode",
                "--work-class",
                "project-design",
                "--project-matched",
                "--native-subagents",
                "--parallel-subagents",
            ]
        )
        self.assertEqual(0, result)
        self.assertEqual(
            "native-parallel", payload["data"]["decision"]["selected_mode"]
        )
        self.assertEqual(2, payload["data"]["profile"]["max_parallel_agents"])

    def test_cli_validates_a_session_capability_profile(self) -> None:
        result, payload = self.run_cli(
            [
                "capabilities",
                "--session-id",
                "session-001",
                "--client-id",
                "claude-code",
                "--native-subagents",
                "--structured-results",
            ]
        )
        self.assertEqual(0, result)
        self.assertEqual("ok", payload["status"])
        self.assertEqual(
            "native-sequential", payload["data"]["profile"]["selected_mode"]
        )

    def test_cli_blocked_decision_has_nonzero_exit_code(self) -> None:
        result, payload = self.run_cli(
            [
                "delegation",
                "--session-id",
                "session-001",
                "--client-id",
                "codex",
                "--work-class",
                "project-analysis",
                "--project-matched",
            ]
        )
        self.assertEqual(3, result)
        self.assertEqual("blocked", payload["status"])
        self.assertFalse(payload["data"]["decision"]["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
