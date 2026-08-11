from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402


def source_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    snapshot = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        content = path.read_bytes()
        snapshot[path.relative_to(root).as_posix()] = (
            path.stat().st_mtime_ns,
            hashlib.sha256(content).hexdigest(),
        )
    return snapshot


class ApplicationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_temp = tempfile.TemporaryDirectory()
        self.data_temp = tempfile.TemporaryDirectory()
        self.source_root = Path(self.source_temp.name)
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
            Path(self.data_temp.name),
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)
        self.arguments = {
            "workspace_id": "sample-workspace",
            "project_id": "sample-project",
            "binding_id": "sample-project-local",
            "project_name": "Sample Project",
            "description": "Synthetic fixture",
            "source_root": str(self.source_root),
            "policy_refs": [],
            "expected_workspace_revision": 0,
        }

    def tearDown(self) -> None:
        self.source_temp.cleanup()
        self.data_temp.cleanup()

    def _onboard(self) -> None:
        dry_run = self.service.execute(
            ServiceRequest("cli", "project.onboard", self.arguments)
        )
        plan_id = dry_run.data["plan"]["plan_id"]
        self.service.execute(
            ServiceRequest(
                "cli",
                "project.onboard",
                self.arguments,
                apply=True,
                expected_plan_id=plan_id,
                approval_id="onboarding-approval",
            )
        )

    def test_clients_receive_the_same_plan_and_security_behavior(self) -> None:
        plans = []
        for client_kind in (
            "cli",
            "sdk",
            "mcp",
            "plugin",
            "agent",
            "codex",
            "claude",
            "future-client",
        ):
            response = self.service.execute(
                ServiceRequest(client_kind, "project.onboard", self.arguments)
            )
            plans.append(response.data["plan"])
        self.assertTrue(all(plan == plans[0] for plan in plans))

    def test_onboarding_requires_prior_exact_plan_and_explicit_approval(self) -> None:
        before = source_snapshot(self.source_root)
        dry_run = self.service.execute(
            ServiceRequest("cli", "project.onboard", self.arguments)
        )
        self.assertEqual("planned", dry_run.status)
        self.assertEqual((), self.store.list_records("projects"))
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan"):
            self.service.execute(
                ServiceRequest(
                    "cli",
                    "project.onboard",
                    self.arguments,
                    apply=True,
                    expected_plan_id="0" * 64,
                    approval_id="onboarding-approval",
                )
            )
        self.assertEqual((), self.store.list_records("projects"))
        plan_id = dry_run.data["plan"]["plan_id"]
        with self.assertRaisesRegex(ApplicationServiceError, "approval"):
            self.service.execute(
                ServiceRequest(
                    "cli",
                    "project.onboard",
                    self.arguments,
                    apply=True,
                    expected_plan_id=plan_id,
                )
            )
        applied = self.service.execute(
            ServiceRequest(
                "cli",
                "project.onboard",
                self.arguments,
                apply=True,
                expected_plan_id=plan_id,
                approval_id="onboarding-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertEqual(before, source_snapshot(self.source_root))

    def test_list_and_inspect_redact_the_source_locator(self) -> None:
        self._onboard()
        listed = self.service.execute(ServiceRequest("sdk", "project.list", {}))
        inspected = self.service.execute(
            ServiceRequest(
                "plugin",
                "project.inspect",
                {"project_id": "sample-project"},
            )
        )
        output = json.dumps(
            {"listed": listed.as_dict(), "inspected": inspected.as_dict()}
        )
        self.assertNotIn(str(self.source_root), output)
        self.assertEqual("sample-project", listed.data["projects"][0]["project_id"])
        binding = inspected.data["source_bindings"][0]
        self.assertEqual("local-path", binding["locator_kind"])
        self.assertNotIn("locator", binding)

    def test_rescan_uses_the_same_two_step_contract(self) -> None:
        self._onboard()
        before = source_snapshot(self.source_root)
        dry_run = self.service.execute(
            ServiceRequest(
                "mcp",
                "project.rescan",
                {"project_id": "sample-project"},
            )
        )
        self.assertEqual("planned", dry_run.status)
        self.assertIsNone(
            self.store.read("source-states", "sample-project-local")
        )
        plan_id = dry_run.data["plan"]["plan_id"]
        applied = self.service.execute(
            ServiceRequest(
                "mcp",
                "project.rescan",
                {"project_id": "sample-project"},
                apply=True,
                expected_plan_id=plan_id,
                approval_id="rescan-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertIsNotNone(
            self.store.read("source-states", "sample-project-local")
        )
        self.assertEqual(before, source_snapshot(self.source_root))
        self.assertNotIn(str(self.source_root), json.dumps(applied.as_dict()))


if __name__ == "__main__":
    unittest.main()
