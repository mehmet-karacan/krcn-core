from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from krcn_core.application import KrcnApplicationService
from krcn_core.application_contract import ServiceRequest
from krcn_core.cli.app import build_parser
from krcn_core.local_store import LocalWorkspaceStore
from krcn_core.mutation_gate import OwnershipResolver

ROOT = Path(__file__).resolve().parents[1]

class Phase27ApplicationCliTests(unittest.TestCase):
    def test_route_enforcement_service_and_cli_surface(self):
        with tempfile.TemporaryDirectory() as raw:
            store = LocalWorkspaceStore(Path(raw), OwnershipResolver.from_repository(ROOT))
            response = KrcnApplicationService(ROOT, store).execute(ServiceRequest(client_kind="cli", operation="routing.enforcement", arguments={"current_stage": "shadow", "requested_stage": "advisory", "observation_count": 100, "mismatch_count": 0, "project_opt_in": False}))
            self.assertEqual("ok", response.status)
            self.assertFalse(response.data["authority_granted"])
        parser = build_parser()
        parsed = parser.parse_args(["implementation", "plan", "--request-file", "request.json"])
        self.assertEqual(("implementation", "plan"), (parsed.command, parsed.implementation_command))
        routed = parser.parse_args(["routing", "enforcement", "--request-file", "request.json"])
        self.assertEqual("enforcement", routed.routing_command)

    def test_missing_delivery_host_blocks_before_read_or_apply(self):
        with tempfile.TemporaryDirectory() as raw:
            store = LocalWorkspaceStore(Path(raw), OwnershipResolver.from_repository(ROOT))
            service = KrcnApplicationService(ROOT, store)
            with self.assertRaisesRegex(ValueError, "host is unavailable"):
                service.execute(ServiceRequest(client_kind="cli", operation="implementation.plan", arguments={"project_id": "fixture-project", "work_item_id": "work", "task_plan_id": "a" * 64, "report_ref": "report.md", "artifact_id": "b" * 64, "test_specs": [{"test_id": "unit", "command_digest": "c" * 64}], "execution_trace_ref": "traces/run"}))

if __name__ == "__main__": unittest.main()
