from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from krcn_core.repository_context import (  # noqa: E402
    RepositoryContextError,
    main,
    resolve_repo_reference,
    resolve_repository_context,
    validate_repository_context,
)


class RepositoryContextTests(unittest.TestCase):
    def test_repository_context_is_valid(self) -> None:
        self.assertEqual([], validate_repository_context(REPO_ROOT))

    def test_required_clients_share_canonical_context(self) -> None:
        resolved = resolve_repository_context(REPO_ROOT)
        adapters = resolved.manifest["client_adapters"]
        self.assertEqual(
            {"claude-code", "codex", "generic-ai", "plugin", "sdk", "mcp"},
            set(adapters),
        )
        self.assertEqual("AGENTS.md", adapters["codex"]["entrypoint"])
        self.assertEqual("CLAUDE.md", adapters["claude-code"]["entrypoint"])
        self.assertEqual("AI-CONTEXT.md", adapters["generic-ai"]["entrypoint"])
        self.assertEqual(
            ".ai/repository-context.json",
            adapters["plugin"]["entrypoint"],
        )

    def test_claude_adapter_only_imports_shared_sources(self) -> None:
        lines = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(["@AGENTS.md", "@AI-CONTEXT.md"], lines)

    def test_codex_instructions_reference_context_manifest(self) -> None:
        instructions = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(".ai/repository-context.json", instructions)
        self.assertIn(".ai/current-work.json", instructions)
        self.assertIn(
            ".krcn/projects/<project-id>/local-data/client-artifacts/**",
            instructions,
        )

    def test_operational_artifacts_stay_outside_versioned_core(self) -> None:
        policy = resolve_repository_context(REPO_ROOT).manifest["data_policy"]
        self.assertFalse(policy["operational_artifacts_in_core"])
        self.assertEqual(
            ".krcn/projects/<project-id>/local-data/client-artifacts",
            policy["project_operational_artifact_root"],
        )
        self.assertEqual(
            ".krcn/global/local-data/client-artifacts",
            policy["global_operational_artifact_root"],
        )

    def test_model_routing_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "model_routing_policy",
            "model_routing_policy_schema",
            "model_route_selection_schema",
            "model_routing_boundary",
        ):
            with self.subTest(key=key):
                self.assertTrue(resolve_repo_reference(REPO_ROOT, canonical[key]).is_file())

    def test_research_orchestration_boundary_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        self.assertEqual(
            "docs/specifications/RESEARCH-ORCHESTRATION.md",
            canonical["research_orchestration_boundary"],
        )
        self.assertTrue(
            resolve_repo_reference(
                REPO_ROOT,
                canonical["research_orchestration_boundary"],
            ).is_file()
        )

    def test_client_delegation_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "client_capability_policy",
            "client_capability_policy_schema",
            "client_capability_profile_schema",
            "delegation_policy",
            "delegation_policy_schema",
            "delegation_decision_schema",
            "client_delegation_boundary",
        ):
            with self.subTest(key=key):
                self.assertTrue(
                    resolve_repo_reference(REPO_ROOT, canonical[key]).is_file()
                )

    def test_project_capability_profile_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "project_capability_profiler_policy",
            "project_capability_profiler_policy_schema",
            "project_capability_profile_schema",
            "project_capability_profile_boundary",
        ):
            with self.subTest(key=key):
                self.assertTrue(resolve_repo_reference(REPO_ROOT, canonical[key]).is_file())

    def test_model_inventory_health_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "model_inventory_schema",
            "model_health_policy",
            "model_health_policy_schema",
            "model_health_record_schema",
            "model_inventory_health_boundary",
        ):
            with self.subTest(key=key):
                self.assertTrue(resolve_repo_reference(REPO_ROOT, canonical[key]).is_file())

    def test_project_model_benchmark_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "model_benchmark_policy",
            "model_benchmark_policy_schema",
            "model_benchmark_suite_schema",
            "project_model_benchmark_boundary",
        ):
            with self.subTest(key=key):
                self.assertTrue(resolve_repo_reference(REPO_ROOT, canonical[key]).is_file())

    def test_queue_suitability_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "queue_suitability_boundary",
            "queue_suitability_decision",
            "queue_suitability_policy",
            "queue_suitability_policy_schema",
            "queue_suitability_baseline",
            "queue_suitability_baseline_schema",
        ):
            with self.subTest(key=key):
                self.assertTrue(
                    resolve_repo_reference(REPO_ROOT, canonical[key]).is_file()
                )

    def test_model_decision_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "model_decision_boundary",
            "model_decision_policy",
            "model_decision_policy_schema",
            "model_price_catalog_schema",
            "model_benchmark_result_schema",
            "model_runtime_observation_schema",
            "model_decision_schema",
            "task_model_assignments_schema",
            "retrieval_golden_boundary",
            "retrieval_golden_set",
            "retrieval_golden_set_schema",
            "retrieval_golden_result_schema",
            "retrieval_scale_policy",
            "retrieval_scale_policy_schema",
            "retrieval_scale_manifest_schema",
        ):
            with self.subTest(key=key):
                self.assertTrue(
                    resolve_repo_reference(REPO_ROOT, canonical[key]).is_file()
                )

    def test_execution_coordinator_contract_is_canonical(self) -> None:
        canonical = resolve_repository_context(REPO_ROOT).manifest["canonical"]
        for key in (
            "execution_coordinator_boundary",
            "execution_coordination_plan_schema",
            "execution_coordination_result_schema",
            "application_modularity_boundary",
        ):
            with self.subTest(key=key):
                self.assertTrue(
                    resolve_repo_reference(REPO_ROOT, canonical[key]).is_file()
                )

    def test_current_work_references_exist(self) -> None:
        resolved = resolve_repository_context(REPO_ROOT)
        current = resolved.current_work
        references = [current["plan_ref"], *current["progress_refs"]]
        for reference in references:
            with self.subTest(reference=reference):
                self.assertTrue(resolve_repo_reference(REPO_ROOT, reference).is_file())

    def test_json_summary_contains_only_relative_context_references(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = main(
                ["--repo", str(REPO_ROOT), "--format", "json"]
            )
        self.assertEqual(0, return_code)
        summary = json.loads(output.getvalue())
        references = list(summary["canonical"].values())
        references.extend(summary["read_order"])
        references.extend(
            item["entrypoint"] for item in summary["client_adapters"].values()
        )
        for reference in references:
            with self.subTest(reference=reference):
                self.assertFalse(Path(reference).is_absolute())
                self.assertNotIn("..", Path(reference).parts)

    def test_validate_only_command_succeeds(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = main(["--repo", str(REPO_ROOT), "--validate-only"])
        self.assertEqual(0, return_code)
        self.assertEqual("Repository context validation passed.", output.getvalue().strip())

    def test_absolute_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(RepositoryContextError, "Absolute"):
            resolve_repo_reference(REPO_ROOT, str(REPO_ROOT / "AGENTS.md"))

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(RepositoryContextError, "escape"):
            resolve_repo_reference(REPO_ROOT, "../outside.md")

    def test_backslash_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(RepositoryContextError, "forward slashes"):
            resolve_repo_reference(REPO_ROOT, "docs\\plans\\ROADMAP.md")

    def test_context_entrypoints_remain_compact(self) -> None:
        instruction_bytes = (REPO_ROOT / "AGENTS.md").stat().st_size
        orientation_bytes = (REPO_ROOT / "AI-CONTEXT.md").stat().st_size
        self.assertLess(instruction_bytes + orientation_bytes, 30_000)
        self.assertLess(
            len((REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()),
            200,
        )
        self.assertLess(
            len((REPO_ROOT / "AI-CONTEXT.md").read_text(encoding="utf-8").splitlines()),
            200,
        )

    def test_context_schemas_are_valid_json_with_krcn_ids(self) -> None:
        expected = {
            "current-work.schema.json": "urn:krcn:schemas:current-work:1",
            "repository-context.schema.json": "urn:krcn:schemas:repository-context:1",
        }
        for filename, schema_id in expected.items():
            with self.subTest(filename=filename):
                payload = json.loads(
                    (REPO_ROOT / "schemas" / filename).read_text(encoding="utf-8")
                )
                self.assertEqual(schema_id, payload["$id"])


if __name__ == "__main__":
    unittest.main()
