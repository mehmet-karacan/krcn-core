from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.information_records import canonical_json  # noqa: E402
from krcn_core.application import KrcnApplicationService  # noqa: E402
from krcn_core.application_contract import ServiceRequest  # noqa: E402
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.model_benchmark_runner import (  # noqa: E402
    ModelBenchmarkRunnerError,
    aggregate_model_benchmark_trials,
    build_benchmark_execution_profile,
    build_benchmark_execution_claim,
    build_benchmark_execution_host_descriptor,
    build_benchmark_execution_receipt,
    build_execution_authorization_digest,
    execute_model_benchmark_run,
    load_model_benchmark_runner_policy,
    parse_benchmark_execution_profile,
    parse_model_benchmark_aggregate_result,
    parse_model_benchmark_run_plan,
    parse_model_benchmark_trial_result,
    prepare_model_benchmark_run,
    resolve_authoritative_benchmark_inputs,
)
from krcn_core.model_health import (  # noqa: E402
    ModelHealthObservation,
    build_model_health_record,
    load_model_health_policy,
)
from krcn_core.model_inventory import build_model_inventory_record  # noqa: E402
from krcn_core.mutation_gate import (  # noqa: E402
    ApprovalEvidence,
    DryRunEvidence,
    OwnershipResolver,
    authorize_mutation,
)
from krcn_core.provider_gate import (  # noqa: E402
    ProviderApproval,
    ProviderAuthorization,
    authorize_provider_request,
    create_provider_request,
    load_provider_gate_policy,
)


def digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


class DurableFakeBenchmarkHost:
    def __init__(self, adapter, *, model_ref: str = "runner-model") -> None:
        self.adapter = adapter
        self.descriptor = build_benchmark_execution_host_descriptor(
            host_id="durable-test-host",
            ledger_ref="test-ledger",
            model_ref=model_ref,
        )
        self.claims: dict[str, dict[str, object]] = {}
        self.receipts: dict[str, dict[str, object]] = {}
        self.trial_calls = 0

    def describe(self) -> dict[str, object]:
        return dict(self.descriptor)

    def get_claim(self, plan_digest: str) -> dict[str, object] | None:
        claim = self.claims.get(plan_digest)
        return None if claim is None else dict(claim)

    def get_receipt(
        self,
        claim: dict[str, object],
    ) -> dict[str, object] | None:
        receipt = self.receipts.get(str(claim["plan_digest"]))
        return None if receipt is None else dict(receipt)

    def claim(self, request: dict[str, object]) -> dict[str, object]:
        plan_digest = str(request["plan_digest"])
        if plan_digest in self.claims:
            raise RuntimeError("durable ledger rejects replay")
        claim = build_benchmark_execution_claim(
            request,
            claim_id="claim-" + plan_digest[:24],
        )
        self.claims[plan_digest] = claim
        return claim

    def run_trial(
        self,
        claim: dict[str, object],
        request: dict[str, object],
    ) -> dict[str, object]:
        self.trial_calls += 1
        return self.adapter(request)

    def complete(
        self,
        claim: dict[str, object],
        request: dict[str, object],
    ) -> dict[str, object]:
        receipt = build_benchmark_execution_receipt(
            request,
            receipt_id="receipt-" + str(request["plan_digest"])[:24],
        )
        self.receipts[str(request["plan_digest"])] = receipt
        return receipt

    def complete_failure(
        self,
        claim: dict[str, object],
        request: dict[str, object],
    ) -> dict[str, object]:
        receipt = build_benchmark_execution_receipt(
            request,
            receipt_id="failure-receipt-" + str(request["plan_digest"])[:16],
        )
        self.receipts[str(request["plan_digest"])] = receipt
        return receipt


