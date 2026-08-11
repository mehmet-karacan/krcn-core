from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import ServiceRequest, create_application_service  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.policies import evaluate_policies, load_user_policies  # noqa: E402


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def write_project(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text(
        "print('portable project')\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[project]\nname='portable-project'\n",
        encoding="utf-8",
    )


class PhaseSixIntegrationTests(unittest.TestCase):
    def test_backup_restore_and_rebind_preserve_policy_without_copying_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_source = root / "projects" / "original"
            recovered_source = root / "recovered-projects" / "portable"
            original_home = root / "krcn-user-home"
            restored_home = root / "restored-krcn-user-home"
            archive = root / "recovery" / "krcn-portable.zip"
            write_project(original_source)
            write_project(recovered_source)
            policy_directory = original_home / "policies"
            policy_directory.mkdir(parents=True)
            policy_payload = {
                "schema_version": 1,
                "policy_id": "database-select-only",
                "scope": {"kind": "project", "ref": "portable-project"},
                "revision": 1,
                "rules": [
                    {
                        "rule_id": "deny-delete",
                        "resource_type": "database",
                        "operations": ["delete"],
                        "effect": "deny",
                        "constraints": {"allowed_operations": ["select"]},
                        "provenance": {"kind": "explicit-user"},
                        "active": True,
                    }
                ],
            }
            policy_path = policy_directory / "database-select-only.json"
            policy_path.write_text(
                json.dumps(policy_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            secret_directory = original_home / "secrets"
            secret_directory.mkdir()
            (secret_directory / "provider.txt").write_text(
                "synthetic-local-only-value",
                encoding="utf-8",
            )
            service = create_application_service(REPO_ROOT, original_home)
            onboarding_arguments = {
                "workspace_id": "portable-workspace",
                "project_id": "portable-project",
                "binding_id": "portable-project-local",
                "project_name": "Portable Project",
                "description": "Synthetic Phase 6 recovery fixture",
                "source_root": str(original_source),
                "policy_refs": ["database-select-only"],
                "expected_workspace_revision": 0,
            }
            onboarding = service.execute(
                ServiceRequest("codex", "project.onboard", onboarding_arguments)
            )
            service.execute(
                ServiceRequest(
                    "codex",
                    "project.onboard",
                    onboarding_arguments,
                    apply=True,
                    expected_plan_id=onboarding.data["plan"]["plan_id"],
                    approval_id="onboarding-approval",
                )
            )
            rescan_arguments = {"project_id": "portable-project"}
            rescan = service.execute(
                ServiceRequest("plugin", "project.rescan", rescan_arguments)
            )
            service.execute(
                ServiceRequest(
                    "plugin",
                    "project.rescan",
                    rescan_arguments,
                    apply=True,
                    expected_plan_id=rescan.data["plan"]["plan_id"],
                    approval_id="rescan-approval",
                )
            )
            original_before = snapshot(original_source)
            recovered_before = snapshot(recovered_source)
            backup_arguments = {"archive_path": str(archive)}
            backup = service.execute(
                ServiceRequest("mcp", "portability.backup", backup_arguments)
            )
            service.execute(
                ServiceRequest(
                    "mcp",
                    "portability.backup",
                    backup_arguments,
                    apply=True,
                    expected_plan_id=backup.data["plan"]["plan_id"],
                    approval_id="backup-approval",
                )
            )
            restored_service = create_application_service(REPO_ROOT, restored_home)
            restore_arguments = {"archive_path": str(archive)}
            restore = restored_service.execute(
                ServiceRequest("claude", "portability.restore", restore_arguments)
            )
            restored = restored_service.execute(
                ServiceRequest(
                    "claude",
                    "portability.restore",
                    restore_arguments,
                    apply=True,
                    expected_plan_id=restore.data["plan"]["plan_id"],
                    approval_id="restore-approval",
                )
            )
            self.assertEqual(1, restored.data["rebind_required_count"])
            restored_store = LocalWorkspaceStore(
                restored_home,
                OwnershipResolver.from_repository(REPO_ROOT),
            )
            unbound = restored_store.read("source-bindings", "portable-project-local")
            self.assertEqual("unbound", unbound.payload["locator"]["kind"])
            rebind_arguments = {
                "project_id": "portable-project",
                "candidate_root": str(recovered_source),
            }
            rebind = restored_service.execute(
                ServiceRequest("future-client", "project.rebind", rebind_arguments)
            )
            restored_service.execute(
                ServiceRequest(
                    "future-client",
                    "project.rebind",
                    rebind_arguments,
                    apply=True,
                    expected_plan_id=rebind.data["plan"]["plan_id"],
                    approval_id="rebind-approval",
                )
            )
            rebound = restored_store.read("source-bindings", "portable-project-local")
            self.assertEqual("local-path", rebound.payload["locator"]["kind"])
            self.assertEqual(str(recovered_source.resolve()), rebound.payload["locator"]["value"])
            policies = load_user_policies(restored_home / "policies")
            decision = evaluate_policies(
                policies,
                resource_type="database",
                operation="delete",
                scope_refs={"project": "portable-project"},
            )
            self.assertEqual("deny", decision.effect)
            self.assertEqual(original_before, snapshot(original_source))
            self.assertEqual(recovered_before, snapshot(recovered_source))
            self.assertFalse((restored_home / "secrets" / "provider.txt").exists())
            self.assertFalse((restored_home / "portable-project").exists())

    def test_local_clean_clone_doctor_pull_and_merge_regressions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "clean-core"
            cloned = subprocess.run(
                ["git", "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(clone)],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, cloned.returncode, cloned.stderr)
            self.assertFalse((clone / ".krcn").exists())
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            for command in (
                [sys.executable, "tools/verify_repository.py"],
                [sys.executable, "tools/krcn.py", "doctor"],
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "tests.test_merge_service",
                    "tests.test_phase_three_completion",
                ],
                ["git", "pull", "--ff-only", "--quiet"],
            ):
                result = subprocess.run(
                    command,
                    cwd=clone,
                    capture_output=True,
                    check=False,
                    text=True,
                    encoding="utf-8",
                    env=environment,
                )
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
