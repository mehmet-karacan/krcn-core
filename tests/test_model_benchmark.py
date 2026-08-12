from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import (  # noqa: E402
    ApplicationServiceError,
    KrcnApplicationService,
    ServiceRequest,
)
from krcn_core.cli.app import build_parser  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.information_records import parse_information_record  # noqa: E402
from krcn_core.local_store import LocalStoreError, LocalWorkspaceStore  # noqa: E402
from krcn_core.model_benchmark import (  # noqa: E402
    ModelBenchmarkError,
    build_project_benchmark_suite,
    list_project_benchmark_suites,
    load_model_benchmark_policy,
    parse_model_benchmark_suite,
    prepare_project_benchmark_suite,
)
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
from krcn_core.project_capability_profile import (  # noqa: E402
    load_project_capability_profiler_policy,
    parse_project_capability_profile,
)


def source_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


class ModelBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "benchmark-sample"
        (self.source / "src").mkdir(parents=True)
        (self.source / "tests").mkdir()
        (self.source / "package.json").write_text(
            json.dumps(
                {
                    "name": "benchmark-sample",
                    "dependencies": {"react": "19.0.0"},
                    "devDependencies": {"vitest": "3.0.0"},
                    "scripts": {"test": "vitest"},
                }
            ),
            encoding="utf-8",
        )
        (self.source / "src" / "index.js").write_text(
            "export const value = 1;\n",
            encoding="utf-8",
        )
        (self.source / "tests" / "index.test.js").write_text(
            "// synthetic test marker\n",
            encoding="utf-8",
        )
        (self.source / "benchmark_package.pks").write_text(
            "CREATE OR REPLACE PACKAGE benchmark_package AS END;\n",
            encoding="utf-8",
        )
        self.home = self.root / "home"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.store = LocalWorkspaceStore(
            self.home,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)
        integration = self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": "manual"},
            )
        )
        self.service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": "manual"},
                apply=True,
                expected_plan_id=integration.data["plan"]["plan_id"],
                approval_id="integration-approval",
            )
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _plan(self):
        return self.service.execute(
            ServiceRequest(
                "codex",
                "model.benchmark-suite",
                {"project_id": "benchmark-sample"},
            )
        )

    def _apply(self, plan):
        return self.service.execute(
            ServiceRequest(
                "codex",
                "model.benchmark-suite",
                {"project_id": "benchmark-sample"},
                apply=True,
                expected_plan_id=plan.data["plan"]["plan_id"],
            )
        )

    def test_suite_is_project_specific_contentless_and_derived(self) -> None:
        before = source_snapshot(self.source)
        planned = self._plan()
        self.assertEqual("planned", planned.status)
        summary = planned.data["plan"]
        self.assertEqual("benchmark-sample", summary["project_id"])
        self.assertGreater(summary["case_count"], 4)
        self.assertFalse(summary["source_content_included"])
        self.assertFalse(summary["paths_disclosed"])
        self.assertFalse(summary["remote_call_performed"])
        self.assertEqual("derived", summary["effect"]["mutation"]["ownership"])
        self.assertFalse(summary["effect"]["mutation"]["approval_required"])
        applied = self._apply(planned)
        self.assertEqual("applied", applied.status)
        self.assertTrue(applied.data["applied"])
        self.assertEqual(before, source_snapshot(self.source))
        stored = self.store.read(
            "model-benchmark-suites",
            "benchmark-sample-micro-benchmark",
        )
        suite = parse_model_benchmark_suite(stored.payload)
        serialized = json.dumps(suite)
        self.assertNotIn(str(self.source), serialized)
        self.assertNotIn("export const", serialized)
        self.assertNotIn("CREATE OR REPLACE", serialized)
        expected = (
            self.home
            / "projects"
            / "benchmark-sample"
            / "derived"
            / "model-benchmark-suites"
            / "benchmark-sample-micro-benchmark.json"
        ).resolve(strict=False)
        self.assertTrue(expected.is_file())

    def test_identical_suite_is_no_op_and_list_is_safe(self) -> None:
        self._apply(self._plan())
        second = self._plan()
        self.assertEqual("ok", second.status)
        self.assertTrue(second.data["no_op"])
        self.assertIsNone(second.data["plan"]["effect"])
        listed = self.service.execute(
            ServiceRequest(
                "opencode",
                "model.benchmark-list",
                {"project_id": "benchmark-sample"},
            )
        )
        self.assertEqual(1, listed.data["suite_count"])
        self.assertFalse(listed.data["source_content_included"])
        self.assertFalse(listed.data["paths_disclosed"])
        self.assertEqual(
            1,
            len(
                list_project_benchmark_suites(
                    REPO_ROOT,
                    self.store,
                    project_id="benchmark-sample",
                )
            ),
        )
        self.assertEqual("current", listed.data["suites"][0]["effective_state"])

    def test_database_case_is_local_only_and_remote_cases_are_explicit(self) -> None:
        suite = build_project_benchmark_suite(
            REPO_ROOT,
            self.store,
            "benchmark-sample",
            suite_revision=1,
        )
        cases = {item["workload_id"]: item for item in suite["cases"]}
        self.assertIn("database-analysis", cases)
        self.assertFalse(cases["database-analysis"]["remote_eligible"])
        self.assertEqual("local-only", cases["database-analysis"]["fixture_policy"])
        self.assertTrue(cases["analysis"]["remote_eligible"])
        self.assertEqual(
            100,
            sum(
                cases["analysis"]["rubric"][field]
                for field in (
                    "quality_weight",
                    "reliability_weight",
                    "latency_weight",
                )
            ),
        )

    def test_case_and_suite_digest_tampering_are_rejected(self) -> None:
        suite = build_project_benchmark_suite(
            REPO_ROOT,
            self.store,
            "benchmark-sample",
            suite_revision=1,
        )
        tampered = copy.deepcopy(suite)
        tampered["cases"][0]["template_id"] = "fabricated-template"
        with self.assertRaisesRegex(ModelBenchmarkError, "case digest"):
            parse_model_benchmark_suite(tampered)
        tampered = copy.deepcopy(suite)
        tampered["suite_digest"] = "0" * 64
        with self.assertRaisesRegex(ModelBenchmarkError, "suite digest"):
            parse_model_benchmark_suite(tampered)

    def test_suite_requires_complete_integrated_project(self) -> None:
        empty_store = LocalWorkspaceStore(
            self.root / "empty",
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        with self.assertRaisesRegex(ModelBenchmarkError, "integration"):
            build_project_benchmark_suite(
                REPO_ROOT,
                empty_store,
                "missing-project",
                suite_revision=1,
            )

    def test_exact_plan_is_required_and_store_identity_is_enforced(self) -> None:
        planned = self._plan()
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan"):
            self.service.execute(
                ServiceRequest(
                    "codex",
                    "model.benchmark-suite",
                    {"project_id": "benchmark-sample"},
                    apply=True,
                    expected_plan_id="0" * 64,
                )
            )
        plan = prepare_project_benchmark_suite(
            REPO_ROOT,
            self.store,
            "benchmark-sample",
        )
        with self.assertRaises(LocalStoreError):
            self.store.prepare_put(
                "model-benchmark-suites",
                "another-suite",
                plan.suite,
                expected_revision=0,
                project_id="benchmark-sample",
            )

    def test_policy_is_versioned_and_contains_every_workload_template(self) -> None:
        policy = load_model_benchmark_policy(REPO_ROOT)
        self.assertEqual(10, len(policy.templates))
        self.assertEqual(80, policy.quality_weight)
        self.assertEqual(10, policy.reliability_weight)
        self.assertEqual(10, policy.latency_weight)

    def test_current_policy_and_profile_validate_every_generated_case(self) -> None:
        policy = load_model_benchmark_policy(REPO_ROOT)
        information = parse_information_record(
            self.store.read(
                "knowledge",
                "benchmark-sample-capabilities",
            ).payload
        )
        profile = parse_project_capability_profile(
            information.payload["profile"],
            policy=load_project_capability_profiler_policy(REPO_ROOT),
        )
        suite = build_project_benchmark_suite(
            REPO_ROOT,
            self.store,
            "benchmark-sample",
            suite_revision=1,
        )
        self.assertEqual(
            suite,
            parse_model_benchmark_suite(
                suite,
                policy=policy,
                profile=profile,
            ),
        )
        with self.assertRaisesRegex(ModelBenchmarkError, "policy is stale"):
            parse_model_benchmark_suite(
                suite,
                policy=replace(policy, policy_digest="0" * 64),
                profile=profile,
            )

    def test_cli_exposes_benchmark_suite_and_list_commands(self) -> None:
        parser = build_parser()
        suite_args = parser.parse_args(
            ["model", "benchmark-suite", "benchmark-sample"]
        )
        self.assertEqual("benchmark-suite", suite_args.model_command)
        list_args = parser.parse_args(
            ["model", "benchmark-list", "--project", "benchmark-sample"]
        )
        self.assertEqual("benchmark-sample", list_args.project)


if __name__ == "__main__":
    unittest.main()