def suite(*, fixture_policy: str = "synthetic-only") -> dict[str, object]:
    case_semantic = {
        "workload_id": "analysis-primary",
        "workload_kind": "analysis",
        "workload_digest": "a" * 64,
        "template_id": "profile-analysis-v1",
        "fixture_policy": fixture_policy,
        "remote_eligible": fixture_policy != "local-only",
        "trust_role": "worker",
        "specialization_profile_id": "analysis-profile",
        "context": {
            "capability_refs": ["python"],
            "module_refs": ["core"],
            "evidence_refs": [],
        },
        "fixture_descriptor": {
            "technology_refs": ["python"],
            "framework_refs": [],
            "database_refs": [],
            "testing_refs": ["unittest"],
            "quality_refs": ["evidence-bound"],
        },
        "required_output_sections": ["answer", "evidence", "risks"],
        "rubric": {
            "quality_weight": 80,
            "reliability_weight": 10,
            "latency_weight": 10,
            "dimension_refs": ["evidence"],
            "evaluation_traits": ["correctness"],
        },
    }
    case_digest = digest(case_semantic)
    case = {
        "case_id": f"case-{case_digest}",
        **case_semantic,
        "case_digest": case_digest,
    }
    semantic = {
        "suite_id": "runner-project-micro-benchmark",
        "project_id": "runner-project",
        "profile_digest": "b" * 64,
        "capability_digest": "c" * 64,
        "source_digest": "d" * 64,
        "builder": {
            "builder_id": "project-micro-benchmark-v1",
            "builder_revision": 1,
            "policy_revision": 1,
            "policy_digest": "e" * 64,
        },
        "cases": [case],
        "case_count": 1,
        "remote_eligible_case_count": int(fixture_policy != "local-only"),
        "local_only_case_count": int(fixture_policy == "local-only"),
        "invariants": {
            "source_content_included": False,
            "prompt_content_included": False,
            "secret_values_included": False,
            "absolute_paths_included": False,
            "remote_call_performed": False,
            "grants_authority": False,
        },
    }
    return {
        "schema_ref": "schemas/model-benchmark-suite.schema.json",
        "schema_version": 1,
        **semantic,
        "suite_revision": 1,
        "suite_digest": digest(semantic),
    }


