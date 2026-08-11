from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "build_backend"))

import krcn_build_backend  # noqa: E402
from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_record(
    store: LocalWorkspaceStore,
    record_type: str,
    record_id: str,
    payload: dict,
) -> None:
    plan = store.prepare_put(
        record_type,
        record_id,
        payload,
        expected_revision=0,
    )
    authorization = authorize_mutation(
        plan.mutation,
        dry_run=DryRunEvidence(plan.mutation.plan_id, True),
        approval=ApprovalEvidence(
            plan.mutation.plan_id,
            f"existing-{record_type}-approval",
            True,
        ),
    )
    store.apply_put(plan, authorization)


class PhaseTwoCompletionTests(unittest.TestCase):
    def test_phase_two_baseline_is_complete_and_versioned(self) -> None:
        baseline = load_json(REPO_ROOT / ".ai" / "phase-2-baseline.json")
        schema = load_json(REPO_ROOT / "schemas" / "phase-baseline.schema.json")
        self.assertEqual("urn:krcn:schemas:phase-baseline:1", schema["$id"])
        self.assertEqual("ready", baseline["status"])
        self.assertEqual(10, baseline["completed_steps"])
        self.assertEqual(
            {
                "project.list",
                "project.inspect",
                "project.onboard",
                "project.rescan",
            },
            set(baseline["safe_operations"]),
        )
        self.assertTrue(baseline["guarantees"]["user_policy_preserved"])
        self.assertFalse(baseline["guarantees"]["source_content_mutated"])
        self.assertEqual("phase-3", baseline["next_phase"]["phase_id"])
        self.assertFalse(baseline["next_phase"]["implementation_started"])

    def test_phase_two_completion_and_phase_three_boundary_are_recorded(self) -> None:
        completion = REPO_ROOT / "docs" / "progress" / "PHASE-2-COMPLETION.md"
        boundary = (
            REPO_ROOT
            / "docs"
            / "specifications"
            / "PHASE-3-MERGE-BOUNDARY.md"
        )
        self.assertTrue(completion.is_file())
        self.assertTrue(boundary.is_file())
        self.assertIn(
            "Faz 2 - yerel çalışma alanı ve entegrasyon modeli tamamlandı",
            completion.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "The first slice is read-only",
            boundary.read_text(encoding="utf-8"),
        )
        current_work = load_json(REPO_ROOT / ".ai" / "current-work.json")
        self.assertEqual("phase-2", current_work["phase_id"])
        self.assertEqual("completed", current_work["status"])

    def test_wheel_installs_offline_and_exposes_phase_two_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel_directory = root / "wheel"
            target = root / "installed"
            filename = krcn_build_backend.build_wheel(str(wheel_directory))
            wheel = wheel_directory / filename
            environment = os.environ.copy()
            environment["PIP_NO_INDEX"] = "1"
            install = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--disable-pip-version-check",
                    "--target",
                    str(target),
                    str(wheel),
                ],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertEqual(0, install.returncode, install.stderr)
            imported = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {str(target)!r}); "
                        "from krcn_core.application import KrcnApplicationService; "
                        "from krcn_core.rescan import prepare_rescan; "
                        "print(KrcnApplicationService.__name__, prepare_rescan.__name__)"
                    ),
                ],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, imported.returncode, imported.stderr)
            self.assertEqual(
                "KrcnApplicationService prepare_rescan",
                imported.stdout.strip(),
            )

    def test_existing_workspace_records_are_preserved_during_onboarding(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_directory,
            tempfile.TemporaryDirectory() as source_directory,
        ):
            data_root = Path(data_directory)
            source_root = Path(source_directory)
            (source_root / "README.md").write_text(
                "New synthetic project\n",
                encoding="utf-8",
            )
            store = LocalWorkspaceStore(
                data_root,
                OwnershipResolver.from_repository(REPO_ROOT),
            )
            existing_workspace = {
                "schema_version": 1,
                "workspace_id": "existing-workspace",
                "project_refs": ["existing-project"],
                "policy_refs": ["database-read-only"],
                "metadata": {"owner_note": "preserve exactly"},
            }
            existing_project = {
                "schema_version": 1,
                "project_id": "existing-project",
                "name": "Existing Project",
                "description": "Preserved fixture",
                "source_refs": [],
                "technologies": [{"name": "Manual Tool", "category": "manual"}],
                "modules": [],
                "skill_refs": [],
                "status": "active",
            }
            existing_integration = {
                "schema_version": 1,
                "integration_id": "existing-integration",
                "adapter_id": "sample-adapter",
                "source_binding_ref": "existing-source",
                "status": "disabled",
                "configuration": {"region": "local"},
                "secret_refs": {"credential": "keyring://existing/credential"},
                "policy_refs": ["database-read-only"],
                "revision": 1,
            }
            apply_record(
                store,
                "workspaces",
                "existing-workspace",
                existing_workspace,
            )
            apply_record(
                store,
                "projects",
                "existing-project",
                existing_project,
            )
            apply_record(
                store,
                "integrations",
                "existing-integration",
                existing_integration,
            )
            policy_directory = data_root / "policies"
            policy_directory.mkdir()
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
                                    "evidence_ref": "existing-workspace-fixture",
                                },
                                "active": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            policy_before = policy_path.read_bytes()
            integration_before = store.read(
                "integrations",
                "existing-integration",
            )
            project_before = store.read("projects", "existing-project")
            arguments = {
                "workspace_id": "existing-workspace",
                "project_id": "new-project",
                "binding_id": "new-project-local",
                "project_name": "New Project",
                "description": "Compatibility fixture",
                "source_root": str(source_root),
                "policy_refs": [],
                "expected_workspace_revision": 1,
            }
            service = KrcnApplicationService(REPO_ROOT, store)
            planned = service.execute(
                ServiceRequest("sdk", "project.onboard", arguments)
            )
            service.execute(
                ServiceRequest(
                    "sdk",
                    "project.onboard",
                    arguments,
                    apply=True,
                    expected_plan_id=planned.data["plan"]["plan_id"],
                    approval_id="existing-workspace-approval",
                )
            )
            workspace_after = store.read("workspaces", "existing-workspace")
            self.assertEqual(
                ["existing-project", "new-project"],
                workspace_after.payload["project_refs"],
            )
            self.assertEqual(
                {"owner_note": "preserve exactly"},
                workspace_after.payload["metadata"],
            )
            self.assertEqual(project_before, store.read("projects", "existing-project"))
            self.assertEqual(
                integration_before,
                store.read("integrations", "existing-integration"),
            )
            self.assertEqual(policy_before, policy_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
