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

class Phase28ApplicationCliTests(unittest.TestCase):
    def test_local_first_assessment_and_cli(self):
        with tempfile.TemporaryDirectory() as raw:
            service = KrcnApplicationService(ROOT, LocalWorkspaceStore(Path(raw), OwnershipResolver.from_repository(ROOT)))
            response = service.execute(ServiceRequest(client_kind="cli", operation="team-runtime.assess", arguments={"machine_count": 1, "concurrent_worker_count": 4, "cross_machine_claim_required": False, "enterprise_needs": [], "migration_owner_assigned": False, "rollback_owner_assigned": False, "operating_budget_approved": False}))
            self.assertEqual("deferred", response.data["assessment"]["decision"])
            self.assertEqual("keep-local-first", response.data["next_stage"])
        parsed = build_parser().parse_args(["runtime", "team-assess", "--request-file", "request.json"])
        self.assertEqual("team-assess", parsed.runtime_command)

if __name__ == "__main__": unittest.main()
