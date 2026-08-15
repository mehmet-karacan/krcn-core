from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.application import KrcnApplicationService, ServiceRequest  # noqa: E402
from krcn_core.capability_registry import (  # noqa: E402
    load_capability_registry,
    select_capability_records,
)
from krcn_core.home_layout import user_home_layout_bytes  # noqa: E402
from krcn_core.local_store import LocalWorkspaceStore  # noqa: E402
from krcn_core.model_benchmark import build_project_benchmark_suite  # noqa: E402
from krcn_core.model_decision import (  # noqa: E402
    ModelDecisionError,
    apply_model_evidence,
    build_model_benchmark_result,
    build_model_price_catalog,
    build_model_runtime_observation,
    decide_model_assignment,
    load_model_decision_policy,
    parse_model_decision,
    parse_task_model_assignments,
    prepare_model_evidence,
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
from krcn_core.orchestration_intent import create_task_intent  # noqa: E402
from krcn_core.orchestration_plan import create_task_plan  # noqa: E402


def _value(
    text: str,
    *,
    origin: str = "explicit-user",
    reversible: bool = False,
) -> dict[str, object]:
    return {"value": text, "origin": origin, "reversible": reversible}


def extraction() -> dict[str, object]:
    return {
        "task_id": "protect-database-task",
        "goal": _value("Veritabanı erişimini salt okunur tut"),
        "scope": [
            _value("decision-sample"),
            _value(
                "Mevcut ayarları koru",
                origin="safe-assumption",
                reversible=True,
            ),
        ],
        "sources": [_value("integration:decision-sample")],
        "constraints": [_value("Yalnız SELECT işlemlerine izin ver")],
        "acceptance_criteria": [_value("DELETE işlemi reddedilir")],
        "ownership_impact": ["user-data", "runtime"],
        "verification_requirements": [_value("Policy kararı deny olmalıdır")],
        "assumptions": [
            {
                "assumption_id": "preserve-settings",
                "statement": "Mevcut ayarlar korunur",
                "rationale": "Kullanıcı aksini istemedi",
                "reversible": True,
                "impact": "minor",
            }
        ],
        "ambiguities": [],
    }


def task_steps() -> list[dict[str, object]]:
    worker = {
        "title": "Inspect one reviewed input",
        "role": "worker",
        "depends_on": [],
        "required_capabilities": ["plan.execute", "record.read"],
        "capability_record_refs": ["worker-agent", "local-store-reader-tool"],
        "side_effects": ["read"],
        "ownership_impacts": ["user-data"],
        "provider_mode": "none",
        "approval_triggers": [],
        "acceptance_criteria": [],
        "verification_requirements": [],
        "reversible": True,
        "rollback_strategy": "not-required",
    }
    return [
        {**worker, "step_id": "inspect-left"},
        {**worker, "step_id": "inspect-right"},
        {
            **worker,
            "step_id": "merge-findings",
            "depends_on": ["inspect-left", "inspect-right"],
        },
        {
            "step_id": "verify-result",
            "title": "Verify the merged result",
            "role": "verifier",
            "depends_on": ["merge-findings"],
            "required_capabilities": ["evidence.verify"],
            "capability_record_refs": ["verifier-agent"],
            "side_effects": ["read"],
            "ownership_impacts": ["user-data"],
            "provider_mode": "none",
            "approval_triggers": [],
            "acceptance_criteria": ["DELETE işlemi reddedilir"],
            "verification_requirements": ["Policy kararı deny olmalıdır"],
            "reversible": True,
            "rollback_strategy": "not-required",
        },
    ]


class ModelDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "decision-sample"
        (self.source / "src").mkdir(parents=True)
        (self.source / "package.json").write_text(
            json.dumps(
                {
                    "name": "decision-sample",
                    "dependencies": {"react": "19.0.0"},
                    "scripts": {"test": "vitest"},
                }
            ),
            encoding="utf-8",
        )
        (self.source / "src" / "index.js").write_text(
            "export const value = 1;\n",
            encoding="utf-8",
        )
        home = self.root / "home"
        home.mkdir()
        (home / "layout.json").write_bytes(user_home_layout_bytes())
        self.store = LocalWorkspaceStore(
            home,
            OwnershipResolver.from_repository(REPO_ROOT),
        )
        service = KrcnApplicationService(REPO_ROOT, self.store)
        planned = service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": "manual"},
            )
        )
        service.execute(
            ServiceRequest(
                "codex",
                "project.integrate",
                {"source_root": str(self.source), "scan_mode": "manual"},
                apply=True,
                expected_plan_id=planned.data["plan"]["plan_id"],
                approval_id="decision-integration",
            )
        )
        self.suite = build_project_benchmark_suite(
            REPO_ROOT,
            self.store,
            "decision-sample",
            suite_revision=1,
        )
        self.now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        self.models = [self.model("model-alpha"), self.model("model-beta")]
        health_policy = load_model_health_policy(REPO_ROOT)
        self.health = [
            build_model_health_record(
                model,
                health_policy,
                ModelHealthObservation(True, True, True, True, 1000, None),
                checked_at=self.now,
            )
            for model in self.models
        ]
        self.benchmarks = [
            build_model_benchmark_result(
                self.suite,
                model,
                workload_id="analysis",
                observed_at="2026-08-15T12:00:00Z",
                quality_score_basis_points=9000,
                reliability_score_basis_points=9000,
                latency_ms=1000,
                passed=True,
            )
            for model in self.models
        ]
        self.catalog = build_model_price_catalog(
            catalog_id="local-prices",
            catalog_revision=1,
            currency="USD",
            observed_at="2026-08-15T00:00:00Z",
            expires_at="2026-08-16T00:00:00Z",
            entries=[
                {
                    "model_ref": "model-alpha",
                    "input_microunits_per_million": 900000,
                    "output_microunits_per_million": 900000,
                    "fixed_microunits": 800000,
                },
                {
                    "model_ref": "model-beta",
                    "input_microunits_per_million": 10000,
                    "output_microunits_per_million": 10000,
                    "fixed_microunits": 0,
                },
            ],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def model(model_ref: str) -> dict[str, object]:
        suffix = "Alpha" if model_ref == "model-alpha" else "Beta"
        return build_model_inventory_record(
            {
                "model_ref": model_ref,
                "provider_ref": "local-router",
                "model_id": f"openai/Model-{suffix}",
                "display_name": f"Model {suffix}",
                "modalities": ["text"],
                "supported_workloads": ["analysis", "verification"],
                "client_refs": ["codex"],
                "remote": True,
                "enabled": True,
            },
            revision=1,
        )

    def decide(self, **changes):
        arguments = {
            "project_id": "decision-sample",
            "client_id": "codex",
            "workload": "analysis",
            "role": "planner",
            "available_bindings": {
                "client-high-reasoning": "openai/Model-Alpha",
                "client-default": "openai/Model-Beta",
            },
            "inventory_records": self.models,
            "health_records": self.health,
            "benchmark_suite": self.suite,
            "benchmark_results": self.benchmarks,
            "runtime_observations": [],
            "price_catalog": self.catalog,
            "now": self.now,
            "input_token_budget": 10000,
            "output_token_budget": 2000,
        }
        arguments.update(changes)
        return decide_model_assignment(REPO_ROOT, **arguments)

    def put_record(
        self,
        record_type: str,
        record_id: str,
        payload: dict[str, object],
        *,
        project_id: str | None = None,
    ) -> None:
        plan = self.store.prepare_put(
            record_type,
            record_id,
            payload,
            expected_revision=0,
            project_id=project_id,
        )
        approval = (
            ApprovalEvidence(plan.mutation.plan_id, "model-record-approval", True)
            if plan.mutation.approval_required
            else None
        )
        authorization = authorize_mutation(
            plan.mutation,
            dry_run=DryRunEvidence(plan.mutation.plan_id, True),
            approval=approval,
        )
        self.store.apply_put(plan, authorization)

    def test_net_value_prefers_lower_cost_qualified_model(self) -> None:
        decision = self.decide().as_dict()
        self.assertEqual("model-beta", decision["selected_model_ref"])
        self.assertEqual("qualified-net-value", decision["selection_basis"])
        self.assertEqual("client-default", decision["selected_candidate_ref"])
        self.assertFalse(decision["provider_call_performed"])
        self.assertFalse(decision["grants_authority"])
        self.assertGreater(len(decision["evidence_digests"]), 2)

    def test_runtime_success_feedback_changes_the_next_assignment(self) -> None:
        observations = []
        for index in range(3):
            observations.append(
                build_model_runtime_observation(
                    self.models[0],
                    project_id="decision-sample",
                    workload="analysis",
                    model_assignment_id=f"assignment-alpha-{index}",
                    trace_digest=(str(index + 1) * 64)[:64],
                    observed_at=f"2026-08-15T11:0{index}:00Z",
                    successful=True,
                    verifier_passed=True,
                    latency_ms=100,
                    input_tokens=100,
                    output_tokens=50,
                    actual_cost_microunits=1,
                )
            )
            observations.append(
                build_model_runtime_observation(
                    self.models[1],
                    project_id="decision-sample",
                    workload="analysis",
                    model_assignment_id=f"assignment-beta-{index}",
                    trace_digest=(str(index + 4) * 64)[:64],
                    observed_at=f"2026-08-15T11:1{index}:00Z",
                    successful=False,
                    verifier_passed=False,
                    latency_ms=1000,
                    input_tokens=100,
                    output_tokens=50,
                    actual_cost_microunits=1,
                )
            )
        decision = self.decide(runtime_observations=observations).as_dict()
        self.assertEqual("model-alpha", decision["selected_model_ref"])

    def test_unhealthy_stale_and_verifier_model_are_excluded(self) -> None:
        unhealthy = build_model_health_record(
            self.models[0],
            load_model_health_policy(REPO_ROOT),
            ModelHealthObservation(True, True, True, True, 1000, None),
            checked_at=self.now - timedelta(days=2),
        )
        decision = self.decide(
            role="verifier",
            health_records=[unhealthy, self.health[1]],
            excluded_model_refs=["model-beta"],
        ).as_dict()
        self.assertEqual("client-default-fallback", decision["selection_basis"])
        reasons = {
            item["candidate_ref"]: item["reason_codes"]
            for item in decision["excluded_candidates"]
        }
        self.assertIn("health-stale", reasons["client-high-reasoning"])
        self.assertIn("verifier-independence", reasons["client-default"])

    def test_quarantine_and_stale_benchmark_never_enter_the_score(self) -> None:
        health_policy = load_model_health_policy(REPO_ROOT)
        failed_once = build_model_health_record(
            self.models[0],
            health_policy,
            ModelHealthObservation(False, False, False, False, 30000, "timeout"),
            checked_at=self.now - timedelta(minutes=1),
        )
        quarantined = build_model_health_record(
            self.models[0],
            health_policy,
            ModelHealthObservation(False, False, False, False, 30000, "timeout"),
            checked_at=self.now,
            previous=failed_once,
        )
        stale_benchmark = build_model_benchmark_result(
            self.suite,
            self.models[1],
            workload_id="analysis",
            observed_at="2026-08-01T12:00:00Z",
            quality_score_basis_points=9900,
            reliability_score_basis_points=9900,
            latency_ms=10,
            passed=True,
        )
        decision = self.decide(
            health_records=[quarantined, self.health[1]],
            benchmark_results=[self.benchmarks[0], stale_benchmark],
        ).as_dict()
        self.assertEqual("client-default-fallback", decision["selection_basis"])
        reasons = {
            item["candidate_ref"]: item["reason_codes"]
            for item in decision["excluded_candidates"]
        }
        self.assertIn("health-unavailable", reasons["client-high-reasoning"])
        self.assertIn("benchmark-stale", reasons["client-default"])

    def test_missing_evidence_falls_back_without_inventing_cost(self) -> None:
        decision = self.decide(
            health_records=[],
            benchmark_results=[],
            price_catalog=None,
        ).as_dict()
        self.assertEqual("client-default-fallback", decision["selection_basis"])
        self.assertIsNone(decision["selected_model_ref"])
        self.assertIsNone(decision["estimated_cost_microunits"])

    def test_policy_records_and_decision_are_versioned_and_tamper_safe(self) -> None:
        policy = load_model_decision_policy(REPO_ROOT)
        self.assertEqual(100, sum(policy.score_weights.values()))
        policy_document = json.loads(
            (REPO_ROOT / "config/model-decision.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("prices", policy_document)
        self.assertNotIn("entries", policy_document)
        decision = self.decide()
        schema = json.loads(
            (REPO_ROOT / "schemas/model-decision.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [],
            list(Draft202012Validator(schema).iter_errors(decision.as_dict())),
        )
        self.assertEqual(decision, parse_model_decision(decision.as_dict()))
        tampered = decision.as_dict()
        tampered["selected_model_ref"] = "model-alpha"
        with self.assertRaisesRegex(ModelDecisionError, "digest"):
            parse_model_decision(tampered)

    def test_expired_price_catalog_and_budget_fail_closed(self) -> None:
        with self.assertRaisesRegex(ModelDecisionError, "price catalog is stale"):
            self.decide(now=self.now + timedelta(days=2))
        decision = self.decide(maximum_cost_microunits=1000).as_dict()
        self.assertEqual("model-beta", decision["selected_model_ref"])
        reasons = {
            item["candidate_ref"]: item["reason_codes"]
            for item in decision["excluded_candidates"]
        }
        self.assertIn("cost-budget-exceeded", reasons["client-high-reasoning"])

    def test_price_benchmark_and_runtime_evidence_use_exact_local_plans(self) -> None:
        price_plan = prepare_model_evidence(self.store, self.catalog)
        self.assertEqual("user-data", price_plan.effect_plan.mutation.ownership)
        self.assertTrue(price_plan.effect_plan.mutation.approval_required)
        price_authorization = authorize_mutation(
            price_plan.effect_plan.mutation,
            dry_run=DryRunEvidence(price_plan.effect_plan.mutation.plan_id, True),
            approval=ApprovalEvidence(
                price_plan.effect_plan.mutation.plan_id,
                "price-catalog-approval",
                True,
            ),
        )
        applied_price = apply_model_evidence(
            self.store,
            price_plan,
            price_authorization,
            expected_plan_id=price_plan.plan_id,
        )
        self.assertEqual(self.catalog["catalog_digest"], applied_price["catalog_digest"])
        self.assertTrue(prepare_model_evidence(self.store, self.catalog).public_summary()["no_op"])
        updated_catalog = build_model_price_catalog(
            catalog_id="local-prices",
            catalog_revision=2,
            currency="USD",
            observed_at="2026-08-15T01:00:00Z",
            expires_at="2026-08-17T00:00:00Z",
            entries=self.catalog["entries"],
        )
        update_plan = prepare_model_evidence(self.store, updated_catalog)
        self.assertEqual(1, update_plan.effect_plan.previous_revision)
        self.assertEqual(2, update_plan.effect_plan.next_revision)

        benchmark_plan = prepare_model_evidence(
            self.store,
            self.benchmarks[0],
            project_id="decision-sample",
        )
        self.assertEqual("derived", benchmark_plan.effect_plan.mutation.ownership)
        benchmark_authorization = authorize_mutation(
            benchmark_plan.effect_plan.mutation,
            dry_run=DryRunEvidence(
                benchmark_plan.effect_plan.mutation.plan_id,
                True,
            ),
        )
        apply_model_evidence(
            self.store,
            benchmark_plan,
            benchmark_authorization,
            expected_plan_id=benchmark_plan.plan_id,
        )
        observation = build_model_runtime_observation(
            self.models[0],
            project_id="decision-sample",
            workload="analysis",
            model_assignment_id="assignment-persisted",
            trace_digest="9" * 64,
            observed_at="2026-08-15T12:00:00Z",
            successful=True,
            verifier_passed=True,
            latency_ms=100,
            input_tokens=50,
            output_tokens=25,
            actual_cost_microunits=2,
        )
        observation_plan = prepare_model_evidence(
            self.store,
            observation,
            project_id="decision-sample",
        )
        observation_authorization = authorize_mutation(
            observation_plan.effect_plan.mutation,
            dry_run=DryRunEvidence(
                observation_plan.effect_plan.mutation.plan_id,
                True,
            ),
        )
        apply_model_evidence(
            self.store,
            observation_plan,
            observation_authorization,
            expected_plan_id=observation_plan.plan_id,
        )
        self.assertTrue(
            (
                self.store.data_root
                / "projects/decision-sample/derived/model-runtime-observations"
                / f"{observation['observation_id']}.json"
            ).is_file()
        )

    def test_application_decision_reads_the_persistent_closed_loop(self) -> None:
        for model, health in zip(self.models, self.health, strict=True):
            self.put_record(
                "model-inventory",
                str(model["model_ref"]),
                model,
            )
            self.put_record(
                "model-health",
                str(health["model_ref"]),
                health,
            )
        self.put_record(
            "model-benchmark-suites",
            str(self.suite["suite_id"]),
            self.suite,
            project_id="decision-sample",
        )
        price_plan = prepare_model_evidence(self.store, self.catalog)
        apply_model_evidence(
            self.store,
            price_plan,
            authorize_mutation(
                price_plan.effect_plan.mutation,
                dry_run=DryRunEvidence(price_plan.effect_plan.mutation.plan_id, True),
                approval=ApprovalEvidence(
                    price_plan.effect_plan.mutation.plan_id,
                    "price-catalog-approval",
                    True,
                ),
            ),
            expected_plan_id=price_plan.plan_id,
        )
        for benchmark in self.benchmarks:
            plan = prepare_model_evidence(
                self.store,
                benchmark,
                project_id="decision-sample",
            )
            apply_model_evidence(
                self.store,
                plan,
                authorize_mutation(
                    plan.effect_plan.mutation,
                    dry_run=DryRunEvidence(plan.effect_plan.mutation.plan_id, True),
                ),
                expected_plan_id=plan.plan_id,
            )
        response = KrcnApplicationService(REPO_ROOT, self.store).execute(
            ServiceRequest(
                "codex",
                "model.decide",
                {
                    "project_id": "decision-sample",
                    "client_id": "codex",
                    "workload": "analysis",
                    "role": "planner",
                    "available_bindings": {
                        "client-high-reasoning": "openai/Model-Alpha",
                        "client-default": "openai/Model-Beta",
                    },
                    "price_catalog_id": "local-prices",
                    "now": "2026-08-15T12:00:00Z",
                    "input_token_budget": 10000,
                    "output_token_budget": 2000,
                },
            )
        )
        self.assertEqual("ok", response.status)
        self.assertEqual("model-beta", response.data["decision"]["selected_model_ref"])

        verification_results = [
            build_model_benchmark_result(
                self.suite,
                model,
                workload_id="verification",
                observed_at="2026-08-15T12:00:00Z",
                quality_score_basis_points=9000,
                reliability_score_basis_points=9000,
                latency_ms=1000,
                passed=True,
            )
            for model in self.models
        ]
        for benchmark in verification_results:
            plan = prepare_model_evidence(
                self.store,
                benchmark,
                project_id="decision-sample",
            )
            apply_model_evidence(
                self.store,
                plan,
                authorize_mutation(
                    plan.effect_plan.mutation,
                    dry_run=DryRunEvidence(plan.effect_plan.mutation.plan_id, True),
                ),
                expected_plan_id=plan.plan_id,
            )
        intent = create_task_intent(
            "Keep database access read-only.",
            extraction(),
        )
        registry = load_capability_registry(REPO_ROOT)
        selection = select_capability_records(
            registry,
            ["worker-agent", "verifier-agent", "local-store-reader-tool"],
            ["plan.execute", "record.read", "evidence.verify"],
        )
        task_plan = create_task_plan(
            intent,
            selection,
            task_steps(),
        )
        plan_response = KrcnApplicationService(REPO_ROOT, self.store).execute(
            ServiceRequest(
                "codex",
                "model.decide-plan",
                {
                    "project_id": "decision-sample",
                    "client_id": "codex",
                    "task_plan": task_plan.as_dict(),
                    "step_workloads": {
                        "inspect-left": "analysis",
                        "inspect-right": "analysis",
                        "merge-findings": "analysis",
                        "verify-result": "verification",
                    },
                    "available_bindings": {
                        "client-high-reasoning": "openai/Model-Alpha",
                        "client-default": "openai/Model-Beta",
                    },
                    "price_catalog_id": "local-prices",
                    "now": "2026-08-15T12:00:00Z",
                    "input_token_budget": 10000,
                    "output_token_budget": 2000,
                },
            )
        )
        assignment_payload = plan_response.data["assignments"]
        self.assertEqual(4, len(assignment_payload["assignments"]))
        self.assertEqual(
            4,
            len(
                {
                    item["model_assignment_id"]
                    for item in assignment_payload["assignments"]
                }
            ),
        )
        self.assertEqual(
            ["model-beta", "model-beta", "model-beta", "model-alpha"],
            [
                item["model_ref"]
                for item in assignment_payload["assignments"]
            ],
        )
        self.assertFalse(assignment_payload["verifier_model_reuse_detected"])
        assignment_schema = json.loads(
            (REPO_ROOT / "schemas/task-model-assignments.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [],
            list(
                Draft202012Validator(assignment_schema).iter_errors(
                    assignment_payload
                )
            ),
        )
        self.assertEqual(
            assignment_payload,
            parse_task_model_assignments(assignment_payload).as_dict(),
        )


if __name__ == "__main__":
    unittest.main()
