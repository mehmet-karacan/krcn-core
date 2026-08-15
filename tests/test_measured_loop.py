from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from krcn_core.agent_execution_identity import create_agent_execution_identity  # noqa: E402
from krcn_core.measured_loop import (  # noqa: E402
    MeasuredLoopError,
    build_measured_loop_plan,
    build_measured_loop_status,
    build_morning_digest,
    create_cancellation_record,
    create_iteration_record,
    decide_admission,
    load_measured_loop_policy,
    parse_admission_decision,
    parse_cancellation_record,
    parse_iteration_record,
    parse_measured_loop_plan,
    parse_measured_loop_status,
    parse_morning_digest,
    resume_measured_loop,
    validate_iteration_chain,
)


def digest(character: str) -> str:
    return character * 64


class MeasuredLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_measured_loop_policy(REPO_ROOT)
        self.worker = create_agent_execution_identity(
            task_id="loop-task", plan_id=digest("a"), step_id="work",
            role="worker", actor_digest=digest("b"), session_digest=digest("c"),
            assignment_digest=digest("d"), runtime_kind="native-subagent",
        )
        self.verifier = create_agent_execution_identity(
            task_id="loop-task", plan_id=digest("a"), step_id="verify",
            role="verifier", actor_digest=digest("e"), session_digest=digest("f"),
            assignment_digest=digest("1"), runtime_kind="native-subagent",
        )

    def plan(self, **overrides):
        values = {
            "run_id": "run-one", "project_id": "project-one", "work_item_id": "work-one",
            "task_id": "loop-task", "task_plan_id": digest("a"),
            "task_authorization_id": digest("2"), "objective_id": "improve-quality",
            "objective_statement": "Improve verified quality within fixed constraints.",
            "constraint_refs": ["policy:bounded"], "acceptance_refs": ["test:measured"],
            "metrics": [{"metric_id": "quality", "owner_ref": "role:product",
                         "source_ref": "metric:test", "direction": "maximize", "unit": "points",
                         "baseline": 100, "target": 130, "minimum_delta": 10}],
            "budget": {"max_rounds": 4, "max_wall_time_seconds": 3600,
                       "max_input_tokens": 1000, "max_output_tokens": 1000,
                       "max_cost_microunits": 1000, "max_attempts": 4,
                       "max_concurrency": 2},
            "worker_execution_identity": self.worker.as_dict(),
            "verifier_execution_identity": self.verifier.as_dict(),
            "created_at": "2026-08-16T00:00:00Z",
        }
        values.update(overrides)
        return build_measured_loop_plan(self.policy, **values)

    def iteration(self, plan, previous, value, number, *, decision="continue", usage=None):
        return create_iteration_record(
            plan, [item.as_dict() for item in previous],
            started_at=f"2026-08-16T00:00:{number * 2 - 1:02d}Z",
            ended_at=f"2026-08-16T00:00:{number * 2:02d}Z",
            metric_values={"quality": value},
            usage=usage or {"input_tokens": 10, "output_tokens": 10,
                            "cost_microunits": 10, "attempts": 1, "peak_concurrency": 1},
            decision=decision, verification_passed=True, evidence_digest=digest("3"),
            checkpoint_digest=digest("4"), verifier_evidence_digest=digest("5"),
        )

    def assert_schema_valid(self, name: str, payload: dict) -> None:
        schema = json.loads((REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"))
        registry = Registry().with_resource(
            "urn:krcn:schemas:agent-execution-identity:1",
            Resource.from_contents(json.loads((REPO_ROOT / "schemas" / "agent-execution-identity.schema.json").read_text(encoding="utf-8"))),
        )
        self.assertEqual([], list(Draft202012Validator(schema, registry=registry).iter_errors(payload)))

    def test_default_effects_are_safe_and_extra_effects_require_existing_approval(self) -> None:
        plan = self.plan().as_dict()
        self.assertEqual(["plan", "read", "research"], plan["allowed_effects"])
        self.assertFalse(plan["grants_authority"])
        with self.assertRaisesRegex(MeasuredLoopError, "approval"):
            self.plan(allowed_effects=["read", "write"])
        approved = self.plan(
            allowed_effects=["read", "write"],
            effect_authorizations=[{"effect": "write", "approval_ref": "approval:change-42", "authorization_digest": digest("6")}],
        ).as_dict()
        self.assertEqual("approval:change-42", approved["effect_authorizations"][0]["approval_ref"])
        self.assertFalse(approved["grants_authority"])

    def test_worker_and_verifier_must_be_independent(self) -> None:
        nonindependent = create_agent_execution_identity(
            task_id="loop-task", plan_id=digest("a"), step_id="verify",
            role="verifier", actor_digest=digest("b"), session_digest=digest("f"),
            assignment_digest=digest("d"), runtime_kind="native-subagent",
        )
        with self.assertRaisesRegex(MeasuredLoopError, "independent"):
            self.plan(verifier_execution_identity=nonindependent.as_dict())

    def test_plan_iteration_and_chain_tampering_fail_closed(self) -> None:
        plan = self.plan()
        tampered_plan = copy.deepcopy(plan.as_dict())
        tampered_plan["objective"]["statement"] = "Different objective"
        with self.assertRaisesRegex(MeasuredLoopError, "digest"):
            parse_measured_loop_plan(tampered_plan, self.policy)
        first = self.iteration(plan, [], 111, 1)
        tampered = copy.deepcopy(first.as_dict())
        tampered["usage"]["input_tokens"] = 11
        with self.assertRaisesRegex(MeasuredLoopError, "digest"):
            parse_iteration_record(tampered)
        second = self.iteration(plan, [first], 122, 2).as_dict()
        second["previous_iteration_digest"] = digest("9")
        with self.assertRaises(MeasuredLoopError):
            validate_iteration_chain(plan, [first.as_dict(), second])

    def test_budgets_stop_at_limit_and_reject_overrun(self) -> None:
        plan = self.plan(budget={"max_rounds": 2, "max_wall_time_seconds": 3600,
            "max_input_tokens": 20, "max_output_tokens": 20, "max_cost_microunits": 20,
            "max_attempts": 2, "max_concurrency": 1})
        first = self.iteration(plan, [], 111, 1)
        second = self.iteration(plan, [first], 122, 2)
        status = build_measured_loop_status(self.policy, plan, [first.as_dict(), second.as_dict()], observed_at="2026-08-16T00:00:05Z")
        self.assertEqual(("stopped", "budget"), (status.payload["state"], status.payload["stop_reason"]))
        with self.assertRaisesRegex(MeasuredLoopError, "budget"):
            self.iteration(plan, [first, second], 125, 3)

    def test_plateau_accept_and_revert_are_explicit_stop_reasons(self) -> None:
        plan = self.plan()
        chain = []
        for number, value in enumerate((105, 108, 109), start=1):
            chain.append(self.iteration(plan, chain, value, number))
        plateau = build_measured_loop_status(self.policy, plan, [item.as_dict() for item in chain], observed_at="2026-08-16T00:00:07Z")
        self.assertEqual("plateau", plateau.payload["stop_reason"])
        accepted = self.iteration(plan, [], 130, 1, decision="accept")
        accept_status = build_measured_loop_status(self.policy, plan, [accepted.as_dict()], observed_at="2026-08-16T00:00:03Z")
        self.assertEqual("accept", accept_status.payload["stop_reason"])
        reverted = self.iteration(plan, [], 90, 1, decision="revert")
        revert_status = build_measured_loop_status(self.policy, plan, [reverted.as_dict()], observed_at="2026-08-16T00:00:03Z")
        self.assertEqual("revert", revert_status.payload["stop_reason"])

    def test_resume_requires_verified_records(self) -> None:
        plan = self.plan()
        first = self.iteration(plan, [], 111, 1)
        status = build_measured_loop_status(self.policy, plan, [first.as_dict()], observed_at="2026-08-16T00:00:03Z")
        resumed = resume_measured_loop(self.policy, plan, [first.as_dict()], status.as_dict(), observed_at="2026-08-16T00:00:04Z")
        self.assertEqual(first.payload["iteration_digest"], resumed.payload["latest_iteration_digest"])
        tampered = copy.deepcopy(status.as_dict())
        tampered["latest_iteration_digest"] = digest("8")
        with self.assertRaises(MeasuredLoopError):
            resume_measured_loop(self.policy, plan, [first.as_dict()], tampered, observed_at="2026-08-16T00:00:04Z")

    def test_cancellation_is_durable_record_only(self) -> None:
        plan = self.plan()
        cancellation = create_cancellation_record(plan, requested_at="2026-08-16T00:00:01Z", requester_digest=digest("7"), reason_code="user-request")
        parsed = parse_cancellation_record(cancellation.as_dict()).payload
        self.assertTrue(parsed["record_only"])
        self.assertFalse(parsed["process_signal_sent"])
        self.assertFalse(parsed["process_termination_claimed"])
        status = build_measured_loop_status(self.policy, plan, [], observed_at="2026-08-16T00:00:02Z", cancellation_record=cancellation.as_dict())
        self.assertEqual(("cancelled", "cancel"), (status.payload["state"], status.payload["stop_reason"]))
        with self.assertRaisesRegex(MeasuredLoopError, "cancelled"):
            create_iteration_record(plan, [], started_at="2026-08-16T00:00:03Z", ended_at="2026-08-16T00:00:04Z",
                metric_values={"quality": 111}, usage={"input_tokens": 1, "output_tokens": 1, "cost_microunits": 1, "attempts": 1, "peak_concurrency": 1},
                decision="continue", verification_passed=True, evidence_digest=digest("3"), checkpoint_digest=digest("4"), verifier_evidence_digest=digest("5"), cancellation_record=cancellation.as_dict())

    def test_zombie_requires_recovery(self) -> None:
        status = build_measured_loop_status(self.policy, self.plan(), [], observed_at="2026-08-16T00:15:00Z")
        self.assertEqual(("recovery-required", "zombie"), (status.payload["state"], status.payload["stop_reason"]))

    def test_admission_only_admits_or_defers_and_preserves_active_work(self) -> None:
        plan = self.plan()
        status = build_measured_loop_status(self.policy, plan, [], observed_at="2026-08-16T00:00:01Z")
        healthy = decide_admission(self.policy, plan, status.as_dict(), observed_at="2026-08-16T00:00:02Z",
            requested_claims=3, active_claims=0, cpu_pressure_basis_points=1000, ram_pressure_basis_points=1000,
            provider_required=False, provider_quota_remaining_basis_points=None, cost_headroom_microunits=5000, failure_pressure_basis_points=0)
        self.assertEqual(("admit", 2), (healthy.payload["decision"], healthy.payload["admitted_claims"]))
        pressured = decide_admission(self.policy, plan, status.as_dict(), observed_at="2026-08-16T00:00:02Z",
            requested_claims=1, active_claims=1, cpu_pressure_basis_points=1000, ram_pressure_basis_points=9000,
            provider_required=True, provider_quota_remaining_basis_points=500, cost_headroom_microunits=500, failure_pressure_basis_points=4000)
        self.assertEqual("defer", pressured.payload["decision"])
        self.assertEqual("preserve", pressured.payload["active_work_action"])
        self.assertFalse(pressured.payload["kill_requested"])
        self.assertIn("ram-pressure", pressured.payload["reason_codes"])
        parse_admission_decision(pressured.as_dict())

    def test_previous_run_must_be_terminal_and_cooldown_must_elapse(self) -> None:
        plan = self.plan()
        running = build_measured_loop_status(self.policy, plan, [], observed_at="2026-08-16T00:00:01Z")
        with self.assertRaisesRegex(MeasuredLoopError, "terminal"):
            self.plan(run_id="run-two", created_at="2026-08-16T00:10:00Z", previous_status=running.as_dict())
        cancelled = create_cancellation_record(plan, requested_at="2026-08-16T00:00:01Z", requester_digest=digest("7"), reason_code="user-request")
        terminal = build_measured_loop_status(self.policy, plan, [], observed_at="2026-08-16T00:00:02Z", cancellation_record=cancelled.as_dict())
        with self.assertRaisesRegex(MeasuredLoopError, "cooldown"):
            self.plan(run_id="run-two", created_at="2026-08-16T00:04:00Z", previous_status=terminal.as_dict())
        self.assertEqual("run-two", self.plan(run_id="run-two", created_at="2026-08-16T00:05:02Z", previous_status=terminal.as_dict()).payload["run_id"])

    def test_all_public_records_are_strict_schema_valid_and_safe(self) -> None:
        plan = self.plan()
        iteration = self.iteration(plan, [], 111, 1)
        status = build_measured_loop_status(self.policy, plan, [iteration.as_dict()], observed_at="2026-08-16T00:00:03Z")
        cancellation = create_cancellation_record(plan, requested_at="2026-08-16T00:00:04Z", requester_digest=digest("7"), reason_code="user-request")
        admission = decide_admission(self.policy, plan, status.as_dict(), observed_at="2026-08-16T00:00:04Z", requested_claims=1, active_claims=0,
            cpu_pressure_basis_points=0, ram_pressure_basis_points=0, provider_required=False, provider_quota_remaining_basis_points=None,
            cost_headroom_microunits=5000, failure_pressure_basis_points=0)
        morning = build_morning_digest(status.as_dict(), generated_at="2026-08-16T00:00:05Z")
        records = {
            "measured-loop-policy.schema.json": self.policy.as_dict(), "measured-loop-plan.schema.json": plan.as_dict(),
            "measured-loop-iteration.schema.json": iteration.as_dict(), "measured-loop-status.schema.json": status.as_dict(),
            "measured-loop-cancellation.schema.json": cancellation.as_dict(), "measured-loop-admission.schema.json": admission.as_dict(),
            "measured-loop-morning-digest.schema.json": morning.as_dict(),
        }
        for name, payload in records.items():
            with self.subTest(schema=name):
                self.assert_schema_valid(name, payload)
        parsed = parse_morning_digest(morning.as_dict()).payload
        serialized = json.dumps(parsed).lower()
        for forbidden in ("objective_statement", "prompt_text", "output_text", "working_directory"):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(parsed["contains_prompts"] or parsed["contains_outputs"] or parsed["contains_physical_paths"] or parsed["contains_secrets"])


if __name__ == "__main__":
    unittest.main()