class ModelBenchmarkRunnerTests(unittest.TestCase):
    now = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)

    def model(self, *, remote: bool = False) -> dict[str, object]:
        return build_model_inventory_record(
            {
                "model_ref": "runner-model",
                "provider_ref": "remote-provider" if remote else "local-provider",
                "model_id": "runner/model-v1",
                "display_name": "Runner model",
                "modalities": ["text"],
                "supported_workloads": ["analysis", "verification"],
                "client_refs": ["codex"],
                "remote": remote,
                "enabled": True,
            },
            revision=1,
        )

    def health(self, model: dict[str, object], *, passed: bool = True) -> dict[str, object]:
        return build_model_health_record(
            model,
            load_model_health_policy(REPO_ROOT),
            ModelHealthObservation(
                available=passed,
                protocol_valid=passed,
                response_parseable=passed,
                response_matches=passed,
                latency_ms=25,
                failure_category=None if passed else "unavailable",
            ),
            checked_at=self.now,
        )

    def profile(self, model: dict[str, object], *, revision: str = "2026.08.16") -> dict[str, object]:
        return build_benchmark_execution_profile(
            model,
            client_id="codex",
            harness_id="codex-cli",
            harness_revision="1.0.0",
            model_revision=revision,
            model_family="primary-family",
            execution_ref="worker-execution",
            provider_route_ref="declared-route",
            quantization="none",
            reasoning_effort="high",
            reasoning_budget_tokens=4096,
            environment_digest="f" * 64,
            verifier_execution_ref="verifier-execution",
            verifier_model_family="independent-family",
        )

    def plan(
        self,
        *,
        model: dict[str, object] | None = None,
        fixture_policy: str = "synthetic-only",
        repetitions: int = 5,
        provider_authorization: ProviderAuthorization | None = None,
        provider_authorization_ref: str | None = None,
        provider_approval_id: str | None = None,
        execution_host: DurableFakeBenchmarkHost | None = None,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
        selected = model or self.model()
        selected_suite = suite(fixture_policy=fixture_policy)
        selected_health = self.health(selected)
        selected_profile = self.profile(selected)
        self.execution_host = execution_host or DurableFakeBenchmarkHost(
            lambda request: self.outcome(int(request["repetition"])),
            model_ref=str(selected["model_ref"]),
        )
        plan = prepare_model_benchmark_run(
            REPO_ROOT,
            suite=selected_suite,
            model=selected,
            health_record=selected_health,
            execution_profile=selected_profile,
            current_source_digest=str(selected_suite["source_digest"]),
            execution_host_descriptor=self.execution_host.describe(),
            workload_id="analysis-primary",
            repetitions=repetitions,
            model_assignment_id="analysis-assignment",
            timeout_ms=5000,
            now=self.now,
            provider_authorization=provider_authorization,
            provider_authorization_ref=provider_authorization_ref,
            provider_approval_id=provider_approval_id,
        )
        return plan, selected_suite, selected_health, selected_profile

    @staticmethod
    def outcome(index: int) -> dict[str, object]:
        return {
            "quality_score_basis_points": 8000 + index * 100,
            "reliability_score_basis_points": 9000,
            "latency_ms": index * 100,
            "input_tokens": index * 10,
            "output_tokens": index * 5,
            "retry_count": index % 2,
            "human_corrections": 0,
            "estimated_cost_microunits": index * 20,
            "actual_cost_microunits": index * 18,
            "parse_passed": True,
            "format_passed": True,
            "evidence_passed": True,
            "verifier_passed": True,
            "timed_out": False,
            "failure_category": None,
            "verifier_execution_ref": "verifier-execution",
            "verifier_model_family": "independent-family",
        }

    def authoritative_store(self, *, remote: bool = False):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        source = root / "authoritative-project"
        (source / "src").mkdir(parents=True)
        (source / "tests").mkdir()
        (source / "package.json").write_text(
            json.dumps(
                {
                    "name": "authoritative-project",
                    "dependencies": {"fastapi": "1.0.0"},
                    "scripts": {"test": "python -m unittest"},
                }
            ),
            encoding="utf-8",
        )
        (source / "src" / "main.py").write_text("value = 1\n", encoding="utf-8")
        (source / "tests" / "test_main.py").write_text(
            "import unittest\n",
            encoding="utf-8",
        )
        home = root / ".krcn"
        home.mkdir()
        (home / "layout.json").write_bytes(user_home_layout_bytes())
        ownership = OwnershipResolver.from_repository(REPO_ROOT)
        store = LocalWorkspaceStore(home, ownership)
        service = KrcnApplicationService(REPO_ROOT, store)
        integration = service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(source), "scan_mode": "manual"},
            )
        )
        service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(source), "scan_mode": "manual"},
                apply=True,
                expected_plan_id=integration.data["plan"]["plan_id"],
                approval_id="integration-approval",
            )
        )
        suite_plan = service.execute(
            ServiceRequest(
                "codex",
                "model.benchmark-suite",
                {"project_id": "authoritative-project"},
            )
        )
        service.execute(
            ServiceRequest(
                "codex",
                "model.benchmark-suite",
                {"project_id": "authoritative-project"},
                apply=True,
                expected_plan_id=suite_plan.data["plan"]["plan_id"],
            )
        )
        model = self.model(remote=remote)
        inventory_plan = store.prepare_put(
            "model-inventory",
            str(model["model_ref"]),
            model,
            expected_revision=0,
        )
        inventory_authorization = authorize_mutation(
            inventory_plan.mutation,
            dry_run=DryRunEvidence(inventory_plan.mutation.plan_id, verified=True),
            approval=ApprovalEvidence(
                inventory_plan.mutation.plan_id,
                "inventory-approval",
                True,
            ),
        )
        store.apply_put(inventory_plan, inventory_authorization)
        health = self.health(model)
        health_plan = store.prepare_put(
            "model-health",
            str(model["model_ref"]),
            health,
            expected_revision=0,
        )
        health_authorization = authorize_mutation(
            health_plan.mutation,
            dry_run=DryRunEvidence(health_plan.mutation.plan_id, verified=True),
        )
        store.apply_put(health_plan, health_authorization)
        return temporary, source, store, service

    def test_local_injected_adapter_executes_repeated_trials_and_statistics(self) -> None:
        model = self.model()
        calls: list[dict[str, object]] = []

        def adapter(request: dict[str, object]) -> dict[str, object]:
            calls.append(request)
            return self.outcome(int(request["repetition"]))

        host = DurableFakeBenchmarkHost(adapter)
        plan, selected_suite, health, profile = self.plan(
            model=model,
            execution_host=host,
        )

        result = execute_model_benchmark_run(
            REPO_ROOT,
            plan,
            expected_plan_id=str(plan["plan_id"]),
            suite=selected_suite,
            model=model,
            health_record=health,
            execution_profile=profile,
            current_source_digest=str(selected_suite["source_digest"]),
            execution_host=host,
            execution_authorization_digest=build_execution_authorization_digest(
                plan_digest=str(plan["plan_digest"]),
                approval_id="execution-approval",
            ),
            observed_at=self.now,
        )
        payload = result.as_dict()
        self.assertEqual(5, len(calls))
        self.assertEqual(5, payload["aggregate"]["sample_count"])
        self.assertEqual(
            {"mean": 300, "median": 300, "p95": 500, "variance": 20000},
            payload["aggregate"]["statistics"]["latency_ms"],
        )
        self.assertEqual(300, payload["aggregate"]["totals"]["estimated_cost_microunits"])
        self.assertEqual(60, payload["aggregate"]["cost_per_verifier_approved_result_microunits"])
        self.assertEqual(1, len(payload["benchmark_records"]))
        self.assertEqual(5, len(payload["runtime_observations"]))
        self.assertTrue(payload["benchmark_records"][0]["passed"])
        self.assertEqual("claimed", payload["execution_claim"]["status"])
        self.assertEqual("completed", payload["execution_receipt"]["status"])
        self.assertEqual(1, len(host.receipts))
        self.assertFalse(payload["store_mutated"])
        for request in calls:
            self.assertFalse(request["raw_content_included"])
            self.assertNotIn("prompt", request)
            self.assertNotIn("output", request)
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "claim"):
            execute_model_benchmark_run(
                REPO_ROOT,
                plan,
                expected_plan_id=str(plan["plan_id"]),
                suite=selected_suite,
                model=model,
                health_record=health,
                execution_profile=profile,
                current_source_digest=str(selected_suite["source_digest"]),
                execution_host=host,
                execution_authorization_digest=build_execution_authorization_digest(
                    plan_digest=str(plan["plan_digest"]),
                    approval_id="execution-approval",
                ),
                observed_at=self.now,
            )
        self.assertEqual(5, len(calls))

    def test_one_shot_and_non_confidence_safe_samples_are_rejected(self) -> None:
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "repetitions"):
            self.plan(repetitions=1)
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "confidence-safe"):
            self.plan(repetitions=4)

    def test_authoritative_resolver_rejects_empty_store_and_ignores_caller_substitutes(self) -> None:
        with tempfile.TemporaryDirectory() as empty_root:
            empty_home = Path(empty_root)
            (empty_home / "layout.json").write_bytes(user_home_layout_bytes())
            empty_store = LocalWorkspaceStore(
                empty_home,
                OwnershipResolver.from_repository(REPO_ROOT),
            )
            with self.assertRaisesRegex(ModelBenchmarkRunnerError, "authoritative"):
                resolve_authoritative_benchmark_inputs(
                    REPO_ROOT,
                    empty_store,
                    project_id="authoritative-project",
                    suite_id="authoritative-project-micro-benchmark",
                    model_ref="runner-model",
                )
        temporary, _, store, _ = self.authoritative_store()
        try:
            resolved = resolve_authoritative_benchmark_inputs(
                REPO_ROOT,
                store,
                project_id="authoritative-project",
                suite_id="authoritative-project-micro-benchmark",
                model_ref="runner-model",
            )
            self.assertEqual("authoritative-project", resolved.suite["project_id"])
            self.assertEqual("runner-model", resolved.model["model_ref"])
            with self.assertRaisesRegex(ModelBenchmarkRunnerError, "mismatch"):
                resolve_authoritative_benchmark_inputs(
                    REPO_ROOT,
                    store,
                    project_id="another-project",
                    suite_id="authoritative-project-micro-benchmark",
                    model_ref="runner-model",
                )
        finally:
            temporary.cleanup()

    def test_authoritative_resolver_rejects_stale_source_profile(self) -> None:
        temporary, source, store, service = self.authoritative_store()
        try:
            (source / "src" / "main.py").write_text("value = 2\n", encoding="utf-8")
            integration = service.execute(
                ServiceRequest(
                    "codex",
                    "project.integrate",
                    {"source_root": str(source), "scan_mode": "manual"},
                )
            )
            service.execute(
                ServiceRequest(
                    "codex",
                    "project.integrate",
                    {"source_root": str(source), "scan_mode": "manual"},
                    apply=True,
                    expected_plan_id=integration.data["plan"]["plan_id"],
                    approval_id="reintegration-approval",
                )
            )
            with self.assertRaisesRegex(ModelBenchmarkRunnerError, "stale"):
                resolve_authoritative_benchmark_inputs(
                    REPO_ROOT,
                    store,
                    project_id="authoritative-project",
                    suite_id="authoritative-project-micro-benchmark",
                    model_ref="runner-model",
                )
        finally:
            temporary.cleanup()

    def test_health_passed_is_required(self) -> None:
        model = self.model()
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "health-passed"):
            prepare_model_benchmark_run(
                REPO_ROOT,
                suite=suite(),
                model=model,
                health_record=self.health(model, passed=False),
                execution_profile=self.profile(model),
                current_source_digest=str(suite()["source_digest"]),
                execution_host_descriptor=build_benchmark_execution_host_descriptor(
                    host_id="durable-test-host",
                    ledger_ref="test-ledger",
                    model_ref="runner-model",
                ),
                workload_id="analysis-primary",
                repetitions=5,
                model_assignment_id="analysis-assignment",
                timeout_ms=5000,
                now=self.now,
            )

    def test_remote_requires_exact_authorization_and_local_only_is_never_remote(self) -> None:
        model = self.model(remote=True)
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "provider authorization"):
            self.plan(model=model)
        request = create_provider_request(
            provider="remote-provider",
            endpoint="https://provider.invalid/v1",
            data_categories=("synthetic-test",),
            operation_scope="model-benchmark",
            retention_assumptions="no-retention-contract",
            session_id="session-1",
            remote=True,
        )
        approval = ProviderApproval(
            request_id=request.request_id,
            session_id=request.session_id,
            approval_id="approval-one",
            approved=True,
        )
        authorization = authorize_provider_request(
            load_provider_gate_policy(REPO_ROOT),
            request,
            approval=approval,
        )
        plan, selected_suite, health, profile = self.plan(
            model=model,
            provider_authorization=authorization,
            provider_authorization_ref="approval-one",
            provider_approval_id="approval-one",
        )
        self.assertEqual(request.request_id, plan["provider_request_id"])
        swapped = authorize_provider_request(
            load_provider_gate_policy(REPO_ROOT),
            request,
            approval=ProviderApproval(
                request_id=request.request_id,
                session_id=request.session_id,
                approval_id="approval-two",
                approved=True,
            ),
        )
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "changed"):
            execute_model_benchmark_run(
                REPO_ROOT,
                plan,
                expected_plan_id=str(plan["plan_id"]),
                suite=selected_suite,
                model=model,
                health_record=health,
                execution_profile=profile,
                current_source_digest=str(selected_suite["source_digest"]),
                execution_host=self.execution_host,
                execution_authorization_digest=build_execution_authorization_digest(
                    plan_digest=str(plan["plan_digest"]),
                    approval_id="execution-approval",
                ),
                observed_at=self.now,
                provider_authorization=swapped,
                provider_authorization_ref="approval-one",
                provider_approval_id="approval-two",
            )
        self.assertEqual(0, self.execution_host.trial_calls)
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "local-only"):
            self.plan(
                model=model,
                fixture_policy="local-only",
                provider_authorization=authorization,
                provider_authorization_ref="approval-one",
                provider_approval_id="approval-one",
            )

    def test_mixed_execution_profiles_are_never_pooled(self) -> None:
        model = self.model()
        plan, selected_suite, health, profile = self.plan(model=model)
        result = execute_model_benchmark_run(
            REPO_ROOT,
            plan,
            expected_plan_id=str(plan["plan_id"]),
            suite=selected_suite,
            model=model,
            health_record=health,
            execution_profile=profile,
            current_source_digest=str(selected_suite["source_digest"]),
            execution_host=self.execution_host,
            execution_authorization_digest=build_execution_authorization_digest(
                plan_digest=str(plan["plan_digest"]),
                approval_id="execution-approval",
            ),
            observed_at=self.now,
        )
        mixed = [copy.deepcopy(item) for item in result.trials]
        mixed[2]["execution_profile_digest"] = "1" * 64
        semantic = {
            key: mixed[2][key]
            for key in mixed[2]
            if key not in {"schema_ref", "schema_version", "trial_digest", "invariants"}
        }
        mixed[2]["trial_digest"] = digest(semantic)
        parse_model_benchmark_trial_result(mixed[2])
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "incomparable"):
            aggregate_model_benchmark_trials(
                REPO_ROOT,
                plan,
                mixed,
                observed_at="2026-08-16T00:00:00Z",
            )

    def test_tamper_is_fail_closed(self) -> None:
        plan, _, _, _ = self.plan()
        tampered = copy.deepcopy(plan)
        tampered["source_digest"] = "0" * 64
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "digest"):
            parse_model_benchmark_run_plan(
                tampered,
                policy=load_model_benchmark_runner_policy(REPO_ROOT),
            )

    def test_stale_current_source_is_rejected_before_adapter_execution(self) -> None:
        model = self.model()
        called = False

        def adapter(request: dict[str, object]) -> dict[str, object]:
            nonlocal called
            called = True
            return self.outcome(int(request["repetition"]))

        host = DurableFakeBenchmarkHost(adapter)
        plan, selected_suite, health, profile = self.plan(
            model=model,
            execution_host=host,
        )

        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "changed"):
            execute_model_benchmark_run(
                REPO_ROOT,
                plan,
                expected_plan_id=str(plan["plan_id"]),
                suite=selected_suite,
                model=model,
                health_record=health,
                execution_profile=profile,
                current_source_digest="0" * 64,
                execution_host=host,
                execution_authorization_digest=build_execution_authorization_digest(
                    plan_digest=str(plan["plan_digest"]),
                    approval_id="execution-approval",
                ),
                observed_at=self.now,
            )
        self.assertFalse(called)

    def test_adapter_exception_is_sanitized_and_does_not_stop_repetitions(self) -> None:
        model = self.model()
        calls = 0

        def adapter(request: dict[str, object]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            raise RuntimeError("api_key=do-not-reflect")

        host = DurableFakeBenchmarkHost(adapter)
        plan, selected_suite, health, profile = self.plan(
            model=model,
            execution_host=host,
        )

        result = execute_model_benchmark_run(
            REPO_ROOT,
            plan,
            expected_plan_id=str(plan["plan_id"]),
            suite=selected_suite,
            model=model,
            health_record=health,
            execution_profile=profile,
            current_source_digest=str(selected_suite["source_digest"]),
            execution_host=host,
            execution_authorization_digest=build_execution_authorization_digest(
                plan_digest=str(plan["plan_digest"]),
                approval_id="execution-approval",
            ),
            observed_at=self.now,
        )
        self.assertEqual(5, calls)
        self.assertFalse(result.aggregate["passed"])
        self.assertTrue(
            all(item["failure_category"] == "adapter-error" for item in result.trials)
        )
        self.assertNotIn("do-not-reflect", str(result.as_dict()))

    def test_secret_path_and_raw_adapter_fields_are_rejected_without_echo(self) -> None:
        model = self.model()
        physical_path = chr(67) + ":\\" + "Users\\person\\file.txt"

        def unsafe_adapter(request: dict[str, object]) -> dict[str, object]:
            return {
                **self.outcome(int(request["repetition"])),
                "raw_output": "api_key=supersecret " + physical_path,
            }

        host = DurableFakeBenchmarkHost(unsafe_adapter)
        plan, selected_suite, health, profile = self.plan(
            model=model,
            execution_host=host,
        )

        arguments = {
            "expected_plan_id": str(plan["plan_id"]),
            "suite": selected_suite,
            "model": model,
            "health_record": health,
            "execution_profile": profile,
            "current_source_digest": str(selected_suite["source_digest"]),
            "execution_host": host,
            "execution_authorization_digest": build_execution_authorization_digest(
                plan_digest=str(plan["plan_digest"]),
                approval_id="execution-approval",
            ),
            "observed_at": self.now,
        }
        first = execute_model_benchmark_run(REPO_ROOT, plan, **arguments)
        self.assertEqual("failed", first.as_dict()["status"])
        self.assertEqual("outcome-validation-failed", first.as_dict()["failure_category"])
        self.assertEqual(1, host.trial_calls)
        self.assertEqual(1, len(host.claims))
        self.assertEqual(1, len(host.receipts))
        replay = execute_model_benchmark_run(REPO_ROOT, plan, **arguments)
        self.assertEqual(first.as_dict(), replay.as_dict())
        self.assertFalse(replay.execution_performed)
        self.assertEqual(1, host.trial_calls)
        self.assertNotIn("supersecret", str(first.as_dict()))
        self.assertNotIn("Users", str(first.as_dict()))
        with self.assertRaises(ModelBenchmarkRunnerError):
            self.profile(model, revision=physical_path)

    def test_pending_claim_requires_explicit_recovery_without_trial(self) -> None:
        model = self.model()
        host = DurableFakeBenchmarkHost(
            lambda request: self.outcome(int(request["repetition"]))
        )
        plan, selected_suite, health, profile = self.plan(
            model=model,
            execution_host=host,
        )
        execution_digest = build_execution_authorization_digest(
            plan_digest=str(plan["plan_digest"]),
            approval_id="execution-approval",
        )
        claim_semantic = {
            "plan_digest": plan["plan_digest"],
            "execution_authorization_digest": execution_digest,
            "provider_authorization_digest": plan["provider_authorization_digest"],
            "execution_host_digest": host.descriptor["host_digest"],
        }
        host.claim(
            {
                "schema_version": 1,
                **claim_semantic,
                "claim_request_digest": digest(claim_semantic),
            }
        )

        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "recovery is required"):
            execute_model_benchmark_run(
                REPO_ROOT,
                plan,
                expected_plan_id=str(plan["plan_id"]),
                suite=selected_suite,
                model=model,
                health_record=health,
                execution_profile=profile,
                current_source_digest=str(selected_suite["source_digest"]),
                execution_host=host,
                execution_authorization_digest=execution_digest,
                observed_at=self.now,
            )
        self.assertEqual(0, host.trial_calls)
        self.assertEqual(0, len(host.receipts))

    def test_strict_parsers_round_trip_and_verifier_must_be_independent(self) -> None:
        model = self.model()
        profile = self.profile(model)
        self.assertEqual(profile, parse_benchmark_execution_profile(profile))
        with self.assertRaisesRegex(ModelBenchmarkRunnerError, "model family"):
            build_benchmark_execution_profile(
                model,
                client_id="codex",
                harness_id="codex-cli",
                harness_revision="1",
                model_revision="1",
                model_family="same-family",
                execution_ref="worker-execution",
                provider_route_ref="declared-route",
                quantization="none",
                reasoning_effort="high",
                reasoning_budget_tokens=None,
                environment_digest="f" * 64,
                verifier_execution_ref="verifier-execution",
                verifier_model_family="same-family",
            )


if __name__ == "__main__":
    unittest.main()
