from __future__ import annotations

import json
import shutil
import sqlite3
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
from krcn_core.source_code_index import source_code_index_path  # noqa: E402


class SourceCodeIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "sample-code"
        (self.source / "src").mkdir(parents=True)
        (self.source / "ui").mkdir()
        self.java = self.source / "src" / "UserService.java"
        self.java.write_text(
            """package sample;

public class UserService {
    public void deleteAccount(String accountId) {
        String marker = "SOURCE_ONLY_LITERAL_9284";
        System.out.println(accountId + marker);
    }
}
""",
            encoding="utf-8",
        )
        self.typescript = self.source / "ui" / "account.ts"
        self.typescript.write_text(
            """export function deactivateAccount(accountId: string): string {
  return `deactivated:${accountId}`;
}
""",
            encoding="utf-8",
        )
        (self.source / "README.md").write_text(
            "Account lifecycle sample.\n",
            encoding="utf-8",
        )
        (self.source / "application.properties").write_text(
            "spring.datasource.password=" + "SYNTHETIC_PASSWORD_12345" + "\n",
            encoding="utf-8",
        )
        (self.source / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.data_root = self.root / "data"
        self.store = LocalWorkspaceStore(
            self.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _integration_plan(self):
        return self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": "manual"},
            )
        )

    def _apply_integration(self, plan):
        return self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": "manual"},
                apply=True,
                expected_plan_id=plan.data["plan"]["plan_id"],
                approval_id="source-code-integration-approval",
            )
        )

    def _integrate(self):
        return self._apply_integration(self._integration_plan())

    def _query(
        self,
        text: str,
        *,
        path_prefix: str | None = None,
        include_content: bool = True,
        limit: int = 5,
    ):
        return self.service.execute(
            ServiceRequest(
                "plugin",
                "project.search-source-code",
                {
                    "query": {
                        "schema_ref": "schemas/source-code-query.schema.json",
                        "schema_version": 1,
                        "query_id": "source-query",
                        "project_id": "sample-code",
                        "text": text,
                        "languages": [],
                        "path_prefix": path_prefix,
                        "include_content": include_content,
                        "limit": limit,
                    }
                },
            )
        )

    def test_complete_integration_builds_contentless_source_code_index(self) -> None:
        plan = self._integration_plan()
        summary = plan.data["plan"]
        self.assertIn("source-code-index", summary["missing_stages"])
        code_plan = summary["source_code_index"]["plan"]
        self.assertEqual(3, code_plan["selected_file_count"])
        self.assertEqual(1, code_plan["skipped"]["sensitive_content"])
        self.assertGreaterEqual(code_plan["chunk_count"], 3)
        self.assertFalse(code_plan["source_content_persisted"])
        self.assertFalse(code_plan["source_copy"])

        applied = self._apply_integration(plan)
        result = applied.data["source_code_index"]
        self.assertTrue(result["integrity_verified"])
        self.assertEqual(3, result["file_count"])
        index = source_code_index_path(self.data_root, "sample-code")
        self.assertTrue(index.is_file())
        raw = index.read_bytes()
        self.assertNotIn(b"SOURCE_ONLY_LITERAL_9284", raw)
        self.assertNotIn(str(self.source).encode("utf-8"), raw)

        connection = sqlite3.connect(index)
        try:
            chunk_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(chunks)")
            }
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            indexed_paths = {
                row[0] for row in connection.execute("SELECT relative_path FROM files")
            }
        finally:
            connection.close()
        self.assertNotIn("content", chunk_columns)
        self.assertNotIn("text", chunk_columns)
        self.assertNotIn("application.properties", indexed_paths)
        self.assertEqual("false", metadata["source_content_persisted"])

    def test_plsql_package_sources_under_coverage_are_indexed(self) -> None:
        coverage = self.source / "framework" / "source" / "core" / "coverage"
        coverage.mkdir(parents=True)
        (coverage / "ut_coverage.pks").write_text(
            "create or replace package ut_coverage as procedure run; end;\n",
            encoding="utf-8",
        )
        (coverage / "ut_coverage.pkb").write_text(
            "create or replace package body ut_coverage as procedure run is begin null; end; end;\n",
            encoding="utf-8",
        )
        report = self.source / "coverage" / "lcov-report"
        report.mkdir(parents=True)
        (report / "index.html").write_text("generated report\n", encoding="utf-8")

        applied = self._integrate()
        self.assertEqual(5, applied.data["source_code_index"]["file_count"])
        index = source_code_index_path(self.data_root, "sample-code")
        connection = sqlite3.connect(index)
        try:
            indexed = dict(
                connection.execute("SELECT relative_path, language FROM files")
            )
        finally:
            connection.close()
        self.assertEqual(
            "plsql",
            indexed["framework/source/core/coverage/ut_coverage.pks"],
        )
        self.assertEqual(
            "plsql",
            indexed["framework/source/core/coverage/ut_coverage.pkb"],
        )
        self.assertNotIn("coverage/lcov-report/index.html", indexed)

    def test_search_returns_verified_relative_path_lines_and_live_content(self) -> None:
        self._integrate()
        response = self._query("deleteAccount", path_prefix="src")
        result = response.data["result"]
        self.assertEqual("ok", response.status)
        self.assertTrue(result["source_read_in_place"])
        self.assertFalse(result["source_content_persisted"])
        self.assertGreater(result["hit_count"], 0)
        hit = result["hits"][0]
        self.assertEqual("src/UserService.java", hit["relative_path"])
        self.assertLessEqual(hit["start_line"], 4)
        self.assertGreaterEqual(hit["end_line"], 4)
        self.assertIn("deleteAccount", hit["symbols"])
        self.assertIn("SOURCE_ONLY_LITERAL_9284", hit["content"])
        self.assertNotIn(str(self.source), json.dumps(result))

        metadata_only = self._query(
            "deleteAccount",
            path_prefix="src",
            include_content=False,
        )
        self.assertFalse(metadata_only.data["result"]["source_read_in_place"])
        self.assertIsNone(metadata_only.data["result"]["hits"][0]["content"])

    def test_changed_source_fails_closed_until_reintegration(self) -> None:
        self._integrate()
        self.java.write_text(
            self.java.read_text(encoding="utf-8") + "// changed after index\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ApplicationServiceError, "reintegrate"):
            self._query("deleteAccount", path_prefix="src")

    def test_reintegration_reuses_unchanged_and_removes_deleted_files(self) -> None:
        self._integrate()
        self.java.write_text(
            self.java.read_text(encoding="utf-8").replace(
                "deleteAccount", "archiveAccount"
            ),
            encoding="utf-8",
        )
        (self.source / "README.md").unlink()
        (self.source / "src" / "AuditService.java").write_text(
            "public class AuditService { public void recordAudit() {} }\n",
            encoding="utf-8",
        )
        plan = self._integration_plan()
        code_plan = plan.data["plan"]["source_code_index"]["plan"]
        self.assertEqual(2, code_plan["processed_file_count"])
        self.assertEqual(1, code_plan["reused_file_count"])
        self.assertEqual(1, code_plan["removed_file_count"])
        applied = self._apply_integration(plan)
        self.assertEqual(3, applied.data["source_code_index"]["file_count"])

        index = source_code_index_path(self.data_root, "sample-code")
        connection = sqlite3.connect(index)
        try:
            paths = {
                row[0] for row in connection.execute("SELECT relative_path FROM files")
            }
        finally:
            connection.close()
        self.assertNotIn("README.md", paths)
        self.assertIn("src/AuditService.java", paths)

    def test_missing_source_code_index_is_repaired_without_source_rescan(self) -> None:
        self._integrate()
        source_code_index_path(self.data_root, "sample-code").unlink()
        plan = self.service.execute(
            ServiceRequest(
                "mcp",
                "project.integrate",
                {"project_id": "sample-code", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("planned", plan.status)
        self.assertIn("source-code-index", plan.data["plan"]["missing_stages"])
        self.assertFalse(plan.data["plan"]["scan"]["performed_during_plan"])
        applied = self.service.execute(
            ServiceRequest(
                "mcp",
                "project.integrate",
                {"project_id": "sample-code", "scan_mode": "automatic"},
                apply=True,
                expected_plan_id=plan.data["plan"]["plan_id"],
                approval_id="repair-source-index",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertTrue(source_code_index_path(self.data_root, "sample-code").is_file())

    def test_direct_index_operation_is_no_op_after_integration(self) -> None:
        self._integrate()
        response = self.service.execute(
            ServiceRequest(
                "sdk",
                "project.index-source-code",
                {"project_id": "sample-code"},
            )
        )
        self.assertEqual("ok", response.status)
        self.assertTrue(response.data["no_op"])
        self.assertEqual("current", response.data["index"]["status"])

    def test_rebind_with_same_content_rebuilds_stale_binding_revision(self) -> None:
        self._integrate()
        rebound_source = self.root / "rebound-code"
        shutil.copytree(self.source, rebound_source)
        rebind_plan = self.service.execute(
            ServiceRequest(
                "codex",
                "project.rebind",
                {
                    "project_id": "sample-code",
                    "candidate_root": str(rebound_source),
                },
            )
        )
        self.assertEqual(
            "relocated-same-source", rebind_plan.data["plan"]["classification"]
        )
        self.assertEqual(
            "verify-current-manifest-and-reuse",
            rebind_plan.data["plan"]["index_action"],
        )
        rebound = self.service.execute(
            ServiceRequest(
                "codex",
                "project.rebind",
                {
                    "project_id": "sample-code",
                    "candidate_root": str(rebound_source),
                },
                apply=True,
                expected_plan_id=rebind_plan.data["plan"]["plan_id"],
                approval_id="source-rebind-approval",
            )
        )
        self.assertEqual("applied", rebound.status)

        with self.assertRaisesRegex(ApplicationServiceError, "stale"):
            self._query("deleteAccount", path_prefix="src")

        index_plan = self.service.execute(
            ServiceRequest(
                "sdk",
                "project.index-source-code",
                {"project_id": "sample-code"},
            )
        )
        self.assertEqual("planned", index_plan.status)
        self.assertFalse(index_plan.data["no_op"])
        self.assertEqual(0, index_plan.data["plan"]["processed_file_count"])
        self.assertEqual(3, index_plan.data["plan"]["reused_file_count"])

        rebuilt = self.service.execute(
            ServiceRequest(
                "sdk",
                "project.index-source-code",
                {"project_id": "sample-code"},
                apply=True,
                expected_plan_id=index_plan.data["plan"]["plan_id"],
            )
        )
        self.assertEqual("applied", rebuilt.status)
        result = self._query("deleteAccount", path_prefix="src")
        self.assertEqual("ok", result.status)
        self.assertGreater(result.data["result"]["hit_count"], 0)

    def test_tampered_vector_invalidates_summary_and_search(self) -> None:
        self._integrate()
        index = source_code_index_path(self.data_root, "sample-code")
        connection = sqlite3.connect(index)
        try:
            chunk_id, payload = connection.execute(
                "SELECT chunk_id, vector_json FROM chunks ORDER BY chunk_id LIMIT 1"
            ).fetchone()
            vector = json.loads(payload)
            vector[0] = float(vector[0]) + 0.25
            connection.execute(
                "UPDATE chunks SET vector_json = ? WHERE chunk_id = ?",
                (json.dumps(vector, separators=(",", ":")), chunk_id),
            )
            connection.commit()
        finally:
            connection.close()

        status = self.service.execute(
            ServiceRequest(
                "sdk",
                "project.index-source-code",
                {"project_id": "sample-code"},
            )
        )
        self.assertEqual("planned", status.status)
        self.assertFalse(status.data["no_op"])
        with self.assertRaisesRegex(ApplicationServiceError, "invalid"):
            self._query("deleteAccount", path_prefix="src")


if __name__ == "__main__":
    unittest.main()
