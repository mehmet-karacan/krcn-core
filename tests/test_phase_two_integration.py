from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.adapter_gate import AdapterGateError  # noqa: E402
from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.integrations import IntegrationMetadataError  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)


def directory_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        content = path.read_bytes()
        result[path.relative_to(root).as_posix()] = (
            path.stat().st_mtime_ns,
            hashlib.sha256(content).hexdigest(),
        )
    return result


class PhaseTwoIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_temp = tempfile.TemporaryDirectory()
        self.data_temp = tempfile.TemporaryDirectory()
        self.source_root = Path(self.source_temp.name)
        self.data_root = Path(self.data_temp.name)
        (self.source_root / "src").mkdir()
        (self.source_root / "src" / "main.py").write_text(
            "print('sample')\n",
            encoding="utf-8",
        )
        (self.source_root / "pyproject.toml").write_text(
            "[project]\nname='sample'\n",
            encoding="utf-8",
        )
        self.store = LocalWorkspaceStore(
            self.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)
        self.onboarding_arguments = {
            "workspace_id": "sample-workspace",
            "project_id": "sample-project",
            "binding_id": "sample-project-local",
            "project_name": "Sample Project",
            "description": "Hermetic integration fixture",
            "source_root": str(self.source_root),
            "policy_refs": [],
            "expected_workspace_revision": 0,
        }

    def tearDown(self) -> None:
        self.source_temp.cleanup()
        self.data_temp.cleanup()

    def _apply_onboarding(self):
        planned = self.service.execute(
            ServiceRequest("codex", "project.onboard", self.onboarding_arguments)
        )
        return self.service.execute(
            ServiceRequest(
                "codex",
                "project.onboard",
                self.onboarding_arguments,
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
                approval_id="integration-onboarding-approval",
            )
        )

    def _apply_rescan(self):
        arguments = {"project_id": "sample-project"}
        planned = self.service.execute(
            ServiceRequest("claude", "project.rescan", arguments)
        )
        return self.service.execute(
            ServiceRequest(
                "claude",
                "project.rescan",
                arguments,
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
                approval_id="integration-rescan-approval",
            )
        )

    def _write_database_policy(self) -> Path:
        policy_directory = self.data_root / "policies"
        policy_directory.mkdir(parents=True)
        policy_path = policy_directory / "database-read-only.json"
        policy_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy_id": "database-read-only",
                    "scope": {"kind": "global", "ref": None},
                    "revision": 1,
                    "rules": [
                        {
                            "rule_id": "deny-database-delete",
                            "resource_type": "database",
                            "operations": ["delete"],
                            "effect": "deny",
                            "constraints": {},
                            "provenance": {
                                "kind": "explicit-user",
                                "evidence_ref": "integration-fixture",
                            },
                            "active": True,
                        }
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return policy_path

    def test_end_to_end_flow_is_offline_read_only_and_redacted(self) -> None:
        policy_path = self._write_database_policy()
        policy_before = policy_path.read_bytes()
        source_before = directory_snapshot(self.source_root)
        responses = []
        with patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network access is prohibited"),
        ):
            responses.append(self._apply_onboarding())
            responses.append(self._apply_rescan())
            responses.append(
                self.service.execute(ServiceRequest("mcp", "project.list", {}))
            )
            responses.append(
                self.service.execute(
                    ServiceRequest(
                        "plugin",
                        "project.inspect",
                        {"project_id": "sample-project"},
                    )
                )
            )
        output = json.dumps([item.as_dict() for item in responses])
        self.assertEqual(source_before, directory_snapshot(self.source_root))
        self.assertEqual(policy_before, policy_path.read_bytes())
        self.assertNotIn(str(self.source_root), output)
        self.assertNotIn(str(self.data_root), output)
        self.assertIsNotNone(
            self.store.read("source-states", "sample-project-local")
        )

    def test_rescan_rejects_missing_binding_capability_without_writes(self) -> None:
        self._apply_onboarding()
        binding = self.store.read("source-bindings", "sample-project-local")
        payload = dict(binding.payload)
        payload["capabilities"] = ["read"]
        payload["revision"] = 2
        write_plan = self.store.prepare_put(
            "source-bindings",
            "sample-project-local",
            payload,
            expected_revision=binding.revision,
        )
        authorization = authorize_mutation(
            write_plan.mutation,
            dry_run=DryRunEvidence(write_plan.mutation.plan_id, True),
            approval=ApprovalEvidence(
                write_plan.mutation.plan_id,
                "binding-update-approval",
                True,
            ),
        )
        self.store.apply_put(write_plan, authorization)
        with self.assertRaisesRegex(AdapterGateError, "missing required capabilities"):
            self.service.execute(
                ServiceRequest(
                    "future-client",
                    "project.rescan",
                    {"project_id": "sample-project"},
                )
            )
        self.assertIsNone(
            self.store.read("source-states", "sample-project-local")
        )

    def test_global_deny_policy_blocks_discovery_before_source_read(self) -> None:
        self._apply_onboarding()
        policy_directory = self.data_root / "policies"
        policy_directory.mkdir(parents=True)
        (policy_directory / "deny-discovery.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy_id": "deny-discovery",
                    "scope": {"kind": "global", "ref": None},
                    "revision": 1,
                    "rules": [
                        {
                            "rule_id": "deny-source-discovery",
                            "resource_type": "source",
                            "operations": ["discover"],
                            "effect": "deny",
                            "constraints": {},
                            "provenance": {
                                "kind": "explicit-user",
                                "evidence_ref": "integration-fixture",
                            },
                            "active": True,
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        with patch(
            "krcn_core.application.discover_local_source",
            side_effect=AssertionError("discovery must not run after policy denial"),
        ) as discovery:
            with self.assertRaisesRegex(AdapterGateError, "denied"):
                self.service.execute(
                    ServiceRequest(
                        "sdk",
                        "project.rescan",
                        {"project_id": "sample-project"},
                    )
                )
        discovery.assert_not_called()
        self.assertIsNone(
            self.store.read("source-states", "sample-project-local")
        )

    def test_literal_secret_is_rejected_before_integration_record_plan(self) -> None:
        payload = {
            "schema_version": 1,
            "integration_id": "sample-github",
            "adapter_id": "github",
            "source_binding_ref": "sample-project-local",
            "status": "active",
            "configuration": {"access_token": "literal-value"},
            "secret_refs": {},
            "policy_refs": [],
            "revision": 1,
        }
        with self.assertRaisesRegex(IntegrationMetadataError, "secret-like"):
            self.store.prepare_put(
                "integrations",
                "sample-github",
                payload,
                expected_revision=0,
            )
        self.assertEqual((), self.store.list_records("integrations"))


if __name__ == "__main__":
    unittest.main()
