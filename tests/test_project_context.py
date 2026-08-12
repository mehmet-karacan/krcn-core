from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import main as cli_main  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.information_records import payload_digest  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_context import (  # noqa: E402
    ProjectContextError,
    build_project_resume_summary,
    resolve_current_project,
)
class ProjectContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "shared-home"
        self.project_root = self.root / "projects" / "gpu-fusion"
        self.project_child = self.project_root / "backend" / "src"
        self.project_child.mkdir(parents=True)
        self.ownership = OwnershipResolver.from_repository(REPO_ROOT)
        self.store = LocalWorkspaceStore(self.home, self.ownership)
        self._register_project(
            "gpu-fusion",
            "GPU Fusion",
            self.project_root,
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
                "technologies": ["Java", "Node.js"],
            },
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _put(self, record_type: str, record_id: str, payload: dict) -> None:
        plan = self.store.prepare_put(
            record_type,
            record_id,
            payload,
            expected_revision=0,
        )
        self.store.apply_put(
            plan,
            authorize_mutation(
                plan.mutation,
                dry_run=DryRunEvidence(plan.mutation.plan_id, True),
                approval=ApprovalEvidence(plan.mutation.plan_id, "fixture", True),
            ),
        )

    def _register_project(
        self,
        project_id: str,
        name: str,
        source_root: Path,
    ) -> None:
        binding_id = f"{project_id}-local"
        self._put(
            "source-bindings",
            binding_id,
            {
                "schema_version": 1,
                "binding_id": binding_id,
                "source_id": project_id,
                "source_kind": "project",
                "locator": {"kind": "local-path", "value": str(source_root)},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": [],
                "revision": 1,
            },
        )
        self._put(
            "projects",
            project_id,
            {
                "schema_version": 1,
                "project_id": project_id,
                "name": name,
                "description": "Synthetic project",
                "source_refs": [binding_id],
                "status": "active",
            },
        )

    def test_working_directory_selects_project_without_exposing_path(self) -> None:
        match = resolve_current_project(
            self.store,
            working_directory=self.project_child,
        )
        assert match is not None
        summary = match.public_summary(self.store)
        self.assertEqual("gpu-fusion", summary["project"]["project_id"])
        self.assertEqual("working-directory", summary["selection_basis"])
        self.assertEqual(1, len(summary["source_states"]))
        self.assertNotIn(str(self.project_root), json.dumps(summary))

    def test_request_mention_selects_project_from_unrelated_directory(self) -> None:
        match = resolve_current_project(
            self.store,
            working_directory=self.root,
            request_text="GPU Fusion projesinde nerede kaldık?",
        )
        assert match is not None
        self.assertEqual("gpu-fusion", match.project.record_id)
        self.assertEqual("request-mention", match.selection_basis)

    def test_explicit_project_has_priority(self) -> None:
        other_root = self.root / "projects" / "other"
        other_root.mkdir()
        self._register_project("other-project", "Other Project", other_root)
        match = resolve_current_project(
            self.store,
            working_directory=other_root,
            project_ref="gpu-fusion",
            request_text="other-project",
        )
        assert match is not None
        self.assertEqual("gpu-fusion", match.project.record_id)
        self.assertEqual("explicit-project", match.selection_basis)

    def test_nested_project_uses_the_deepest_binding(self) -> None:
        nested_root = self.project_root / "backend"
        self._register_project("gpu-backend", "GPU Backend", nested_root)
        match = resolve_current_project(
            self.store,
            working_directory=self.project_child,
        )
        assert match is not None
        self.assertEqual("gpu-backend", match.project.record_id)

    def test_multiple_request_mentions_fail_as_ambiguous(self) -> None:
        other_root = self.root / "projects" / "other"
        other_root.mkdir()
        self._register_project("other-project", "Other Project", other_root)
        with self.assertRaisesRegex(ProjectContextError, "ambiguous"):
            resolve_current_project(
                self.store,
                working_directory=self.root,
                request_text="gpu-fusion ile other-project karşılaştır",
            )

    def test_resume_summary_reports_knowledge_and_no_active_task(self) -> None:
        content = {
            "title": "GPU Fusion source",
            "source_id": "gpu-fusion",
            "binding_id": "gpu-fusion-local",
            "binding_revision": 1,
            "source_revision_id": "rev-1",
            "source_digest": "a" * 64,
            "aliases": ["gpu-fusion"],
        }
        self._put(
            "authoritative-sources",
            "gpu-fusion-source",
            {
                "schema_ref": "schemas/information-record.schema.json",
                "schema_version": 1,
                "record_id": "gpu-fusion-source",
                "information_class": "authoritative-source",
                "ownership": "user-data",
                "subject_ref": "source:gpu-fusion",
                "revision": 1,
                "content_digest": payload_digest(content),
                "provenance": {
                    "kind": "system-observation",
                    "evidence": [
                        {
                            "source_ref": "source:gpu-fusion",
                            "revision_id": "rev-1",
                            "digest": "a" * 64,
                            "relation": "observed-at",
                        }
                    ],
                },
                "lifecycle": "current",
                "payload": content,
            },
        )
        match = resolve_current_project(
            self.store,
            working_directory=self.project_root,
        )
        assert match is not None
        summary = build_project_resume_summary(self.store, match)
        self.assertEqual(1, summary["resume"]["information"]["record_count"])
        self.assertEqual(0, summary["resume"]["work"]["active_task_count"])
        self.assertIn(
            "no-active-task-start-from-user-request",
            summary["resume"]["next_actions"],
        )

    def test_application_clients_receive_the_same_resume_summary(self) -> None:
        service = KrcnApplicationService(REPO_ROOT, self.store)
        arguments = {
            "working_directory": str(self.project_root),
            "request_text": "Nerede kaldık?",
        }
        summaries = []
        for client in ("cli", "sdk", "mcp", "plugin", "codex", "claude", "opencode"):
            response = service.execute(ServiceRequest(client, "project.resume", arguments))
            self.assertEqual("ok", response.status)
            summaries.append(response.data)
        self.assertTrue(all(summary == summaries[0] for summary in summaries))

    def test_cli_current_uses_directory_argument(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = cli_main(
                [
                    "project",
                    "current",
                    "--directory",
                    str(self.project_child),
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(self.home),
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(0, return_code)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["data"]["matched"])
        self.assertEqual("gpu-fusion", payload["data"]["project"]["project_id"])


if __name__ == "__main__":
    unittest.main()
