from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from krcn_core.application import KrcnApplicationService  # noqa: E402
from krcn_core.application_contract import ServiceRequest  # noqa: E402
from krcn_core.application_contract import ApplicationServiceError  # noqa: E402
from krcn_core.cli.app import build_parser, main as cli_main  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import OwnershipResolver  # noqa: E402
import test_measured_loop as measured_fixtures  # noqa: E402
import test_model_benchmark_runner as benchmark_fixtures  # noqa: E402
import test_skill_lifecycle as skill_fixtures  # noqa: E402


class Phase22ApplicationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / ".krcn"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        self.store = LocalWorkspaceStore(
            self.home, OwnershipResolver.from_repository(REPO_ROOT)
        )
        self.service = KrcnApplicationService(REPO_ROOT, self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_autonomy_status_morning_and_admission_are_read_only(self) -> None:
        fixture = measured_fixtures.MeasuredLoopTests()
        fixture.setUp()
        plan = fixture.plan().as_dict()
        status_response = self.service.execute(
            ServiceRequest(
                "cli",
                "autonomy.status",
                {
                    "plan": plan,
                    "iterations": [],
                    "observed_at": "2026-08-16T00:00:01Z",
                },
            )
        )
        status = status_response.data["status"]
        self.assertEqual("planned", status["state"])
        morning = self.service.execute(
            ServiceRequest(
                "cli",
                "autonomy.morning",
                {
                    "status": status,
                    "generated_at": "2026-08-16T00:00:02Z",
                },
            )
        )
        self.assertFalse(morning.data["digest"]["contains_prompts"])
        admission = self.service.execute(
            ServiceRequest(
                "cli",
                "autonomy.admission",
                {
                    "plan": plan,
                    "status": status,
                    "observed_at": "2026-08-16T00:00:02Z",
                    "requested_claims": 3,
                    "active_claims": 0,
                    "cpu_pressure_basis_points": 1000,
                    "ram_pressure_basis_points": 1000,
                    "provider_required": False,
                    "provider_quota_remaining_basis_points": None,
                    "cost_headroom_microunits": 5000,
                    "failure_pressure_basis_points": 0,
                },
            )
        )
        self.assertEqual(2, admission.data["admission"]["admitted_claims"])
        self.assertFalse(admission.data["grants_authority"])

    def test_skill_evaluation_and_change_plan_never_mutate_registry(self) -> None:
        fixture = skill_fixtures.SkillLifecycleTests()
        fixture.setUp()
        candidate = fixture.candidate()
        evaluation_args = {
            "evaluation_id": "context-evaluation",
            "project_fixture_digest": "e" * 64,
            "evaluation_run_digest": "f" * 64,
            "evaluator_ref": "actor:evaluator",
            "evaluator_identity_digest": "5" * 64,
            "verifier_ref": "actor:verifier",
            "verifier_identity_digest": "6" * 64,
            "tested_model_digest": "1" * 64,
            "verifier_model_digest": "2" * 64,
            "environment_digest": "3" * 64,
            "trial_count": 3,
            "passed_trials": 3,
            "score_basis_points": 9500,
            "evaluated_at": "2026-08-16T08:00:00Z",
        }
        evaluated = self.service.execute(
            ServiceRequest(
                "cli",
                "skill.evaluate",
                {"candidate": candidate.as_payload(), "evaluation": evaluation_args},
            )
        )
        planned = self.service.execute(
            ServiceRequest(
                "cli",
                "skill.plan-change",
                {
                    "change_kind": "activation",
                    "candidate": candidate.as_payload(),
                    "evaluation": evaluated.data["evaluation"],
                    "expected_registry_digest": None,
                    "rollback_target_ref": "registry:empty",
                    "approver_identity_digest": "7" * 64,
                },
            )
        )
        self.assertEqual("planned", planned.status)
        self.assertTrue(planned.data["approval_required"])
        self.assertFalse(planned.data["registry_mutated"])
        self.assertFalse(any("skill-registry" in str(path) for path in self.home.rglob("*")))

    def test_memory_measurement_and_hygiene_are_content_free_reads(self) -> None:
        arguments = {
            "evaluation_id": "context-evaluation",
            "required_evidence_refs": ["evidence:one", "evidence:two"],
            "recalled_evidence_refs": ["evidence:one", "evidence:two"],
            "selected_bytes": 1000,
            "used_bytes": 800,
            "selected_tokens": 250,
            "used_tokens": 200,
            "selected_count": 10,
            "stale_selected_count": 0,
            "duplicate_selected_count": 0,
            "omitted_required_count": 0,
            "downstream_success_basis_points": 10000,
            "compaction_rehydration_passed": True,
        }
        measured = self.service.execute(
            ServiceRequest("cli", "memory.context-effectiveness", arguments)
        )
        self.assertTrue(measured.data["evaluation"]["passed"])
        report = self.service.execute(
            ServiceRequest(
                "cli",
                "memory.hygiene",
                {
                    "report_id": "hygiene-report",
                    "as_of": "2026-08-16T00:00:00Z",
                    "memories": [],
                    "research_evidence": [],
                    "context_evaluations": [measured.data["evaluation"]],
                },
            )
        )
        self.assertEqual([], report.data["report"]["action_suggestions"])
        self.assertFalse(report.data["automatic_actions_performed"])

    def test_benchmark_prepare_and_injected_execution_use_exact_digest(self) -> None:
        fixture = benchmark_fixtures.ModelBenchmarkRunnerTests()
        model = fixture.model()
        selected_suite = benchmark_fixtures.suite()
        health = fixture.health(model)
        profile = fixture.profile(model)
        common = {
            "suite": selected_suite,
            "model": model,
            "health_record": health,
            "execution_profile": profile,
            "current_source_digest": selected_suite["source_digest"],
        }
        prepared = self.service.execute(
            ServiceRequest(
                "cli",
                "model.benchmark-prepare",
                {
                    **common,
                    "workload_id": "analysis-primary",
                    "repetitions": 5,
                    "model_assignment_id": "analysis-assignment",
                    "timeout_ms": 5000,
                    "now": "2026-08-16T00:00:00Z",
                },
            )
        )
        calls = []

        def adapter(payload):
            calls.append(payload)
            return fixture.outcome(int(payload["repetition"]))

        service = KrcnApplicationService(
            REPO_ROOT,
            self.store,
            model_benchmark_adapters={"runner-model": adapter},
        )
        with self.assertRaisesRegex(ApplicationServiceError, "exact plan digest"):
            service.execute(
                ServiceRequest(
                    "cli",
                    "model.benchmark-execute",
                    {
                        **common,
                        "plan": prepared.data["plan"],
                        "observed_at": "2026-08-16T00:00:00Z",
                    },
                    apply=True,
                    expected_plan_id="0" * 64,
                    approval_id="benchmark-approval",
                )
            )
        result = service.execute(
            ServiceRequest(
                "cli",
                "model.benchmark-execute",
                {
                    **common,
                    "plan": prepared.data["plan"],
                    "observed_at": "2026-08-16T00:00:00Z",
                },
                apply=True,
                expected_plan_id=prepared.data["expected_plan_id"],
                approval_id="benchmark-approval",
            )
        )
        self.assertEqual("applied", result.status)
        self.assertEqual(5, len(calls))
        self.assertFalse(result.data["persisted"])

    def test_remote_benchmark_preparation_requires_exact_provider_approval(self) -> None:
        fixture = benchmark_fixtures.ModelBenchmarkRunnerTests()
        model = fixture.model(remote=True)
        selected_suite = benchmark_fixtures.suite()
        arguments = {
            "suite": selected_suite,
            "model": model,
            "health_record": fixture.health(model),
            "execution_profile": fixture.profile(model),
            "current_source_digest": selected_suite["source_digest"],
            "workload_id": "analysis-primary",
            "repetitions": 5,
            "model_assignment_id": "analysis-assignment",
            "timeout_ms": 5000,
            "now": "2026-08-16T00:00:00Z",
            "provider_disclosure": {
                "provider": "remote-provider",
                "endpoint": "https://provider.invalid/v1",
                "data_categories": ["synthetic-fixture"],
                "operation_scope": "model-benchmark",
                "retention_assumptions": "No retention for synthetic fixture.",
                "session_id": "benchmark-session",
                "remote": True,
                "authorization_ref": "benchmark-authorization",
            },
        }
        with self.assertRaisesRegex(ApplicationServiceError, "approval"):
            self.service.execute(
                ServiceRequest("cli", "model.benchmark-prepare", arguments)
            )
        prepared = self.service.execute(
            ServiceRequest(
                "cli",
                "model.benchmark-prepare",
                arguments,
                approval_id="provider-approval",
            )
        )
        serialized = json.dumps(prepared.as_dict())
        self.assertNotIn("provider.invalid", serialized)
        self.assertFalse(prepared.data["provider_call_performed"])

    def test_default_cli_benchmark_execute_is_explicitly_blocked_and_readable(self) -> None:
        parser = build_parser()
        parsed = parser.parse_args(
            ["models", "benchmark", "prepare", "--request-file", "request.json"]
        )
        self.assertEqual("prepare", parsed.benchmark_command)
        request_path = Path(self.temporary.name) / "execute.json"
        request_path.write_text(
            json.dumps(
                {
                    "plan": {},
                    "suite": {},
                    "model": {"model_ref": "runner-model"},
                    "health_record": {},
                    "execution_profile": {},
                    "current_source_digest": "a" * 64,
                    "observed_at": "2026-08-16T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(
                [
                    "models",
                    "benchmark",
                    "execute",
                    "--repo",
                    str(REPO_ROOT),
                    "--data-root",
                    str(self.home),
                    "--request-file",
                    str(request_path),
                    "--apply",
                    "--approval-id",
                    "benchmark-approval",
                ]
            )
        self.assertEqual(3, exit_code)
        self.assertIn("benchmark-adapter-unavailable", output.getvalue())
        self.assertIn("Çalıştırıldı", output.getvalue())


if __name__ == "__main__":
    unittest.main()
