from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.installation import InstallationState, ManagedFile  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.release import manifest_sha256  # noqa: E402


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class MergeApplicationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installation_temp = tempfile.TemporaryDirectory()
        self.release_temp = tempfile.TemporaryDirectory()
        self.root = Path(self.installation_temp.name)
        self.release = Path(self.release_temp.name)
        self.old_readme = b"Old readme\n"
        self.new_readme = b"New readme\n"
        self.new_module = b"print('new')\n"
        (self.root / "README.md").write_bytes(self.old_readme)
        runtime = self.root / ".krcn" / "runtime"
        runtime.mkdir(parents=True)
        self.state_path = runtime / "installation-state.json"
        self.state = InstallationState(
            installation_id="service-installation",
            core_version="0.1.0",
            release_id="krcn-core-0.1.0",
            source_commit="a" * 40,
            managed_files=(
                ManagedFile(
                    "README.md",
                    sha256(self.old_readme),
                    len(self.old_readme),
                ),
            ),
            schema_versions={},
            completed_migrations=(),
            pending_derived_actions=(),
            revision=1,
        )
        self.state_path.write_text(
            json.dumps(self.state.as_payload(), sort_keys=True),
            encoding="utf-8",
        )
        payload = self.release / "payload"
        (payload / "src").mkdir(parents=True)
        (payload / "README.md").write_bytes(self.new_readme)
        (payload / "src" / "new.py").write_bytes(self.new_module)
        self.manifest = {
            "schema_ref": "schemas/release-manifest.schema.json",
            "schema_version": 1,
            "release_id": "krcn-core-0.2.0",
            "core_version": "0.2.0",
            "compatibility": {
                "minimum_core_version": "0.1.0",
                "maximum_core_version": "0.1.0",
            },
            "source_commit": "b" * 40,
            "files": [
                {
                    "path": "README.md",
                    "operation": "upsert",
                    "sha256": sha256(self.new_readme),
                    "size": len(self.new_readme),
                },
                {
                    "path": "src/new.py",
                    "operation": "upsert",
                    "sha256": sha256(self.new_module),
                    "size": len(self.new_module),
                },
            ],
            "migrations": [],
            "derived_actions": [],
        }
        (self.release / "release-manifest.json").write_text(
            json.dumps(self.manifest, sort_keys=True),
            encoding="utf-8",
        )
        self.trusted_digest = manifest_sha256(self.manifest)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.root / ".krcn", self.ownership)
        self.service = KrcnApplicationService(REPO_ROOT, self.store)
        self.release_arguments = {
            "installation_root": str(self.root),
            "release_root": str(self.release),
            "trusted_manifest_sha256": self.trusted_digest,
        }

    def tearDown(self) -> None:
        self.installation_temp.cleanup()
        self.release_temp.cleanup()

    @staticmethod
    def _run_cli(arguments: list[str]) -> tuple[int, str, str]:
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = main(arguments)
        return result, output.getvalue(), error.getvalue()

    def test_all_clients_receive_the_same_merge_plan(self) -> None:
        plans = []
        for client_kind in (
            "cli",
            "sdk",
            "mcp",
            "plugin",
            "agent",
            "codex",
            "claude",
        ):
            response = self.service.execute(
                ServiceRequest(
                    client_kind,
                    "release.merge",
                    self.release_arguments,
                )
            )
            self.assertEqual("planned", response.status)
            plans.append(response.data["plan"])
        self.assertTrue(all(plan == plans[0] for plan in plans))
        self.assertNotIn(str(self.root), json.dumps(plans[0]))
        self.assertNotIn(str(self.release), json.dumps(plans[0]))

    def test_shared_service_inspects_merges_verifies_and_rolls_back(self) -> None:
        inspection = self.service.execute(
            ServiceRequest(
                "plugin",
                "installation.inspect",
                {"installation_root": str(self.root)},
            )
        )
        self.assertTrue(inspection.data["inspection"]["managed_clean"])
        diff = self.service.execute(
            ServiceRequest("mcp", "release.diff", self.release_arguments)
        )
        self.assertTrue(diff.data["diff"]["applicable"])
        planned = self.service.execute(
            ServiceRequest("codex", "release.merge", self.release_arguments)
        )
        plan_id = planned.data["plan"]["plan_id"]
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan"):
            self.service.execute(
                ServiceRequest(
                    "codex",
                    "release.merge",
                    self.release_arguments,
                    apply=True,
                    expected_plan_id="0" * 64,
                )
            )
        applied = self.service.execute(
            ServiceRequest(
                "codex",
                "release.merge",
                self.release_arguments,
                apply=True,
                expected_plan_id=plan_id,
            )
        )
        self.assertEqual("completed", applied.data["result"]["status"])
        verified = self.service.execute(
            ServiceRequest(
                "claude",
                "installation.verify",
                {"installation_root": str(self.root)},
            )
        )
        self.assertEqual("verified", verified.data["verification"]["status"])
        deployment_id = applied.data["result"]["deployment_id"]
        rollback_arguments = {
            "installation_root": str(self.root),
            "deployment_id": deployment_id,
        }
        rollback = self.service.execute(
            ServiceRequest("sdk", "deployment.rollback", rollback_arguments)
        )
        rollback_id = rollback.data["plan"]["plan_id"]
        rolled_back = self.service.execute(
            ServiceRequest(
                "sdk",
                "deployment.rollback",
                rollback_arguments,
                apply=True,
                expected_plan_id=rollback_id,
                approval_id="rollback-approval",
            )
        )
        self.assertEqual("rolled-back", rolled_back.data["result"]["status"])
        self.assertEqual(self.old_readme, (self.root / "README.md").read_bytes())
        self.assertFalse((self.root / "src" / "new.py").exists())

    def test_cli_routes_installation_and_release_through_shared_service(self) -> None:
        result, output, error = self._run_cli(
            [
                "installation",
                "inspect",
                "--repo",
                str(REPO_ROOT),
                "--installation",
                str(self.root),
            ]
        )
        self.assertEqual(0, result, error)
        self.assertEqual("installation.inspect", json.loads(output)["operation"])
        result, output, error = self._run_cli(
            [
                "release",
                "merge",
                "--repo",
                str(REPO_ROOT),
                "--installation",
                str(self.root),
                "--release",
                str(self.release),
                "--trusted-manifest-sha256",
                self.trusted_digest,
            ]
        )
        self.assertEqual(0, result, error)
        self.assertEqual("planned", json.loads(output)["status"])


if __name__ == "__main__":
    unittest.main()
