from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.hybrid_retrieval import hybrid_index_path  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.information_records import payload_digest  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.project_integration_state import (  # noqa: E402
    parse_project_integration_state,
)


def source_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


class CompleteProjectIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "sample-source"
        (self.source / "src").mkdir(parents=True)
        (self.source / "tests").mkdir()
        (self.source / "package.json").write_text(
            json.dumps(
                {
                    "name": "complete-sample",
                    "scripts": {"test": "node test.js"},
                }
            ),
            encoding="utf-8",
        )
        (self.source / "src" / "index.js").write_text(
            "export const value = 1;\n",
            encoding="utf-8",
        )
        (self.source / "tests" / "index.test.js").write_text(
            "// synthetic test\n",
            encoding="utf-8",
        )
        self.data_root = self.root / "data"
        self.store = LocalWorkspaceStore(
            self.data_root,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _plan(self, *, mode: str = "manual"):
        return self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": mode},
            )
        )

    def _apply(self, plan, *, mode: str = "manual"):
        return self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": mode},
                apply=True,
                expected_plan_id=plan.data["plan"]["plan_id"],
                approval_id="complete-integration-approval",
            )
        )

    @staticmethod
    def _authorize_record(plan):
        return authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                plan.mutation.plan_id,
                "synthetic-test-approval",
                approved=True,
            ),
        )

    def test_new_project_integration_completes_every_stage_without_source_copy(self) -> None:
        before = source_snapshot(self.source)
        plan = self._plan()
        self.assertEqual("planned", plan.status)
        summary = plan.data["plan"]
        self.assertFalse(summary["already_registered"])
        self.assertEqual("manual", summary["scan"]["mode"])
        self.assertEqual(
            "explicit-integration-request",
            summary["scan"]["trigger"],
        )
        self.assertTrue(summary["scan"]["performed_during_plan"])
        self.assertIn("registration", summary["missing_stages"])
        self.assertIn("vector-index", summary["missing_stages"])
        self.assertIn("source-code-index", summary["missing_stages"])
        self.assertEqual(
            ["qwen3-embedding-0-6b", "bge-m3"],
            summary["vector_index"]["remote_profile_order"],
        )
        self.assertEqual(
            "deterministic-hashing",
            summary["vector_index"]["profile_id"],
        )
        self.assertFalse(
            summary["source_code_index"]["source_content_persisted"]
        )
        self.assertEqual("planned", summary["capability_profile"]["status"])
        self.assertIn("analysis", summary["capability_profile"]["workload_ids"])
        self.assertFalse(summary["capability_profile"]["paths_disclosed"])
        applied = self._apply(plan)
        self.assertEqual("applied", applied.status)
        self.assertTrue(applied.data["verified"])
        self.assertEqual(before, source_snapshot(self.source))
        self.assertIsNotNone(self.store.read("projects", "complete-sample"))
        self.assertEqual(1, len(self.store.list_records("authoritative-sources")))
        self.assertEqual(4, len(self.store.list_records("knowledge")))
        capability_record = self.store.read("knowledge", "complete-sample-capabilities")
        self.assertEqual(
            "schemas/project-capability-profile.schema.json",
            capability_record.payload["payload"]["profile"]["schema_ref"],
        )
        state = parse_project_integration_state(
            self.store.read("project-integrations", "complete-sample").payload
        )
        self.assertEqual("manual", state.scan_mode)
        self.assertIn("nodejs-project-skill", state.skill_refs)
        self.assertEqual(
            ("planner-agent", "read-only-worker-agent", "verifier-agent"),
            state.role_refs,
        )
        self.assertTrue(hybrid_index_path(self.data_root).is_file())
        self.assertNotIn(str(self.source), json.dumps(applied.as_dict()))

    def test_capability_keyword_matching_project_id_is_deduplicated(self) -> None:
        source = self.root / "utplsql"
        source.mkdir()
        (source / "ut_example.pks").write_text(
            "create or replace package ut_example as end ut_example;\n",
            encoding="utf-8",
        )
        plan = self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(source), "scan_mode": "manual"},
            )
        )
        applied = self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(source), "scan_mode": "manual"},
                apply=True,
                expected_plan_id=plan.data["plan"]["plan_id"],
                approval_id="capability-keyword-deduplication",
            )
        )
        self.assertEqual("applied", applied.status)
        capability_record = self.store.read("knowledge", "utplsql-capabilities")
        keywords = capability_record.payload["payload"]["keywords"]
        self.assertEqual(len(keywords), len(set(keywords)))
        self.assertEqual(1, keywords.count("utplsql"))

    def test_automatic_check_is_no_op_while_integration_is_fresh(self) -> None:
        self._apply(self._plan())
        response = self.service.execute(
            ServiceRequest(
                "plugin",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("ok", response.status)
        self.assertTrue(response.data["no_op"])
        self.assertEqual("automatic", response.data["plan"]["scan"]["mode"])
        self.assertEqual(
            "freshness-current",
            response.data["plan"]["scan"]["trigger"],
        )
        self.assertFalse(response.data["plan"]["scan"]["performed_during_plan"])

    def test_blocked_git_metadata_does_not_cause_an_endless_repair_plan(self) -> None:
        git_directory = self.source / ".git"
        git_directory.mkdir()
        (git_directory / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n",
            encoding="utf-8",
        )
        self._apply(self._plan())
        capability_record = self.store.read(
            "knowledge",
            "complete-sample-capabilities",
        )
        self.assertGreater(
            capability_record.payload["payload"]["profile"]["limitations"][
                "discovery_skipped"
            ],
            0,
        )
        response = self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("ok", response.status)
        self.assertTrue(response.data["no_op"])
        self.assertEqual(
            "freshness-current",
            response.data["plan"]["scan"]["trigger"],
        )

    def test_legacy_shallow_capability_record_gets_one_approved_repair(self) -> None:
        self._apply(self._plan())
        current = self.store.read("knowledge", "complete-sample-capabilities")
        legacy_payload = dict(current.payload)
        legacy_content = {
            key: value
            for key, value in legacy_payload["payload"].items()
            if key in {"title", "text", "keywords", "aliases"}
        }
        legacy_payload["revision"] = current.revision + 1
        legacy_payload["payload"] = legacy_content
        legacy_payload["content_digest"] = payload_digest(legacy_content)
        downgrade = self.store.prepare_put(
            "knowledge",
            "complete-sample-capabilities",
            legacy_payload,
            expected_revision=current.revision,
        )
        self.store.apply_put(downgrade, self._authorize_record(downgrade))

        repair = self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("planned", repair.status)
        self.assertIn("capability-profile", repair.data["plan"]["missing_stages"])
        self.assertEqual(
            "missing-integration-stage",
            repair.data["plan"]["scan"]["trigger"],
        )
        applied = self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
                apply=True,
                expected_plan_id=repair.data["plan"]["plan_id"],
                approval_id="capability-profile-repair",
            )
        )
        self.assertEqual("applied", applied.status)
        final = self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("ok", final.status)
        self.assertTrue(final.data["no_op"])

    def test_source_change_before_apply_rejects_plan_without_writes(self) -> None:
        plan = self._plan()
        (self.source / "package.json").write_text(
            json.dumps({"name": "changed-before-apply"}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan id"):
            self._apply(plan)
        self.assertIsNone(self.store.read("knowledge", "complete-sample-capabilities"))
        self.assertIsNone(self.store.read("project-integrations", "complete-sample"))

    def test_resume_exposes_compact_current_profile_without_paths(self) -> None:
        self._apply(self._plan())
        response = self.service.execute(
            ServiceRequest(
                "codex",
                "project.resume",
                {
                    "working_directory": str(self.source),
                    "request_text": "Nerede kaldık?",
                },
            )
        )
        profile = response.data["resume"]["integration"]["capability_profile"]
        self.assertEqual("current", profile["status"])
        self.assertFalse(profile["paths_disclosed"])
        self.assertNotIn(str(self.source), json.dumps(response.as_dict()))

    def test_missing_vector_index_is_repaired_without_unneeded_rescan(self) -> None:
        self._apply(self._plan())
        hybrid_index_path(self.data_root).unlink()
        plan = self.service.execute(
            ServiceRequest(
                "mcp",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("planned", plan.status)
        self.assertIn("vector-index", plan.data["plan"]["missing_stages"])
        self.assertFalse(plan.data["plan"]["scan"]["performed_during_plan"])
        applied = self.service.execute(
            ServiceRequest(
                "mcp",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
                apply=True,
                expected_plan_id=plan.data["plan"]["plan_id"],
                approval_id="repair-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertTrue(hybrid_index_path(self.data_root).is_file())

    def test_expired_automatic_scan_and_manual_source_change_are_visible(self) -> None:
        first = self._apply(self._plan())
        first_index_digest = first.data["index"]["document_digest"]
        state_path = self.data_root / "projects" / "integration-states" / "complete-sample.json"
        expired = time.time() - 25 * 60 * 60
        os.utime(state_path, (expired, expired))
        automatic = self.service.execute(
            ServiceRequest(
                "generic-ai",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("planned", automatic.status)
        self.assertEqual(
            "freshness-expired",
            automatic.data["plan"]["scan"]["trigger"],
        )
        self.assertTrue(automatic.data["plan"]["scan"]["performed_during_plan"])

        (self.source / "src" / "new.js").write_text(
            "export const next = 2;\n",
            encoding="utf-8",
        )
        manual = self._plan()
        self.assertEqual("manual", manual.data["plan"]["scan"]["mode"])
        self.assertGreaterEqual(manual.data["plan"]["scan"]["file_count"], 4)
        updated = self._apply(manual)
        self.assertNotEqual(
            first_index_digest,
            updated.data["index"]["document_digest"],
        )
        self.assertEqual(
            2,
            self.store.read(
                "authoritative-sources",
                "complete-sample-source",
            ).revision,
        )
        state = parse_project_integration_state(
            self.store.read("project-integrations", "complete-sample").payload
        )
        self.assertEqual(2, state.scan_sequence)

    def test_registered_project_refresh_reconciles_source_changes_without_second_approval(self) -> None:
        self._apply(self._plan())
        project_before = self.store.read("projects", "complete-sample")
        (self.source / "src" / "index.js").write_text(
            "export const value = 2;\n",
            encoding="utf-8",
        )
        (self.source / "src" / "added.js").write_text(
            "export const added = true;\n",
            encoding="utf-8",
        )
        (self.source / "tests" / "index.test.js").unlink()
        source_after_user_change = source_snapshot(self.source)

        planned = self.service.execute(
            ServiceRequest(
                "opencode",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "manual"},
            )
        )
        self.assertEqual("planned", planned.status)
        stored_before_apply = self.store.read(
            "source-states",
            str(project_before.payload["source_refs"][0]),
        )
        self.assertNotIn(
            "src/added.js",
            {item["relative_path"] for item in stored_before_apply.payload["files"]},
        )

        refreshed = self.service.execute(
            ServiceRequest(
                "opencode",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "manual"},
                apply=True,
            )
        )

        self.assertEqual("applied", refreshed.status)
        self.assertTrue(refreshed.data["local_reconciliation"])
        self.assertEqual(source_after_user_change, source_snapshot(self.source))
        self.assertTrue(
            all(
                not item["mutation"]["approval_required"]
                for item in refreshed.data["plan"]["record_plans"]
            )
        )
        source_index_plan = refreshed.data["plan"]["source_code_index"]["plan"]
        self.assertGreaterEqual(source_index_plan["processed_file_count"], 2)
        self.assertEqual(1, source_index_plan["removed_file_count"])
        project_after = self.store.read("projects", "complete-sample")
        source_state = self.store.read(
            "source-states",
            str(project_after.payload["source_refs"][0]),
        )
        observed_paths = {
            item["relative_path"] for item in source_state.payload["files"]
        }
        self.assertIn("src/added.js", observed_paths)
        self.assertNotIn("tests/index.test.js", observed_paths)
        for field in ("project_id", "name", "description", "status", "source_refs"):
            self.assertEqual(project_before.payload[field], project_after.payload[field])

        unchanged = self.service.execute(
            ServiceRequest(
                "opencode",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "manual"},
                apply=True,
            )
        )
        self.assertEqual("ok", unchanged.status)
        self.assertTrue(unchanged.data["no_op"])
        self.assertFalse(unchanged.data["applied"])

    def test_missing_knowledge_record_triggers_complete_repair(self) -> None:
        self._apply(self._plan())
        missing = self.data_root / "knowledge" / "records" / "complete-sample-overview.json"
        missing.unlink()
        plan = self.service.execute(
            ServiceRequest(
                "claude",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
            )
        )
        self.assertEqual("planned", plan.status)
        self.assertIn("knowledge", plan.data["plan"]["missing_stages"])
        self.assertEqual(
            "missing-integration-stage",
            plan.data["plan"]["scan"]["trigger"],
        )
        applied = self.service.execute(
            ServiceRequest(
                "claude",
                "project.integrate",
                {"project_id": "complete-sample", "scan_mode": "automatic"},
                apply=True,
                expected_plan_id=plan.data["plan"]["plan_id"],
                approval_id="repair-knowledge-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertTrue(missing.is_file())


if __name__ == "__main__":
    unittest.main()
