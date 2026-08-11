from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    OPERATIONS,
    ServiceRequest,
    create_application_service,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.portable_backup import prepare_portable_backup  # noqa: E402


CLIENTS = ("cli", "sdk", "mcp", "plugin", "codex", "claude", "future-client")


class PortabilityClientParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.user_home = root / "user-home"
        self.archive = root / "portable.zip"
        (self.user_home / "policies").mkdir(parents=True)
        (self.user_home / "policies" / "select-only.json").write_text(
            json.dumps({"effect": "deny", "operation": "delete"}),
            encoding="utf-8",
        )
        self.service = create_application_service(REPO_ROOT, self.user_home)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_clients_receive_the_same_portability_plan(self) -> None:
        plans = []
        for client in CLIENTS:
            response = self.service.execute(
                ServiceRequest(
                    client,
                    "portability.backup",
                    {"archive_path": str(self.archive)},
                )
            )
            self.assertEqual("planned", response.status)
            plans.append(response.data["plan"])
        self.assertTrue(all(plan == plans[0] for plan in plans))

    def test_application_schema_exposes_every_runtime_operation(self) -> None:
        schema = json.loads(
            (REPO_ROOT / "schemas" / "application-request.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(OPERATIONS, set(schema["properties"]["operation"]["enum"]))

    def test_backup_identity_is_independent_from_physical_home_and_source_paths(self) -> None:
        root = Path(self.temporary.name)
        first_home = root / "windows-logical-home"
        second_home = root / "macos-logical-home"
        first_source = root / "windows-project-location"
        second_source = root / "macos-project-location"
        for home, source in ((first_home, first_source), (second_home, second_source)):
            source.mkdir()
            store = LocalWorkspaceStore(home, OwnershipResolver.from_repository(REPO_ROOT))
            payload = {
                "schema_version": 1,
                "binding_id": "portable-project-local",
                "source_id": "portable-project",
                "source_kind": "project",
                "locator": {"kind": "local-path", "value": str(source)},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": [],
                "revision": 1,
            }
            write = store.prepare_put(
                "source-bindings",
                "portable-project-local",
                payload,
                expected_revision=0,
            )
            store.apply_put(
                write,
                authorize_mutation(
                    write.mutation,
                    dry_run=DryRunEvidence(write.mutation.plan_id, True),
                    approval=ApprovalEvidence(write.mutation.plan_id, "setup", True),
                ),
            )
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        first = prepare_portable_backup(first_home, root / "first.zip", ownership)
        second = prepare_portable_backup(second_home, root / "second.zip", ownership)
        self.assertEqual(first.backup_id, second.backup_id)
        self.assertTrue(all("\\" not in item.path for item in first.entries))


if __name__ == "__main__":
    unittest.main()
