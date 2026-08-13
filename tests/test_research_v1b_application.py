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
    ServiceRequest,
    create_application_service,
)
from krcn_core.cli.app import main  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.research_runtime import RESEARCH_DAG  # noqa: E402
from krcn_core.research_execution import ProcessOutcome  # noqa: E402
from krcn_core.provider_gate import create_provider_request  # noqa: E402
from krcn_core.work_graph import apply_work_item, prepare_work_item  # noqa: E402


def authorize(plan):
    return authorize_mutation(
        plan,
        dry_run=DryRunEvidence(plan.plan_id, verified=True),
        approval=(
            ApprovalEvidence(plan.plan_id, "test-approval", approved=True)
            if plan.approval_required
            else None
        ),
    )


class ResearchV1BApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / ".krcn"
        self.home.mkdir()
        (self.home / "layout.json").write_bytes(user_home_layout_bytes())
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        store = LocalWorkspaceStore(self.home, ownership)
        project = {
            "schema_version": 1,
            "project_id": "gpu-fusion",
            "name": "gpu-fusion",
            "description": "V1B native research pilot",
            "status": "active",
            "source_refs": [],
            "modules": [],
            "technologies": [],
            "skill_refs": [],
        }
        project_plan = store.prepare_put(
            "projects", "gpu-fusion", project,
            expected_revision=0, project_id="gpu-fusion",
        )
        store.apply_put(project_plan, authorize(project_plan.mutation))
        work_plan = prepare_work_item(
            store,
            ownership,
            {
                "work_item_id": "gtd-893614",
                "project_id": "gpu-fusion",
                "work_type": "task",
                "title": "Research pilot",
                "description": "V1B runtime research",
                "status": "active",
                "acceptance_criteria": ["Native research completes"],
                "relations": [],
                "evidence": [],
                "provenance": {"source_kind": "user", "source_ref": "test"},
            },
        )
        apply_work_item(
            store,
            work_plan,
            {effect.plan_id: authorize(effect) for effect in work_plan.effect_plans},
        )
        self.work_item = work_plan.item
        self.service = create_application_service(
            REPO_ROOT,
            self.home,
            research_execution_adapters={role: self.fake_adapter for role in RESEARCH_DAG},
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def fake_adapter(unit):
        response = f"# {unit.role}\n\nVerified fake result.\n"
        session_id = f"gpu-fusion-{unit.role}"
        provider_request = create_provider_request(
            provider="deterministic-hashing", endpoint="local-deterministic-runtime",
            data_categories=("research-prompt",), operation_scope="research-execution",
            retention_assumptions="No remote retention", session_id=session_id, remote=False,
        )
        return {
            "execution_mode": "native",
            "worker_id": f"fake-{unit.role}",
            "agent_result": {
                "status": "completed",
                "summary": f"Completed {unit.role}",
                "evidence": [{"kind": "test", "reference": unit.role}],
                "changes": [],
                "preserved_areas": ["project-source"],
            },
            "research_result": {
                "response_markdown": response,
                "findings": {"sources": [], "claims": [], "conflicts": []},
            },
            "execution": {
                "schema_ref": "schemas/research-execution-result.schema.json",
                "schema_version": 1,
                "status": "completed",
                "client_id": "codex-cli",
                "provider": "deterministic-hashing",
                "provider_request_id": provider_request.request_id,
                "session_id": session_id,
                "model_ref": None,
                "response_markdown": response,
                "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                "stderr_sha256": "b" * 64,
                "exit_code": 0,
                "duration_ms": 1,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "executable_ref_sha256": "c" * 64,
                "cwd_sha256": "d" * 64,
                "output_contract": "research-agent-result-v1",
                "provider_authority_granted": False,
                "physical_paths_included": False,
                "credential_values_included": False,
            },
        }

    def dispatch_arguments(self) -> dict[str, object]:
        capabilities = {
            "native_subagents": True,
            "parallel_subagents": True,
            "per_agent_model_selection": False,
            "agent_cancellation": True,
            "structured_results": True,
            "isolated_role_execution": False,
        }
        executions = {}
        for role in RESEARCH_DAG:
            session_id = f"gpu-fusion-{role}"
            disclosure = {
                "provider": "deterministic-hashing",
                "endpoint": "local-deterministic-runtime",
                "data_categories": ["research-prompt"],
                "operation_scope": "research-execution",
                "retention_assumptions": "No remote retention",
                "session_id": session_id,
                "remote": False,
            }
            provider_request = create_provider_request(
                provider="deterministic-hashing",
                endpoint="local-deterministic-runtime",
                data_categories=("research-prompt",),
                operation_scope="research-execution",
                retention_assumptions="No remote retention",
                session_id=session_id,
                remote=False,
            )
            executions[role] = {
                "worker_id": f"fake-{role}",
                "execution_request": {
                    "schema_ref": "schemas/research-execution-request.schema.json",
                    "schema_version": 1,
                    "client_id": "codex-cli",
                    "cwd": str(self.root),
                    "cwd_boundary": str(self.root),
                    "provider": "deterministic-hashing",
                    "provider_request_id": provider_request.request_id,
                    "session_id": session_id,
                    "output_contract": "research-agent-result-v1",
                },
                "provider_disclosure": disclosure,
            }
        return {
            "project_id": "gpu-fusion",
            "work_item_id": "gtd-893614",
            "work_item_revision": self.work_item.revision,
            "work_item_digest": self.work_item.work_digest,
            "research_id": "gpu-fusion-v1b-pilot",
            "task_plan_id": hashlib.sha256(b"gpu-fusion-v1b-plan").hexdigest(),
            "prompts": {role: f"Bounded prompt for {role}" for role in RESEARCH_DAG},
            "max_concurrency": 2,
            "delegation": {
                "session_id": "gpu-fusion-v1b-session",
                "client_id": "codex-desktop",
                "capabilities": capabilities,
                "max_parallel_agents": 2,
                "work_class": "project-analysis",
                "project_matched": True,
            },
            "executions": executions,
        }

    def test_gpu_fusion_fake_adapter_dispatch_uses_exact_plan(self) -> None:
        arguments = self.dispatch_arguments()
        planned = self.service.execute(
            ServiceRequest("codex", "research.dispatch", arguments)
        )
        self.assertEqual("planned", planned.status)
        plan_id = str(planned.data["plan"]["plan_id"])
        self.assertTrue(planned.data["plan"]["execution_adapter_available"])
        with self.assertRaisesRegex(ApplicationServiceError, "exact"):
            self.service.execute(
                ServiceRequest(
                    "codex", "research.dispatch", arguments, apply=True,
                    expected_plan_id="0" * 64, approval_id="pilot-approval",
                )
            )
        applied = self.service.execute(
            ServiceRequest(
                "codex", "research.dispatch", arguments, apply=True,
                expected_plan_id=plan_id, approval_id="pilot-approval",
            )
        )
        self.assertEqual("applied", applied.status)
        self.assertTrue(applied.data["result"]["native_completion"])
        status = self.service.execute(
            ServiceRequest(
                "codex", "research.runtime-status",
                {"project_id": "gpu-fusion", "research_id": "gpu-fusion-v1b-pilot"},
            )
        )
        self.assertEqual({"completed": 5}, status.data["result"]["counts"])

    def test_gemini_is_optional_and_does_not_gain_execution_authority(self) -> None:
        request = {
            "schema_ref": "schemas/research-execution-request.schema.json",
            "schema_version": 1,
            "client_id": "gemini",
            "cwd": str(self.root),
            "cwd_boundary": str(self.root),
            "provider": "gemini",
            "provider_request_id": "a" * 64,
            "session_id": "optional-gemini-session",
        }
        response = self.service.execute(
            ServiceRequest(
                "codex", "research.availability",
                {"execution_request": request},
            )
        )
        self.assertEqual("ok", response.status)
        self.assertFalse(response.data["availability"]["available"])
        self.assertTrue(response.data["availability"]["optional"])
        self.assertFalse(response.data["gemini_required"])
        self.assertFalse(response.data["authority_granted"])

    def test_default_factory_executes_structured_cli_results(self) -> None:
        class Runner:
            def run(inner_self, _argv, **_kwargs):
                payload = {
                    "schema_ref": "schemas/research-agent-output.schema.json",
                    "schema_version": 1,
                    "agent_result": {
                        "status": "completed", "summary": "Native structured result",
                        "evidence": [{"kind": "test", "reference": "runtime:fake"}],
                        "changes": [], "preserved_areas": ["project-source"],
                    },
                    "research_result": {
                        "response_markdown": "# Native result\n",
                        "findings": {"sources": [], "claims": [], "conflicts": []},
                    },
                }
                stdout = json.dumps(
                    {"item": {"type": "agent_message", "text": json.dumps(payload)}}
                ).encode("utf-8")
                return ProcessOutcome(0, stdout, b"", 1)

        service = create_application_service(
            REPO_ROOT,
            self.home,
            research_process_runners={role: Runner() for role in RESEARCH_DAG},
            research_executable_resolver=lambda _reference: "codex.cmd",
        )
        arguments = self.dispatch_arguments()
        planned = service.execute(ServiceRequest("codex", "research.dispatch", arguments))
        applied = service.execute(
            ServiceRequest(
                "codex", "research.dispatch", arguments, apply=True,
                expected_plan_id=str(planned.data["plan"]["plan_id"]),
                approval_id="native-test-approval",
            )
        )
        self.assertTrue(applied.data["result"]["native_completion"])

    def test_authoritative_work_item_and_provider_assignment_must_match(self) -> None:
        stale = self.dispatch_arguments()
        stale["work_item_digest"] = "0" * 64
        with self.assertRaisesRegex(ApplicationServiceError, "authoritative active record"):
            self.service.execute(ServiceRequest("codex", "research.dispatch", stale))
        mismatch = self.dispatch_arguments()
        mismatch["executions"]["researcher"]["execution_request"]["provider_request_id"] = "0" * 64
        with self.assertRaisesRegex(ApplicationServiceError, "exact provider request"):
            self.service.execute(ServiceRequest("codex", "research.dispatch", mismatch))

    def test_cancel_without_same_process_dispatch_is_explicitly_unavailable(self) -> None:
        arguments = {"project_id": "gpu-fusion", "research_id": "separate-process"}
        planned = self.service.execute(ServiceRequest("codex", "research.cancel", arguments))
        response = self.service.execute(
            ServiceRequest(
                "codex", "research.cancel", arguments, apply=True,
                expected_plan_id=str(planned.data["plan"]["plan_id"]),
                approval_id="cancel-approval",
            )
        )
        self.assertEqual("unavailable", response.status)
        self.assertFalse(response.data["separate_process_supported"])

    def test_cancellation_registry_is_project_scoped(self) -> None:
        self.service._research_cancellations[("other-project", "shared-run")] = __import__("threading").Event()
        response = self.service.execute(
            ServiceRequest(
                "codex", "research.runtime-status",
                {"project_id": "gpu-fusion", "research_id": "shared-run"},
            )
        )
        self.assertFalse(response.data["result"]["process_local_running"])

    def test_cli_exposes_runtime_status_without_inventing_an_adapter(self) -> None:
        request_file = self.root / "runtime-status.json"
        request_file.write_text(
            json.dumps(
                {
                    "project_id": "gpu-fusion",
                    "research_id": "gpu-fusion-v1b-pilot",
                }
            ),
            encoding="utf-8",
        )
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            exit_code = main(
                [
                    "research", "runtime-status",
                    "--request-file", str(request_file),
                    "--repo", str(REPO_ROOT),
                    "--data-root", str(self.home),
                ]
            )
        self.assertEqual(0, exit_code, error.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual("research.runtime-status", payload["operation"])
        self.assertFalse(payload["data"]["result"]["native_completion"])

    def test_cli_cancel_in_a_separate_process_reports_nonzero_unavailable(self) -> None:
        request_file = self.root / "cancel.json"
        request_file.write_text(
            json.dumps({"project_id": "gpu-fusion", "research_id": "separate-process"}),
            encoding="utf-8",
        )
        planned_output = io.StringIO()
        with redirect_stdout(planned_output), redirect_stderr(io.StringIO()):
            planned_code = main(
                [
                    "research", "cancel", "--request-file", str(request_file),
                    "--repo", str(REPO_ROOT), "--data-root", str(self.home),
                ]
            )
        self.assertEqual(0, planned_code)
        plan_id = json.loads(planned_output.getvalue())["data"]["plan"]["plan_id"]
        applied_output = io.StringIO()
        with redirect_stdout(applied_output), redirect_stderr(io.StringIO()):
            applied_code = main(
                [
                    "research", "cancel", "--request-file", str(request_file),
                    "--repo", str(REPO_ROOT), "--data-root", str(self.home),
                    "--apply", "--expected-plan", plan_id, "--approval-id", "cancel-approval",
                ]
            )
        self.assertEqual(3, applied_code)
        self.assertEqual("unavailable", json.loads(applied_output.getvalue())["status"])


if __name__ == "__main__":
    unittest.main()
