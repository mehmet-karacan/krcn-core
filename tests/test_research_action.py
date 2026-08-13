from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.cli.app import main as cli_main  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)


class ResearchActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.project_root = self.root / "projects" / "gpu-fusion"
        self.project_root.mkdir(parents=True)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        self._put(
            "source-bindings",
            "gpu-fusion-local",
            {
                "schema_version": 1,
                "binding_id": "gpu-fusion-local",
                "source_id": "gpu-fusion",
                "source_kind": "project",
                "locator": {"kind": "local-path", "value": str(self.project_root)},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": [],
                "revision": 1,
            },
        )
        self._put(
            "projects",
            "gpu-fusion",
            {
                "schema_version": 1,
                "project_id": "gpu-fusion",
                "name": "GPU Fusion",
                "description": "Synthetic project",
                "source_refs": ["gpu-fusion-local"],
                "status": "active",
            },
        )
        self._put(
            "source-states",
            "gpu-fusion-local",
            {
                "schema_version": 1,
                "binding_id": "gpu-fusion-local",
                "binding_revision": 1,
                "root_digest": hashlib.sha256(b"[]").hexdigest(),
                "files": [],
                "technologies": ["Java"],
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _put(self, record_type: str, record_id: str, payload: dict) -> None:
        plan = self.store.prepare_put(record_type, record_id, payload, expected_revision=0)
        self.store.apply_put(
            plan,
            authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, True),
                approval=ApprovalEvidence(plan.mutation.plan_id, "fixture", True),
            ),
        )

    def _request(
        self,
        text: str,
        *,
        client_kind: str = "codex",
        context: str | None = None,
    ) -> ServiceRequest:
        arguments = {
            "request_text": text,
            "working_directory": str(self.project_root),
        }
        if context is not None:
            arguments["context_text"] = context
        return ServiceRequest(client_kind, "research.action", arguments)

    def test_project_request_prepares_deep_research_without_provider_call(self) -> None:
        service = create_application_service(REPO_ROOT, self.home)
        response = service.execute(
            self._request("Bu projedeki rapor hatasını detaylı bir şekilde araştır.")
        )
        self.assertEqual("planned", response.status)
        self.assertEqual("deep", response.data["route"]["mode"])
        self.assertEqual("gpu-fusion", response.data["route"]["project_id"])
        self.assertEqual("project", response.data["plan"]["scope"])
        self.assertEqual(0, response.data["plan"]["provider_calls_planned"])
        self.assertFalse(response.data["route"]["authority_granted"])
        self.assertFalse(response.data["automatic_implementation"])
        self.assertNotIn(str(self.project_root), json.dumps(response.as_dict()))

    def test_deictic_request_uses_context_and_missing_context_is_preserved(self) -> None:
        service = create_application_service(REPO_ROOT, self.home)
        missing = service.execute(self._request("Bunu detaylı araştır."))
        self.assertEqual("choice-required", missing.status)
        self.assertTrue(missing.data["route"]["needs_context"])
        self.assertTrue(missing.data["request_preserved"])
        ready = service.execute(
            self._request(
                "Bunu detaylı araştır.",
                context="Kurumsal SMS hazine payı oranının yetkili kaynağını doğrula.",
            )
        )
        self.assertEqual("planned", ready.status)
        self.assertFalse(ready.data["route"]["needs_context"])

    def test_clients_receive_the_same_natural_research_plan(self) -> None:
        service = create_application_service(REPO_ROOT, self.home)
        plan_ids = {
            service.execute(
                self._request(
                    "Rapor hatasının kök nedenini araştır ve planla.",
                    client_kind=client,
                )
            ).data["plan"]["plan_id"]
            for client in ("codex", "claude", "opencode")
        }
        self.assertEqual(1, len(plan_ids))

    def test_cli_ask_prints_a_short_human_research_route(self) -> None:
        output = io.StringIO()
        previous = Path.cwd()
        try:
            os.chdir(self.project_root)
            with redirect_stdout(output):
                exit_code = cli_main(
                    [
                        "ask",
                        "Bu projedeki rapor hatasını detaylı araştır",
                        "--repo",
                        str(REPO_ROOT),
                        "--data-root",
                        str(self.home),
                    ]
                )
        finally:
            os.chdir(previous)
        self.assertEqual(0, exit_code)
        rendered = output.getvalue()
        self.assertIn("Araştırma rotası: detaylı araştırma", rendered)
        self.assertIn("Work Item seçimi", rendered)
        self.assertNotIn('"schema_version"', rendered)

    def test_global_cli_route_describes_operator_or_client_execution(self) -> None:
        output = io.StringIO()
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with redirect_stdout(output):
                exit_code = cli_main(
                    [
                        "ask",
                        "Spring Boot ile Quarkus'u karşılaştır",
                        "--repo",
                        str(REPO_ROOT),
                        "--data-root",
                        str(self.home),
                    ]
                )
        finally:
            os.chdir(previous)
        self.assertEqual(0, exit_code)
        self.assertIn("operatör aracılı araştırma", output.getvalue())

    def test_explicit_unknown_project_never_falls_back_to_global(self) -> None:
        service = create_application_service(REPO_ROOT, self.home)
        response = service.execute(
            ServiceRequest(
                "sdk",
                "research.action",
                {
                    "request_text": "Python packaging değişikliklerini araştır",
                    "working_directory": str(self.root),
                    "project_id": "missing-project",
                },
            )
        )
        self.assertEqual("choice-required", response.status)
        self.assertEqual("project-not-found", response.data["selection_reason"])
        self.assertIsNone(response.data["plan"])


if __name__ == "__main__":
    unittest.main()
