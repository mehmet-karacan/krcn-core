from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from krcn_core.application import KrcnApplicationService
from krcn_core.application_contract import ServiceRequest
from krcn_core.cli.app import build_parser
from krcn_core.home_layout import user_home_layout_bytes
from krcn_core.local_store import LocalWorkspaceStore
from krcn_core.mutation_gate import OwnershipResolver
from krcn_core.outbound_assurance import create_provider_assurance_profile
from krcn_core.provider_gate import create_provider_request
from krcn_core.worktree_sandbox import build_sandbox_host_profile


ROOT = Path(__file__).resolve().parents[1]
SHA = hashlib.sha256(b"phase-26").hexdigest()


class Phase26ApplicationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.home = base / ".krcn"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.store = LocalWorkspaceStore(self.home, OwnershipResolver.from_repository(ROOT))
        self.service = KrcnApplicationService(ROOT, self.store)
        self.repo = base / "repo"
        self.repo.mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        mail = "test" + "@" + "example.invalid"
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", f"user.email={mail}", "commit", "-q", "-m", "base"], check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_outbound_assessment_is_client_neutral_and_content_free(self) -> None:
        provider = create_provider_request(
            provider="reviewed-provider", endpoint="logical-endpoint",
            data_categories=("confidential-ip",), operation_scope="research",
            retention_assumptions="no-training", session_id="phase26-session", remote=True,
        )
        profile = create_provider_assurance_profile(
            profile_id="reviewed-provider-current", provider_id="reviewed-provider",
            observed_at="2026-08-17T10:00:00Z", valid_until="2026-08-18T10:00:00Z",
            accepted_categories=("confidential-ip",), retention_class="no-training",
            training_opt_out_verified=True, regional_processing_verified=True,
            canary_credential_test_passed=True, evidence_ref="evidence:provider-review",
            evidence_digest=SHA,
        )
        arguments = {
            "provider_request": {
                "schema_version": 1, "request_id": provider.request_id,
                "provider": provider.provider, "endpoint": provider.endpoint,
                "data_categories": list(provider.data_categories),
                "operation_scope": provider.operation_scope,
                "retention_assumptions": provider.retention_assumptions,
                "session_id": provider.session_id, "remote": provider.remote,
            },
            "provider_approval": {
                "request_id": provider.request_id, "session_id": provider.session_id,
                "approval_id": "approval-phase26", "approved": True,
            },
            "payload_digest": SHA,
            "data_categories": ["confidential-ip"],
            "evaluated_at": "2026-08-17T11:00:00Z",
            "assurance_profile": profile.as_dict(),
        }
        outputs = [
            self.service.execute(ServiceRequest(client, "outbound.assess", arguments)).as_dict()
            for client in ("cli", "sdk", "opencode")
        ]
        self.assertEqual(["ok", "ok", "ok"], [item["status"] for item in outputs])
        self.assertTrue(all(item["data"]["payload_disclosed"] is False for item in outputs))
        self.assertEqual(outputs[0]["data"], outputs[1]["data"])

    def test_sandbox_plan_is_read_only_redacted_and_blocks_weak_host(self) -> None:
        host = build_sandbox_host_profile(
            host_id="windows-host", os_family="windows", detached_worktree=True,
            path_isolation=True, environment_allowlist=True, network_default_deny=True,
            commit_push_blocked=True, junction_guard=True,
        )
        arguments = {
            "source_root": str(self.repo), "project_id": "fixture-project",
            "task_plan_id": SHA, "worker_step_id": "implementation",
            "validation_gate_id": SHA, "effect_claim_id": SHA,
            "allowed_paths": ["src"], "allowed_executables": ["python"],
            "allowed_env_keys": ["PYTHONPATH"], "host_profile": host.as_dict(),
        }
        response = self.service.execute(ServiceRequest("cli", "sandbox.plan", arguments))
        self.assertEqual("planned", response.status)
        self.assertFalse(response.data["source_path_disclosed"])
        self.assertFalse(response.data["apply_supported"])
        weak = dict(arguments)
        weak["host_profile"] = build_sandbox_host_profile(
            host_id="weak-host", os_family="windows", detached_worktree=True,
            path_isolation=True, environment_allowlist=True, network_default_deny=False,
            commit_push_blocked=True, junction_guard=True,
        ).as_dict()
        blocked = self.service.execute(ServiceRequest("cli", "sandbox.plan", weak))
        self.assertEqual("blocked", blocked.status)

    def test_cli_exposes_readable_outbound_and_sandbox_routes(self) -> None:
        parser = build_parser()
        outbound = parser.parse_args(["outbound", "assess", "--request-file", "request.json"])
        sandbox = parser.parse_args(["sandbox", "plan", "--request-file", "request.json"])
        self.assertEqual("assess", outbound.outbound_command)
        self.assertEqual("plan", sandbox.sandbox_command)
        self.assertEqual("text", outbound.format)
        self.assertEqual("text", sandbox.format)


if __name__ == "__main__":
    unittest.main()
