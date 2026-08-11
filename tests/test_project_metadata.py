from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_metadata import (  # noqa: E402
    ProjectMetadataError,
    infer_project_metadata,
    portable_slug,
)


class ProjectMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "Çalışma Projesi"
        self.source.mkdir()
        self.store = LocalWorkspaceStore(
            self.root / "data",
            OwnershipResolver.from_repository(REPO_ROOT),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _authorize(plan):
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                "synthetic-test-approval",
                approved=True,
            ),
        )

    def _put(self, record_type: str, record_id: str, payload: dict) -> None:
        plan = self.store.prepare_put(
            record_type,
            record_id,
            payload,
            expected_revision=0,
        )
        self.store.apply_put(plan, self._authorize(plan))

    def test_marker_precedence_and_turkish_slug(self) -> None:
        (self.source / "package.json").write_text(
            json.dumps({"name": "paket-adi"}),
            encoding="utf-8",
        )
        (self.source / "pyproject.toml").write_text(
            '[project]\nname = "İş Çözüm Projesi"\n',
            encoding="utf-8",
        )
        metadata = infer_project_metadata(self.source, self.store)
        self.assertEqual("İş Çözüm Projesi", metadata.project_name)
        self.assertEqual("is-cozum-projesi", metadata.project_id)
        self.assertEqual("is-cozum-projesi-workspace", metadata.workspace_id)
        self.assertEqual("is-cozum-projesi-local", metadata.binding_id)
        self.assertEqual("pyproject", metadata.metadata_source)

    def test_package_cargo_csproj_and_directory_fallbacks(self) -> None:
        cases = (
            ("package.json", '{"name":"web-client"}', "web-client", "package-json"),
            ("Cargo.toml", '[package]\nname = "rust-core"\n', "rust-core", "cargo"),
            ("Example.csproj", "<Project />", "Example", "csproj"),
        )
        for marker, content, expected_name, expected_source in cases:
            with self.subTest(marker=marker):
                child = self.root / marker.replace(".", "-")
                child.mkdir()
                (child / marker).write_text(content, encoding="utf-8")
                metadata = infer_project_metadata(child, self.store)
                self.assertEqual(expected_name, metadata.project_name)
                self.assertEqual(expected_source, metadata.metadata_source)
        fallback = infer_project_metadata(self.source, self.store)
        self.assertEqual("Çalışma Projesi", fallback.project_name)
        self.assertEqual("calisma-projesi", fallback.project_id)
        self.assertEqual("directory", fallback.metadata_source)

    def test_portable_slug_handles_numeric_and_non_latin_names(self) -> None:
        self.assertEqual("project-42-urun", portable_slug("42 Ürün"))
        self.assertEqual("project", portable_slug("東京"))

    def test_existing_ids_receive_one_shared_numeric_suffix(self) -> None:
        self._put(
            "projects",
            "calisma-projesi",
            {
                "schema_version": 1,
                "project_id": "calisma-projesi",
                "name": "Başka proje",
                "description": "",
                "source_refs": [],
                "technologies": [],
                "modules": [],
                "skill_refs": [],
                "status": "active",
            },
        )
        metadata = infer_project_metadata(self.source, self.store)
        self.assertEqual("calisma-projesi-2", metadata.project_id)
        self.assertEqual("calisma-projesi-2-workspace", metadata.workspace_id)
        self.assertEqual("calisma-projesi-2-local", metadata.binding_id)
        self.assertEqual(2, metadata.collision_index)

    def test_existing_source_binding_rejects_duplicate_directory(self) -> None:
        self._put(
            "source-bindings",
            "existing-local",
            {
                "schema_version": 1,
                "binding_id": "existing-local",
                "source_id": "existing",
                "source_kind": "project",
                "locator": {"kind": "local-path", "value": str(self.source)},
                "default_access": "read-only",
                "capabilities": ["read", "metadata"],
                "policy_refs": [],
                "revision": 1,
            },
        )
        with self.assertRaisesRegex(ProjectMetadataError, "already registered"):
            infer_project_metadata(self.source, self.store)

    def test_public_summary_and_inference_do_not_mutate_source(self) -> None:
        marker = self.source / "package.json"
        marker.write_text('{"name":"stable-project"}', encoding="utf-8")
        before = (marker.read_bytes(), marker.stat().st_mtime_ns)
        metadata = infer_project_metadata(self.source, self.store)
        after = (marker.read_bytes(), marker.stat().st_mtime_ns)
        serialized = json.dumps(metadata.public_summary(), ensure_ascii=False)
        self.assertEqual(before, after)
        self.assertNotIn(str(self.source), serialized)
        self.assertFalse(metadata.public_summary()["path_disclosed"])


if __name__ == "__main__":
    unittest.main()
