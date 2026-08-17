from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.adaptive_routing import (  # noqa: E402
    create_route_request,
    load_adaptive_routing_policy,
)
from krcn_core.application import KrcnApplicationService  # noqa: E402
from krcn_core.application_contract import (  # noqa: E402
    ApplicationServiceError,
    ServiceRequest,
)
from krcn_core.cli.app import build_parser, main as cli_main  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


def digest(character: str) -> str:
    return character * 64


class AdaptiveRoutingApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / ".krcn"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.store = LocalWorkspaceStore(
            self.home, OwnershipResolver.from_repository(REPO_ROOT)
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)
        policy = load_adaptive_routing_policy(REPO_ROOT)
        self.route_request = create_route_request(
            policy,
            request_id="request-one",
            correlation_id="correlation-one",
            client_id="codex-desktop",
            project_id="project-one",
            work_item_id="work-one",
            source_revision_digest=digest("a"),
            intent_digest=digest("b"),
            context_digest=digest("c"),
            task_type="analysis",
            risk_level="low",
            mutation_level="none",
            data_classification="internal",
            estimated_work_units=4,
            context_size_tokens=8000,
            context_pressure_millis=10,
            independent_subproblem_count=2,
            dependency_depth=0,
            required_capabilities=["source-read"],
            available_capabilities=["source-read"],
            deterministic_validator_available=True,
            verifier_available=True,
            sandbox_available=True,
            resources=[
                {
                    "node_id": "inspect-source",
                    "resource_ref": "path:project-one/src",
                    "access": "read",
                },
                {
                    "node_id": "inspect-tests",
                    "resource_ref": "path:project-one/tests",
                    "access": "read",
                },
            ],
            approval_required=False,
            approval_verified=False,
            pending_claim_without_receipt=False,
            input_tokens=12000,
            output_tokens=4000,
            cost_microunits=1000,
            latency_seconds=120,
            maximum_concurrency=2,
            remote_required=False,
            provider_assurance_available=False,
            source_revision_current=True,
            authoritative_context_required=True,
        ).as_dict()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_application_decide_and_explain_are_read_only_and_transport_neutral(self) -> None:
        decisions = []
        for client in ("cli", "sdk", "mcp", "codex", "claude", "opencode"):
            response = self.service.execute(
                ServiceRequest(
                    client,
                    "routing.decide",
                    {"route_request": self.route_request},
                )
            )
            self.assertEqual("ok", response.status)
            self.assertEqual("parallel-dag", response.data["decision"]["selected"]["route_mode"])
            self.assertTrue(response.data["shadow_only"])
            self.assertFalse(response.data["behavior_changed"])
            self.assertFalse(response.data["persisted"])
            self.assertFalse(response.data["grants_authority"])
            decisions.append(response.data["decision"]["decision_digest"])
        self.assertEqual(1, len(set(decisions)))
        explained = self.service.execute(
            ServiceRequest(
                "cli",
                "routing.explain",
                {
                    "route_request": self.route_request,
                    "observed_route": "delegated-dag",
                },
            )
        )
        self.assertEqual("matched", explained.data["comparison"]["comparison_status"])
        self.assertFalse(explained.data["comparison"]["behavior_changed"])
        self.assertEqual([], [path for path in self.home.rglob("*") if path.name != "layout.json"])

    def test_application_rejects_apply_and_unknown_arguments(self) -> None:
        with self.assertRaisesRegex(ApplicationServiceError, "read-only"):
            self.service.execute(
                ServiceRequest(
                    "cli",
                    "routing.decide",
                    {"route_request": self.route_request},
                    apply=True,
                )
            )
        with self.assertRaisesRegex(ApplicationServiceError, "arguments"):
            self.service.execute(
                ServiceRequest(
                    "cli",
                    "routing.decide",
                    {"route_request": self.route_request, "authority": True},
                )
            )

    def test_cli_parser_and_text_renderer_are_readable(self) -> None:
        parser = build_parser()
        parsed = parser.parse_args(
            ["routing", "decide", "--request-file", "route.json"]
        )
        self.assertEqual("routing", parsed.command)
        self.assertEqual("decide", parsed.routing_command)

        request_file = self.root / "route.json"
        request_file.write_text(
            json.dumps(
                {
                    "route_request": self.route_request,
                    "observed_route": "delegated-dag",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        output = StringIO()
        with redirect_stdout(output):
            result = cli_main(
                [
                    "routing",
                    "explain",
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(self.home),
                    "--request-file",
                    str(request_file),
                    "--format",
                    "text",
                ]
            )
        self.assertEqual(0, result)
        rendered = output.getvalue()
        self.assertIn("Gölge rota", rendered)
        self.assertIn("parallel-dag", rendered)
        self.assertIn("matched", rendered)
        self.assertIn("verilmedi", rendered)


if __name__ == "__main__":
    unittest.main()
